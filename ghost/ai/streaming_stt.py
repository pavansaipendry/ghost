"""Real-time streaming STT for Ghost AI — Apple on-device speech recognition.

Unlike the chunked Whisper pipeline (which needs a 3.5s window before it can
transcribe), this streams PARTIAL results word-by-word as audio arrives — "hey…
what's… up…" appears live. It runs fully on-device (no network, no cost, nothing
to detect), which preserves Ghost's stealth philosophy.

Engine: SFSpeechRecognizer + SFSpeechAudioBufferRecognitionRequest with
requiresOnDeviceRecognition = True.

Feed it 16kHz mono float32 numpy chunks (same format the rest of Ghost produces):

    stt = StreamingSTT(on_partial=lambda t: print(t), on_final=lambda t: ...)
    stt.authorize()         # one-time TCC permission
    stt.start()
    stt.feed(chunk_16k)     # call repeatedly as audio arrives
    ...
    stt.stop()

NOTE: a single SFSpeech recognition task has a finite duration. For a long
interview, call rotate() on silence/utterance boundaries to start a fresh task.
"""

import threading
import time

import numpy as np
import AVFoundation
import Speech
from Foundation import NSLocale, NSRunLoop, NSDate


# SFSpeechRecognizerAuthorizationStatus
_AUTH_NOT_DETERMINED = 0
_AUTH_DENIED = 1
_AUTH_RESTRICTED = 2
_AUTH_AUTHORIZED = 3

WHISPER_SAMPLE_RATE = 16000


class StreamingSTT:
    """Apple on-device streaming speech recognition over fed numpy audio."""

    def __init__(self, locale: str = "en-US", on_partial=None, on_final=None,
                 on_device: bool = True, sample_rate: int = WHISPER_SAMPLE_RATE,
                 contextual_strings: list = None):
        """
        Args:
            locale: BCP-47 locale, e.g. "en-US".
            on_partial: Callback(text) - fires continuously as words are recognized.
            on_final:   Callback(text) - fires when a recognition result is final.
            on_device:  Force on-device recognition (local, no network).
            sample_rate: Sample rate of the audio you'll feed (must match chunks).
            contextual_strings: Domain vocabulary (tech terms, product/project names,
                acronyms) to bias recognition toward - words like "PyTorch", "RLHF",
                "Pinecone" that the general model otherwise mishears. On-device hint only.
        """
        self._on_partial = on_partial
        self._on_final = on_final
        self._on_device = on_device
        self._sample_rate = sample_rate
        self._contextual_strings = list(contextual_strings) if contextual_strings else []

        ns_locale = NSLocale.localeWithLocaleIdentifier_(locale)
        self._recognizer = Speech.SFSpeechRecognizer.alloc().initWithLocale_(ns_locale)
        if self._recognizer is None:
            raise RuntimeError(f"No speech recognizer for locale {locale!r}")

        # float32, mono, non-interleaved - matches Ghost's 16kHz mono chunks.
        self._fmt = AVFoundation.AVAudioFormat.alloc().\
            initStandardFormatWithSampleRate_channels_(float(sample_rate), 1)

        self._request = None
        self._task = None
        self._running = False
        self._lock = threading.Lock()
        self._last_text = ""

        # Generation counter for stale-callback rejection. Apple delivers task
        # results asynchronously on its own queue, and task.cancel() does NOT
        # guarantee no more callbacks - a partial computed just before the cancel
        # can land AFTER rotate() has reset _last_text for the next utterance.
        # Without this guard, that stale partial (the ENTIRE previous utterance)
        # overwrites _last_text, and the next rotate() delivers it as a final
        # again: the same question gets answered twice, and the question detector
        # receives ghost partials of text that was already committed. Each task's
        # result handler captures its generation and drops results once a newer
        # task exists.
        self._generation = 0

    # ── Permissions ──

    @staticmethod
    def authorize(timeout: float = 10.0) -> bool:
        """Request Speech Recognition authorization (one-time TCC prompt).

        Returns True if authorized. From a bare script the prompt may not appear
        without an Info.plist NSSpeechRecognitionUsageDescription - Ghost's .app
        bundle supplies that, so this "just works" in the packaged app.
        """
        result = {"status": None}

        def _handler(status):
            result["status"] = status

        Speech.SFSpeechRecognizer.requestAuthorization_(_handler)

        deadline = time.time() + timeout
        while result["status"] is None and time.time() < deadline:
            NSRunLoop.currentRunLoop().runUntilDate_(
                NSDate.dateWithTimeIntervalSinceNow_(0.05)
            )
        status = result["status"]
        names = {0: "not_determined", 1: "denied", 2: "restricted", 3: "authorized"}
        print(f"[StreamingSTT] Speech auth: {names.get(status, status)}")
        return status == _AUTH_AUTHORIZED

    @property
    def supports_on_device(self) -> bool:
        return bool(self._recognizer.supportsOnDeviceRecognition())

    # ── Lifecycle ──

    def start(self):
        """Begin a recognition task. Partial results stream via on_partial."""
        with self._lock:
            self._start_task_locked()
            self._running = True
        print(f"[StreamingSTT] Started (on_device={self._on_device}, "
              f"supported={self.supports_on_device})")

    def _start_task_locked(self):
        req = Speech.SFSpeechAudioBufferRecognitionRequest.alloc().init()
        req.setShouldReportPartialResults_(True)
        if self._on_device and self.supports_on_device:
            req.setRequiresOnDeviceRecognition_(True)
        # Bias recognition toward my domain vocabulary (resume/JD jargon, project &
        # product names) so the recognizer stops mangling the terms that matter most.
        if self._contextual_strings:
            try:
                req.setContextualStrings_(self._contextual_strings)
            except Exception as e:
                print(f"[StreamingSTT] contextualStrings unsupported, skipping: {e}")

        # New task = new generation. The handler closure captures ITS generation;
        # once rotate()/stop() bumps the counter, anything the old task still
        # delivers is dropped instead of polluting the next utterance's state.
        self._generation += 1
        gen = self._generation

        def _result_handler(result, error):
            if gen != self._generation:
                # Stale callback from a cancelled task. This also swallows the
                # cancellation error Apple fires on every task.cancel(), which
                # would otherwise spam the log once per rotate.
                return
            if error is not None and result is None:
                # A live task errored (recognizer hiccup, model issue). Audio
                # keeps being fed but nothing transcribes until the next
                # rotate() builds a fresh task - the silence/backstop finalize
                # guarantees that happens within MAX_UTTERANCE_SECONDS, so this
                # self-heals; log it so a recurring failure is visible.
                print(f"[StreamingSTT] Recognition task error: {error}")
                return
            # We rely on PARTIALS only. The "final" for an utterance is the last
            # partial we saw, delivered by rotate() - this avoids depending on the
            # async isFinal callback, which is unreliable across rapid task restarts.
            if result is not None:
                text = str(result.bestTranscription().formattedString())
                self._last_text = text
                if not bool(result.isFinal()) and self._on_partial:
                    self._on_partial(text)

        self._request = req
        self._task = self._recognizer.recognitionTaskWithRequest_resultHandler_(
            req, _result_handler
        )
        self._last_text = ""

    def set_contextual_strings(self, strings: list):
        """Update the recognition bias vocabulary. Takes effect on the next recognition
        task (i.e. after the next rotate()), so it never disrupts an in-flight utterance."""
        with self._lock:
            self._contextual_strings = list(strings) if strings else []

    def feed(self, audio: np.ndarray):
        """Feed a 16kHz mono float32 chunk into the recognizer."""
        if not self._running:
            return
        n = len(audio)
        if n == 0:
            return

        with self._lock:
            if self._request is None:
                self._start_task_locked()
            req = self._request
        if req is None:
            return

        buf = AVFoundation.AVAudioPCMBuffer.alloc().\
            initWithPCMFormat_frameCapacity_(self._fmt, n)
        buf.setFrameLength_(n)
        # floatChannelData() -> tuple of objc.varlist; varlist supports slice-assign.
        channel = buf.floatChannelData()[0]
        channel[0:n] = np.ascontiguousarray(audio, dtype=np.float32).tolist()
        # Known benign race: rotate() can cancel this request between the lock
        # release above and this append. Appending to a cancelled request is a
        # no-op, so at worst one 0.5s chunk at the utterance boundary is dropped.
        req.appendAudioPCMBuffer_(buf)

    def rotate(self):
        """End the current utterance: deliver the last partial as the final, then
        immediately start a fresh task for the next utterance.

        Using the last partial as the final (instead of awaiting the async isFinal)
        makes multi-utterance recognition reliable and lower-latency.
        """
        final_text = None
        with self._lock:
            if not self._running:
                return
            final_text = self._last_text
            if self._task is not None:
                try:
                    self._task.cancel()
                except Exception:
                    pass
            self._request = None
            self._task = None
            # Restart inside the SAME lock hold. If the lock were released first,
            # a concurrent feed() would see _request None and lazily start its own
            # task, and the restart here would create a second one - two live tasks
            # on one recognizer starve each other (audio flows, nothing transcribes).
            # _start_task_locked also bumps the generation, which is what makes the
            # cancel above safe: any result the cancelled task still delivers is
            # now stale and gets dropped by the handler's generation check.
            self._start_task_locked()

        if final_text and final_text.strip() and self._on_final:
            self._on_final(final_text)

    def stop(self):
        """Stop recognition and release the task."""
        with self._lock:
            self._running = False
            self._generation += 1  # invalidate any in-flight callbacks
            if self._task is not None:
                try:
                    self._task.cancel()
                except Exception:
                    pass
            self._request = None
            self._task = None
        print("[StreamingSTT] Stopped")