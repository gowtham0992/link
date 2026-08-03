"""Event stream for the Link memory-hygiene benchmark.

Deterministic and fully auditable, like the recall dataset: every event is
authored text with a ground-truth label, so hygiene metrics (junk rate,
contradiction exposure, stale recall) are exact — no LLM, no judging.

The stream simulates months of agent sessions over one memory workspace:

- fact:        the user states a durable preference/decision (both pipelines store)
- revision:    the user changes their mind about an earlier fact (contradiction)
- echo:        the agent restates a stored memory with framing words
- brief_echo:  Link's own injected session brief appears in the transcript
- noise:       a session with nothing memory-worthy

Facts and their recall queries come from the recall benchmark dataset so the
two benchmarks stay consistent.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from recall_dataset import INTENTS  # noqa: E402

# Revisions: the user changes their mind about an earlier fact. Written to
# genuinely contradict the original (same subject, opposing content).
# (intent_name, revised_title, revised_body, revision_query_expectation)
REVISIONS: list[tuple[str, str, str]] = [
    ("ruff-linting", "Biome replaces Ruff",
     "We decided Python linting does not use Ruff anymore; linting now runs through Biome with the shared config."),
    ("deploy-from-main", "Deploy from release branches",
     "We decided releases never deploy from the main branch now; production ships only from release/* branches after sign-off."),
    ("pytest-over-unittest", "Vitest-style specs via pytest plugins",
     "We decided new tests do not use plain pytest functions anymore; the team settled on behavior-spec style suites."),
    ("weekly-release", "Daily release trains",
     "We decided releases never ship weekly on Thursdays now; a release train leaves every day after CI passes."),
    ("sqlite-storage", "DuckDB replaces SQLite",
     "We decided local data does not live in SQLite anymore; the project settled on DuckDB files with the same no-service rule."),
    ("morning-syncs", "Afternoon syncs",
     "The user does not prefer morning meetings anymore; schedule syncs in the afternoon after two focus blocks."),
    ("dark-theme", "Light theme for demos",
     "The user does not use dark theme for demos anymore; capture screenshots in light mode for print legibility."),
    ("node-version", "Node 24 LTS required",
     "We decided builds do not require Node 22 anymore; the frontend now requires Node 24 LTS and CI fails below it."),
    ("api-port-8080", "API moves to port 9000",
     "We decided the backend API does not listen on port 8080 anymore; local development now binds port 9000."),
    ("release-notes-short", "Detailed release notes",
     "The user does not prefer short release notes anymore; write detailed notes with migration guidance per change."),
    ("backups-nightly", "Hourly incremental backups",
     "We decided databases are not backed up nightly anymore; incremental backups now run hourly with 7-day retention."),
    ("commit-style", "Stacked-diff workflow",
     "The user does not prefer small standalone commits anymore; we settled on stacked diffs with one reviewable stack per feature."),
]

# Echo templates: how agents restate stored memory back into a transcript.
ECHO_TEMPLATES = (
    "Per your saved preference, {claim} I will keep following that.",
    "As Link memory says, {claim} Noted again for this session.",
    "Just confirming what we already know: {claim}",
)

# Question sessions: quiz/debug questions that contain absolute keywords.
# Found in real dogfooding — "always" inside a question matched the preference
# cue and a quiz question ranked as a top durable memory. A perfect system
# proposes none of these.
QUESTION_SESSIONS = (
    "Is the number of walkers always fixed in this design, or can it change per round?",
    "Should we always deploy on Fridays, or does that break the on-call rotation?",
    "Why does the linter never flag this file even when the rule is enabled?",
    "Do we only support Python 3.12 in CI, and what happens below that?",
    "Wait, the cache never invalidates on write? How does the read path stay fresh?",
    "Is it true that failed jobs are never retried by the scheduler?",
)

# Pasted third-party prose: the user pastes advice from another AI, a forum,
# or a blog into their own turn. The words sit in a user turn but are not the
# user's claims — storing them attributes someone else's advice to the user
# (found in real dogfooding: Gemini's prose proposed as the user's memory).
PASTED_AI_SESSIONS = (
    "Pasting what the other assistant told me for context. People on Reddit "
    "emphasize that companies always screen for candidates who do not outsource "
    "their thinking. Reviewers never accept generic cover letters, according to "
    "several threads on the hiring process.",
    "From the blog post: successful maintainers always squash their commits before "
    "merging, and popular projects never allow force-pushes to shared branches. "
    "The post recommends branch protection for everything.",
    "Copying the guide here. The tutorial says beginners should avoid premature "
    "optimization, and that profiling always comes before rewriting hot loops. "
    "It also says garbage collection never runs during a benchmark window.",
    "Here is the other model's summary for reference. It claims teams always "
    "benefit from trunk-based development and never need long-lived feature "
    "branches once CI is fast enough.",
)

# Sessions with nothing memory-worthy (no decision/preference cues).
NOISE_SESSIONS = (
    "Looked through the failing test output together and reran the suite twice. "
    "Second run was green. Closed the terminal and moved on to reviewing the open pull request.",
    "Walked the directory layout, opened a few files, and renamed a local variable for readability. "
    "Nothing else came up during the session today.",
    "Compared two stack traces from the crash report and confirmed both point at the same frame. "
    "Filed the reproduction steps into the ticket and ended there.",
    "Read the vendor changelog aloud, skimmed the migration table, and concluded it does not affect us this quarter.",
)

INJECTED_BRIEF_TEMPLATE = (
    "Link memory (local, source-backed) · project demo\n"
    "Link memory brief\n"
    "Relevant memories\n"
    "- {title} ({memory_type} · user)\n"
    "Agent guidance\n"
    "- Use relevant_memories as durable local context before answering or coding."
)


def _day(index: int) -> str:
    """Deterministic YYYY-MM-DD dates spanning ~6 simulated months."""
    month = 1 + (index // 28)
    day = 1 + (index % 28)
    return f"2026-{month:02d}-{day:02d}"


def build_event_stream() -> list[dict[str, str]]:
    """Interleave facts, echoes, revisions, brief echoes, and noise over time.

    Ground truth per event: `kind` says what a perfect memory system should do
    (store / supersede / drop).
    """
    events: list[dict[str, str]] = []
    intents = list(INTENTS)
    revision_by_name = {name: (title, body) for name, title, body in REVISIONS}

    day = 0
    noise_cursor = 0
    echo_cursor = 0
    question_cursor = 0
    pasted_cursor = 0
    for position, (name, _domain, title, _tldr, body, _queries) in enumerate(intents):
        # The user states a durable fact.
        events.append({
            "kind": "fact", "date": _day(day), "intent": name,
            "title": title, "text": f"We decided: {body}",
        })
        day += 1
        # Agents echo roughly every other stored fact in a later session.
        if position % 2 == 0:
            template = ECHO_TEMPLATES[echo_cursor % len(ECHO_TEMPLATES)]
            echo_cursor += 1
            events.append({
                "kind": "echo", "date": _day(day), "intent": name,
                "text": template.format(claim=body),
            })
            day += 1
        # Link's own brief shows up in transcripts periodically.
        if position % 3 == 0:
            events.append({
                "kind": "brief_echo", "date": _day(day), "intent": name,
                "text": INJECTED_BRIEF_TEMPLATE.format(title=title, memory_type="preference"),
            })
            day += 1
        # And some sessions simply contain nothing memory-worthy.
        if position % 4 == 0:
            events.append({
                "kind": "noise", "date": _day(day), "intent": "",
                "text": NOISE_SESSIONS[noise_cursor % len(NOISE_SESSIONS)],
            })
            noise_cursor += 1
            day += 1
        # Quiz/debug questions carrying absolute keywords ("always", "never").
        if position % 5 == 0:
            events.append({
                "kind": "question", "date": _day(day), "intent": "",
                "text": QUESTION_SESSIONS[question_cursor % len(QUESTION_SESSIONS)],
            })
            question_cursor += 1
            day += 1
        # Pasted third-party advice inside a user turn.
        if position % 6 == 0:
            events.append({
                "kind": "pasted_ai", "date": _day(day), "intent": "",
                "text": PASTED_AI_SESSIONS[pasted_cursor % len(PASTED_AI_SESSIONS)],
            })
            pasted_cursor += 1
            day += 1
        # The same conversation continues in a later session and restates the
        # fact verbatim — cross-session re-proposal. A perfect system keeps
        # exactly one copy.
        if position % 3 == 1:
            events.append({
                "kind": "repeat", "date": _day(day), "intent": name,
                "text": f"We decided: {body}",
            })
            day += 1

    # Mid-stream, the user revises a third of the facts.
    for name, (revised_title, revised_body) in revision_by_name.items():
        events.append({
            "kind": "revision", "date": _day(day), "intent": name,
            "title": revised_title, "text": revised_body,
        })
        day += 1
        # Revised facts get echoed too — of the NEW truth.
        events.append({
            "kind": "echo", "date": _day(day), "intent": name,
            "text": ECHO_TEMPLATES[echo_cursor % len(ECHO_TEMPLATES)].format(claim=revised_body),
        })
        echo_cursor += 1
        day += 1

    return events


def revision_names() -> set[str]:
    return {name for name, _title, _body in REVISIONS}
