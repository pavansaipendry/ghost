"""Claude Brain for Ghost AI.

Streaming LLM integration with Anthropic's Claude API.
Handles system prompts, conversation memory, answer modes,
predictive pre-fetch, and follow-up anticipation.

Usage:
    brain = ClaudeBrain(api_key="sk-...", context_loader=loader)
    brain.answer_question(
        question="Tell me about your experience with data pipelines",
        on_token=lambda token: print(token, end=""),
        on_done=lambda full_text: print("\\nDone:", full_text),
    )
"""

import os
import re
import threading
import time
from typing import Generator

import anthropic

from ghost.ai.model_router import ModelRouter, is_coding_question


# Main answer model (router escalates from here; see ModelRouter).
DEFAULT_MODEL = "claude-opus-4-8"
# Fast utility model for side tasks (connection pre-warm, follow-up prediction,
# completeness classification). These are latency/cost-sensitive helpers whose
# output quality barely matters - this MUST be a cheap fast model. It used to be
# set to the Opus answer model by mistake, which made every side call cost
# Opus money for throwaway output.
FAST_MODEL = "claude-haiku-4-5"

# Common resume/JD/English words to exclude when harvesting bias terms from context,
# so the speech recognizer's contextual hints stay focused on real jargon and names.
_KEYTERM_STOPWORDS = {
    "I", "A", "An", "The", "My", "We", "It", "This", "That", "And", "But", "Or",
    "For", "With", "To", "In", "On", "At", "Of", "As", "By", "From", "Into",
    "Built", "Led", "Worked", "Developed", "Designed", "Created", "Used", "Using",
    "Implemented", "Managed", "Owned", "Drove", "Shipped", "Delivered", "Improved",
    "Deployed", "Architected", "Building", "Scaled", "Optimized", "Migrated",
    "Experience", "Skills", "Summary", "Education", "Projects", "Resume", "About",
    "Job", "Description", "Role", "Company", "Team", "Senior", "Junior", "Lead",
    "Engineer", "Engineering", "Developer", "Manager", "Data", "Software", "System",
    "Systems", "Years", "Year", "Months", "January", "February", "March", "April",
    "May", "June", "July", "August", "September", "October", "November", "December",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    # All-caps résumé section headers / location codes that aren't real vocabulary.
    "PROFILE", "SUMMARY", "SKILLS", "TECHNICAL", "EXPERIENCE", "PROJECTS", "EDUCATION",
    "HACKATHONS", "LANGUAGES", "USA", "OOP", "ID", "TX", "KS", "CA", "NY",
}


class ContextLoader:
    """Loads and manages context files (resume, projects, job description)."""

    def __init__(self, context_dir: str = None):
        """
        Args:
            context_dir: Directory containing context markdown files.
                        Expected files: resume.md, projects.md, about_me.md, job_description.md
        """
        self._context_dir = context_dir
        self._resume = ""
        self._projects = ""
        self._about_me = ""
        self._job_description = ""
        self._custom_context = ""
        self._screen_context = ""  # live "what's on screen right now" (from ScreenVision)

        if context_dir:
            self.load_from_directory(context_dir)

    def load_from_directory(self, path: str):
        """Load all context files from a directory.

        The four role files (resume.md, projects.md, about_me.md, job_description.md)
        map to their labeled sections. ANY OTHER .md file in the directory is loaded
        as free-form reference context - so a role can be defined by a single, arbitrarily
        named .md (e.g. an interview prep sheet) with none of the four files present.
        """
        self._context_dir = path
        self._resume = self._load_file(os.path.join(path, "resume.md"))
        self._projects = self._load_file(os.path.join(path, "projects.md"))
        self._about_me = self._load_file(os.path.join(path, "about_me.md"))
        self._job_description = self._load_file(os.path.join(path, "job_description.md"))

        # Any other .md becomes free-form reference material (see build_context_block).
        known = {"resume.md", "projects.md", "about_me.md", "job_description.md"}
        extra = []
        try:
            for fname in sorted(os.listdir(path)):
                if fname.lower().endswith(".md") and fname not in known:
                    text = self._load_file(os.path.join(path, fname))
                    if text:
                        self._custom_context += ("\n\n" if self._custom_context else "") + text
                        extra.append(fname)
        except OSError:
            pass

        loaded = []
        if self._resume: loaded.append("resume")
        if self._projects: loaded.append("projects")
        if self._about_me: loaded.append("about_me")
        if self._job_description: loaded.append("job_description")
        loaded.extend(extra)
        print(f"[ContextLoader] Loaded: {', '.join(loaded) or 'nothing'} from {path}")

    def load_resume(self, text: str):
        self._resume = text

    def load_projects(self, text: str):
        self._projects = text

    def load_about_me(self, text: str):
        self._about_me = text

    def load_job_description(self, text: str):
        self._job_description = text

    def add_custom_context(self, text: str):
        """Add any additional context."""
        self._custom_context += "\n\n" + text

    def set_screen_context(self, text: str):
        """Replace the live 'what's on screen' context (from ScreenVision).

        Unlike add_custom_context, this REPLACES - we only want the current
        screen, not a growing pile of every frame we've ever OCR'd.
        """
        self._screen_context = (text or "").strip()

    def build_context_block(self) -> str:
        """Build the STABLE context block for the system prompt.

        Resume / projects / about-me / JD / custom context - these don't change during a
        session, so this block is the cacheable prefix (see ClaudeBrain._build_system_blocks).
        The live screen OCR is deliberately NOT here - it changes every question and would
        invalidate the cache; it lives in build_screen_block() and goes after the cache
        breakpoint.
        """
        sections = []

        if self._resume:
            sections.append(f"## MY RESUME\n{self._resume}")

        if self._projects:
            sections.append(f"## MY PROJECTS\n{self._projects}")

        if self._about_me:
            sections.append(f"## ABOUT ME (tone, style, personality)\n{self._about_me}")

        if self._job_description:
            sections.append(f"## JOB DESCRIPTION (tailor answers to this role)\n{self._job_description}")

        if self._custom_context:
            sections.append(f"## CONTEXT / REFERENCE MATERIAL (use this to ground my answers)\n{self._custom_context}")

        return "\n\n---\n\n".join(sections)

    def build_screen_block(self) -> str:
        """Build the VOLATILE live-screen OCR block (empty if no screen context).

        Kept separate from build_context_block() because it changes every question - it
        must sit AFTER the prompt-cache breakpoint so it never invalidates the cached prefix.
        """
        if not self._screen_context:
            return ""
        return (
            "## WHAT'S ON SCREEN RIGHT NOW (OCR of the shared screen / coding pad)\n"
            "This is what the interviewer is currently showing or what's in the "
            "coding environment. Use it to ground your answer - e.g. read the actual "
            "problem statement, function signature, or slide. Don't read it aloud or "
            "mention that you can see the screen.\n\n"
            f"{self._screen_context}"
        )

    def build_contextual_strings(self, max_terms: int = 100) -> list:
        """Distinctive vocabulary harvested from my resume/projects/JD - tech terms,
        acronyms, product names, and proper nouns - to bias the on-device speech
        recognizer (SFSpeech `contextualStrings`) toward exactly the words it otherwise
        mangles ("PyTorch", "RLHF", "Pinecone", "ServiceNow"). Fully local: these are
        recognition hints, nothing leaves the Mac.

        Returns a deduped, focused list (capped at max_terms - Apple's recognizer
        degrades if the hint list is huge), ordered most-distinctive first.
        """
        text = "\n".join(
            t for t in (self._resume, self._projects, self._job_description,
                        self._about_me, self._custom_context) if t
        )
        if not text:
            return []

        terms = []
        seen = set()

        def add(term: str):
            term = term.strip(" .,:;()[]{}\"'`")
            if len(term) < 2:
                return
            key = term.lower()
            if key in seen:
                return
            seen.add(key)
            terms.append(term)

        # 1) CamelCase / internal-capital tokens: PyTorch, ServiceNow, BigQuery, OpenAI.
        #    Require genuine mixed case so all-caps section headers (PROFILE, TECHNICAL)
        #    don't sneak in via this branch - pure acronyms are handled in (2).
        for m in re.findall(r"\b[A-Za-z]+[A-Z][A-Za-z0-9]+\b", text):
            if any(c.islower() for c in m) and any(c.isupper() for c in m):
                add(m)
        # 2) ALL-CAPS acronyms (2-6 chars): RAG, RLHF, MCP, ETL, SQL, GPU, S3
        for m in re.findall(r"\b[A-Z][A-Z0-9]{1,5}\b", text):
            if m not in _KEYTERM_STOPWORDS:
                add(m)
        # 3) hyphenated / dotted lowercase tech tokens: scikit-learn, pgvector, gpt-4
        for m in re.findall(r"\b[a-z][a-z0-9]*(?:[-.][a-z0-9]+)+\b", text):
            add(m)
        # 4) Capitalized words / short proper-noun phrases (companies, products, project
        #    names), up to 3 words. Strip leading sentence-starter/verb words so
        #    "Used Pinecone" -> "Pinecone" and "Deployed Kubernetes" -> "Kubernetes".
        for m in re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b", text):
            words = m.split()
            while words and words[0] in _KEYTERM_STOPWORDS:
                words = words[1:]
            if words:
                add(" ".join(words))

        return terms[:max_terms]

    @staticmethod
    def _load_file(path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            return ""


def detect_answer_mode(question: str, is_follow_up: bool = False) -> str:
    """Kept for backward compatibility with entry.py logging. Returns a label only."""
    if is_follow_up:
        return "follow_up"
    q = question.lower()
    coding_signals = {
        "matrix", "array", "string", "binary", "tree", "graph", "node",
        "linked", "list", "stack", "queue", "hash", "sort", "search",
        "subarray", "substring", "palindrome", "pointer",
        "integer", "number", "square", "grid", "path",
        "maximum", "minimum", "sum", "dynamic", "greedy",
        "ones", "zeros", "find the", "given a", "return the",
        "write a function", "implement", "time complexity",
        "design", "distributed", "caching", "system design",
        "microservice", "database", "scale", "scalable",
        "api", "endpoint", "pipeline", "etl", "deploy",
        "docker", "kubernetes", "sql", "query",
    }
    if sum(1 for s in coding_signals if s in q) >= 2:
        return "technical"
    behavioral_signals = [
        "tell me about a time", "describe a situation", "give me an example",
        "tell me about yourself", "why do you want", "biggest challenge",
    ]
    if any(s in q for s in behavioral_signals):
        return "behavioral"
    return "general"


# Prompt design notes (v3):
#
# v1 had contradictory hard rules ("ZERO projects" vs "at most ONE project") and
# threat framing, which muzzled the context system entirely. v2 fixed the
# contradictions but kept hard SENTENCE CAPS as the length mechanism, and hard
# caps have a known failure mode: when content doesn't fit, the model doesn't
# shrink everything evenly - it DROPS parts, classically the second half of a
# multi-part question ("what is X and have you used it?" loses the "have you
# used it"). v3 changes the length mechanism itself:
#
#   1. Length is anchored to SPEAKING TIME (what a candidate actually spends per
#      question type out loud), with sentence counts as rough guidance only.
#   2. An explicit tiebreaker: completeness beats the guideline - everything the
#      question asked for gets answered; room is made by tightening, never by
#      skipping. Multi-part questions get every part.
#   3. The opposite tiebreaker: answered means stop. No pre-answering follow-ups;
#      the interview is a conversation and depth gets pulled on demand.
#   4. "Tell me about yourself" is its own category (~30-40s) instead of being
#      crushed into the 2-3 sentence motivational bucket - a 2-3 sentence intro
#      reads as unprepared in a real interview.
SYSTEM_PROMPT = """You ARE me - a real candidate speaking out loud in a live interview, first person. Sound like a sharp, normal human, never like an AI. Every response should contain some filler words like "um" or "you know", "like" general english filler words. But for the answers, be concise and direct.

LENGTH - the one rule: answer the question COMPLETELY, in the fewest words that still cover it, then stop. Think in speaking time, not word count - most answers are 10-30 seconds said out loud. The times below are what a good candidate actually spends per question type; treat them as strong guidance. When they conflict, two tiebreakers:
- Completeness beats the guideline. If the question explicitly asked for something, it goes in - make room by cutting everything else tighter, never by skipping what was asked. Multi-part questions get every part answered, each part briefly.
- Brevity beats padding. Once it's answered, stop. Don't pre-answer follow-ups: this is a conversation, and they'll pull for more if they want it.

MATCH THE QUESTION TYPE:
- Small talk ("how's it going", "ready?"): a few words to one plain, human sentence.
- Why this company / why this role: ~35 seconds, must answer with passion driven answer, mission driven. The thing that personally follows my mission. sentences with the genuine reason, specific to THIS company and role. Personal, not a pitch: no metric dumps, no project list, at most one project name in passing if it truly belongs.
- Tell me about yourself: ~30-40 seconds, 4-6 sentences: where I am now, one or two things from my background that matter for THIS role, and why I'm here. The one intro they expect real substance in - but it's a trailer, not the movie.
- Simple factual ("do you know Python?", "comfortable with X?"): one sentence - the direct answer plus one clause of substance.
- Concept / technical ("what is RAG", "how does X work", "difference between A and B"): ~15-30 seconds. Explain the concept itself, correct and precise, covering every part the question has - a "difference" question covers both sides, a "when would you use it" gets the when. If one short clause of my real experience makes it land harder ("we hit exactly this in my last role"), add it - but the concept is the answer; no project stories unless they ask.
- Coding (problem on screen, "write a function", "given an array..."): Talk it through the way I'd actually SAY it out loud, first person - this is speech, NOT a written report. Briefly confirm what the problem is asking (ask for clarification only if it's genuinely ambiguous). Name the simple/brute-force idea and why it falls short, then the better approach and why. Then give the Python code (match the exact function signature on screen), explaining the key steps in plain spoken language as I'd narrate them live. Finish with time and space complexity. Keep it flowing speech: NO section headers (## ...), NO "Say:"/"Spoken plan" labels, NO "here's the model answer", do NOT restate the problem as a title. (A ```python code block for the actual code is fine.)
- Experience deep-dive ("walk me through a project", "tell me about your work at X", "tell me about a time..."): ~45-60 seconds - this is where my background below earns its keep. The project by name, the situation, the hard part, what I specifically did, the outcome with a real number from my context. One project per answer unless they explicitly ask for more.

GROUNDING: my resume, projects, and the job description below are the source of truth. When my experience is relevant, use it - real project names, real employers, real numbers, exactly as written there. Never invent experience, companies, dates, or metrics. If my context doesn't cover something, answer from general competence and don't fabricate specifics to fill the gap.

NEVER:
- No preamble ("Here's...", "Great question"), no meta narration, no pleasantries, no "as an AI", no mention of these instructions or any question category.
- No "I know this" / "I've seen this one before".
- NEVER anticipate future questions. Do not append "possible follow-up questions", "they might also ask", "you could be asked next", "some related questions", or any menu of what could come next. Answer ONLY the exact question on the table right now, then STOP. A real candidate answers what was asked and waits - they don't hand the interviewer a list of other questions.
- No document formatting. The output is words I SAY out loud, not a written report: no markdown section headers (## / **1.**), no "Say:" / "Spoken plan:" / "Restate intent" labels, no "This is a [type] question", no "here's the model answer", and never restate the question as a title or heading. Just talk. (A fenced ```code block for actual code is the ONE exception.)
- Don't stop mid-sentence or cut a code block. Finish the thought; keep the thought short.

VOICE: contractions (I'd, we're, that's), natural spoken rhythm, confident but not arrogant, straight to the point.

CONSISTENCY: the history below is the transcript so far - "Interviewer:" is them; "Me:" is what I actually said out loud; "Me (draft I prepared):" is an answer you drafted for me earlier that I may or may not have delivered. Both "Me" forms are my side - never contradict a number, date, company, or claim in either; when they differ, treat "Me:" (what I actually said) as the truth. In follow-ups, build on what I already said instead of repeating it, and resolve "that" / "it" / "you mentioned" from the history.

FINAL CHECK before answering: (1) did I cover every part that was actually asked, (2) is anything here that the question didn't ask for - cut it, (3) would a real person say this out loud in roughly its type's time? If it's generic where my context has something real, ground it.

{context_block}"""


# Activated ONLY when a coding problem is on the table (see is_coding_question). Injected
# as an extra system block so the answer follows the real coding-interview flow — but
# still delivered as spoken speech, never a formatted document.
CODING_MODE = """CODING PROBLEM MODE — a coding problem is on the table. Here is exactly how I work through it OUT LOUD, in this order. This is me thinking at a whiteboard, NOT a written report:

1. Restate the problem in my own words so we're aligned on what's actually being asked.
2. Ask the clarifying questions a strong candidate asks BEFORE coding — input size / constraints, is the input sorted, can there be duplicates or negatives, what about empty input, what do I return when there's no valid answer, in-place vs a new output. Then state the reasonable assumptions I'll run with so I can move forward.
3. The brute-force / simplest approach first, its cost, and why it's not good enough ("that's O(n^2), too slow if n is large").
4. Then the better approach and WHY it beats the brute force — the key insight that makes it faster or cleaner.
5. Say the plan out loud for a beat, THEN write the Python — match the exact function signature if one's on the screen.
6. LINE-BY-LINE VIA INLINE COMMENTS: put a SHORT comment on the end of each meaningful line, in plain spoken language, saying what that line does and why — phrased so I can just read the comment aloud AS I type that line. Comment every non-trivial line; skip only dead-obvious boilerplate. For example:
   left, right = 0, len(arr) - 1   # left starts at the front, right at the end
   while left < right:             # keep going until the two pointers meet
       s = arr[left] + arr[right]  # sum of the current pair
       elif s < target:            # sum's too small, so move left up to a bigger number
   This inline narration REPLACES a separate after-the-code walkthrough — the comments ARE the line-by-line explanation.
7. Finish with time and space complexity.

Deliver ALL of it as natural, flowing speech with my normal filler ("um", "so", "you know") — NOT a document. No numbered headings, no "Step 1:", no "Say:", no "here's the model answer". Just talk it through in that order like a sharp candidate thinking on their feet. The ```python code block (WITH its inline comments) is the only formatting allowed."""


class ClaudeBrain:
    """Streaming Claude integration for Ghost AI."""

    def __init__(self, api_key: str = None, context_loader: ContextLoader = None,
                 model: str = DEFAULT_MODEL):
        """
        Args:
            api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.
            context_loader: ContextLoader with resume/projects/etc.
            model: Claude model to use.
        """
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self._api_key:
            raise ValueError("Anthropic API key required. Set ANTHROPIC_API_KEY env var or pass api_key.")

        self._client = anthropic.Anthropic(api_key=self._api_key)
        self._context_loader = context_loader or ContextLoader()
        self._model = model
        # Per-question model routing: QUICK/STANDARD/DEEP tiers. The QUICK tier uses
        # `model` (the configured default) so existing behavior holds for simple
        # questions; harder questions escalate. Local heuristic - no added latency.
        self._router = ModelRouter(quick_model=model)
        self._conversation_history = ""
        self._lock = threading.Lock()
        self._current_stream = None
        self._cancel_flag = threading.Event()
        # HUD/vision cancel is per-stream, same pattern as the interview flag (see
        # answer_question for why): each new HUD stream gets its OWN Event. The old
        # shared-event clear() had the exact bug the interview path already fixed -
        # starting stream B cleared the flag stream A was watching, resurrecting A
        # to run (and bill) to completion in parallel.
        self._hud_cancel = threading.Event()
        self._warmed_up = False

        print(f"[ClaudeBrain] Initialized with model: {self._model}")

        # Pre-warm: establish TLS + HTTP/2 connection in background
        # Saves ~200-500ms on the first real question
        threading.Thread(target=self._pre_warm, daemon=True).start()

    def set_conversation_history(self, history: str):
        """Update the conversation history (from ConversationTracker)."""
        with self._lock:
            self._conversation_history = history

    def answer_question(
        self,
        question: str,
        is_follow_up: bool = False,
        on_token: callable = None,
        on_done: callable = None,
        on_error: callable = None,
    ):
        """Generate a streaming answer to a question.

        Runs in a background thread. Tokens are delivered via on_token callback.

        Args:
            question: The interviewer's question
            is_follow_up: Whether this is a follow-up to the previous question
            on_token: Callback(token_str) - called for each streamed token
            on_done: Callback(full_text, mode) - called when answer is complete
            on_error: Callback(error_str) - called on error
        """
        # Each answer gets its OWN cancel event. With a single shared flag,
        # set-then-clear (cancel the old answer, start the new one) leaves a
        # window where the superseded stream never sees the set and runs to
        # completion - burning tokens in parallel with the real answer.
        self._cancel_flag.set()
        cancel_flag = threading.Event()
        self._cancel_flag = cancel_flag

        def _work():
            # Track whether any token reached the UI. Retrying after a MID-STREAM
            # failure would restart the stream from token zero while the chat
            # bubble already contains the partial - the answer's first half would
            # appear twice. So: retry freely while nothing was delivered, but once
            # tokens are out, surface the error instead of double-printing.
            delivered = False

            def _tok(t):
                nonlocal delivered
                delivered = True
                if on_token:
                    on_token(t)

            max_retries = 2
            for attempt in range(max_retries + 1):
                try:
                    if cancel_flag.is_set():
                        return
                    full_text = self._stream_answer(question, is_follow_up, _tok,
                                                    cancel_flag)
                    if on_done and not cancel_flag.is_set():
                        mode = detect_answer_mode(question, is_follow_up)
                        on_done(full_text, mode)
                    return  # Success
                except anthropic.APIConnectionError as e:
                    if attempt < max_retries and not delivered:
                        wait = 1.0 * (attempt + 1)
                        print(f"[ClaudeBrain] Connection error, retry {attempt + 1}/{max_retries} in {wait}s: {e}")
                        time.sleep(wait)
                    else:
                        print(f"[ClaudeBrain] Connection failed"
                              f"{' mid-stream' if delivered else f' after {max_retries} retries'}: {e}")
                        if on_error:
                            on_error(f"Connection failed: {e}")
                        return
                except anthropic.RateLimitError as e:
                    if attempt < max_retries and not delivered:
                        wait = 2.0 * (attempt + 1)
                        print(f"[ClaudeBrain] Rate limited, retry {attempt + 1}/{max_retries} in {wait}s")
                        time.sleep(wait)
                    else:
                        print(f"[ClaudeBrain] Rate limited"
                              f"{' mid-stream' if delivered else f' after {max_retries} retries'}")
                        if on_error:
                            on_error(f"Rate limited: {e}")
                        return
                except Exception as e:
                    print(f"[ClaudeBrain] Error: {e}")
                    if on_error:
                        on_error(str(e))
                    return  # Don't retry on other errors

        thread = threading.Thread(target=_work, daemon=True)
        thread.start()

    def answer_question_sync(self, question: str, is_follow_up: bool = False) -> str:
        """Synchronous version - blocks until answer is complete. For testing."""
        return self._stream_answer(question, is_follow_up)

    def ask(self, question: str, on_token: callable = None,
            on_done: callable = None, on_error: callable = None):
        """Direct typed question -> streamed answer (for the floating HUD box).

        Uses the SAME system prompt + resume/JD context, so it answers as me and
        knows my background. Runs on its own cancel flag so it never interferes with
        the live interview answer stream.
        """
        # Per-stream cancel event (see __init__ comment): cancel the previous HUD
        # stream, then give THIS stream a fresh event.
        self._hud_cancel.set()
        hud_cancel = threading.Event()
        self._hud_cancel = hud_cancel
        messages = [{"role": "user", "content": question}]
        self._run_hud_stream(messages, hud_cancel, on_token, on_done, on_error, label="ask")

    def answer_from_image(self, image_b64: str, media_type: str = "image/png",
                          instruction: str = None, on_token: callable = None,
                          on_done: callable = None, on_error: callable = None):
        """Vision: a screenshot of my screen -> streamed answer (for screen-shared
        questions OCR can't read). Sends the image to the vision model with my full
        interview context and answer rules - coding problems come back with code.
        """
        self._hud_cancel.set()
        hud_cancel = threading.Event()
        self._hud_cancel = hud_cancel
        instr = instruction or (
            "This is a screenshot of my interview screen (the interviewer may be "
            "sharing it). Read whatever question, coding problem, or prompt is shown "
            "and answer it AS ME, out loud, following ALL my answer rules - first "
            "person, spoken, no meta, no document formatting. If it's a coding problem, "
            "follow my coding-walkthrough flow (restate, clarify, brute force, better "
            "approach and why, then code matching the on-screen signature WITH a short "
            "inline comment on each meaningful line, then complexity) - all as natural "
            "speech, not a document. If nothing looks like a question, just say briefly "
            "what's on screen."
        )
        content = [
            {"type": "image", "source": {
                "type": "base64", "media_type": media_type, "data": image_b64}},
            {"type": "text", "text": instr},
        ]
        messages = [{"role": "user", "content": content}]
        # Vision is almost always a screen-shared coding/problem, so activate coding mode.
        self._run_hud_stream(messages, hud_cancel, on_token, on_done, on_error,
                             label="vision", coding_mode=True)

    def _run_hud_stream(self, messages, cancel_flag, on_token, on_done, on_error,
                        label="hud", coding_mode=False):
        """Stream a one-shot answer for the HUD box in a background thread."""
        def _work():
            try:
                full = self._stream_messages(messages, cancel_flag, on_token,
                                             coding_mode=coding_mode)
                if on_done and not cancel_flag.is_set():
                    on_done(full)
            except Exception as e:
                print(f"[ClaudeBrain] {label} error: {e}")
                if on_error:
                    on_error(str(e))
        threading.Thread(target=_work, daemon=True).start()

    def cancel_hud(self):
        """Cancel the current HUD/vision answer stream."""
        self._hud_cancel.set()

    def cancel(self):
        """Cancel the current streaming answer."""
        self._cancel_flag.set()

    def anticipate_followup(self, question: str, answer: str, on_done: callable = None):
        """Predict what the interviewer might ask next.

        Uses the fast model for quick prediction. NOTE: only call this if something
        actually consumes the prediction - entry.py's consumer was a no-op for a
        while, which made this a pure per-answer cost (and FAST_MODEL was
        accidentally Opus, so a wasted Opus request after EVERY answer).
        """
        def _work():
            try:
                prompt = (
                    f"Given this interview exchange:\n"
                    f"Interviewer: {question}\n"
                    f"Candidate: {answer}\n\n"
                    f"Predict the 2-3 most likely follow-up questions the interviewer would ask. "
                    f"Be specific. One line each, no numbering."
                )

                response = self._client.messages.create(
                    model=FAST_MODEL,
                    max_tokens=200,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.content[0].text.strip()
                if on_done:
                    on_done(text)
            except Exception as e:
                print(f"[ClaudeBrain] Anticipation error: {e}")

        thread = threading.Thread(target=_work, daemon=True)
        thread.start()

    def classify_question_completeness(self, text: str) -> bool:
        """Fast classifier: is this a complete question?

        Uses the fast model for speed.

        Args:
            text: Transcribed text to classify

        Returns:
            True if the text is a complete question
        """
        try:
            response = self._client.messages.create(
                model=FAST_MODEL,
                max_tokens=10,
                messages=[{
                    "role": "user",
                    "content": f"Is this a complete interview question or is the speaker likely to continue? "
                               f"Answer only COMPLETE or INCOMPLETE.\n\nText: \"{text}\""
                }],
            )
            result = response.content[0].text.strip().upper()
            return "COMPLETE" in result
        except Exception:
            return False  # Default to incomplete on error

    # ── Internal ──

    def _pre_warm(self):
        """Establish connection to Anthropic API so first real request is fast."""
        try:
            start = time.time()
            self._client.messages.create(
                model=FAST_MODEL,
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            latency = time.time() - start
            self._warmed_up = True
            print(f"[ClaudeBrain] Connection pre-warmed ({latency:.1f}s)")
        except Exception as e:
            print(f"[ClaudeBrain] Pre-warm failed (non-critical): {e}")

        # If context is already loaded, warm the prompt cache too so the FIRST
        # interview question reads the cached prefix instead of writing it cold.
        self.warm_cache()

    def warm_cache(self):
        """Pre-warm the prompt cache on EVERY model the router can pick.

        Caches are per-model, so without this the first question that escalates to a
        bigger model would pay a cold ~6K-token prefill - a TTFT spike on exactly the
        hardest question. Each warm request runs prefill, writes that model's cache at
        the breakpoint, and stops after a single output token.

        max_tokens is 1, not 0: the Messages API rejects max_tokens=0 as invalid, so
        the old 0 meant every one of these calls errored out and the cache was NEVER
        warmed - the feature silently didn't exist. One billed output token per model
        is the cost of it actually working.
        """
        if not self._context_loader.build_context_block():
            return  # nothing stable worth caching yet
        stable_block = self._build_system_blocks()[0]  # the cache_control'd prefix
        for model in self._router.models:
            try:
                self._client.messages.create(
                    model=model,
                    max_tokens=1,
                    system=[stable_block],
                    messages=[{"role": "user", "content": "warmup"}],
                )
                print(f"[ClaudeBrain] Prompt cache warmed: {model}")
            except Exception as e:
                print(f"[ClaudeBrain] Cache warm skipped for {model} (non-critical): {e}")

    def _stream_answer(self, question: str, is_follow_up: bool, on_token: callable = None,
                       cancel_flag: threading.Event = None) -> str:
        """Stream an answer from Claude (interview path; uses the interview cancel flag).

        Routes the question to the right model/effort first (see ModelRouter). Only the
        interviewer-answer path is routed; the HUD/vision paths keep the default model."""
        screen = getattr(self._context_loader, "_screen_context", "") or None
        decision = self._router.route(question, is_follow_up, screen_context=screen)
        coding = is_coding_question(question, screen)
        print(f"[Router] tier={decision.tier} model={decision.model} "
              f"effort={decision.effort} coding={coding} | q={question[:60]!r}")
        return self._stream_messages(
            [{"role": "user", "content": question}],
            cancel_flag if cancel_flag is not None else self._cancel_flag, on_token,
            model=decision.model, effort=decision.effort, thinking=decision.thinking,
            coding_mode=coding,
        )

    def _stream_messages(self, messages, cancel_flag, on_token: callable = None,
                         model: str = None, effort: str = None, thinking: dict = None,
                         coding_mode: bool = False) -> str:
        """Stream an answer for the given messages, honoring `cancel_flag`.

        Shared by the interview path, the typed-chat (ask) path, and the vision path -
        all use the same system prompt (resume + JD + answer rules). `model`/`effort`/
        `thinking` default to the configured model (no effort/thinking). `coding_mode`
        appends the coding-walkthrough instruction for coding problems."""
        system_blocks = self._build_system_blocks(coding_mode=coding_mode)

        kwargs = dict(
            model=model or self._model,
            # Adaptive thinking (DEEP tier) spends from this same budget before a
            # single visible token - 4096 total let a hard question think the whole
            # cap away and truncate the answer. Streaming, so no timeout risk.
            max_tokens=16000,
            system=system_blocks,
            messages=messages,
        )
        # Only attach effort/thinking when the router asked for a model that
        # supports them.
        if effort:
            kwargs["output_config"] = {"effort": effort}
        if thinking:
            kwargs["thinking"] = thinking

        full_text = ""
        with self._client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                if cancel_flag.is_set():
                    break
                full_text += text
                if on_token:
                    on_token(text)

        return full_text

    def _build_system_blocks(self, coding_mode: bool = False) -> list:
        """System prompt as cache-aware content blocks (what the API actually receives).

        Block 1 - STABLE, cached: the answer rules + my resume / projects / JD / about-me.
        Identical on every question in a session, so it carries cache_control:ephemeral.
        The model reads it from cache (~0.1x input cost, lower time-to-first-token)
        instead of reprocessing the whole prefix every turn.

        Block 2 - VOLATILE, uncached: the live screen OCR + the growing conversation
        history. These change every question, so they MUST sit AFTER the cache breakpoint -
        if they were inside Block 1 they'd invalidate the cached prefix on every call.
        """
        context_block = self._context_loader.build_context_block()
        stable_text = SYSTEM_PROMPT.format(
            context_block=context_block if context_block else "(No context files loaded)",
        )

        blocks = [{
            "type": "text",
            "text": stable_text,
            "cache_control": {"type": "ephemeral"},
        }]

        # Coding-walkthrough mode: an extra block AFTER the cache breakpoint (so toggling
        # it never invalidates the cached prefix), present only for coding problems.
        if coding_mode:
            blocks.append({"type": "text", "text": CODING_MODE})

        volatile_text = self._build_volatile_text()
        if volatile_text:
            blocks.append({"type": "text", "text": volatile_text})

        return blocks

    def _build_volatile_text(self) -> str:
        """The per-question (uncached) tail: live screen OCR + conversation so far."""
        parts = []

        screen = self._context_loader.build_screen_block()
        if screen:
            parts.append(screen)

        with self._lock:
            conversation = self._conversation_history
        if conversation:
            parts.append(f"## INTERVIEW CONVERSATION SO FAR\n{conversation}")

        return "\n\n---\n\n".join(parts)

    def _build_system_prompt(self) -> str:
        """Flattened string form of the system prompt (for tests / logging only).

        The live API path uses _build_system_blocks() so it can cache the stable prefix;
        this just concatenates the same blocks for callers that want a single string.
        """
        return "\n\n".join(b["text"] for b in self._build_system_blocks())