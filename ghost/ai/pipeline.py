"""Ghost AI Pipeline — connects audio capture, dual-engine STT, and question detection.

This is the main orchestrator. Two speakers, two INDEPENDENT engines running at
the same time:

    Interviewer (BlackHole / app / mic single-source)
        → Apple on-device streaming STT (word-by-word, ~0.1-0.3s latency)
        → Question Detector → AI answer

    You (mic, only in dual-voice mode)
        → mlx-whisper (batch, ~1-2s/utterance) → conversation context (NO AI answer)

Why two engines instead of one time-shared recognizer: macOS allows only a single
SFSpeechRecognizer, and sharing it between the two sources starved one side and
caused the recurring user/interviewer mislabeling. Giving YOUR voice its own
mlx-whisper engine means both people are transcribed simultaneously, the
interviewer's low-latency recognizer is never interrupted, and the mislabeling
bug is structurally impossible (see user_voice.py's echo gate).

Usage:
    pipeline = GhostAIPipeline(target_app="zoom.us", on_question=handle_question)
    pipeline.start()
    ...
    pipeline.stop()
"""

import time
import threading
import numpy as np

from ghost.ai.audio_capture import (
    AudioCapture, MicCapture, BlackHoleCapture,
    WHISPER_SAMPLE_RATE as CAPTURE_SAMPLE_RATE,
)
from ghost.ai.streaming_stt import StreamingSTT, WHISPER_SAMPLE_RATE
from ghost.ai.question_detector import QuestionDetector, SilenceDetector
from ghost.ai.user_voice import UserVoiceTranscriber


# Energy above which the interviewer (a clean BlackHole/app feed) counts as
# "present". Low, because the digital call signal is clean - any real energy on it
# means the interviewer is talking.
_IV_PRESENT_ENERGY = 0.006

# Interviewer HANGOVER: once the interviewer has signal, treat them as "still
# holding the floor" for this long after their last energy. Bridges the natural
# gaps between words so the user-voice echo gate stays closed through a brief pause
# in the interviewer's speech (prevents echo leaking into the user transcript).
_IV_HANGOVER = 0.7

# Interviewer backstop: force-finalize after this many seconds with no detected
# pause (noisy VoIP lines never go fully quiet -> words would never commit otherwise).
# Raised from 12s so a long continuous question is far less likely to be chopped
# mid-sentence (the chop clips trailing audio and splits the question).
MAX_UTTERANCE_SECONDS = 20.0

# Merge window: after an interviewer utterance finalizes on a pause, hold it this
# long before answering. If the interviewer starts speaking again within the window
# (they were just pausing mid-question), the next utterance is COALESCED into the
# same question - so a mid-question pause is never answered as if it were the whole
# question. The manual answer-now hotkey bypasses this entirely.
MERGE_WINDOW_SECONDS = 1.6

# Completeness gate: a finalized fragment that trails off mid-clause (no terminal
# punctuation, ends on a connective/function word) is a PAUSE, not the end of the
# question — hold it (up to the cap) for the continuation instead of answering half the
# question and then answering the rest as a disconnected new one.
_COMPLETE_HOLD_CAP = 2.5
_INCOMPLETE_TAIL = {
    "and", "but", "so", "or", "because", "the", "a", "an", "to", "of", "for", "with",
    "in", "on", "at", "as", "is", "are", "was", "were", "that", "which", "what", "how",
    "when", "where", "why", "who", "can", "could", "would", "should", "do", "does", "did",
    "if", "my", "your", "our", "their", "i", "we", "you", "they", "he", "she", "it",
    "this", "these", "those", "about", "into", "like", "between", "from", "than", "then",
    "also", "not", "um", "uh", "okay",
}


def _looks_incomplete(text: str) -> bool:
    t = (text or "").strip()
    if not t or t[-1] in ".?!":
        return False                     # punctuated (Deepgram smart_format) → complete
    last = t.split()[-1].strip(",;:\"'").lower()
    return last in _INCOMPLETE_TAIL

# How often the dedicated flush thread checks whether a pending merged turn is
# ready to answer. See _flush_loop for why this is a thread and not piggybacked
# on incoming audio chunks.
_FLUSH_TICK_SECONDS = 0.25


class GhostAIPipeline:
    """Main AI pipeline: dual-engine STT -> question detection."""

    def __init__(
        self,
        target_app: str = None,
        target_pid: int = None,
        whisper_model: str = "small",
        on_question=None,
        on_partial=None,
        on_prefetch=None,
        on_transcript=None,
        on_status=None,
        on_audio_chunk=None,
        on_user_response=None,
        on_safety_trigger=None,
        on_audio_level=None,
        on_source_level=None,
        on_live_transcript=None,
        on_final_transcript=None,
        voice_profile_path: str = None,
        use_mic: bool = False,
        use_blackhole: bool = False,
        locale: str = "en-US",
        track_user_voice: bool = False,
        contextual_strings: list = None,
        use_parakeet: bool = False,
        use_deepgram: bool = False,
    ):
        """
        Args:
            target_app: App name to capture audio from (e.g., "zoom.us", "Google Chrome")
            target_pid: PID of app (alternative to target_app)
            whisper_model: mlx-whisper model for YOUR voice ("tiny"/"small"/...).
            on_question: Callback(text, confidence, is_follow_up) - complete question.
            on_partial: Callback(text, confidence) - partial question building (live).
            on_prefetch: Callback(text, confidence) - 70%+ confidence, start pre-fetching.
            on_transcript: Callback(text, latency) - live transcript.
            on_status: Callback(status_str) - pipeline status updates.
            on_audio_chunk: Callback(np.ndarray) - 16kHz mono chunks for logging.
            on_user_response: Callback(text) - user's transcribed spoken response.
            on_safety_trigger: Callback(trigger_text) - suspicious question -> auto-kill.
            on_audio_level: Callback(peak) - overall peak level (drives the greenlight
                + no-audio watchdog).
            on_source_level: Callback(source, peak) - PER-SOURCE level for the two
                meters ("interviewer" = them, "you" = your mic).
            on_live_transcript: Callback(source, text) - in-progress line.
            on_final_transcript: Callback(source, text) - committed line.
            track_user_voice: Also transcribe YOUR voice (mlx-whisper). Off = the
                interviewer-only default (mic never opened).
            locale: BCP-47 locale for the interviewer's speech recognition.
        """
        self._target_app = target_app
        self._target_pid = target_pid
        self._locale = locale
        self._whisper_model = whisper_model
        self._contextual_strings = contextual_strings or []
        self._use_parakeet = use_parakeet
        self._use_deepgram = use_deepgram
        # Deepgram emits a reliable ~0.5s end-of-speech signal (speech_final), so the
        # fragment-merge window — which exists to coalesce fragments from FLAKY on-device
        # endpointing — can be tiny. Left at 1.6s it would mask the cloud endpoint's speed.
        self._merge_window = 0.8 if use_deepgram else MERGE_WINDOW_SECONDS

        # Components
        self._capture = None
        self._stt = None                       # interviewer streaming STT (Apple)
        self._user_voice = None                # YOUR voice transcriber (mlx-whisper)

        # Wrap on_question to flush user response before firing next question
        self._original_on_question = on_question
        self._question_detector = QuestionDetector(
            on_question=self._on_question_with_user_flush,
            on_partial=on_partial,
            on_prefetch=on_prefetch,
        )

        # Callbacks
        self._on_transcript = on_transcript
        self._on_status = on_status
        self._on_audio_chunk = on_audio_chunk
        self._on_user_response = on_user_response
        self._on_safety_trigger = on_safety_trigger
        self._on_audio_level = on_audio_level
        self._on_source_level = on_source_level
        self._on_live_transcript = on_live_transcript
        self._on_final_transcript = on_final_transcript

        # Per-source level metering (peak-hold, emitted ~1/s each).
        self._level_peak = {"interviewer": 0.0, "you": 0.0}
        self._level_last_emit = {"interviewer": 0.0, "you": 0.0}
        self._overall_peak = 0.0
        self._overall_last_emit = 0.0

        # State
        self._running = False
        self._voice_profile_path = voice_profile_path
        self._use_mic = use_mic
        self._use_blackhole = use_blackhole
        self._track_user_voice = track_user_voice
        self._mic_capture = None
        self._bh_capture = None
        self._user_mic = None
        self._has_pending_utterance = False    # interviewer is mid-utterance
        self._suppress_next_final = False      # ignore the final after a manual answer-now

        # Interviewer turn segmentation (silence-based, one recognizer to itself now).
        self._iv_silence = SilenceDetector()
        self._iv_active_flag = False           # is an interviewer utterance in progress
        self._iv_utterance_start = 0.0
        self._iv_last_speech = 0.0             # last time the interviewer had energy
        # Pre-roll: the most recent below-threshold chunk while idle. Fed to the
        # recognizer right before the first energetic chunk of a new turn, so a
        # word that starts near the END of a 0.5s chunk (whose RMS stays under the
        # gate) isn't clipped - first-word loss is the classic failure of
        # chunk-level energy gating.
        self._iv_pre_roll = None
        # Pending merged interviewer turn awaiting the merge window before it's
        # answered (see MERGE_WINDOW_SECONDS). Coalesces fragments of one question.
        self._pending_answer_text = ""
        self._pending_answer_since = 0.0
        self._lock = threading.Lock()

        # Dedicated flush timer (started in start()). See _flush_loop.
        self._flush_thread = None

    def start(self):
        """Start capture -> dual-engine STT -> question detection."""
        self._status("Starting pipeline...")

        # Pick the interviewer STT engine. Both expose the SAME interface
        # (authorize/start/feed/rotate/stop + on_partial/on_final), so the rest of
        # the pipeline is engine-agnostic. Parakeet is the reliable on-device path
        # (no ~20-30min recognizer death, no vanishing partials); Apple stays as the
        # opt-out low-latency word-by-word engine. Parakeet is imported lazily so the
        # Apple path never pays the mlx/model load.
        if self._use_deepgram:
            # CLOUD path (opt-in): interviewer audio streams to Deepgram for a fast
            # ~0.5s endpoint. Lazily imported so the on-device paths never load it.
            from ghost.ai.deepgram_stt import DeepgramSTT
            engine_cls = DeepgramSTT
        elif self._use_parakeet:
            from ghost.ai.parakeet_stt import ParakeetSTT
            engine_cls = ParakeetSTT
        else:
            engine_cls = StreamingSTT

        # One-time Speech Recognition authorization (no-op for Parakeet / if granted).
        if not engine_cls.authorize():
            self._status("Speech Recognition not authorized - transcription disabled. "
                         "Grant it in System Settings → Privacy & Security → Speech Recognition.")

        # Interviewer STT (drives the AI).
        self._stt = engine_cls(
            locale=self._locale,
            on_partial=self._handle_iv_partial,
            on_final=self._handle_iv_final,
            contextual_strings=self._contextual_strings,
        )
        if self._use_deepgram:
            self._stt._label = "interviewer"
        self._stt.start()

        if self._use_blackhole:
            # BlackHole (the call) = the interviewer. Always captured; drives answers.
            self._bh_capture = BlackHoleCapture()
            self._bh_capture.start(
                on_audio_chunk=self._feed_interviewer,
                chunk_duration=0.5,
            )
            if self._track_user_voice:
                # YOUR voice -> its OWN mlx-whisper engine, running in parallel. The
                # interviewer's recognizer is never touched by this, so both speakers
                # are transcribed at once and the interviewer can't be mislabeled.
                self._start_user_voice()
                self._user_mic = MicCapture()
                self._user_mic.start_continuous(
                    on_audio_chunk=self._feed_user,
                    chunk_duration=0.5,
                )
                self._running = True
                self._status("Pipeline running - BLACKHOLE (interviewer, Apple STT) "
                             "+ MIC (you, Whisper), both live")
            else:
                self._running = True
                self._status("Pipeline running - BLACKHOLE (interviewer only; mic disabled)")
        elif self._use_mic:
            # Microphone as the single source - treated entirely as the interviewer.
            self._mic_capture = MicCapture()
            self._mic_capture.start_continuous(
                on_audio_chunk=self._feed_interviewer,
                chunk_duration=0.5,
            )
            self._running = True
            self._status("Pipeline running - listening via MICROPHONE")
        else:
            # ScreenCaptureKit per-app capture (single source = interviewer).
            self._capture = AudioCapture(
                target_app=self._target_app,
                target_pid=self._target_pid,
                chunk_duration=0.5,
            )
            self._capture.start(on_audio_chunk=self._feed_interviewer)
            self._running = True
            self._status("Pipeline running - listening for questions")

        # Merge-window flush runs on its own clock, not on incoming audio.
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

    def _flush_loop(self):
        """Answer pending merged turns on a wall-clock timer.

        Previously _maybe_flush_pending only ran inside _feed_interviewer, i.e.
        only when audio chunks were arriving. That coupling had two failure
        modes: (a) a BlackHole stall (the exact thing the capture watchdog
        exists for) stops chunks, so a fully-asked question sat unanswered
        until the stream recovered; (b) the ProcTap path only produces chunks
        while the target app emits audio, so a question asked right before the
        app went silent could hang indefinitely. A dedicated 4Hz timer makes
        the answer trigger independent of audio delivery.
        """
        while self._running:
            time.sleep(_FLUSH_TICK_SECONDS)
            self._maybe_flush_pending(time.time())

    def _start_user_voice(self):
        """Spin up the independent user-voice transcriber. With --deepgram, YOUR mic
        streams to a SECOND Deepgram connection (so BOTH voices now leave the machine);
        the interviewer-echo gate is applied in _feed_user so interviewer bleed-through
        is never mislabeled as 'you'."""
        if self._use_deepgram:
            from ghost.ai.deepgram_stt import DeepgramSTT
            self._user_voice = DeepgramSTT(
                locale=self._locale,
                on_partial=lambda t: self._handle_user_live(),
                on_final=self._handle_user_final,
                contextual_strings=self._contextual_strings,
                label="you",
            )
            self._user_voice.start()
            return
        self._user_voice = UserVoiceTranscriber(
            on_final=self._handle_user_final,
            on_live=self._handle_user_live,
            is_interviewer_active=self._interviewer_active,
            whisper_model=self._whisper_model,
            use_parakeet=self._use_parakeet,
            contextual_strings=self._contextual_strings,
        )
        self._user_voice.start()

    def stop(self):
        """Stop the pipeline."""
        self._running = False

        if self._capture:
            self._capture.stop()
        if self._mic_capture:
            self._mic_capture.stop_continuous()
        if self._bh_capture:
            self._bh_capture.stop()
        if self._user_mic:
            self._user_mic.stop_continuous()
        if self._user_voice:
            self._user_voice.stop()
        if self._stt:
            self._stt.stop()

        # Drop anything still pending so a restart can't answer a stale question.
        with self._lock:
            self._pending_answer_text = ""
            self._iv_active_flag = False
            self._iv_pre_roll = None

        self._status("Pipeline stopped")

    def record_voice_sample(self, duration: float = 5.0, save_path: str = None) -> np.ndarray:
        """Record the user's voice (legacy speaker-diarization helper)."""
        self._status(f"Recording voice sample for {duration}s...")
        mic = MicCapture()
        sample = mic.record_voice_sample(duration=duration)
        self._status("Voice sample recorded")
        return sample

    def add_user_response(self, text: str):
        """Manually record what the user said (for conversation tracking)."""
        self._question_detector.add_user_response(text)

    def get_conversation(self) -> list[dict]:
        """Get the full conversation history."""
        return self._question_detector.conversation.get_conversation()

    def get_formatted_conversation(self) -> str:
        """Get conversation formatted for Claude context."""
        return self._question_detector.conversation.get_formatted_history()

    def force_process(self):
        """Force process the current transcript buffer as a question."""
        if self._stt:
            self._stt.rotate()  # flush any in-flight audio to a final
        self._question_detector.force_process()

    def answer_now(self):
        """Manual hotkey - answer the interviewer's current question immediately,
        from the text captured so far (zero extra STT latency). Includes any pending
        merged fragments so the WHOLE question is answered, not just the last piece."""
        buf_text = self._question_detector.buffer.get_current_text().strip()
        self._has_pending_utterance = False
        with self._lock:
            self._iv_active_flag = False
            pending = self._pending_answer_text
            self._pending_answer_text = ""
        if self._stt:
            self._suppress_next_final = True
            self._stt.rotate()
            # rotate() delivers its final synchronously, so the flag has been
            # consumed by now if anything was in flight. Clear it regardless -
            # a flag left armed (hotkey pressed with nothing transcribing) would
            # swallow the NEXT real utterance's final.
            self._suppress_next_final = False
        # Answer = already-finalized pending fragments + the in-flight buffer.
        answer_text = " ".join(t for t in (pending, buf_text) if t).strip()
        if not answer_text:
            self._status("Answer-now pressed, but nothing transcribed yet")
            return
        self._status(f"Answer now (manual trigger): {answer_text[:60]}")
        # Pending fragments were already shown in the transcript as they finalized;
        # only the not-yet-committed buffer still needs to be emitted to the display.
        if buf_text and self._on_final_transcript:
            self._on_final_transcript("interviewer", buf_text)
        self._question_detector.emit_now(answer_text)

    # ── Interviewer path (BlackHole / app / mic single-source) ──

    def _interviewer_active(self) -> bool:
        """True if the interviewer had energy within the hangover window. Used by the
        user-voice echo gate so mic echo of the interviewer is never transcribed."""
        return (time.time() - self._iv_last_speech) < _IV_HANGOVER

    def _feed_interviewer(self, audio_chunk: np.ndarray):
        """Feed interviewer audio into the Apple recognizer, segmenting on silence."""
        if not self._running or self._stt is None:
            return

        energy = float(np.sqrt(np.mean(audio_chunk ** 2)))
        now = time.time()
        self._emit_levels("interviewer", energy, now)

        if self._on_audio_chunk:
            self._on_audio_chunk(audio_chunk)

        finalize_reason = None
        pre_roll = None
        with self._lock:
            if energy > _IV_PRESENT_ENERGY:
                self._iv_last_speech = now

            if not self._iv_active_flag:
                if energy > _IV_PRESENT_ENERGY:
                    # Idle -> start a turn. Grab the pre-roll chunk (the quiet
                    # chunk immediately before this one) so speech that began
                    # near the end of that chunk isn't clipped.
                    self._iv_active_flag = True
                    self._iv_utterance_start = now
                    self._iv_silence.reset()
                    pre_roll = self._iv_pre_roll
                    self._iv_pre_roll = None
                    if pre_roll is not None:
                        self._stt.feed(pre_roll)
                    self._stt.feed(audio_chunk)
                else:
                    # Still idle: remember this chunk as the next turn's pre-roll.
                    self._iv_pre_roll = audio_chunk
                return

            # Mid-turn: keep feeding, finalize on a pause or the backstop.
            self._stt.feed(audio_chunk)
            info = self._iv_silence.feed_audio(audio_chunk)
            silence_done = info["is_silent"] and info["silence_type"] in ("medium", "long")
            too_long = (now - self._iv_utterance_start) >= MAX_UTTERANCE_SECONDS
            if silence_done or too_long:
                self._iv_active_flag = False
                self._iv_silence.reset()
                finalize_reason = "silence" if silence_done else "backstop"

        # rotate() delivers the final synchronously into _handle_iv_final, which
        # takes self._lock - so it MUST run outside the lock above (threading.Lock
        # is not reentrant, and holding it here would deadlock).
        if finalize_reason is not None:
            print(f"[Pipeline] Finalizing interviewer utterance ({finalize_reason})")
            self._stt.rotate()  # -> _handle_iv_final

    # ── User path (mic -> mlx-whisper, parallel, context only) ──

    def _feed_user(self, audio_chunk: np.ndarray):
        """Feed mic audio into the independent user-voice transcriber."""
        if not self._running or self._user_voice is None:
            return
        energy = float(np.sqrt(np.mean(audio_chunk ** 2)))
        self._emit_levels("you", energy, time.time())
        if self._on_audio_chunk:
            self._on_audio_chunk(audio_chunk)
        # Echo gate for the Deepgram user path: UserVoiceTranscriber gates internally,
        # but a raw DeepgramSTT does not — drop mic audio while the interviewer is active
        # so their bleed-through the mic is never transcribed as "you".
        if self._use_deepgram and self._interviewer_active():
            return
        self._user_voice.feed(audio_chunk)

    # ── Level metering (per-source + overall) ──

    def _emit_levels(self, source: str, energy: float, now: float):
        """Peak-hold per-source and overall levels, emitted ~once/sec each."""
        # Per-source meter.
        self._level_peak[source] = max(self._level_peak[source], energy)
        if self._on_source_level and (now - self._level_last_emit[source]) >= 1.0:
            self._level_last_emit[source] = now
            self._on_source_level(source, self._level_peak[source])
            self._level_peak[source] = 0.0

        # Overall level (greenlight dot + no-audio watchdog).
        self._overall_peak = max(self._overall_peak, energy)
        if self._on_audio_level and (now - self._overall_last_emit) >= 1.0:
            self._overall_last_emit = now
            self._on_audio_level(self._overall_peak)
            self._overall_peak = 0.0

    # ── STT result handlers ──

    def _handle_iv_partial(self, text: str):
        """Live partial from the interviewer recognizer (cumulative)."""
        text = text.strip()
        if not text:
            return
        if self._check_safety(text):
            return
        if self._on_live_transcript:
            self._on_live_transcript("interviewer", text)
        self._has_pending_utterance = True
        self._question_detector.set_partial_transcript(text)

    def _handle_iv_final(self, text: str):
        """A finalized interviewer utterance (they paused). Commit it to the transcript
        immediately, but DON'T answer yet - queue it for the merge window so a
        mid-question pause is coalesced with the continuation instead of being
        answered as a fragment (see _maybe_flush_pending)."""
        text = text.strip()
        self._has_pending_utterance = False

        if self._suppress_next_final:
            self._suppress_next_final = False
            return
        if not text:
            return

        print(f"[Pipeline] Final (interviewer fragment): {text[:100]}")
        if self._check_safety(text):
            return
        if self._on_final_transcript:
            self._on_final_transcript("interviewer", text)
        # Queue for merge (the display already merges consecutive interviewer turns,
        # so we only accumulate text here for the ANSWER).
        with self._lock:
            self._pending_answer_text = (
                (self._pending_answer_text + " " + text).strip()
                if self._pending_answer_text else text
            )
            self._pending_answer_since = time.time()

    def _maybe_flush_pending(self, now: float):
        """Answer the merged interviewer turn once it's stayed quiet for the merge
        window. Called from the flush thread (it acquires the lock itself)."""
        with self._lock:
            if not self._running:
                return
            if not self._pending_answer_text or self._iv_active_flag:
                return
            if (now - self._pending_answer_since) < self._merge_window:
                return
            # Don't answer a question that trailed off mid-clause; wait for the rest
            # (bounded by the cap so a genuine trail-off still eventually fires).
            if (_looks_incomplete(self._pending_answer_text)
                    and (now - self._pending_answer_since) < _COMPLETE_HOLD_CAP):
                return
            text = self._pending_answer_text
            self._pending_answer_text = ""
        print(f"[Pipeline] Answering merged interviewer turn: {text[:100]}")
        self._question_detector.process_final(text)

    def _handle_user_live(self):
        """The user is actively speaking - show a live 'you' indicator (Whisper is
        batch, so there are no partial words yet, just an 'I hear you' pulse)."""
        if self._on_live_transcript:
            self._on_live_transcript("you", "🎤 …")

    def _handle_user_final(self, text: str):
        """A finished user utterance was transcribed by Whisper - context only."""
        text = text.strip()
        if not text:
            return
        print(f"[Pipeline] Final (you): {text[:100]}")
        if self._check_safety(text):
            return
        if self._on_final_transcript:
            self._on_final_transcript("you", text)
        self._question_detector.add_user_response(text)
        if self._on_user_response:
            self._on_user_response(text)

    # ── Safety ──

    _SAFETY_PATTERNS = [
        "are you using any tools",
        "are you using ai",
        "are you using chatgpt",
        "are you using an ai",
        "are you cheating",
        "are you getting help",
        "is someone helping you",
        "are you looking something up",
        "are you reading something",
        "do you have notes",
        "are you using notes",
        "what are you looking at",
        "why are you looking away",
        "what's on your screen",
    ]

    def _check_safety(self, text: str) -> bool:
        """Check if transcript contains suspicious phrases. Returns True if triggered."""
        text_lower = text.lower()
        for pattern in self._SAFETY_PATTERNS:
            if pattern in text_lower:
                print(f"[Pipeline] SAFETY TRIGGER: '{pattern}' detected in transcript")
                if self._on_safety_trigger:
                    self._on_safety_trigger(text)
                return True
        return False

    def notify_answer_done(self):
        """No-op: user speech is captured continuously via the parallel Whisper engine."""
        return

    def _on_question_with_user_flush(self, text, confidence, is_follow_up):
        """Pass an interviewer question through to the AI trigger."""
        if self._original_on_question:
            self._original_on_question(text, confidence, is_follow_up)

    def _status(self, msg: str):
        """Emit status update."""
        print(f"[GhostAI] {msg}")
        if self._on_status:
            self._on_status(msg)