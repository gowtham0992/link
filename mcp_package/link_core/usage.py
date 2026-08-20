"""Retrieval observability: did an agent actually use this memory?

Every memory system can tell you what it stored. None can tell you whether
the agent ever read it back — which makes "your agents have memory" a hope
rather than a measurement. This module closes that gap the local-first way.

What is recorded: a timestamp, which surface retrieved (session brief,
recall, query), how many memories came back, and their names.

What is never recorded: the query text, the answer, the conversation, or
anything about the machine. The ledger says *that* memory was used and
*which* memory it was — never what you were asking about.

Where it lives: `.link-usage.json` at the workspace root — machine-local by
design. It is excluded from sync (behavior is not memory), bounded to a
ring of recent events so it cannot grow without limit, and switched off
entirely with `LINK_USAGE=off`. Recording never raises: a failed write
must never break a recall.
"""
from __future__ import annotations

import math
import json
import os
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone
from pathlib import Path

USAGE_FILE = ".link-usage.json"
USAGE_DISABLE_ENV = "LINK_USAGE"
MAX_EVENTS = 500
# Surfaces that count as "an agent read memory back".
RETRIEVAL_KINDS = ("brief", "recall", "query", "guard")


def usage_disabled() -> bool:
    return os.environ.get(USAGE_DISABLE_ENV, "").strip().lower() in {"0", "off", "false", "no"}


def usage_path(root: Path) -> Path:
    return root.expanduser().resolve() / USAGE_FILE


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_usage(root: Path) -> list[dict[str, object]]:
    """Recorded retrieval events, oldest first. Missing/corrupt ledger = none."""
    try:
        payload = json.loads(usage_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)]


def record_retrieval(
    root: Path,
    kind: str,
    memories: Iterable[str] = (),
    *,
    project: str = "",
) -> bool:
    """Append one retrieval event. Returns False when disabled or unwritable.

    Deliberately best-effort: observability must never be able to break the
    thing it observes.
    """
    if usage_disabled():
        return False
    clean_kind = str(kind or "").strip().lower()
    if clean_kind not in RETRIEVAL_KINDS:
        return False
    names = [str(name).strip() for name in memories if str(name).strip()][:20]
    try:
        events = load_usage(root)
        events.append({
            "at": _utc_now(),
            "kind": clean_kind,
            "count": len(names),
            "memories": names,
            "project": str(project or ""),
        })
        path = usage_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"schema": "link-usage-v1", "events": events[-MAX_EVENTS:]}, indent=1) + "\n",
            encoding="utf-8",
        )
        return True
    except (OSError, ValueError, TypeError):
        return False


def _within(stamp: object, days: int, today: date) -> bool:
    text = str(stamp or "")[:10]
    try:
        return (today - date.fromisoformat(text)).days <= days
    except ValueError:
        return False


def usage_summary(
    root: Path,
    *,
    days: int = 7,
    records: Iterable[Mapping[str, object]] | None = None,
    today: str | None = None,
) -> dict[str, object]:
    """What actually got read back, and what never did.

    `records` (active memories) enables the honest other half: memories
    that have never been retrieved are dead weight the user can archive.
    """
    events = load_usage(root)
    now = date.fromisoformat(today) if today else date.today()
    recent = [event for event in events if _within(event.get("at"), days, now)]

    by_kind: dict[str, int] = {}
    surfaced: dict[str, int] = {}
    for event in recent:
        kind = str(event.get("kind") or "")
        by_kind[kind] = by_kind.get(kind, 0) + 1
        names = event.get("memories")
        for name in names if isinstance(names, list) else []:
            key = str(name)
            surfaced[key] = surfaced.get(key, 0) + 1

    top = [
        {"memory": name, "times": times}
        for name, times in sorted(surfaced.items(), key=lambda item: (-item[1], item[0]))[:5]
    ]

    never_used: list[str] = []
    if records is not None:
        ever_surfaced: set[str] = set()
        for event in events:
            names_obj = event.get("memories")
            if isinstance(names_obj, list):
                ever_surfaced.update(str(name) for name in names_obj)
        never_used = sorted(
            str(record.get("name"))
            for record in records
            if str(record.get("name") or "")
            and str(record.get("name")) not in ever_surfaced
            # Grace period: a memory younger than the window has not had a
            # fair chance to be recalled — day-one users must never be told
            # their first memory is dead weight.
            and not _within(record.get("date_captured"), days, now)
        )

    return {
        "tracking": not usage_disabled(),
        "has_data": bool(events),
        "window_days": days,
        "retrievals": len(recent),
        "by_kind": by_kind,
        "briefs": by_kind.get("brief", 0),
        "memories_surfaced": len(surfaced),
        "top_memories": top,
        "never_retrieved": never_used[:10],
        "never_retrieved_count": len(never_used),
        "total_recorded": len(events),
    }


# MEASURED AND NOT ADOPTED. Ranking is not usage-aware, and this is the
# function that was tried. scripts/eval_salience.py splits queries by whether
# the answer is a memory with retrieval history, and at every ceiling from 1
# to 4 the cold half got harder to find: at ceiling 1 the hot half gained
# nothing and cold still fell. The average improves, which is exactly how this
# kind of change gets shipped without anyone noticing what it cost.
#
# That trade is backwards for Link specifically. The memory worth having is
# the constraint you had forgotten - the cold one - and the frequently read
# memories are the ones you would have remembered anyway.
#
# Kept, off by default, so the experiment stays reproducible and the next
# attempt at popularity ranking has to clear the same bar.
#
# Salience is a tiebreaker, never a ranking force of its own. The failure it
# has to avoid is well known from every feed that ranks by popularity: the
# memory you reach for often crowds out the correct-but-rarely-needed one.
# The ceiling here is deliberately smaller than a lexical match, so usage can
# separate near-equals and nothing else.
SALIENCE_MAX_BOOST = 4
SALIENCE_MIN_RETRIEVALS = 2


def usage_salience(events: list[dict[str, object]]) -> dict[str, int]:
    """Bounded per-memory boost derived from how often memory was actually read.

    Counts retrievals only. A memory the user has never pulled gets nothing
    rather than a penalty: absence of evidence is not evidence of uselessness,
    and a new memory has no history by definition.
    """
    counts: dict[str, int] = {}
    for event in events:
        names = event.get("memories")
        if not isinstance(names, list):
            continue
        for name in names:
            key = str(name)
            if key:
                counts[key] = counts.get(key, 0) + 1
    if not counts:
        return {}
    ceiling = max(counts.values())
    if ceiling < SALIENCE_MIN_RETRIEVALS:
        return {}
    boosts: dict[str, int] = {}
    for name, count in counts.items():
        if count < SALIENCE_MIN_RETRIEVALS:
            continue
        # Linear in the log of the count: the tenth read should matter far
        # less than the second, or one habit dominates every query.
        share = math.log1p(count) / math.log1p(ceiling)
        boost = int(round(share * SALIENCE_MAX_BOOST))
        if boost:
            boosts[name] = boost
    return boosts
