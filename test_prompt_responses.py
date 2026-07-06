#!/usr/bin/env python3
"""Run interviewer questions through Ghost's REAL brain and check the answers.

This exercises the actual system — SYSTEM_PROMPT + your ./contexts context + the
model router + the Claude API — exactly as a live answer would, then flags the
specific leaks we've been fixing:

  * document scaffolding  (## headers, "Say:" / "Spoken plan" labels)
  * "here's the model answer" / "This is a <type> question" preambles
  * role labels leaking into the answer (Interviewer: / Question:)
  * follow-up-question menus ("they might also ask ...")

Run:
    venv/bin/python test_prompt_responses.py

Needs your Anthropic key. It reads .env at the project root (ANTHROPIC_API_KEY=sk-...),
or you can export the var. This makes real API calls (a handful of them).
"""

import os
import re
import sys
import pathlib

ROOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))


def load_env():
    """Minimal .env loader (avoids importing the GUI stack just to read one key)."""
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("❌ No ANTHROPIC_API_KEY found. Put it in .env (ANTHROPIC_API_KEY=sk-...) "
             "or `export` it, then re-run.")

from ghost.ai.claude_brain import ClaudeBrain, ContextLoader  # noqa: E402


# Interviewer questions — one of each type that has leaked before.
QUESTIONS = [
    ("concept",    "Can you explain the difference between overfitting and underfitting?"),
    ("coding",     "Given an array of integers and a target, write a function that returns "
                   "the indices of the two numbers that add up to the target. Walk me through it."),
    ("behavioral", "Tell me about a challenging project you worked on."),
    ("factual",    "Are you comfortable working with Spark and Kafka?"),
    ("small talk", "Hey, how's it going? You ready to get started?"),
]


# Leak detectors. Code blocks are stripped first so a Python comment can't trip them.
def strip_code(t: str) -> str:
    return re.sub(r"```.*?```", " ", t, flags=re.S)


LEAKS = {
    "markdown header (## / **1.)":    re.compile(r"(^|\n)\s*(#{1,6}\s|\*\*\d+\.)", re.M),
    "'Say:'/'Spoken plan'/'Restate' label": re.compile(r"\b(Say:|Spoken plan|Restate intent)\b", re.I),
    "'model answer'":                 re.compile(r"model answer", re.I),
    "'This is a <type> question' preamble": re.compile(r"^\W*(okay,?\s*)?this is (a|an|the)\b[^.]*\bquestion\b", re.I),
    "role label (Interviewer:/Question:)":  re.compile(r"(^|\n)\s*(Interviewer|Question|Follow[- ]?up)\s*:", re.I),
    "follow-up-question menu":        re.compile(r"follow[- ]?up question|they might also ask|you (could|might) (be|get) asked|related questions", re.I),
}


def check(answer: str):
    body = strip_code(answer)
    return [name for name, rx in LEAKS.items() if rx.search(body)]


def main():
    brain = ClaudeBrain(context_loader=ContextLoader(context_dir=str(ROOT / "contexts" / "ml_engineer")))
    all_clean = True

    for kind, q in QUESTIONS:
        print("\n" + "=" * 74)
        print(f"[{kind}]  INTERVIEWER: {q}")
        print("-" * 74)
        try:
            answer = brain.answer_question_sync(q)
        except Exception as e:
            all_clean = False
            print(f"  ❌ API/error: {e}")
            continue
        print(answer.strip())
        print("-" * 74)
        leaks = check(answer)
        if leaks:
            all_clean = False
            print("  ❌ LEAKS: " + "; ".join(leaks))
        else:
            print("  ✅ clean — spoken answer, no scaffolding / labels / follow-up menu")

        # For coding questions, also confirm the walkthrough STRUCTURE is present.
        if kind == "coding":
            body = strip_code(answer)
            struct = {
                "restate/clarify": bool(re.search(r"assum|constraint|sorted|duplicat|empty|input size|clarif|negative|\?", body, re.I)),
                "brute-force + better": bool(re.search(r"brute|naive|nested loop|two loops|O\(n\^?2|n squared", body, re.I)),
                "complexity": "O(" in body,
                "has code": "```" in answer,
            }
            print("  coding walkthrough: " + "  ".join(f"{'✓' if v else '✗'} {k}" for k, v in struct.items()))
            if not all(struct.values()):
                all_clean = False

    print("\n" + "=" * 74)
    print("RESULT:", "ALL CLEAN ✅" if all_clean else "SOME LEAKS ❌ (see the ❌ lines above)")
    sys.exit(0 if all_clean else 1)


if __name__ == "__main__":
    main()
