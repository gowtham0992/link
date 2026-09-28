"""Retrieval observability: did an agent actually use this memory?

Every memory system can tell you what it stored. None can tell you whether
the agent ever read it back — which makes "your agents have memory" a hope
rather than a measurement. This module closes that gap the local-first way.

What is recorded: a timestamp, which surface retrieved (session brief,
recall, query), how many memories came back, their names, and - for the
memory receipt - where it happened (hook, MCP, CLI), roughly how many
tokens it cost and whether a budget cut anything.

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

from .files import atomic_write_text_unlocked, file_lock

USAGE_FILE = ".link-usage.json"
USAGE_DISABLE_ENV = "LINK_USAGE"
MAX_EVENTS = 500
# Surfaces that count as "an agent read memory back": the session brief,
# recalls, guard reminders, reminders when the agent touched anchored code,
# and reviewed rules checked against a tool call.
RETRIEVAL_KINDS = ("brief", "recall", "query", "guard", "touch", "enforce")
# Whether each hook injection arrived, checked against the transcript at
# session end (delivered / truncated / missing). Not a retrieval.
DELIVERY_KIND = "delivery"


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
    surface: str = "",
    tokens: int = 0,
    truncated: bool = False,
    session: str = "",
    delivery: str = "",
    decision: str = "",
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
        event: dict[str, object] = {
            "at": _utc_now(),
            "kind": clean_kind,
            "count": len(names),
            "memories": names,
            "project": str(project or ""),
        }
        if surface:
            event["surface"] = str(surface)[:20]
        if tokens:
            event["tokens"] = int(tokens)
        if truncated:
            event["truncated"] = True
        if session:
            event["session"] = str(session)[:80]
        if delivery:
            event["delivery"] = str(delivery)[:16]
        if decision:
            event["decision"] = str(decision)[:10]
        return _append_event(root, event)
    except (OSError, ValueError, TypeError):
        return False


def record_delivery(root: Path, session: str, results: Mapping[str, str]) -> bool:
    """Record whether each injection of a session reached the agent's context."""
    if usage_disabled() or not results:
        return False
    try:
        return _append_event(root, {
            "at": _utc_now(),
            "kind": DELIVERY_KIND,
            "session": str(session or "")[:80],
            "results": {str(key)[:16]: str(value)[:10] for key, value in results.items()},
        })
    except (OSError, ValueError, TypeError):
        return False


def _append_event(root: Path, event: dict[str, object]) -> bool:
    try:
        path = usage_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Read, append and replace under one lock: a hook, an MCP server and
        # the CLI record at the same moment, and an unlocked read-modify-write
        # kept only the last writer's events.
        with file_lock(path):
            events = load_usage(root)
            events.append(event)
            atomic_write_text_unlocked(
                path, json.dumps({"schema": "link-usage-v1", "events": events[-MAX_EVENTS:]}, indent=1) + "\n",
            )
        return True
    except (OSError, ValueError, TypeError):
        return False


def estimated_tokens(value: object) -> int:
    """Rough token count of what an agent receives (4 characters per token)."""
    try:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return 0
    return max(1, (len(text) + 3) // 4)


def record_query_packet(root: Path, payload: Mapping[str, object], *, project: str = "", surface: str = "") -> bool:
    """Record a query packet: the memories in it, its size, and whether a budget cut it."""
    memory_section = payload.get("memory")
    items = memory_section.get("items") if isinstance(memory_section, Mapping) else None
    budget_section = payload.get("budget_report")
    budget_report: Mapping[str, object] = budget_section if isinstance(budget_section, Mapping) else {}
    total = budget_report.get("packet_total")
    tokens = total.get("estimated_tokens") if isinstance(total, Mapping) else 0
    return record_retrieval(
        root, "query",
        [str(item.get("name") or "") for item in (items if isinstance(items, list) else []) if isinstance(item, Mapping)],
        project=project, surface=surface,
        tokens=tokens if isinstance(tokens, int) else 0,
        truncated=any(bool(section.get("has_more")) for section in budget_report.values() if isinstance(section, Mapping)),
    )


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


# ── Memory receipt: what reached the agent, session by session ──────────
# A session is a run of retrieval events with no gap longer than this.
RECEIPT_SESSION_GAP_MINUTES = 30


def _event_time(event: Mapping[str, object]) -> datetime | None:
    stamp = str(event.get("at") or "")
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None


def memory_receipts(
    events: Iterable[Mapping[str, object]],
    *,
    sessions: int = 3,
    gap_minutes: int = RECEIPT_SESSION_GAP_MINUTES,
) -> list[dict[str, object]]:
    """The most recent sessions, newest first, as receipts.

    Each receipt says what the agent was given from memory: the session
    brief (how many memories, roughly how many tokens, whether it was cut
    to fit), each recall, guard reminders, and every memory that reached the
    agent with how many times. Rule checks say what a reviewed rule asked
    or blocked, and each hook injection says whether the transcript shows it
    arrived whole, cut off, or not at all. Built from the local ledger only;
    the ledger never holds queries, so neither does the receipt.
    """
    events = list(events)
    delivered: dict[str, str] = {}
    for event in events:
        results = event.get("results")
        if str(event.get("kind") or "") == DELIVERY_KIND and isinstance(results, dict):
            delivered.update({str(k): str(v) for k, v in results.items()})

    def delivery_state(event: Mapping[str, object]) -> str | None:
        token = str(event.get("delivery") or "")
        if not token:
            return None
        return delivered.get(token, "unverified")

    timed = [
        (moment, event) for event in events
        if (moment := _event_time(event)) is not None
        and str(event.get("kind") or "") in RETRIEVAL_KINDS
    ]
    timed.sort(key=lambda pair: pair[0])
    by_gap: list[list[tuple[datetime, Mapping[str, object]]]] = []
    for moment, event in timed:
        if by_gap and (moment - by_gap[-1][-1][0]).total_seconds() <= gap_minutes * 60:
            by_gap[-1].append((moment, event))
        else:
            by_gap.append([(moment, event)])
    # Sessions that overlap in time (two agents at once) carry their own
    # session ids: split on those, and give events without one (CLI, MCP) to
    # the session active just before them.
    grouped: list[list[tuple[datetime, Mapping[str, object]]]] = []
    for group in by_gap:
        ids = [str(event.get("session") or "") for _moment, event in group]
        if len({item for item in ids if item}) <= 1:
            grouped.append(group)
            continue
        parts: dict[str, list[tuple[datetime, Mapping[str, object]]]] = {}
        order: list[str] = []
        last = next(item for item in ids if item)
        for pair, session in zip(group, ids):
            key = session or last
            last = key
            if key not in parts:
                parts[key] = []
                order.append(key)
            parts[key].append(pair)
        grouped.extend(sorted((parts[key] for key in order), key=lambda part: part[0][0]))
    receipts: list[dict[str, object]] = []
    for group in reversed(grouped[-max(1, sessions):]):
        used: dict[str, int] = {}
        briefs: list[dict[str, object]] = []
        recalls = 0
        guards: list[str] = []
        tokens = 0
        truncated = False
        surfaces: set[str] = set()
        rule_checks: list[dict[str, object]] = []
        code_reminders: list[dict[str, object]] = []
        deliveries: dict[str, int] = {}
        for _moment, event in group:
            state = delivery_state(event)
            if state:
                deliveries[state] = deliveries.get(state, 0) + 1
            kind = str(event.get("kind") or "")
            raw_names = event.get("memories")
            names = [str(name) for name in raw_names if str(name)] if isinstance(raw_names, list) else []
            for name in names:
                used[name] = used.get(name, 0) + 1
            event_tokens = event.get("tokens")
            tokens += event_tokens if isinstance(event_tokens, int) else 0
            truncated = truncated or bool(event.get("truncated"))
            if event.get("surface"):
                surfaces.add(str(event.get("surface")))
            if kind == "brief":
                brief: dict[str, object] = {
                    "memories": len(names),
                    "tokens": event_tokens if isinstance(event_tokens, int) else None,
                    "truncated": bool(event.get("truncated")),
                }
                if state:
                    brief["delivery"] = state
                briefs.append(brief)
            elif kind == "guard":
                guards.extend(names)
            elif kind == "enforce":
                rule_checks.append({"decision": str(event.get("decision") or "ask"), "memories": names})
            elif kind == "touch":
                code_reminders.append({"memories": names, **({"delivery": state} if state else {})})
            else:
                recalls += 1
        receipts.append({
            "started": str(group[0][1].get("at") or ""),
            "ended": str(group[-1][1].get("at") or ""),
            "project": str(group[-1][1].get("project") or ""),
            "surfaces": sorted(surfaces),
            "briefs": briefs,
            "recalls": recalls,
            "guard_reminders": guards,
            "memories_used": [
                {"name": name, "times": times}
                for name, times in sorted(used.items(), key=lambda item: (-item[1], item[0]))
            ],
            "estimated_tokens": tokens,
            "anything_truncated": truncated,
            "rule_checks": rule_checks,
            "code_reminders": code_reminders,
            # delivered / truncated / missing per hook injection; "unverified"
            # when the agent gave no transcript to check against.
            "delivery": deliveries,
            "anything_undelivered": bool(deliveries.get("missing") or deliveries.get("truncated")),
        })
    return receipts
