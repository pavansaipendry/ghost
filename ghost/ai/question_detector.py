"""Smart Question Detector for Ghost AI.

Detects when the interviewer has finished asking a question by analyzing:
1. Silence patterns (short pause vs end of question)
2. Transcript completeness (grammar, question words)
3. Confidence scoring (0-100)
4. Conversation flow (ignore non-questions, detect follow-ups)

Usage:
    detector = QuestionDetector(on_question=my_callback)
    detector.feed_transcript("Tell me about your experience with")
    detector.feed_silence(duration=2.0)
    # callback fires when question is detected with high confidence
"""

import re
import time
import threading
import numpy as np


# Silence thresholds (seconds) - tuned for low latency
SILENCE_SHORT = 1.0     # Probably a pause, keep listening
SILENCE_MEDIUM = 2.0    # Might be done, classify
SILENCE_LONG = 3.0      # Definitely done, process it

# Energy threshold for silence detection
SILENCE_ENERGY = 0.01

# Question-ending patterns
QUESTION_ENDINGS = re.compile(
    r'(?:thoughts|experience|explain|describe|opinion|examples?|approach|'
    r'handle|manage|deal|solve|improve|design|build|create|'
    r'walk me through|tell me about|how would you|what would you|'
    r'can you|could you|have you|do you|did you|are you|were you|'
    r'why did|why do|why would|what is|what are|what was|'
    r'how do|how did|how is|how are|how was)\b.*[?]?\s*$',
    re.IGNORECASE
)

# Non-question patterns (statements, acknowledgments)
NON_QUESTION_PATTERNS = re.compile(
    r'^(?:that\'s (?:interesting|great|good|nice|cool|fine)|'
    r'okay|ok|sure|right|i see|got it|understood|makes sense|'
    r'mm-?hmm|uh-?huh|yeah|yes|no|alright|'
    r'thank you|thanks|great|good|perfect|awesome|wonderful|excellent)\s*[.!]?\s*$',
    re.IGNORECASE
)

# Filler/thinking words (interviewer still thinking)
FILLER_PATTERNS = re.compile(
    r'(?:^|\s)(?:um+|uh+|hmm+|so+|like|you know|basically|essentially|'
    r'let me think|actually|well)\s*$',
    re.IGNORECASE
)

# Incomplete sentence patterns (likely more coming)
# Only match if the word is preceded by a short fragment (< 5 words after it)
# "What tools do you work with" -> NOT incomplete (question pattern)
# "Tell me about" -> incomplete
INCOMPLETE_PATTERNS = re.compile(
    r'(?:^.{0,30})\s+(?:about|for|from|to|in|on|at|by|the|a|an|and|or|but|'
    r'if|because|since|while|although|though)\s*$',
    re.IGNORECASE
)


class SilenceDetector:
    """Detects silence periods in audio based on energy levels."""

    def __init__(self, sample_rate: int = 16000, energy_threshold: float = SILENCE_ENERGY):
        self._sample_rate = sample_rate
        self._energy_threshold = energy_threshold
        self._silence_start = None
        self._is_silent = False
        self._lock = threading.Lock()

    def feed_audio(self, audio: np.ndarray) -> dict:
        """Analyze audio chunk and return silence info.

        Args:
            audio: numpy float32 array at 16kHz mono

        Returns:
            dict with:
                "is_silent": bool
                "silence_duration": float (seconds, 0 if not silent)
                "silence_type": "none" | "short" | "medium" | "long"
                "energy": float
        """
        energy = float(np.sqrt(np.mean(audio ** 2)))

        with self._lock:
            now = time.time()

            if energy < self._energy_threshold:
                if not self._is_silent:
                    self._is_silent = True
                    self._silence_start = now

                duration = now - self._silence_start

                if duration >= SILENCE_LONG:
                    silence_type = "long"
                elif duration >= SILENCE_MEDIUM:
                    silence_type = "medium"
                elif duration >= SILENCE_SHORT:
                    silence_type = "short"
                else:
                    silence_type = "none"

                return {
                    "is_silent": True,
                    "silence_duration": duration,
                    "silence_type": silence_type,
                    "energy": energy,
                }
            else:
                self._is_silent = False
                self._silence_start = None
                return {
                    "is_silent": False,
                    "silence_duration": 0.0,
                    "silence_type": "none",
                    "energy": energy,
                }

    def reset(self):
        """Reset silence tracking."""
        with self._lock:
            self._is_silent = False
            self._silence_start = None


class TranscriptBuffer:
    """Accumulates transcript text and manages the current question buffer."""

    def __init__(self):
        self._buffer = []           # Current accumulating text segments
        self._full_history = []     # All past complete questions/statements
        self._lock = threading.Lock()

    def add_text(self, text: str):
        """Add transcribed text to the buffer."""
        text = text.strip()
        if not text:
            return
        with self._lock:
            self._buffer.append(text)

    def set_text(self, text: str):
        """REPLACE the buffer with text (for streaming partials, which are
        cumulative - each partial already contains the whole utterance so far)."""
        text = text.strip()
        with self._lock:
            self._buffer = [text] if text else []

    def get_current_text(self) -> str:
        """Get the current accumulated text."""
        with self._lock:
            return " ".join(self._buffer)

    def flush(self) -> str:
        """Flush the buffer, move text to history, return the flushed text."""
        with self._lock:
            text = " ".join(self._buffer)
            if text.strip():
                self._full_history.append(text.strip())
            self._buffer.clear()
            return text.strip()

    def get_history(self) -> list[str]:
        """Get all past flushed texts."""
        with self._lock:
            return list(self._full_history)

    def is_empty(self) -> bool:
        with self._lock:
            return len(self._buffer) == 0

    def clear(self):
        """Clear buffer only (keep history)."""
        with self._lock:
            self._buffer.clear()


class ConfidenceScorer:
    """Scores how confident we are that the current text is a complete question.

    Designed for unpunctuated Whisper output - does NOT over-rely on "?" marks.
    Uses multiple weak signals combined rather than any single strong signal.
    """

    # Question starter words (covers both direct and indirect questions)
    QUESTION_STARTERS = {
        "what", "how", "why", "when", "where", "who", "which",
        "can", "could", "would", "will", "do", "does", "did",
        "is", "are", "was", "were", "have", "has", "had",
        "tell", "describe", "explain", "walk", "give",
    }

    # Words that typically appear near the end of a complete question
    QUESTION_END_WORDS = {
        "experience", "thoughts", "approach", "opinion", "examples",
        "challenges", "projects", "team", "role", "process",
        "architecture", "design", "system", "data", "pipeline",
        "tools", "technologies", "language", "framework",
        "situation", "outcome", "result", "impact", "metrics",
    }

    def score(self, text: str, silence_duration: float = 0.0, silence_type: str = "none") -> dict:
        """Score the transcript for question completeness."""
        text = text.strip()
        if not text:
            return self._result(0, False, False, "empty text", False)

        confidence = 0
        reasons = []
        text_lower = text.lower()
        words = text.split()
        n_words = len(words)

        # ── Early exit: pure acknowledgment ──
        if NON_QUESTION_PATTERNS.match(text):
            return self._result(5, False, True, "non-question acknowledgment", False)

        # ── Negative signals (reduce confidence) ──

        # Ends with filler (still thinking)
        if FILLER_PATTERNS.search(text):
            confidence -= 15
            reasons.append("ends with filler")

        # Very short (< 3 words) - likely incomplete
        if n_words < 3:
            confidence -= 15
            reasons.append("too short")

        # Incomplete sentence - only if total text is short (< 30 chars)
        if INCOMPLETE_PATTERNS.search(text):
            confidence -= 20
            reasons.append("incomplete sentence")

        # ── Positive signals (increase confidence) ──

        # Question mark (still valuable but not required)
        if "?" in text:
            confidence += 25
            reasons.append("has question mark")

        # Starts with question word (strong signal even without punctuation)
        first_word = words[0].lower() if words else ""
        if first_word in self.QUESTION_STARTERS:
            confidence += 20
            reasons.append("starts with question word")

        # Contains question pattern
        if QUESTION_ENDINGS.search(text):
            confidence += 15
            reasons.append("question pattern")

        # Sufficient length (5+ words = likely a real statement)
        if n_words >= 5:
            confidence += 10
            reasons.append("sufficient length")

        # Longer statement (10+ words = almost certainly complete)
        if n_words >= 10:
            confidence += 10
            reasons.append("long statement")

        # Ends with a content word (noun/verb) - likely complete
        last_word = words[-1].lower().rstrip("?.!,") if words else ""
        if last_word in self.QUESTION_END_WORDS:
            confidence += 10
            reasons.append("ends with content word")

        # Contains "you" or "your" - likely directed at the user
        if "you" in text_lower or "your" in text_lower:
            confidence += 10
            reasons.append("directed at user")

        # ── Silence signals ──
        if silence_type == "long":
            confidence += 30
            reasons.append("long silence")
        elif silence_type == "medium":
            confidence += 20
            reasons.append("medium silence")
        elif silence_type == "short":
            confidence += 5
            reasons.append("short silence")

        # ── Compound boosts ──

        # Question word + 5+ words + any silence = very likely complete
        if first_word in self.QUESTION_STARTERS and n_words >= 5 and silence_type in ("medium", "long"):
            confidence += 10
            reasons.append("compound: question word + length + silence")

        # Clamp
        confidence = max(0, min(100, confidence))

        is_question = confidence >= 25
        is_complete = confidence >= 45
        should_process = confidence >= 55

        reason = "; ".join(reasons) if reasons else "no strong signals"

        return self._result(confidence, is_question, is_complete, reason, should_process)

    @staticmethod
    def _result(confidence, is_question, is_complete, reason, should_process):
        return {
            "confidence": confidence,
            "is_question": is_question,
            "is_complete": is_complete,
            "reason": reason,
            "should_process": should_process,
        }


class ConversationTracker:
    """Tracks the full interview conversation for context."""

    def __init__(self):
        self._turns = []  # [{"role": "interviewer"|"user", "text": str, "timestamp": float}]
        self._lock = threading.Lock()

    def add_interviewer_question(self, text: str):
        """Record an interviewer question."""
        with self._lock:
            self._turns.append({
                "role": "interviewer",
                "text": text.strip(),
                "timestamp": time.time(),
            })

    def add_user_response(self, text: str):
        """Record what the user said."""
        with self._lock:
            self._turns.append({
                "role": "user",
                "text": text.strip(),
                "timestamp": time.time(),
            })

    def get_conversation(self) -> list[dict]:
        """Get the full conversation history."""
        with self._lock:
            return list(self._turns)

    def get_last_n_turns(self, n: int = 5) -> list[dict]:
        """Get the last N conversation turns."""
        with self._lock:
            return list(self._turns[-n:])

    def get_formatted_history(self) -> str:
        """Get conversation formatted for Claude's context."""
        with self._lock:
            lines = []
            for turn in self._turns:
                role = "Interviewer" if turn["role"] == "interviewer" else "You"
                lines.append(f"[{role}]: {turn['text']}")
            return "\n".join(lines)

    def is_follow_up(self, text: str) -> bool:
        """Check if the text is a follow-up to the previous question."""
        follow_up_patterns = [
            r"can you (?:elaborate|expand|go deeper|tell me more)",
            r"what about",
            r"how about",
            r"and (?:what|how|why)",
            r"could you (?:explain|clarify)",
            r"what do you mean",
            r"give me (?:an example|more details)",
            r"anything else",
        ]
        text_lower = text.lower().strip()
        for pattern in follow_up_patterns:
            if re.search(pattern, text_lower):
                return True
        return False

    def clear(self):
        with self._lock:
            self._turns.clear()


class QuestionDetector:
    """Main question detection orchestrator.

    Combines silence detection, transcript buffering, confidence scoring,
    and conversation tracking to detect complete questions.
    """

    # Minimum seconds between emitting questions (prevents duplicate answers)
    QUESTION_COOLDOWN = 6.0
    # Minimum confidence to emit a question (heuristic / non-finalized path only)
    MIN_EMIT_CONFIDENCE = 65
    # Minimum word count to emit a question (heuristic / non-finalized path only)
    MIN_EMIT_WORDS = 6

    # A FINALIZED interviewer turn (they stopped talking) is a complete utterance and
    # should be answered regardless of confidence - interview prompts are often
    # imperatives ("Tell me about…", "Walk me through…", "Explain…") with no question
    # word or "?", which score low. We only require a couple of meaningful words and
    # skip pure acknowledgments / fillers.
    _MIN_FINAL_WORDS = 2
    _FILLER_WORDS = {
        "okay", "ok", "right", "got", "it", "mm", "mhm", "hmm", "uh", "huh",
        "yeah", "yep", "yes", "no", "sure", "cool", "great", "thanks", "thank",
        "you", "perfect", "alright", "nice", "good", "awesome", "gotcha",
        "makes", "sense", "i", "see", "so", "well", "and", "the",
    }

    def __init__(self, on_question=None, on_partial=None, on_prefetch=None):
        """
        Args:
            on_question: Callback(text, confidence, is_follow_up) - fired when a complete question is detected
            on_partial: Callback(text, confidence) - fired for partial/building questions (for UI status)
            on_prefetch: Callback(text, confidence) - fired at 70%+ confidence for predictive pre-fetch
        """
        self._on_question = on_question
        self._on_partial = on_partial
        self._on_prefetch = on_prefetch

        self.silence = SilenceDetector()
        self.buffer = TranscriptBuffer()
        self.scorer = ConfidenceScorer()
        self.conversation = ConversationTracker()

        self._prefetch_sent = False
        self._last_question_time = 0.0  # Timestamp of last emitted question
        self._last_question_text = ""   # text of last emitted question (dedupe)
        self._lock = threading.Lock()

    def feed_transcript(self, text: str):
        """Feed new transcribed text from Whisper."""
        if not text.strip():
            return

        self.buffer.add_text(text)
        current = self.buffer.get_current_text()

        # Score the current buffer
        result = self.scorer.score(current)

        # Notify partial listeners
        if self._on_partial:
            self._on_partial(current, result["confidence"])

        # Predictive pre-fetch at 70%+ confidence
        if result["confidence"] >= 70 and not self._prefetch_sent:
            self._prefetch_sent = True
            if self._on_prefetch:
                self._on_prefetch(current, result["confidence"])

    def set_partial_transcript(self, text: str):
        """Streaming partial result (cumulative). Replaces the buffer, scores it,
        and fires partial/pre-fetch callbacks - but never emits a question.
        Emission happens on the final (see process_final)."""
        if not text.strip():
            return

        self.buffer.set_text(text)
        current = self.buffer.get_current_text()
        result = self.scorer.score(current)

        if self._on_partial:
            self._on_partial(current, result["confidence"])

        # Predictive pre-fetch at 70%+ confidence - start answering before the
        # speaker has even finished.
        if result["confidence"] >= 70 and not self._prefetch_sent:
            self._prefetch_sent = True
            if self._on_prefetch:
                self._on_prefetch(current, result["confidence"])

    def process_final(self, text: str):
        """Streaming final result - a COMPLETE interviewer utterance (they paused).
        Answer it regardless of question-word heuristics; only fillers are skipped."""
        if not text.strip():
            return
        self.buffer.set_text(text)
        result = self.scorer.score(text, SILENCE_LONG, "long")
        self._emit_question(text, result["confidence"], finalized=True)

    def feed_silence(self, duration: float, silence_type: str):
        """Feed silence information from the audio stream.

        Called periodically by the audio pipeline when silence is detected.
        """
        current = self.buffer.get_current_text()
        if not current:
            return

        # Score with silence info
        result = self.scorer.score(current, duration, silence_type)

        # Long silence - always process
        if silence_type == "long" and current.strip():
            self._emit_question(current, result["confidence"])
            return

        # Medium silence - process if confidence is high enough
        if silence_type == "medium" and result["should_process"]:
            self._emit_question(current, result["confidence"])
            return

        # Notify partial listeners with updated confidence
        if self._on_partial:
            self._on_partial(current, result["confidence"])

    def feed_audio_for_silence(self, audio: np.ndarray):
        """Convenience: feed audio directly for silence detection.

        Combines silence detection with question detection.
        """
        silence_info = self.silence.feed_audio(audio)

        if silence_info["is_silent"] and silence_info["silence_type"] != "none":
            self.feed_silence(
                silence_info["silence_duration"],
                silence_info["silence_type"],
            )

    def force_process(self):
        """Force processing the current buffer as a complete question."""
        current = self.buffer.get_current_text()
        if current.strip():
            result = self.scorer.score(current, SILENCE_LONG, "long")
            self._emit_question(current, result["confidence"])

    def emit_now(self, text: str):
        """Manual endpoint (hotkey): emit `text` as a complete question NOW.

        Bypasses the confidence/word-count/cooldown gates entirely - the user
        explicitly signalled the question is done, so we trust that over heuristics.
        Still records the turn and detects follow-ups for conversation consistency.
        """
        text = text.strip()
        if not text:
            return
        now = time.time()
        with self._lock:
            is_follow_up = self.conversation.is_follow_up(text)
            self.conversation.add_interviewer_question(text)
            self.buffer.flush()
            self._prefetch_sent = False
            self.silence.reset()
            self._last_question_time = now
            # Record the text too, not just the time: if a silence-finalize was
            # racing the hotkey on the audio thread and its final slips past the
            # pipeline's suppress flag, process_final() would arrive with this same
            # text moments later - the finalized-path dedupe below catches it ONLY
            # if _last_question_text was updated here. Without this line the same
            # question got answered twice ~1.6s apart.
            self._last_question_text = text
        if self._on_question:
            self._on_question(text, 100, is_follow_up)

    def _emit_question(self, text: str, confidence: int, finalized: bool = False):
        """Emit a detected question and reset state.

        finalized=True  -> the interviewer's turn is complete (they paused). Answer it
                          unless it's just filler. No confidence/word gate.
        finalized=False -> heuristic mid-stream path; keep the strict confidence/word/
                          cooldown debounce so we don't answer fragments.
        """
        text = text.strip()
        if not text:
            return

        now = time.time()
        words = text.split()

        def _drop():
            self.buffer.flush()
            self.silence.reset()
            self._prefetch_sent = False

        if finalized:
            # Skip if the turn is only acknowledgments / filler ("okay, got it").
            meaningful = [w for w in words
                          if w.strip(".,!?;:").lower() not in self._FILLER_WORDS]
            if len(meaningful) < self._MIN_FINAL_WORDS:
                _drop()
                return
            # Dedupe an identical re-final of the same turn within a few seconds.
            if text == self._last_question_text and (now - self._last_question_time) < 3.0:
                _drop()
                return
        else:
            # Debounce: skip if too soon after last question (unless a strong follow-up).
            if now - self._last_question_time < self.QUESTION_COOLDOWN:
                is_follow_up = self.conversation.is_follow_up(text)
                if not is_follow_up and (confidence < 70 or len(words) < 6):
                    _drop()
                    return
            # Skip low-confidence or very short fragments.
            if confidence < self.MIN_EMIT_CONFIDENCE or len(words) < self.MIN_EMIT_WORDS:
                _drop()
                return

        with self._lock:
            is_follow_up = self.conversation.is_follow_up(text)
            self.conversation.add_interviewer_question(text)
            self.buffer.flush()
            self._prefetch_sent = False
            self.silence.reset()
            self._last_question_time = now
            self._last_question_text = text

        if self._on_question:
            self._on_question(text, confidence, is_follow_up)

    def add_user_response(self, text: str):
        """Record what the user said (from speaker diarization)."""
        self.conversation.add_user_response(text)

    def reset(self):
        """Reset all state."""
        self.silence.reset()
        self.buffer.clear()
        self._prefetch_sent = False