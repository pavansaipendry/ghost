#!/usr/bin/env python3
"""Stress-test the dedicated CODING MODE against varied coding problems, live.

Runs each problem through the real ClaudeBrain (SYSTEM_PROMPT + CODING_MODE + router +
Claude API) and checks: (a) coding mode actually fired, (b) the spoken walkthrough is
present (restate/clarify -> brute-force + better -> code -> complexity), (c) no document
scaffolding leaked. Prints full answers.

Run:  venv/bin/python test_coding_mode.py   (needs ANTHROPIC_API_KEY in .env)
"""
import os, re, sys, pathlib

ROOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("❌ No ANTHROPIC_API_KEY — put it in .env and re-run.")

from ghost.ai.claude_brain import ClaudeBrain, ContextLoader  # noqa: E402
from ghost.ai.model_router import is_coding_question  # noqa: E402

# Varied coding problems, each stressing a different part of the flow.
PROBLEMS = [
    ("underspecified (should ask real clarifying qs)",
     "Write a function to merge two lists."),
    ("dynamic programming",
     "Given coin denominations and an amount, return the minimum number of coins to make that amount."),
    ("string",
     "Given two strings, write a function to check whether they are anagrams of each other."),
    ("tree / recursion",
     "Given a binary tree and two node values, find their lowest common ancestor."),
    ("explicit constraint (should honor O(n)/O(1))",
     "Given a SORTED array of integers and a target, is there a pair that sums to the target? Do it in O(n) time and O(1) space."),
]


def strip_code(t): return re.sub(r"```.*?```", " ", t, flags=re.S)


LEAKS = {
    "markdown header": re.compile(r"(^|\n)\s*(#{1,6}\s|\*\*\d+\.)", re.M),
    "'Say:'/'Spoken plan' label": re.compile(r"\b(Say:|Spoken plan|Restate intent)\b", re.I),
    "'model answer'": re.compile(r"model answer", re.I),
    "'This is a <type> question'": re.compile(r"^\W*(okay,?\s*)?this is (a|an|the)\b[^.]*\bquestion\b", re.I),
    "role label": re.compile(r"(^|\n)\s*(Interviewer|Question|Follow[- ]?up)\s*:", re.I),
}


def main():
    brain = ClaudeBrain(context_loader=ContextLoader(context_dir=str(ROOT / "contexts" / "ml_engineer")))
    ok = True
    for label, q in PROBLEMS:
        print("\n" + "=" * 76)
        print(f"[{label}]\nINTERVIEWER: {q}")
        print(f"is_coding_question -> {is_coding_question(q)}")
        print("-" * 76)
        try:
            ans = brain.answer_question_sync(q)
        except Exception as e:
            ok = False; print(f"  ❌ error: {e}"); continue
        print(ans.strip())
        print("-" * 76)
        body = strip_code(ans)
        leaks = [n for n, rx in LEAKS.items() if rx.search(body)]
        code = "\n".join(re.findall(r"```(?:python)?\n(.*?)```", ans, re.S))
        inline_comments = len(re.findall(r"#\s*\S", code))
        struct = {
            "restate/clarify": bool(re.search(r"assum|constraint|sorted|duplicat|empty|input size|clarif|negative|in-place|\?", body, re.I)),
            "brute + better": bool(re.search(r"brute|naive|nested loop|O\(n\^?2|n squared|better|optimal|instead", body, re.I)),
            "complexity": "O(" in body,
            "has code": "```" in ans,
            f"inline comments ({inline_comments})": inline_comments >= 3,
        }
        print("  scaffolding: " + ("❌ " + "; ".join(leaks) if leaks else "✅ none"))
        print("  walkthrough: " + "  ".join(f"{'✓' if v else '✗'} {k}" for k, v in struct.items()))
        if leaks or not all(struct.values()):
            ok = False

    print("\n" + "=" * 76)
    print("RESULT:", "CODING MODE SOLID ✅" if ok else "ISSUES ❌ (see above)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
