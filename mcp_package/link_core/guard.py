"""Proactive guard: surface a saved constraint at the moment it matters.

The session-start brief is a snapshot; forty minutes in, the user says
"let's deploy Friday" and the memory saying deploys happen on Tuesdays
sits unread. This module is the per-prompt check that catches exactly
that moment - and only that moment.

Precision is the whole design. A guard that speaks often is a guard the
user turns off, so it fires only when BOTH hold:

- the memory is constraint-shaped (an absolute: never / always / only /
  do not / must not) - the class of memory whose violation hurts, and
- the prompt overlaps it strongly (the same lexical recall the rest of
  Link uses, top-ranked with a real match, not a weak echo).

Silent otherwise. No model load, no network - a regex and the lexical
ranker, built for a per-prompt latency budget.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from .memory import recall_memories

_CONSTRAINT_RE = re.compile(
    r"\b(?:never|always|only|avoid|do not|don\'t|must not|mustn\'t)\b", re.IGNORECASE
)
# Confidence labels that count as a real overlap, and a score floor so a
# single stray shared token can never trigger an interruption.
_STRONG_CONFIDENCE = {"high", "strong", "moderate"}
_MIN_SCORE = 15
_MIN_PROMPT_CHARS = 12


def is_constraint_memory(record: Mapping[str, object]) -> bool:
    claim = str(record.get("tldr") or record.get("memory") or record.get("title") or "")
    return bool(_CONSTRAINT_RE.search(claim))


def guard_reminder(
    records: Iterable[Mapping[str, object]],
    prompt: str,
    *,
    project: str | None = None,
) -> dict[str, object] | None:
    """The one constraint worth interrupting for, or None (the usual case)."""
    text = (prompt or "").strip()
    if len(text) < _MIN_PROMPT_CHARS:
        return None
    constraints = [record for record in records if is_constraint_memory(record)]
    if not constraints:
        return None
    results = recall_memories(constraints, text, limit=1, project=project)
    if not results:
        return None
    top = results[0]
    confidence = str(top.get("confidence") or "").lower()
    score_obj = top.get("score")
    score = score_obj if isinstance(score_obj, int) else 0
    if confidence not in _STRONG_CONFIDENCE or score < _MIN_SCORE:
        return None
    return {
        "name": str(top.get("name") or ""),
        "claim": str(top.get("tldr") or top.get("memory") or top.get("title") or "").strip(),
        "confidence": confidence,
        "score": score,
    }


def render_guard_text(reminder: Mapping[str, object]) -> str:
    claim = reminder.get("claim")
    name = reminder.get("name")
    return (
        "Link guard - a saved constraint may apply to this request:\n"
        f"- {claim} (memory: {name})\n"
        "If the request conflicts with it, say so and confirm with the user "
        "before proceeding."
    )


# ── Switch-intent nudge ──────────────────────────────────────────────────
# The handoff should suggest itself at the moment it matters: the user
# says they are switching tools, out of quota, or stopping for now. The
# per-prompt hook sees that moment; a session-end hook cannot (its output
# is invisible - the session is already over).

# Tool names make "continue in X" a switch; "continue with the refactor"
# is just work and must never trigger.
_AGENT_NAMES = r"(?:codex|cursor|claude(?:\s+code)?|windsurf|zed|kiro|copilot|gemini|vs\s*code|antigravity|another\s+(?:tool|agent|machine|session))"

_SWITCH_INTENT_RE = re.compile(
    r"(?i)\b(?:"
    r"switch(?:ing)?\s+(?:to|over to)\s+" + _AGENT_NAMES +
    r"|continu(?:e|ing)\s+(?:this\s+|it\s+)?(?:in|on|with)\s+" + _AGENT_NAMES +
    r"|(?:hit(?:ting)?|reached|out of)\s+(?:my\s+|the\s+)?(?:rate\s*limits?|usage\s*limits?|quota|tokens)"
    r"|(?:continue|pick(?:ing)?\s+(?:this|it)\s+(?:back\s+)?up|resume)(?:\s+\w+){0,2}?\s+(?:tomorrow|later|tonight|in the morning|next (?:session|week))"
    r"|stop(?:ping)?\s+(?:here|for\s+(?:now|today|tonight))"
    r"|(?:call(?:ing)?\s+it\s+a\s+(?:day|night))"
    r"|wrap(?:ping)?\s+(?:up|this up)\s+for\s+(?:now|today|tonight)"
    r")\b"
)


def switch_intent(prompt: str) -> bool:
    """Does this prompt announce a stop or a tool switch?"""
    return bool(_SWITCH_INTENT_RE.search(prompt or ""))


def render_switch_nudge() -> str:
    return (
        "Link: this sounds like a stop or a tool switch. Offer to write a "
        "session handoff before ending, so the next session (any agent) "
        "resumes without re-explaining: lnk handoff \"<where we left off>\" "
        "--task \"<short title>\" --next \"<step>\". Keep it standalone."
    )
