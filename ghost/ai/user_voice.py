"""User-voice transcriber - an INDEPENDENT mic -> mlx-whisper path.

Runs in PARALLEL with the interviewer's Apple streaming recognizer, so BOTH
speakers are transcribed at the same time. This is the fix for the old
"one recognizer, time-shared" design that could never hear both people at once
(macOS allows only a single SFSpeechRecognizer, so sharing it starved one side
and produced the recurring user/interviewer mislabeling).

Design:
  * The interviewer keeps the low-latency Apple on-device recognizer (it drives
    the AI answer, so every 100ms counts).
  * YOUR voice goes to mlx-whisper here. Your words are conversation CONTEXT only
    (they never trigger an answer), so batch Whisper latency (~1-2s per utterance)
    is completely fine - and it's a SEPARATE engine, so it can never starve the
    interviewer's recognizer.

Utterances are cut on silence; each finished utterance is transcribed off the
audio thread and delivered via on_final(text).

ECHO SUPPRESSION (why mislabeling is now structurally impossible): chunks that
arrive while the interviewer is speaking are DROPPED - never buffered. On speakers,
the interviewer bleeds into the mic, but that audio is discarded instead of being
transcribed as "you". The user transcriber only ever sees audio captured while the
interviewer is silent, so the interviewer can never be mislabeled as the user.
"""

import queue
import threading
import time
from collections import Counter

import numpy as np

from ghost.ai.whisper_engine import WhisperEngine, WHISPER_SAMPLE_RATE


# Energy above which a mic chunk counts as the user actually speaking.
_SPEECH_ON_ENERGY = 0.015

# Finalize a user utterance after this much continuous silence (generous enough
# not to clip a normal mid-thought pause; the user path isn't latency-critical).
_SILENCE_FINALIZE = 1.5

# Never let a single user utterance grow past this (backstop for noisy mics).
_MAX_UTTERANCE_SECONDS = 30.0

# Require at least this much *voiced* audio before we bother transcribing -
# filters out coughs, keyboard clicks, and stray noise blips.
_MIN_VOICED_SECONDS = 0.4

# Before the user has actually spoken, keep only this much trailing audio as
# pre-roll (captures the word onset without buffering minutes of ambient noise).
_PREROLL_SECONDS = 0.5


# Whisper's classic outputs when fed marginal audio (breath, keyboard, room tone
# that squeaked past the energy gate). These are hallucinations, not the user.
# Deliberately does NOT blanket-ban all single words: "yes" / "no" / "sure" are
# perfectly legitimate things an interviewee says, and this transcript is
# conversation context, so dropping real short answers would be worse than the
# occasional stray filler slipping through.
_HALLUCINATION_EXACT = {
    "thank you", "thanks", "oh", "so", "he just got",
    "you", "bye", "bye bye", "good bye", "goodbye",
    "hmm", "uh", "um", "ah", "huh",
    "i'm going to get out of here",
    "so i'm going to get out of here",
    "thank you for watching",
    "thanks for watching",
    "please subscribe",
    "like and subscribe",
}


def _is_hallucination(text: str) -> bool:
    """Light hallucination filter for user-context transcripts.

    Catches Whisper's noise-induced outputs (known phrases, one word repeated
    over and over, looping n-grams) without banning legitimate short answers.
    """
    text = text.strip()
    if not text:
        return True

    lower = text.lower().strip().rstrip(".,!?")
    if lower in _HALLUCINATION_EXACT:
        return True

    words = lower.split()
    if len(words) < 4:
        return False  # short real answers ("yes", "sounds good") pass through

    # One word dominating the output ("him him him him...").
    _, top_count = Counter(words).most_common(1)[0]
    if top_count / len(words) > 0.5:
        return True

    # Looping n-grams ("gonna be gonna be gonna be...").
    for n in (2, 3, 4):
        if len(words) >= n * 3:
            ngrams = [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]
            _, top = Counter(ngrams).most_common(1)[0]
            if top >= 3 and top / len(ngrams) > 0.25:
                return True

    return False


class UserVoiceTranscriber:
    """Mic -> silence-segmented utterances -> mlx-whisper, on its own thread.

    Feed it 16kHz mono float32 chunks via feed(). It commits finished utterances
    through on_final(text). Call is_interviewer_active to gate out interviewer echo.
    """

    def __init__(
        self,
        on_final=None,
        on_live=None,
        is_interviewer_active=None,
        whisper_model: str = "small",
        sample_rate: int = WHISPER_SAMPLE_RATE,
        use_parakeet: bool = False,
        contextual_strings: list = None,
    ):
        """
        Args:
            on_final: Callback(text) - a finished user utterance was transcribed.
            on_live:  Callback() - fired while the user is actively speaking, so the
                      UI can show a live "you" indicator (Whisper is batch, so there
                      are no partial words, just an "I hear you" pulse).
            is_interviewer_active: Callable() -> bool. When True, incoming mic audio is
                      treated as interviewer echo and DROPPED (never transcribed).
            whisper_model: mlx-whisper model size ("tiny"/"small"/...). "small" is a
                      good accuracy/speed balance for context-only transcription.
            sample_rate: Sample rate of the fed audio (must be 16kHz mono).
        """
        self._on_final = on_final
        self._on_live = on_live
        self._is_iv_active = is_interviewer_active or (lambda: False)
        self._sample_rate = sample_rate
        self._preroll_samples = int(_PREROLL_SECONDS * sample_rate)
        self._min_voiced_samples = int(_MIN_VOICED_SECONDS * sample_rate)
        self._max_samples = int(_MAX_UTTERANCE_SECONDS * sample_rate)

        # Engine: Parakeet (shared with the interviewer path — emits blanks on
        # non-speech, so it kills Whisper's silence hallucinations) or mlx-whisper.
        self._use_parakeet = use_parakeet
        if use_parakeet:
            from ghost.ai.parakeet_stt import ParakeetBatchTranscriber
            self._engine = ParakeetBatchTranscriber(contextual_strings=contextual_strings)
        else:
            self._engine = WhisperEngine(model=whisper_model)

        # Utterance buffer state. feed() runs on the mic callback thread, but
        # flush() (hotkey) and stop() (main thread) also touch this state - the
        # old "audio thread only" assumption was false, so a flush racing a feed
        # could concatenate a half-updated buffer or lose a chunk. Everything
        # below is guarded by _state_lock now.
        self._state_lock = threading.Lock()
        self._buffer = []              # list[np.ndarray] - current utterance audio
        self._buffered_samples = 0
        self._voiced_samples = 0       # how much of the buffer was actual speech
        self._has_voice = False        # has the user spoken in this utterance yet
        self._last_voice_time = 0.0    # wall clock of the last voiced chunk

        # Background transcription (keeps mlx-whisper off the audio callback thread).
        self._jobs = queue.Queue()
        self._running = False
        self._worker = None

    # ── Lifecycle ──

    def start(self):
        """Start the transcription worker and pre-warm the model."""
        self._running = True
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        # Pre-warm: load the model now (first real utterance shouldn't pay for it).
        self._jobs.put(("warmup", np.zeros(int(0.5 * self._sample_rate), dtype=np.float32)))
        engine = "Parakeet (shared model)" if self._use_parakeet else "mlx-whisper"
        print(f"[UserVoice] Started ({engine}, independent of interviewer recognizer)")

    def stop(self):
        """Flush any in-progress utterance and stop the worker.

        The flushed utterance is queued BEFORE the stop sentinel, so it still
        gets transcribed - but _running goes False first, so its on_final is
        suppressed (nothing should mutate conversation state after stop()).
        If you want that last utterance delivered, call flush() first, give the
        worker a beat, then stop().
        """
        self._running = False
        self._flush_utterance()
        self._jobs.put(("stop", None))
        print("[UserVoice] Stopped")

    def flush(self):
        """Force-finalize the current utterance (e.g. hotkey cut)."""
        self._flush_utterance()

    # ── Audio intake (called from the mic callback thread) ──

    def feed(self, audio: np.ndarray):
        """Feed a 16kHz mono float32 mic chunk."""
        if not self._running or audio is None or len(audio) == 0:
            return

        now = time.time()

        # ECHO GATE: while the interviewer is speaking, the mic is (on speakers) just
        # echoing them - drop the chunk entirely so it can never be transcribed as
        # "you". The growing silence gap will finalize whatever the user said before.
        if self._is_iv_active():
            with self._state_lock:
                should_flush = (self._has_voice and
                                (now - self._last_voice_time) >= _SILENCE_FINALIZE)
            if should_flush:
                self._flush_utterance()
            return

        energy = float(np.sqrt(np.mean(audio ** 2)))
        voiced = energy > _SPEECH_ON_ENERGY

        flush_needed = False
        with self._state_lock:
            if voiced:
                self._has_voice = True
                self._last_voice_time = now
                self._voiced_samples += len(audio)
                self._buffer.append(audio)
                self._buffered_samples += len(audio)
            elif self._has_voice:
                # In-utterance pause - keep the silence in the buffer so words don't
                # run together, then finalize once the pause is long enough.
                self._buffer.append(audio)
                self._buffered_samples += len(audio)
                if (now - self._last_voice_time) >= _SILENCE_FINALIZE:
                    flush_needed = True
            else:
                # No speech yet - keep only a short trailing pre-roll so we catch the
                # onset of the next word without buffering endless ambient noise.
                self._buffer.append(audio)
                self._buffered_samples += len(audio)
                self._trim_preroll_locked()

            # Hard cap so a continuously-noisy mic can't buffer forever.
            if self._has_voice and self._buffered_samples >= self._max_samples:
                flush_needed = True

        # on_live outside the lock: it calls into UI/pipeline code we don't control,
        # and holding our state lock through foreign code is how deadlocks are born.
        if voiced and self._on_live:
            self._on_live()

        if flush_needed:
            self._flush_utterance()

    # ── Internals ──

    def _trim_preroll_locked(self):
        """Drop buffered samples beyond the pre-roll window (pre-speech only).
        Caller must hold _state_lock."""
        while self._buffered_samples > self._preroll_samples and len(self._buffer) > 1:
            dropped = self._buffer.pop(0)
            self._buffered_samples -= len(dropped)

    def _flush_utterance(self):
        """Hand the current utterance to the transcription worker and reset."""
        with self._state_lock:
            if not self._buffer or self._voiced_samples < self._min_voiced_samples:
                self._reset_utterance_locked()
                return
            audio = np.concatenate(self._buffer)
            self._reset_utterance_locked()
        self._jobs.put(("transcribe", audio))

    def _reset_utterance_locked(self):
        """Caller must hold _state_lock."""
        self._buffer = []
        self._buffered_samples = 0
        self._voiced_samples = 0
        self._has_voice = False

    def _worker_loop(self):
        while True:
            kind, audio = self._jobs.get()
            if kind == "stop":
                break
            try:
                result = self._engine.transcribe(audio)
                if kind == "warmup":
                    print("[UserVoice] Model warmed up")
                    continue
                text = (result.get("text") or "").strip()
                if not text:
                    continue
                # Whisper hallucinates fixed phrases on marginal audio (breath,
                # clicks, room tone that beat the energy gate). Without this
                # filter, "Thank you." and friends get committed as things YOU
                # said and fed to Claude as conversation context.
                if _is_hallucination(text):
                    print(f"[UserVoice] Dropped likely hallucination: {text[:60]!r}")
                    continue
                # No transcript mutations after stop(): a slow transcription
                # finishing post-shutdown must not resurrect the conversation.
                if self._running and self._on_final:
                    self._on_final(text)
            except Exception as e:
                print(f"[UserVoice] Transcription error: {e}")