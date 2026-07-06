"""Local Whisper Engine for Ghost AI.

On-device speech-to-text using mlx-whisper (optimized for Apple Silicon).
Supports dual model strategy: tiny (fast) + medium (accurate).

Usage:
    engine = WhisperEngine(model="tiny")
    result = engine.transcribe(audio_chunk)  # numpy float32, 16kHz mono
    print(result["text"])
"""

import time
import threading
import numpy as np

# Model repos on HuggingFace (mlx-community quantized models)
MODELS = {
    "tiny": "mlx-community/whisper-tiny",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large": "mlx-community/whisper-large-v3-mlx",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}

# Whisper expects 16kHz mono float32
WHISPER_SAMPLE_RATE = 16000


class WhisperEngine:
    """Single-model Whisper transcription engine."""

    def __init__(self, model: str = "tiny", language: str = "en"):
        """
        Args:
            model: Model size — "tiny", "base", "small", "medium", "large"
            language: Language code for transcription (default "en")
        """
        self._model_name = model
        self._model_repo = MODELS.get(model, model)
        self._language = language
        self._lock = threading.Lock()
        print(f"[WhisperEngine] Using model: {self._model_name} ({self._model_repo})")

    def transcribe(self, audio: np.ndarray) -> dict:
        """Transcribe audio chunk to text.

        Args:
            audio: numpy float32 array at 16kHz mono.

        Returns:
            dict with keys:
                "text": transcribed text (stripped)
                "segments": list of segments with timestamps
                "language": detected language
                "duration": audio duration in seconds
                "latency": transcription time in seconds
        """
        import mlx_whisper

        duration = len(audio) / WHISPER_SAMPLE_RATE
        start = time.time()

        with self._lock:
            result = mlx_whisper.transcribe(
                audio,
                path_or_hf_repo=self._model_repo,
                language=self._language,
                word_timestamps=False,
                condition_on_previous_text=False,
                no_speech_threshold=0.4,
                compression_ratio_threshold=2.0,
                verbose=False,
            )

        latency = time.time() - start
        text = result.get("text", "").strip()

        return {
            "text": text,
            "segments": result.get("segments", []),
            "language": result.get("language", self._language),
            "duration": duration,
            "latency": latency,
        }


class DualWhisperEngine:
    """Dual-model Whisper engine: fast (tiny) + accurate (medium).

    The fast model runs first for quick question detection.
    The accurate model runs in parallel for precise transcription.
    """

    def __init__(self, fast_model: str = "tiny", accurate_model: str = "small", language: str = "en"):
        """
        Args:
            fast_model: Model for quick transcription (default "tiny")
            accurate_model: Model for precise transcription (default "small")
            language: Language code
        """
        self._fast = WhisperEngine(model=fast_model, language=language)
        self._accurate = WhisperEngine(model=accurate_model, language=language)
        self._last_accurate_result = None
        self._accurate_lock = threading.Lock()

    def transcribe_fast(self, audio: np.ndarray) -> dict:
        """Quick transcription using the fast model (~0.3s for tiny).

        Use this for real-time question detection.
        """
        return self._fast.transcribe(audio)

    def transcribe_accurate(self, audio: np.ndarray) -> dict:
        """Precise transcription using the accurate model (~1-2s for small).

        Use this for the final transcript sent to Claude.
        """
        result = self._accurate.transcribe(audio)
        with self._accurate_lock:
            self._last_accurate_result = result
        return result

    def transcribe_accurate_async(self, audio: np.ndarray, callback=None):
        """Run accurate transcription in background thread.

        Args:
            audio: numpy float32 array at 16kHz mono
            callback: called with the result dict when done
        """
        def _work():
            result = self.transcribe_accurate(audio)
            if callback:
                callback(result)

        thread = threading.Thread(target=_work, daemon=True)
        thread.start()

    def get_last_accurate_result(self) -> dict | None:
        """Return the most recent accurate transcription result."""
        with self._accurate_lock:
            return self._last_accurate_result


class ContinuousTranscriber:
    """Continuous transcription pipeline with rolling buffer.

    Accumulates audio, transcribes overlapping chunks, and delivers
    a running transcript to the callback.
    """

    def __init__(
        self,
        engine: WhisperEngine | DualWhisperEngine = None,
        chunk_seconds: float = 3.0,
        overlap_seconds: float = 0.5,
        on_transcript: callable = None,
        use_dual: bool = False,
    ):
        """
        Args:
            engine: WhisperEngine or DualWhisperEngine instance
            chunk_seconds: How many seconds of audio to transcribe at once
            overlap_seconds: Overlap between chunks to avoid cutting words
            on_transcript: Callback(text, is_partial, latency) called with each transcription
            use_dual: If True and engine is DualWhisperEngine, use fast+accurate strategy
        """
        if engine is None:
            engine = WhisperEngine(model="tiny")
        self._engine = engine
        self._chunk_seconds = chunk_seconds
        self._chunk_samples = int(chunk_seconds * WHISPER_SAMPLE_RATE)
        self._overlap_samples = int(overlap_seconds * WHISPER_SAMPLE_RATE)
        self._on_transcript = on_transcript
        self._use_dual = use_dual and isinstance(engine, DualWhisperEngine)

        self._buffer = np.array([], dtype=np.float32)
        self._buffer_lock = threading.Lock()
        self._running = False
        self._transcript_thread = None
        self._first_transcription_done = False

        # Full conversation transcript
        self._full_transcript = []
        self._transcript_lock = threading.Lock()

    def feed_audio(self, audio: np.ndarray):
        """Feed audio chunk into the buffer. Called from AudioCapture callback."""
        with self._buffer_lock:
            self._buffer = np.concatenate([self._buffer, audio])

    def start(self):
        """Start the continuous transcription loop."""
        self._running = True
        self._transcript_thread = threading.Thread(target=self._transcribe_loop, daemon=True)
        self._transcript_thread.start()
        print("[ContinuousTranscriber] Started")

    def stop(self):
        """Stop the transcription loop."""
        self._running = False
        print("[ContinuousTranscriber] Stopped")

    def get_full_transcript(self) -> str:
        """Return the full accumulated transcript."""
        with self._transcript_lock:
            return " ".join(self._full_transcript)

    def clear_transcript(self):
        """Clear the accumulated transcript."""
        with self._transcript_lock:
            self._full_transcript.clear()

    def _transcribe_loop(self):
        """Main transcription loop — runs on background thread."""
        while self._running:
            # Wait for enough audio
            time.sleep(0.1)

            # Adaptive chunk size: use 2.5s for first chunk (fast detection),
            # then switch to full chunk_seconds for accuracy
            if not self._first_transcription_done:
                min_samples = int(2.5 * WHISPER_SAMPLE_RATE)
            else:
                min_samples = self._chunk_samples

            with self._buffer_lock:
                if len(self._buffer) < min_samples:
                    continue
                # Take a chunk with overlap
                take = min(len(self._buffer), self._chunk_samples)
                chunk = self._buffer[:take].copy()
                keep_overlap = min(self._overlap_samples, take)
                self._buffer = self._buffer[take - keep_overlap:]

            # Skip silence (very low energy) — prevents Whisper hallucinations
            energy = np.sqrt(np.mean(chunk ** 2))
            if energy < 0.005:
                continue

            # Transcribe
            if self._use_dual:
                # Fast transcription first
                fast_result = self._engine.transcribe_fast(chunk)
                fast_text = fast_result["text"]

                if fast_text and not self._is_hallucination(fast_text) and self._on_transcript:
                    self._on_transcript(fast_text, True, fast_result["latency"])

                # Accurate transcription in background
                self._engine.transcribe_accurate_async(
                    chunk,
                    callback=lambda r: self._handle_accurate_result(r)
                )
            else:
                result = self._engine.transcribe(chunk) if isinstance(self._engine, WhisperEngine) else self._engine.transcribe_fast(chunk)
                text = result["text"]

                if text and not self._is_hallucination(text):
                    self._first_transcription_done = True
                    with self._transcript_lock:
                        self._full_transcript.append(text)

                    if self._on_transcript:
                        self._on_transcript(text, False, result["latency"])

    @staticmethod
    def _is_hallucination(text: str) -> bool:
        """Detect Whisper hallucination patterns (repeated words/phrases on silence).

        Classic hallucinations: "Him Him Him Him...", "gonna be gonna be...",
        "Art in Heaven Art in Heaven...", "Thank you for watching!",
        "He just got", "Thank you.", "Oh", "So."
        """
        text = text.strip()
        if not text:
            return True

        words = text.lower().split()

        # Single word is always hallucination
        if len(words) <= 1:
            return True

        # Known Whisper hallucination phrases (these appear on silence/noise)
        lower = text.lower().strip().rstrip(".,!?")
        hallucination_exact = {
            "thank you", "thanks", "oh", "so", "he just got",
            "you", "bye", "bye bye", "good bye", "goodbye",
            "hmm", "uh", "um", "ah", "huh",
            "i'm going to get out of here",
            "so i'm going to get out of here",
            "thank you for watching",
            "thanks for watching",
        }
        if lower in hallucination_exact:
            return True

        from collections import Counter

        # Check if one word dominates (>50% of all words)
        counts = Counter(words)
        most_common_word, most_common_count = counts.most_common(1)[0]
        if most_common_count / len(words) > 0.5:
            return True

        # Check for repeated n-grams (e.g., "gonna be gonna be", "I found it so I found it so")
        for n in (2, 3, 4):
            if len(words) >= n * 3:
                ngrams = [" ".join(words[i:i+n]) for i in range(len(words) - n + 1)]
                ngram_counts = Counter(ngrams)
                top_ngram, top_count = ngram_counts.most_common(1)[0]
                if top_count >= 3 and top_count / len(ngrams) > 0.25:
                    return True

        # Known hallucination phrases
        hallucination_phrases = [
            "thank you for watching",
            "thanks for watching",
            "please subscribe",
            "like and subscribe",
        ]
        if any(lower.startswith(p) or lower.endswith(p) for p in hallucination_phrases):
            if len(words) < 8:
                return True

        return False

    def _handle_accurate_result(self, result):
        """Handle accurate transcription result from DualWhisperEngine."""
        text = result["text"]
        if text and not self._is_hallucination(text):
            with self._transcript_lock:
                self._full_transcript.append(text)

            if self._on_transcript:
                self._on_transcript(text, False, result["latency"])
