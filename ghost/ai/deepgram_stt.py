"""Deepgram streaming STT engine — CLOUD, drop-in for the on-device STT seam.

⚠️ STEALTH NOTE: this is the ONE part of Ghost that leaves the machine. Interviewer
audio is streamed to Deepgram's servers over the network. It is opt-in via `--deepgram`
and exists only because cloud streaming ASR gives fast END-OF-SPEECH detection
(`speech_final` ~0.5s) that beats Ghost's on-device 2s silence endpoint. On-device
(Parakeet) stays the default and the stealth-preserving path. Needs DEEPGRAM_API_KEY.

Matches the same interface as StreamingSTT / ParakeetSTT so pipeline.py swaps engines
with no logic change:
    authorize() · start() · set_contextual_strings() · feed(np.float32 16k mono) ·
    rotate() · stop()  + on_partial(text) / on_final(text) callbacks.

ROBUSTNESS (the interview reality): the pipeline only feeds audio when the interviewer
has ENERGY — during long silences (e.g. while the user answers) NO audio is sent. Deepgram
closes the socket after ~10s of no audio, so we (1) send KeepAlive frames during silence to
hold the socket open, and (2) auto-reconnect if it drops anyway (network blip, server
recycle). Without these, capture works at first then silently dies after the first long gap.

Built on deepgram-sdk v7 (client.listen.v1.connect → V1SocketClient).
"""
import os
import time
import threading
from collections import deque
import numpy as np

DEFAULT_MODEL = "nova-3"        # best accuracy + keyterm biasing; streaming
_ENDPOINTING_MS = 300           # silence after speech → speech_final (fast finalize)
_UTTERANCE_END_MS = 1000        # fallback UtteranceEnd event if speech_final is missed
_MAX_KEYTERMS = 50              # Deepgram caps keyterms at 500 tokens; keep the top ~50
_KEEPALIVE_EVERY = 4.0          # send KeepAlive if no media sent for this long (< 10s close)
_RECONNECT_BACKOFF = 1.0        # wait between reconnect attempts
_PENDING_MAX = 200              # bounded backlog while (re)connecting (~ a few seconds)

# ── diagnostic logging (so a real test run is debuggable, not guesswork) ──────
# Everything lands in logs/deepgram.log with per-instance labels (interviewer/you),
# so after a run you can SEE if/when a socket dropped and whether audio kept flowing.
# Set GHOST_DG_TEE=1 to also record exactly what each connection was fed to a WAV.
_LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")
_LOG_PATH = os.path.join(_LOG_DIR, "deepgram.log")
_log_lock = threading.Lock()


def _log(label, msg):
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        with _log_lock, open(_LOG_PATH, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} [{label:11}] {msg}\n")
    except Exception:
        pass


class DeepgramSTT:
    def __init__(self, locale: str = "en-US", on_partial=None, on_final=None,
                 contextual_strings=None, model: str = DEFAULT_MODEL, label: str = "dg",
                 **_ignored):
        self._label = label
        self._language = "en" if (locale or "en-US").lower().startswith("en") else locale
        self._on_partial = on_partial
        self._on_final = on_final
        self._model = model
        self._keyterms = list(contextual_strings or [])[:_MAX_KEYTERMS]

        self._client = None
        self._conn = None                       # V1SocketClient (set on the worker thread)
        self._worker = None
        self._keepalive = None
        self._running = False
        self._send_lock = threading.Lock()
        self._state_lock = threading.Lock()      # guards _final_parts (worker vs rotate threads)
        self._final_event = threading.Event()    # signalled when on_final fires (for rotate)
        self._final_parts = []                   # is_final segments accumulating into one utterance
        self._pending = deque(maxlen=_PENDING_MAX)  # audio buffered before the socket is up
        self._last_media_t = 0.0
        self._n_final = 0                        # utterances emitted (for the heartbeat)
        self._last_hb = 0.0                      # last heartbeat log time
        self._tee = None                         # optional WAV of exactly what we fed

    # ── auth ──────────────────────────────────────────────────────────────────
    @staticmethod
    def authorize(timeout: float = 10.0) -> bool:
        """No OS permission needed (cloud); just require the API key."""
        if not os.environ.get("DEEPGRAM_API_KEY"):
            print("[Deepgram] DEEPGRAM_API_KEY not set — add it to .env "
                  "(get a key at https://console.deepgram.com).")
            return False
        return True

    def set_contextual_strings(self, strings: list):
        """Bias recognition toward these terms (resume/JD jargon, names). Deepgram v1
        keyterms are fixed at connect time; takes effect on the next (re)connect."""
        self._keyterms = list(strings or [])[:_MAX_KEYTERMS]

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start(self):
        if self._running:
            return
        api_key = os.environ.get("DEEPGRAM_API_KEY")
        if not api_key:                          # fail cleanly, not with a raw KeyError
            raise RuntimeError("DEEPGRAM_API_KEY not set; call DeepgramSTT.authorize() "
                               "or add the key to your environment before start().")
        from deepgram import DeepgramClient
        self._client = DeepgramClient(api_key=api_key)
        self._running = True
        if os.environ.get("GHOST_DG_TEE"):       # opt-in: record exactly what we feed
            try:
                import soundfile as sf
                os.makedirs(_LOG_DIR, exist_ok=True)
                self._tee = sf.SoundFile(os.path.join(_LOG_DIR, f"dg_{self._label}.wav"),
                                         "w", samplerate=16000, channels=1, subtype="PCM_16")
            except Exception as e:
                _log(self._label, f"tee open failed: {e}")
        _log(self._label, f"start model={self._model} keyterms={len(self._keyterms)} "
                          f"tee={self._tee is not None}")
        self._worker = threading.Thread(target=self._run_forever, name="DeepgramSTT", daemon=True)
        self._worker.start()
        self._keepalive = threading.Thread(target=self._keepalive_loop, name="DeepgramKA", daemon=True)
        self._keepalive.start()

    def _connect_opts(self) -> dict:
        opts = dict(
            model=self._model, language=self._language,
            encoding="linear16", sample_rate=16000, channels=1,
            interim_results=True, punctuate=True, smart_format=True,
            endpointing=_ENDPOINTING_MS, utterance_end_ms=_UTTERANCE_END_MS, vad_events=True,
        )
        if self._keyterms:
            opts["keyterm"] = self._keyterms
        return opts

    def _run_forever(self):
        """Connect + read messages; RECONNECT if the socket drops while we're still running
        (idle-timeout close, network blip, server recycle). This is what stops the
        'works then dies after the first long silence' failure."""
        while self._running:
            try:
                with self._client.listen.v1.connect(**self._connect_opts()) as conn:
                    # Don't silently drop words the old socket already finalized:
                    # flush any leftover utterance from before the drop, THEN reset.
                    self._emit_final()
                    self._conn = conn
                    self._last_media_t = time.time()   # fresh idle clock, no instant KeepAlive
                    _log(self._label, "connected")
                    self._flush_pending()
                    for message in conn:        # blocks; yields Results/UtteranceEnd/…
                        if not self._running:
                            break
                        self._handle(message)
            except Exception as e:
                if self._running:
                    print(f"[Deepgram] stream dropped ({e}); reconnecting…")
                    _log(self._label, f"DROPPED: {e!r}")
            finally:
                self._conn = None
            if self._running:
                time.sleep(_RECONNECT_BACKOFF)

    def _keepalive_loop(self):
        """Hold the socket open through silences the pipeline doesn't feed. Deepgram
        closes after ~10s of no audio; a KeepAlive frame resets that timer."""
        while self._running:
            time.sleep(1.0)
            now = time.time()
            if now - self._last_hb >= 15:        # heartbeat: the key diagnostic timeline
                self._last_hb = now
                _log(self._label, f"hb connected={self._conn is not None} finals={self._n_final} "
                                  f"since_media={now - self._last_media_t:4.0f}s "
                                  f"pending={len(self._pending)}")
            conn = self._conn
            if conn is None:
                continue
            if (time.time() - self._last_media_t) >= _KEEPALIVE_EVERY:
                try:
                    with self._send_lock:
                        conn.send_keep_alive()
                    self._last_media_t = time.time()   # don't spam; reset the idle clock
                except Exception:
                    pass

    # ── audio in ──────────────────────────────────────────────────────────────
    def feed(self, audio: np.ndarray):
        """float32 [-1,1] 16k mono → 16-bit PCM → Deepgram. Buffers (bounded) if the
        socket is mid-(re)connect."""
        if not self._running:
            return
        if self._tee is not None:                # record exactly what the pipeline handed us
            try:
                self._tee.write(np.asarray(audio, dtype=np.float32))
            except Exception:
                pass
        pcm = np.clip(np.ascontiguousarray(audio, dtype=np.float32), -1.0, 1.0)
        pcm = (pcm * 32767.0).astype("<i2").tobytes()
        conn = self._conn
        if conn is None:
            self._pending.append(pcm)           # deque(maxlen) drops oldest if backlogged
            return
        # A previous send may have failed without killing the socket; drain the
        # backlog first so audio always reaches Deepgram in capture order.
        if self._pending:
            self._flush_pending()
            if self._conn is None:              # flush found the socket dead after all
                self._pending.append(pcm)
                return
        try:
            with self._send_lock:
                conn.send_media(pcm)
            self._last_media_t = time.time()
        except Exception as e:
            print(f"[Deepgram] send failed ({e}); buffering")
            self._pending.append(pcm)

    def _flush_pending(self):
        if not self._pending:
            return
        while self._pending and self._conn is not None:
            pcm = self._pending.popleft()
            try:
                with self._send_lock:
                    self._conn.send_media(pcm)
            except Exception:
                self._pending.appendleft(pcm)
                break
        self._last_media_t = time.time()

    # ── results ───────────────────────────────────────────────────────────────
    def _handle(self, msg):
        # UtteranceEnd = fallback endpoint if speech_final never came (short/ambiguous ends).
        if type(msg).__name__.endswith("UtteranceEnd") or getattr(msg, "type", "") == "UtteranceEnd":
            self._emit_final()
            return

        text = self._transcript(msg)
        is_final = bool(getattr(msg, "is_final", False))
        speech_final = bool(getattr(msg, "speech_final", False))
        # Finalize responses arrive as is_final WITHOUT speech_final; without this
        # check rotate() always times out its full 2s before the fallback emits.
        from_finalize = bool(getattr(msg, "from_finalize", False))
        if not text and not (is_final or speech_final or from_finalize):
            return

        if is_final:
            if text:
                with self._state_lock:
                    self._final_parts.append(text)
            if self._on_partial:
                with self._state_lock:
                    accumulated = " ".join(self._final_parts).strip()
                self._on_partial(accumulated)
            if speech_final or from_finalize:    # end of utterance → commit NOW
                self._emit_final()
        else:
            if self._on_partial:                 # interim: accumulated finals + in-flight guess
                with self._state_lock:
                    live = " ".join(self._final_parts + [text]).strip()
                if live:
                    self._on_partial(live)

    @staticmethod
    def _transcript(msg) -> str:
        try:
            return (msg.channel.alternatives[0].transcript or "").strip()
        except Exception:
            return ""

    def _emit_final(self):
        with self._state_lock:
            text = " ".join(self._final_parts).strip()
            self._final_parts = []
        if text and self._on_final:
            self._n_final += 1
            self._on_final(text)
        self._final_event.set()

    # ── force finalize (silence backstop / answer-now) ─────────────────────────
    def rotate(self):
        """Flush in-flight audio to a final and wait (bounded) so on_final is delivered
        synchronously — matches the StreamingSTT/Parakeet contract the pipeline relies on."""
        conn = self._conn
        if conn is None:
            self._emit_final()
            return
        self._final_event.clear()
        try:
            with self._send_lock:
                conn.send_finalize()
        except Exception:
            self._emit_final()
            return
        # Normally resolves in ~100-300ms now that _handle recognizes from_finalize;
        # the timeout is only a safety net for a wedged socket.
        if not self._final_event.wait(timeout=2.0):
            self._emit_final()                  # idempotent: no-op if parts are empty

    def stop(self):
        self._running = False
        _log(self._label, f"stop finals={self._n_final}")
        if self._tee is not None:
            try:
                self._tee.close()
            except Exception:
                pass
        conn = self._conn
        if conn is not None:
            try:
                with self._send_lock:
                    conn.send_close_stream()
            except Exception:
                pass
        for t in (self._worker, self._keepalive):
            if t is not None:
                t.join(timeout=3.0)