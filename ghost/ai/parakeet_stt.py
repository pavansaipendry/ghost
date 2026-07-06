"""Parakeet on-device STT — a drop-in replacement for the Apple StreamingSTT.

Why this exists: the Apple SFSpeechRecognizer path degrades on long sessions
(the recognizer enters a kAFAssistantErrorDomain state after ~20-30 min and every
task after that errors, so the interviewer transcript silently dies) and its live
partials revise/vanish mid-utterance. Parakeet (NVIDIA TDT, run locally via
parakeet-mlx) is a STATELESS chunk transcriber: each utterance is decoded in one
shot, so there is no long-lived task to rot and no partial that can wipe itself.
It's also more accurate on technical English. Fully on-device — nothing leaves the
Mac, so Ghost's stealth model is preserved.

Interface is identical to StreamingSTT so pipeline.py swaps engines with no logic
change: authorize()/start()/feed()/rotate()/stop()/on_partial/on_final/
set_contextual_strings(). Format is the same 16kHz mono float32 numpy Ghost feeds
everywhere.

Threading (matters — BlackHole delivers chunks ON the PortAudio callback thread):
  - feed() only appends to a buffer. It NEVER runs the model, so the audio callback
    is never blocked.
  - A single worker thread owns the model and does ALL inference (mlx/Metal wants
    one caller). It one-shot re-transcribes the growing utterance every
    ~PARTIAL_INTERVAL for live partials (RTF ~0.04 on Apple Silicon, so it keeps up).
  - rotate() asks the worker for a final pass and waits (bounded) so the final is
    delivered synchronously — the same contract Apple's rotate() has, which the
    answer-now hotkey's suppress logic depends on.
"""

import threading
import time

import numpy as np
import mlx.core as mx
import parakeet_mlx as pk
from parakeet_mlx.audio import get_logmel

from ghost.ai.glossary import build_glossary, correct_transcript

WHISPER_SAMPLE_RATE = 16000

# English TDT model — top-tier accuracy, ~600M params, loads from HF cache in ~1.5s.
DEFAULT_PARAKEET_MODEL = "mlx-community/parakeet-tdt-0.6b-v2"


# ── Shared model + inference lock ────────────────────────────────────────────
# Both voices (interviewer ParakeetSTT + user ParakeetBatchTranscriber) use ONE
# loaded model instead of two ~1.2GB copies. _INFER_LOCK serializes every generate()
# so the two threads never call the model concurrently (mlx wants one caller).
# Contention is near-zero in practice: the user-voice echo gate makes the two voices
# take turns, so while the interviewer is transcribing the user path is dropping audio
# (and vice-versa) — they rarely both want the model at once.
_shared_model = None
_load_lock = threading.Lock()
_INFER_LOCK = threading.Lock()


def _get_shared_model(repo: str = DEFAULT_PARAKEET_MODEL):
    """Load (once) and return the process-wide Parakeet model."""
    global _shared_model
    with _load_lock:
        if _shared_model is None:
            print(f"[Parakeet] Loading shared model {repo} …")
            _shared_model = pk.from_pretrained(repo)
        return _shared_model


def _decode(model, pcfg, audio: np.ndarray) -> str:
    """One-shot decode a float32 numpy buffer → text. Serialized by _INFER_LOCK."""
    mel = get_logmel(mx.array(np.ascontiguousarray(audio, dtype=np.float32)), pcfg)
    with _INFER_LOCK:
        result = model.generate(mel)[0]
    return (result.text or "").strip()


class ParakeetSTT:
    """On-device Parakeet streaming-ish STT with the StreamingSTT interface."""

    # Re-transcribe the growing utterance for a live partial at most this often.
    # One-shot decode of even a 15s buffer is ~0.6s, well under this, so the worker
    # never falls behind real-time.
    _PARTIAL_INTERVAL = 0.8
    # Don't try to decode less than this much audio (get_logmel needs real content;
    # sub-300ms slivers just produce noise/hallucinated single tokens).
    _MIN_SAMPLES = int(0.35 * WHISPER_SAMPLE_RATE)
    # Upper bound on how long rotate() will block waiting for the final decode. A
    # 20s max-length utterance decodes in ~0.8s; 2.0s leaves headroom for one
    # in-flight partial pass to finish first. Fires at a silence boundary, so any
    # audio-callback stall it causes only drops already-silent frames.
    _FINALIZE_TIMEOUT = 2.0

    def __init__(self, locale: str = "en-US", on_partial=None, on_final=None,
                 on_device: bool = True, sample_rate: int = WHISPER_SAMPLE_RATE,
                 contextual_strings: list = None,
                 model_repo: str = DEFAULT_PARAKEET_MODEL):
        """
        Args mirror StreamingSTT. `contextual_strings` (resume/JD terms harvested by
        ContextLoader) are merged with the curated tech glossary and used to correct
        near-miss technical words in the output (Parakeet has no prompt-bias API, so
        biasing is post-hoc + its stronger base accuracy). `locale` is accepted for
        interface parity; the v2 model is English-only.
        """
        self._on_partial = on_partial
        self._on_final = on_final
        self._sample_rate = sample_rate
        self._model_repo = model_repo
        self._glossary = build_glossary(contextual_strings)

        self._model = None
        self._pcfg = None

        # Current utterance buffer (list of float32 chunks + running sample count).
        self._buf = []
        self._buf_samples = 0
        self._buf_lock = threading.Lock()

        self._running = False
        self._worker = None
        self._wake = threading.Event()        # "there may be work" signal
        self._finalize = False                # rotate() requested a final pass
        self._final_ready = threading.Event() # worker sets it once the final is done
        self._final_text = ""

        self._last_text = ""                  # most recent partial (rotate fallback)
        self._last_partial_emitted = ""       # last partial SHOWN (monotonic guard)
        self._last_partial_samples = 0
        self._last_partial_time = 0.0

    # ── Permissions (no-op: Parakeet needs no TCC grant) ──

    @staticmethod
    def authorize(timeout: float = 10.0) -> bool:
        """Parity with StreamingSTT.authorize(). Parakeet is a local model with no
        system permission, so this always succeeds."""
        return True

    @property
    def supports_on_device(self) -> bool:
        return True

    # ── Lifecycle ──

    def start(self):
        """Load + pre-warm the model, then start the inference worker."""
        t0 = time.time()
        self._model = _get_shared_model(self._model_repo)
        self._pcfg = self._model.preprocessor_config
        # Warm the compute graph so the first real utterance doesn't pay JIT cost.
        try:
            _decode(self._model, self._pcfg, np.zeros(int(0.5 * self._sample_rate), dtype=np.float32))
        except Exception:
            pass
        self._running = True
        self._worker = threading.Thread(target=self._run, daemon=True,
                                        name="ParakeetSTT-worker")
        self._worker.start()
        print(f"[ParakeetSTT] Ready in {time.time() - t0:.1f}s "
              f"({len(self._glossary)} glossary terms)")

    def set_contextual_strings(self, strings: list):
        """Update the correction vocabulary (takes effect on the next transcription)."""
        self._glossary = build_glossary(strings)

    def feed(self, audio: np.ndarray):
        """Append a 16kHz mono float32 chunk. Non-blocking — never runs the model, so
        it's safe to call from the audio callback thread."""
        if not self._running or audio is None or len(audio) == 0:
            return
        chunk = np.ascontiguousarray(audio, dtype=np.float32)
        with self._buf_lock:
            self._buf.append(chunk)
            self._buf_samples += len(chunk)
        self._wake.set()

    def rotate(self):
        """End the current utterance: run a final decode over the whole buffer and
        deliver it via on_final, synchronously (bounded by _FINALIZE_TIMEOUT), then
        reset for the next utterance."""
        if not self._running:
            return
        with self._buf_lock:
            has_audio = self._buf_samples >= self._MIN_SAMPLES
        if not has_audio:
            self._reset_buffer()
            return

        self._final_ready.clear()
        self._finalize = True
        self._wake.set()
        got = self._final_ready.wait(timeout=self._FINALIZE_TIMEOUT)
        text = (self._final_text if got else self._last_text).strip()
        self._final_text = ""
        if text and self._on_final:
            self._on_final(text)

    def stop(self):
        """Stop the worker and release."""
        self._running = False
        self._wake.set()
        if self._worker is not None:
            self._worker.join(timeout=3.0)
        print("[ParakeetSTT] Stopped")

    # ── Worker ──

    def _run(self):
        while self._running:
            self._wake.wait(timeout=self._PARTIAL_INTERVAL)
            self._wake.clear()
            if not self._running:
                break

            # Finalize takes priority over partials.
            if self._finalize:
                final = self._transcribe_current()
                # A one-shot decode of a long/noisy buffer can come back empty even
                # when partials had content; fall back to the last good partial so a
                # real utterance is never dropped.
                self._final_text = final or self._last_text
                self._reset_buffer()
                self._finalize = False
                self._final_ready.set()
                continue

            # Live partial: only re-decode when new audio has arrived and enough
            # time has passed since the last one (bounds cost + display flicker).
            with self._buf_lock:
                samples = self._buf_samples
            now = time.time()
            if (samples > self._last_partial_samples
                    and samples >= self._MIN_SAMPLES
                    and (now - self._last_partial_time) >= self._PARTIAL_INTERVAL):
                text = self._transcribe_current()
                self._last_partial_samples = samples
                self._last_partial_time = now
                # Monotonic guard: the live line may only GROW within an utterance.
                # A re-decode that comes back shorter (noisy audio makes Parakeet
                # revise) is held, not shown — so the interviewer's in-progress text
                # never visibly wipes/restarts mid-sentence. The final decode at
                # rotate() is the source of truth and corrects any lingering text.
                if text and len(text) >= len(self._last_partial_emitted):
                    self._last_partial_emitted = text
                    if self._on_partial:
                        self._on_partial(text)

    def _transcribe_current(self) -> str:
        """One-shot decode the current buffer → glossary-corrected text. Runs only on
        the worker thread. Snapshots the buffer under the lock, decodes outside it."""
        with self._buf_lock:
            if self._buf_samples < self._MIN_SAMPLES:
                return self._last_text
            audio = (self._buf[0] if len(self._buf) == 1
                     else np.concatenate(self._buf))
        try:
            text = _decode(self._model, self._pcfg, audio)
        except Exception as e:
            print(f"[ParakeetSTT] transcribe error: {e}")
            return self._last_text
        if text and self._glossary:
            text = correct_transcript(text, self._glossary)
        # Only advance _last_text on a non-empty decode — an empty result (long
        # silence/noise) must not wipe the last good partial rotate() may fall back to.
        if text:
            self._last_text = text
        return text

    def _reset_buffer(self):
        with self._buf_lock:
            self._buf = []
            self._buf_samples = 0
        self._last_partial_samples = 0
        self._last_partial_time = 0.0
        self._last_text = ""
        self._last_partial_emitted = ""


class ParakeetBatchTranscriber:
    """Batch one-shot transcriber for the USER voice path.

    UserVoiceTranscriber already does its own silence-cutting + echo-gating and just
    needs `transcribe(finished_utterance) -> {"text": ...}` — the same interface as
    WhisperEngine — so this is a drop-in swap for it. Shares the interviewer's loaded
    model + inference lock (no second model copy). Parakeet emits blanks on non-speech
    rather than inventing words, so it largely eliminates the Whisper "Yabba!" /
    "festivals festivals" hallucinations the user hit on their own mic.
    """

    def __init__(self, contextual_strings: list = None,
                 model_repo: str = DEFAULT_PARAKEET_MODEL,
                 sample_rate: int = WHISPER_SAMPLE_RATE):
        self._sample_rate = sample_rate
        self._glossary = build_glossary(contextual_strings)
        self._model = _get_shared_model(model_repo)
        self._pcfg = self._model.preprocessor_config

    def transcribe(self, audio: np.ndarray) -> dict:
        """One-shot decode a finished utterance. Returns {"text": ...} to match
        WhisperEngine so UserVoiceTranscriber's worker is unchanged."""
        if audio is None or len(audio) < int(0.2 * self._sample_rate):
            return {"text": ""}
        try:
            text = _decode(self._model, self._pcfg, audio)
        except Exception as e:
            print(f"[ParakeetBatch] transcribe error: {e}")
            return {"text": ""}
        if text and self._glossary:
            text = correct_transcript(text, self._glossary)
        return {"text": text}
