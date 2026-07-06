"""Ghost AI Practice Mode — mock interview with scoring.

Ghost generates interview questions based on your resume/context,
records your spoken answer via mic, transcribes it with Whisper,
and Claude scores your performance.

Usage (CLI):
    python -m ghost.ai.practice --context ./my_context/
    python -m ghost.ai.practice --context ./my_context/ --questions 5 --category technical

Usage (from code):
    session = PracticeSession(api_key="sk-...", context_dir="./context/")
    result = session.run_question()
    print(session.get_report())
"""

import os
import json
import time
import argparse
import numpy as np

from ghost.ai.audio_capture import MicCapture, WHISPER_SAMPLE_RATE
from ghost.ai.whisper_engine import WhisperEngine, ContinuousTranscriber

import anthropic


# ── Constants ──

CATEGORIES = ["behavioral", "technical", "system_design", "general"]

DEFAULT_MODEL = "claude-opus-4-8"

QUESTION_PROMPT = """You are an interviewer conducting a practice interview.

Based on the candidate's background, generate ONE interview question.

Category: {category}

Rules:
- Make the question specific to their background when context is available.
- For behavioral: use "Tell me about a time..." or "Describe a situation..." format.
- For technical: ask about a specific technology, algorithm, or concept they should know.
- For system_design: ask them to design a system relevant to their experience.
- For general: ask about career goals, teamwork, strengths, or leadership.
- Output ONLY the question. No labels, no quotes, no preamble.

{context}"""

SCORING_PROMPT = """Score this practice interview answer.

Question: {question}
Category: {category}

Candidate's answer (transcribed from speech):
\"\"\"{answer}\"\"\"

Score each dimension 1-10 and provide brief, actionable feedback.

Respond in this EXACT JSON format, nothing else:
{{
  "completeness": <1-10>,
  "clarity": <1-10>,
  "relevance": <1-10>,
  "depth": <1-10>,
  "overall": <1-10>,
  "feedback": "<2-3 sentences of constructive feedback>",
  "strengths": "<what they did well, 1 sentence>",
  "improve": "<what to improve, 1 sentence>"
}}"""


# ── Context Loader (reuse from claude_brain) ──

def _load_context(context_dir: str) -> str:
    """Load context files from a directory."""
    if not context_dir or not os.path.isdir(context_dir):
        return ""

    sections = []
    files = {
        "resume.md": "RESUME",
        "projects.md": "PROJECTS",
        "about_me.md": "ABOUT ME",
        "job_description.md": "JOB DESCRIPTION",
    }
    for filename, label in files.items():
        path = os.path.join(context_dir, filename)
        if os.path.isfile(path):
            with open(path, "r") as f:
                content = f.read().strip()
            if content:
                sections.append(f"## {label}\n{content}")

    return "\n\n---\n\n".join(sections)


# ── Practice Session ──

class PracticeSession:
    """Mock interview session with AI-generated questions and scoring."""

    def __init__(
        self,
        api_key: str = None,
        context_dir: str = None,
        model: str = DEFAULT_MODEL,
        whisper_model: str = "small",
    ):
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self._api_key:
            raise ValueError("API key required. Set ANTHROPIC_API_KEY or pass --api-key.")

        self._client = anthropic.Anthropic(api_key=self._api_key)
        self._model = model
        self._context = _load_context(context_dir)
        self._whisper = WhisperEngine(model=whisper_model)

        # Session state
        self._results = []
        self._category_index = 0

    def generate_question(self, category: str = None) -> tuple[str, str]:
        """Generate an interview question. Returns (question, category)."""
        if category is None:
            category = CATEGORIES[self._category_index % len(CATEGORIES)]
            self._category_index += 1

        prompt = QUESTION_PROMPT.format(
            category=category,
            context=self._context if self._context else "(No context provided — ask a generic question)",
        )

        response = self._client.messages.create(
            model=self._model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        question = response.content[0].text.strip()
        return question, category

    def record_answer(self, max_duration: float = 120.0, silence_timeout: float = 5.0) -> tuple[str, float]:
        """Record user's answer via mic. Stops after silence_timeout seconds of silence.

        Returns (transcribed_text, duration_seconds).
        """
        mic = MicCapture()
        audio_chunks = []
        silence_start = None
        recording = True
        has_speech = False
        start_time = time.time()

        no_speech_timeout = 15.0  # Stop if user never speaks for 15s

        def on_chunk(chunk):
            nonlocal silence_start, recording, has_speech
            if not recording:
                return
            audio_chunks.append(chunk.copy())

            energy = float(np.sqrt(np.mean(chunk ** 2)))
            if energy < 0.008:
                if silence_start is None:
                    silence_start = time.time()
                elif has_speech and time.time() - silence_start > silence_timeout:
                    # User spoke then went silent — they're done
                    recording = False
                elif not has_speech and time.time() - silence_start > no_speech_timeout:
                    # User never spoke at all — give up
                    recording = False
            else:
                silence_start = None
                has_speech = True

        mic.start_continuous(on_audio_chunk=on_chunk, chunk_duration=0.5)

        while recording and (time.time() - start_time) < max_duration:
            time.sleep(0.1)

        mic.stop_continuous()
        duration = time.time() - start_time

        if not audio_chunks:
            return "", 0.0

        audio = np.concatenate(audio_chunks)

        # Skip if too quiet overall
        energy = float(np.sqrt(np.mean(audio ** 2)))
        if energy < 0.005:
            return "", duration

        # Transcribe in 30-second chunks
        chunk_samples = 30 * WHISPER_SAMPLE_RATE
        texts = []
        for i in range(0, len(audio), chunk_samples):
            chunk = audio[i:i + chunk_samples]
            if len(chunk) < WHISPER_SAMPLE_RATE:  # Skip < 1s
                continue
            result = self._whisper.transcribe(chunk)
            text = result["text"].strip()
            if text and not ContinuousTranscriber._is_hallucination(text):
                texts.append(text)

        return " ".join(texts), duration

    def score_answer(self, question: str, answer: str, category: str) -> dict:
        """Score the user's answer using Claude. Returns score dict."""
        if not answer.strip():
            return {
                "completeness": 0, "clarity": 0, "relevance": 0,
                "depth": 0, "overall": 0,
                "feedback": "No answer was recorded.",
                "strengths": "N/A",
                "improve": "Try speaking clearly into the microphone.",
            }

        prompt = SCORING_PROMPT.format(
            question=question, category=category, answer=answer,
        )

        response = self._client.messages.create(
            model=self._model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()

        # Parse JSON — handle potential markdown code blocks
        try:
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text.strip())
        except (json.JSONDecodeError, IndexError):
            return {
                "completeness": 5, "clarity": 5, "relevance": 5,
                "depth": 5, "overall": 5,
                "feedback": text[:300],
                "strengths": "Could not parse detailed scores.",
                "improve": "See feedback above.",
            }

    def run_question(self, category: str = None) -> dict:
        """Run one full question cycle: generate → record → score → display."""
        question, cat = self.generate_question(category)
        q_num = len(self._results) + 1

        print(f"\n{'=' * 60}")
        print(f"  [{cat.upper()}] Question {q_num}")
        print(f"{'=' * 60}")
        print(f"\n  {question}\n")
        print(f"{'─' * 60}")
        print("  Speak your answer now... (stops after 5s of silence)\n")

        answer, duration = self.record_answer()

        if not answer:
            print("  [No answer recorded]\n")
        else:
            # Show first 200 chars of what was transcribed
            preview = answer[:200] + ("..." if len(answer) > 200 else "")
            print(f"  Your answer ({duration:.0f}s):")
            print(f"  {preview}\n")

        print("  Scoring...")
        score = self.score_answer(question, answer, cat)

        result = {
            "question": question,
            "category": cat,
            "answer": answer,
            "score": score,
            "duration": duration,
        }
        self._results.append(result)

        # Display score
        s = score
        print(f"\n  {'─' * 40}")
        print(f"  Completeness:  {s['completeness']}/10")
        print(f"  Clarity:       {s['clarity']}/10")
        print(f"  Relevance:     {s['relevance']}/10")
        print(f"  Depth:         {s['depth']}/10")
        print(f"  OVERALL:       {s['overall']}/10")
        print(f"  {'─' * 40}")
        print(f"  Feedback:  {s.get('feedback', '')}")
        print(f"  Strength:  {s.get('strengths', '')}")
        print(f"  Improve:   {s.get('improve', '')}")

        return result

    def get_report(self) -> str:
        """Generate a summary report of the practice session."""
        if not self._results:
            return "No questions answered yet."

        lines = [
            "# Practice Interview Report",
            "",
            f"**Questions answered:** {len(self._results)}",
            "",
        ]

        # Category scores
        cat_scores = {}
        for r in self._results:
            cat = r["category"]
            overall = r["score"].get("overall", 0)
            cat_scores.setdefault(cat, []).append(overall)

        lines.append("## Scores by Category")
        lines.append("")
        for cat, scores in sorted(cat_scores.items()):
            avg = sum(scores) / len(scores)
            lines.append(f"- **{cat}**: {avg:.1f}/10 ({len(scores)} questions)")

        # Overall average
        all_overall = [r["score"].get("overall", 0) for r in self._results]
        avg_overall = sum(all_overall) / len(all_overall)
        lines.append("")
        lines.append(f"**Overall average: {avg_overall:.1f}/10**")

        # Weak areas (< 6/10 average)
        weak = [(cat, sum(s) / len(s)) for cat, s in cat_scores.items()
                if sum(s) / len(s) < 6]
        if weak:
            lines.append("")
            lines.append("## Areas to Improve")
            for cat, avg in sorted(weak, key=lambda x: x[1]):
                lines.append(f"- **{cat}** ({avg:.1f}/10)")

        # Question details
        lines.append("")
        lines.append("## Question Details")
        for i, r in enumerate(self._results):
            s = r["score"]
            lines.append("")
            lines.append(f"### Q{i + 1} [{r['category']}] — {s.get('overall', 0)}/10")
            lines.append(f"**Q:** {r['question']}")
            answer_preview = r["answer"][:300] + ("..." if len(r["answer"]) > 300 else "")
            lines.append(f"**A:** {answer_preview}")
            lines.append(f"**Feedback:** {s.get('feedback', '')}")

        return "\n".join(lines)

    def save_report(self, path: str = None) -> str:
        """Save the practice report to a markdown file. Returns the file path."""
        if path is None:
            from datetime import datetime
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            sessions_dir = os.path.join(project_root, "sessions")
            os.makedirs(sessions_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(sessions_dir, f"practice_{timestamp}.md")

        report = self.get_report()
        with open(path, "w") as f:
            f.write(report)
        print(f"\n  Report saved to: {path}")
        return path


# ── CLI Entry Point ──

def main():
    parser = argparse.ArgumentParser(description="Ghost AI Practice Mode")
    parser.add_argument("--api-key", default=None, help="Anthropic API key")
    parser.add_argument("--context", default=None, help="Directory with context files")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Claude model")
    parser.add_argument("--whisper", default="small", help="Whisper model size")
    parser.add_argument("--questions", type=int, default=5, help="Number of questions")
    parser.add_argument("--category", default=None, choices=CATEGORIES, help="Focus on one category")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  Ghost AI — Practice Interview Mode")
    print("=" * 60)
    print(f"  Questions: {args.questions}")
    if args.category:
        print(f"  Category: {args.category}")
    if args.context:
        print(f"  Context: {args.context}")
    print()

    session = PracticeSession(
        api_key=args.api_key,
        context_dir=args.context,
        model=args.model,
        whisper_model=args.whisper,
    )

    for i in range(args.questions):
        try:
            session.run_question(category=args.category)
        except KeyboardInterrupt:
            print("\n\n  Practice interrupted.")
            break
        except Exception as e:
            print(f"\n  Error: {e}")
            continue

        # Pause between questions
        if i < args.questions - 1:
            print(f"\n  Press Enter for next question (or Ctrl+C to stop)...")
            try:
                input()
            except KeyboardInterrupt:
                print("\n\n  Practice ended.")
                break

    # Show report
    print(f"\n{'=' * 60}")
    print("  SESSION COMPLETE")
    print(f"{'=' * 60}")
    print()
    print(session.get_report())
    session.save_report()


if __name__ == "__main__":
    main()
