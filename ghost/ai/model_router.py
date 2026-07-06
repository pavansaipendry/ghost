"""Model router for Ghost AI — pick the cheapest model that can answer well.

Routing is a fast LOCAL heuristic — there is NO LLM call in the critical path. It scores
the interviewer's question from lexical/structural signals and buckets it into one tier:

    QUICK    -> Haiku 4.5    (instant; behavioral, factual, quick concept checks)
    STANDARD -> Sonnet 4.6   (effort low; typical coding, moderate reasoning, concepts)
    DEEP     -> Opus 4.8     (effort high; system design, hard coding, deep multi-part)

Measured warm-cache time-to-first-token: Haiku ~0.5s, Sonnet ~0.9s, Opus ~1.3-2.1s.
Routing itself adds ~0ms (pure string scoring), so the QUICK path stays sub-second.

Design rules baked in:
  - Behavioral questions ("tell me about a time…") are CAPPED at QUICK — depth doesn't
    help a story, and speed + natural voice matter most there.
  - An actual design/build TASK or hard-coding TASK goes DEEP; a concept *question* about
    the same topic ("what's the difference between sharding and partitioning") stays
    STANDARD — we route on what's being ASKED, not just which nouns appear.
  - When uncertain, bias up one tier (under-answering a hard question is worse than a
    slightly slower answer) — except behavioral, which never escalates past QUICK.
  - Depth follow-ups ("why", "tradeoffs", "edge cases") and multi-part questions bump +1.
"""

QUICK = "quick"
STANDARD = "standard"
DEEP = "deep"

_TIER_ORDER = [QUICK, STANDARD, DEEP]


# ── Signal vocabularies (matched against the lowercased question) ──

# Behavioral / experience stories → QUICK, capped (never escalates).
_BEHAVIORAL = (
    "tell me about a time", "tell me about yourself", "describe a time",
    "describe a situation", "give me an example", "a time when", "how did you handle",
    "why do you want", "why are you interested", "biggest challenge", "greatest weakness",
    "your weakness", "your strength", "walk me through your",
    "tell me about your experience", "how do you deal", "conflict with",
)

# An actual DESIGN / BUILD task (imperative), not just a topic mention → DEEP.
_DESIGN_TASK = (
    "design a", "design an", "design the", "design and", "how would you design",
    "how would you build", "how would you architect", "how would you scale",
    "how do you design", "architect a", "build a system", "system design",
    "scale to", "scale this", "scale it", "design a system",
)

# Hard algorithmic work → DEEP.
_HARD_CODING = (
    "optimize", "most efficient", "optimal solution", "minimize the", "maximize the",
    "dynamic programming", "shortest path", "minimum cost", "minimum number",
    "time and space complexity", "best time complexity", "better than o(", "reduce the time",
)

# Conceptual factual lead-ins → QUICK (short) / STANDARD (longer). A concept question,
# even about a heavy topic, is not a design task.
_FACTUAL_LEAD = (
    "what is", "what's", "what are", "define", "explain", "difference between",
    "do you know", "have you used", "are you familiar", "can you explain", "tell me what",
    "what does", "when would you use", "why would you use",
)

# "This smells like system architecture / scale." A factual question that mentions these
# is a real technical concept (→ STANDARD, not a one-liner), and combined with a depth
# follow-up it earns DEEP.
_SCALE_OR_ARCH = (
    "distributed", "at scale", "scalab", "throughput", "bottleneck", "high availability",
    "fault toler", "sharding", "shard", "partition", "replication", "consistency",
    "load balanc", "microservice", "concurren", "latency", "eventual",
)

# Ordinary coding problems (LeetCode-style) → STANDARD floor.
_CODING = (
    "write a function", "write code", "implement", "given an array", "given a string",
    "given an integer", "given a list", "given a matrix", "return the", "find the",
    "leetcode", "reverse a", "two sum", "valid ", "palindrome", "linked list",
    "binary tree", "binary search", "sort the", "merge ", "subarray", "substring",
)

# Depth follow-ups / drill-downs → bump up one tier.
_DEPTH = (
    "trade-off", "tradeoff", "trade off", "go deeper", "deeper", "edge case", "what if",
    "at scale", "bottleneck", "why did you", "why not", "how would you improve",
    "what about", "any other", "alternatives", "downside",
)


def _contains_any(text: str, needles) -> bool:
    return any(n in text for n in needles)


# A real coding problem shown on the shared screen (function stub, examples, constraints)
# — used so a LeetCode problem the interviewer only SHOWS still triggers coding mode.
_SCREEN_CODE_SIGNALS = (
    "def ", "class solution", "function", "return", "example 1", "example:",
    "constraints", "input:", "output:", "->", "leetcode", "for i in", "nums[",
)


# Extra coding signals not in the router's tier keywords: data-structure phrasings the
# exact `_CODING` needles miss ("given a SORTED array" vs "given an array") and explicit
# complexity constraints, which only ever show up in coding problems.
_CODING_HINTS = (
    "sorted array", "two pointer", "two-pointer", "in-place", "subsequence",
    "sum to", "sums to", "add up to", "o(n", "o(1", "o(log", "o(n^2", "o(nlog",
    "time complexity", "space complexity",
)


def is_coding_question(question: str = "", screen_context: str = None) -> bool:
    """True when the interviewer wants CODE — a LeetCode-style prompt in the question,
    a hard algorithmic ask, or a coding problem sitting on the shared screen. Reuses the
    router's coding keyword sets so detection lives in ONE place; drives claude_brain's
    dedicated coding-walkthrough mode."""
    q = (question or "").lower()
    if _contains_any(q, _CODING) or _contains_any(q, _HARD_CODING) or _contains_any(q, _CODING_HINTS):
        return True
    if screen_context:
        s = screen_context.lower()
        if len(s) > 120 and _contains_any(s, _SCREEN_CODE_SIGNALS):
            return True
    return False


class RouteDecision:
    """The routing result: which model + how hard it should think."""

    def __init__(self, tier: str, model: str, effort: str = None, thinking: dict = None):
        self.tier = tier
        self.model = model
        self.effort = effort        # None | "low" | "medium" | "high" | "xhigh" | "max"
        self.thinking = thinking    # None | {"type": "adaptive"}

    def __repr__(self):
        return (f"RouteDecision(tier={self.tier}, model={self.model}, "
                f"effort={self.effort}, thinking={self.thinking})")


class ModelRouter:
    """Maps an interviewer question to (model, effort, thinking) via local heuristics."""

    def __init__(
        self,
        quick_model: str = "claude-opus-4-8",
        standard_model: str = "claude-opus-4-8",
        deep_model: str = "claude-opus-4-8",
        # Per-tier knobs (effort/thinking). Haiku takes neither (it errors on both).
        # DEEP defaults to Opus + adaptive thinking + high effort (best answer; ~2s TTFT).
        # Drop deep_thinking to None and deep_effort to "low" if you need DEEP faster
        # before the hedged-opener latency masking lands.
        standard_effort: str = "low",
        deep_effort: str = "high",
        deep_thinking: dict = None,
        enabled: bool = True,
    ):
        self._quick_model = quick_model
        self._standard_model = standard_model
        self._deep_model = deep_model
        self._standard_effort = standard_effort
        self._deep_effort = deep_effort
        self._deep_thinking = deep_thinking if deep_thinking is not None else {"type": "adaptive"}
        self._enabled = enabled

    @property
    def models(self) -> list:
        """The distinct models this router can emit — used to pre-warm every cache."""
        return list(dict.fromkeys([self._quick_model, self._standard_model, self._deep_model]))

    def route(self, question: str, is_follow_up: bool = False,
              screen_context: str = None) -> RouteDecision:
        """Score a question and return the model + effort to answer it with."""
        tier = self._score_tier(question or "", is_follow_up, screen_context)
        return self._decision_for_tier(tier)

    # ── Internals ──

    def _score_tier(self, question: str, is_follow_up: bool, screen_context: str) -> str:
        if not self._enabled:
            return QUICK  # routing off → always the fast default model

        q = question.lower().strip()
        words = len(q.split())

        arch = _contains_any(q, _SCALE_OR_ARCH)

        # 1) Behavioral stories are capped at QUICK — never escalate.
        if _contains_any(q, _BEHAVIORAL):
            return QUICK

        # 2) Base tier from what's being ASKED.
        if _contains_any(q, _DESIGN_TASK) or _contains_any(q, _HARD_CODING):
            base = DEEP
        elif _contains_any(q, _FACTUAL_LEAD):
            # A concept *question* — STANDARD if it's about a real architecture/scale topic,
            # otherwise QUICK when short (a quick definition), STANDARD when longer.
            base = STANDARD if (arch or words > 12) else QUICK
        elif _contains_any(q, _CODING):
            base = STANDARD
        else:
            base = STANDARD if (arch or words > 12) else QUICK

        # A full coding/design problem on the shared screen is at least STANDARD.
        if screen_context and len(screen_context) > 120 and base == QUICK:
            base = STANDARD

        # 3) Escalate +1 for depth drill-downs ("tradeoffs", "edge cases", "at scale") or
        #    multi-part questions. is_follow_up reinforces but isn't required — the terms
        #    themselves signal that a deeper answer is wanted.
        depth = _contains_any(q, _DEPTH)
        multipart = (q.count("?") >= 2) or (" and then " in q) or (" and how " in q)
        if depth or multipart:
            base = self._bump(base)

        return base

    @staticmethod
    def _bump(tier: str) -> str:
        i = _TIER_ORDER.index(tier)
        return _TIER_ORDER[min(i + 1, len(_TIER_ORDER) - 1)]

    def _decision_for_tier(self, tier: str) -> RouteDecision:
        if tier == DEEP:
            return RouteDecision(DEEP, self._deep_model, self._deep_effort, self._deep_thinking)
        if tier == STANDARD:
            return RouteDecision(STANDARD, self._standard_model, self._standard_effort, None)
        return RouteDecision(QUICK, self._quick_model, None, None)
