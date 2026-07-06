"""Ghost AI Session Logger.

Records everything from a Ghost AI session for review:
  - Raw captured audio (WAV files)
  - Whisper transcripts
  - Detected questions
  - Claude responses
  - Timestamps for everything

Saves to: ~/Desktop/Projects/Ghost/sessions/<timestamp>/
"""

import os
import json
import time
import threading
import numpy as np
from datetime import datetime

WHISPER_SAMPLE_RATE = 16000


class SessionLogger:
    """Logs audio, transcripts, and Claude responses for a Ghost AI session."""

    def __init__(self, session_dir: str = None):
        """
        Args:
            session_dir: Directory to save session files. If None, auto-creates
                         under ./sessions/<timestamp>/
        """
        if session_dir is None:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            session_dir = os.path.join(project_root, "sessions", timestamp)

        os.makedirs(session_dir, exist_ok=True)
        self._dir = session_dir
        self._audio_dir = os.path.join(session_dir, "audio")
        os.makedirs(self._audio_dir, exist_ok=True)

        self._log_file = os.path.join(session_dir, "session.jsonl")
        self._summary_file = os.path.join(session_dir, "summary.md")
        self._lock = threading.Lock()

        # Running audio buffer for continuous recording
        self._audio_buffer = np.array([], dtype=np.float32)
        self._audio_lock = threading.Lock()
        self._audio_chunk_count = 0

        # Session stats
        self._start_time = time.time()
        self._question_count = 0
        self._transcript_count = 0

        self._log_event("session_start", {
            "timestamp": datetime.now().isoformat(),
            "session_dir": session_dir,
        })
        print(f"[SessionLogger] Saving to: {session_dir}")

    # ── Public API ──

    def log_audio_chunk(self, audio: np.ndarray):
        """Buffer audio chunks. Periodically saved to WAV."""
        with self._audio_lock:
            self._audio_buffer = np.concatenate([self._audio_buffer, audio])
            self._audio_chunk_count += 1

            # Save every ~30 seconds of audio (30 * 16000 = 480000 samples)
            if len(self._audio_buffer) >= 480000:
                self._save_audio_buffer()

    def log_transcript(self, text: str, latency: float):
        """Log a Whisper transcript."""
        self._transcript_count += 1
        self._log_event("transcript", {
            "text": text,
            "latency_s": round(latency, 2),
            "transcript_num": self._transcript_count,
        })

    def log_question(self, text: str, confidence: int, is_follow_up: bool, mode: str):
        """Log a detected question."""
        self._question_count += 1
        self._log_event("question", {
            "text": text,
            "confidence": confidence,
            "is_follow_up": is_follow_up,
            "mode": mode,
            "question_num": self._question_count,
        })

    def log_answer(self, question: str, answer: str, mode: str, latency: float = None):
        """Log a Claude answer."""
        self._log_event("answer", {
            "question": question,
            "answer": answer,
            "mode": mode,
            "answer_length": len(answer),
            "latency_s": round(latency, 2) if latency else None,
            "question_num": self._question_count,
        })

    def log_user_response(self, text: str):
        """Log what the user actually said (transcribed from mic)."""
        self._log_event("user_response", {
            "text": text,
            "question_num": self._question_count,
        })

    def log_error(self, error: str, context: str = ""):
        """Log an error."""
        self._log_event("error", {"error": error, "context": context})

    @property
    def session_dir(self) -> str:
        return self._dir

    def save_chat(self, messages: list):
        """Persist the full labeled chat (list of {speaker, text}).

        Writes chat.json (machine-readable) and chat.md (human-readable). Called
        on every new message so the conversation is never lost, even on a crash.
        """
        labels = {"interviewer": "Interviewer", "you": "You", "ai": "Ghost AI"}
        try:
            with open(os.path.join(self._dir, "chat.json"), "w", encoding="utf-8") as f:
                json.dump(messages, f, indent=2, ensure_ascii=False)
            lines = [f"# Ghost AI Chat — {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
            for m in messages:
                lines.append(f"**{labels.get(m.get('speaker'), m.get('speaker'))}:** {m.get('text','')}")
                lines.append("")
            with open(os.path.join(self._dir, "chat.md"), "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception as e:
            print(f"[SessionLogger] Failed to save chat: {e}")

    def log_hallucination_filtered(self, text: str):
        """Log a filtered hallucination (useful for debugging)."""
        self._log_event("hallucination_filtered", {"text": text[:200]})

    def finalize(self):
        """Save remaining audio and write summary. Call on session end."""
        with self._audio_lock:
            if len(self._audio_buffer) > 0:
                self._save_audio_buffer()

        # Write summary
        duration = time.time() - self._start_time
        minutes = int(duration // 60)
        seconds = int(duration % 60)

        summary_lines = [
            f"# Ghost AI Session — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            f"**Duration:** {minutes}m {seconds}s",
            f"**Questions detected:** {self._question_count}",
            f"**Transcripts:** {self._transcript_count}",
            "",
            "## Timeline",
            "",
        ]

        # Read back events for timeline
        if os.path.exists(self._log_file):
            with open(self._log_file, "r") as f:
                for line in f:
                    event = json.loads(line)
                    ts = event.get("relative_s", 0)
                    ts_str = f"{int(ts//60):02d}:{int(ts%60):02d}"

                    if event["type"] == "question":
                        d = event["data"]
                        summary_lines.append(f"- **[{ts_str}] Q{d['question_num']}** ({d['mode']}, {d['confidence']}%): {d['text'][:100]}...")
                    elif event["type"] == "answer":
                        d = event["data"]
                        preview = d["answer"][:150].replace("\n", " ")
                        summary_lines.append(f"  - **Answer** ({d['answer_length']} chars): {preview}...")
                    elif event["type"] == "user_response":
                        d = event["data"]
                        summary_lines.append(f"  - **You said**: {d['text'][:150]}...")
                    elif event["type"] == "error":
                        summary_lines.append(f"- **[{ts_str}] ERROR:** {event['data']['error']}")

        with open(self._summary_file, "w") as f:
            f.write("\n".join(summary_lines))

        self._log_event("session_end", {
            "duration_s": round(duration, 1),
            "questions": self._question_count,
            "transcripts": self._transcript_count,
        })

        print(f"[SessionLogger] Session saved to: {self._dir}")
        print(f"[SessionLogger] Duration: {minutes}m {seconds}s, Questions: {self._question_count}")

    # ── Internal ──

    def _log_event(self, event_type: str, data: dict):
        """Append a JSON line to the session log."""
        event = {
            "type": event_type,
            "relative_s": round(time.time() - self._start_time, 1),
            "timestamp": datetime.now().isoformat(),
            "data": data,
        }
        with self._lock:
            with open(self._log_file, "a") as f:
                f.write(json.dumps(event) + "\n")

    def _save_audio_buffer(self):
        """Save current audio buffer as WAV file."""
        if len(self._audio_buffer) == 0:
            return

        audio_to_save = self._audio_buffer.copy()
        self._audio_buffer = np.array([], dtype=np.float32)

        # Generate filename with timestamp
        relative_s = time.time() - self._start_time
        filename = f"audio_{int(relative_s):05d}.wav"
        filepath = os.path.join(self._audio_dir, filename)

        # Save as WAV
        try:
            import wave
            import struct

            # Convert float32 [-1, 1] to int16
            audio_int16 = np.clip(audio_to_save * 32767, -32768, 32767).astype(np.int16)

            with wave.open(filepath, 'w') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(WHISPER_SAMPLE_RATE)
                wf.writeframes(audio_int16.tobytes())

            duration = len(audio_to_save) / WHISPER_SAMPLE_RATE
            print(f"[SessionLogger] Saved {duration:.1f}s audio → {filename}")
        except Exception as e:
            print(f"[SessionLogger] Failed to save audio: {e}")
