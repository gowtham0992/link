"""Read-only memory consolidation planning for Link.

Consolidation never writes: it detects backlog (pending raw captures and
memories that need review), groups duplicate captures, and prints the exact
review-gated commands to resolve each item with the user. Automatic session
hooks use the same backlog summary to nudge agents to offer consolidation.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from pathlib import Path

from .mcp_verify import display_command

BACKLOG_CAPTURE_THRESHOLD = 5
BACKLOG_REVIEW_THRESHOLD = 8


def consolidate_command(command_target: str | Path = ".") -> str:
    return display_command(["lnk", "consolidate", str(command_target)])


def memory_backlog_summary(
    *,
    capture_count: int,
    needs_review_count: int,
    command_target: str | Path = ".",
) -> dict[str, object]:
    """Return the shared backlog signal used by hooks, briefs, and status views."""
    backlog = capture_count >= BACKLOG_CAPTURE_THRESHOLD or needs_review_count >= BACKLOG_REVIEW_THRESHOLD
    return {
        "pending_captures": capture_count,
        "needs_review_memories": needs_review_count,
        "backlog": backlog,
        "capture_threshold": BACKLOG_CAPTURE_THRESHOLD,
        "review_threshold": BACKLOG_REVIEW_THRESHOLD,
        "command": consolidate_command(command_target),
    }


DUPLICATE_JACCARD = 0.8


def _snippet_tokens(capture: dict[str, object]) -> set[str]:
    snippet = str(capture.get("snippet") or "").lower()
    return set(re.findall(r"[a-z0-9]{3,}", snippet))


def _duplicate_capture_groups(captures: list[dict[str, object]]) -> list[dict[str, object]]:
    """Cluster near-duplicate captures by snippet token overlap; newest is kept.

    Exact duplicates have Jaccard 1.0, so one similarity clustering covers
    both identical and lightly reworded captures of the same session content.
    """
    clusters: list[dict[str, object]] = []
    for capture in captures:  # capture_records sorts newest first
        tokens = _snippet_tokens(capture)
        if not tokens:
            continue
        for cluster in clusters:
            keep_tokens: set[str] = cluster["tokens"]  # type: ignore[assignment]
            union = tokens | keep_tokens
            if union and len(tokens & keep_tokens) / len(union) >= DUPLICATE_JACCARD:
                cluster["members"].append(capture)  # type: ignore[union-attr]
                break
        else:
            clusters.append({"tokens": tokens, "keep": capture, "members": []})
    groups: list[dict[str, object]] = []
    for cluster in clusters:
        members = cluster["members"]
        if not members:
            continue
        keep = cluster["keep"]
        groups.append({
            "keep": {"path": keep.get("path"), "title": keep.get("title")},
            "duplicates": [
                {
                    "path": item.get("path"),
                    "title": item.get("title"),
                    "delete_command": (item.get("commands") or {}).get("delete", "")
                    if isinstance(item.get("commands"), dict)
                    else "",
                }
                for item in members
            ],
        })
    return groups


THEME_JACCARD_LOW = 0.45


def _recurring_theme_groups(captures: list[dict[str, object]]) -> list[dict[str, object]]:
    """Clusters of related-but-not-duplicate captures: a recurring theme.

    Two captures whose snippets overlap between the theme floor and the
    duplicate threshold are the same topic showing up across sessions —
    the signal that one durable memory (often a preference or recipe)
    should replace scattered captures. Detection is deterministic; writing
    anything remains the user's call.
    """
    themes: list[dict[str, object]] = []
    used: set[str] = set()
    items = [(capture, _snippet_tokens(capture)) for capture in captures if _snippet_tokens(capture)]
    for index, (capture, tokens) in enumerate(items):
        path = str(capture.get("path"))
        if path in used:
            continue
        members = [capture]
        for other, other_tokens in items[index + 1:]:
            other_path = str(other.get("path"))
            if other_path in used:
                continue
            union = tokens | other_tokens
            similarity = len(tokens & other_tokens) / len(union) if union else 0.0
            if THEME_JACCARD_LOW <= similarity < DUPLICATE_JACCARD:
                members.append(other)
                used.add(other_path)
        if len(members) >= 2:
            used.add(path)
            themes.append({
                "sessions": len(members),
                "snippet": str(capture.get("snippet") or "")[:140],
                "captures": [str(item.get("path")) for item in members],
                "suggestion": (
                    "This theme recurs across sessions. Propose one durable memory "
                    "(a preference, or a procedure with a trigger) to the user, then "
                    "accept it and discard the scattered captures."
                ),
            })
    return themes


def build_consolidation_plan(
    *,
    captures_payload: dict[str, object],
    inbox_payload: dict[str, object],
    command_target: str | Path = ".",
    project: str | None = None,
    merge_candidates: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Build a read-only consolidation plan from capture and review backlogs."""
    captures = captures_payload.get("captures") if isinstance(captures_payload.get("captures"), list) else []
    capture_count = int(captures_payload.get("count") or len(captures))
    review_items = inbox_payload.get("items") if isinstance(inbox_payload.get("items"), list) else []
    needs_review_count = int(inbox_payload.get("review_count") or len(review_items))
    capture_dicts = [c for c in captures if isinstance(c, dict)]
    duplicate_groups = _duplicate_capture_groups(capture_dicts)
    duplicate_count = sum(len(group["duplicates"]) for group in duplicate_groups)
    recurring_themes = _recurring_theme_groups(capture_dicts)

    capture_plan = []
    duplicate_paths = {
        str(item["path"])
        for group in duplicate_groups
        for item in group["duplicates"]
    }
    for capture in captures:
        if not isinstance(capture, dict):
            continue
        commands = capture.get("commands") if isinstance(capture.get("commands"), dict) else {}
        capture_plan.append({
            "path": capture.get("path"),
            "title": capture.get("title"),
            "project": capture.get("project"),
            "snippet": capture.get("snippet"),
            "secret_warning_count": capture.get("warning_count", 0),
            "duplicate": str(capture.get("path")) in duplicate_paths,
            "accept_command": commands.get("accept", ""),
            "delete_command": commands.get("delete", ""),
        })

    review_plan = []
    for item in review_items[:10]:
        if not isinstance(item, dict):
            continue
        primary = item.get("primary_action") if isinstance(item.get("primary_action"), dict) else {}
        review_plan.append({
            "title": item.get("title"),
            "severity": item.get("highest_severity"),
            "command": primary.get("command_text") or primary.get("command") or "",
        })

    backlog = memory_backlog_summary(
        capture_count=capture_count,
        needs_review_count=needs_review_count,
        command_target=command_target,
    )
    merge_plan: list[dict[str, object]] = []
    for candidate in merge_candidates or []:
        if not isinstance(candidate, dict):
            continue
        survivor = str(candidate.get("survivor") or "")
        absorbed = str(candidate.get("absorbed") or "")
        absorbed_claim = str(candidate.get("absorbed_claim") or "")
        merge_plan.append({
            **candidate,
            "merge_command": display_command([
                "link", "update-memory", survivor, absorbed_claim, str(command_target),
            ]),
            "archive_command": display_command([
                "link", "archive-memory", absorbed, str(command_target),
                "--reason", f"merged into {survivor}",
            ]),
        })

    return {
        "project": project or "",
        "backlog": backlog,
        "pending_captures": capture_count,
        "needs_review_memories": needs_review_count,
        "duplicate_groups": duplicate_groups,
        "duplicate_capture_count": duplicate_count,
        "recurring_themes": recurring_themes,
        "merge_candidates": merge_plan,
        "captures": capture_plan,
        "review_queue": review_plan,
        "safety": (
            "Read-only plan. Nothing was merged, deleted, or saved. "
            "Run the listed commands only after the user approves each action."
        ),
    }


def render_consolidate_text(payload: dict[str, object]) -> tuple[int, str]:
    """Render the consolidation plan for terminal and agent use."""
    backlog = payload.get("backlog") if isinstance(payload.get("backlog"), dict) else {}
    lines = [
        "Link consolidation plan (read-only)",
        "",
        (
            f"Pending captures: {payload.get('pending_captures', 0)} · "
            f"Memories needing review: {payload.get('needs_review_memories', 0)}"
        ),
    ]
    if backlog.get("backlog"):
        lines.append("Backlog is above threshold; a review session with the user is recommended.")
    else:
        lines.append("Backlog is small; consolidation is optional right now.")

    duplicate_groups = payload.get("duplicate_groups") if isinstance(payload.get("duplicate_groups"), list) else []
    if duplicate_groups:
        lines.extend(["", f"Duplicate captures ({payload.get('duplicate_capture_count', 0)} safe to delete after review):"])
        for group in duplicate_groups:
            if not isinstance(group, dict):
                continue
            keep = group.get("keep") if isinstance(group.get("keep"), dict) else {}
            lines.append(f"- Keep: {keep.get('path')}")
            for item in group.get("duplicates", []):
                if isinstance(item, dict):
                    lines.append(f"  Duplicate: {item.get('path')}")
                    if item.get("delete_command"):
                        lines.append(f"    {item.get('delete_command')}")

    themes = payload.get("recurring_themes") if isinstance(payload.get("recurring_themes"), list) else []
    if themes:
        lines.extend(["", "Recurring themes (candidates for one durable memory):"])
        for theme in themes:
            if not isinstance(theme, dict):
                continue
            lines.append(f"- Seen in {theme.get('sessions')} sessions: {theme.get('snippet')}")
            for capture_path in theme.get("captures", []):
                lines.append(f"    {capture_path}")
            lines.append(f"  {theme.get('suggestion')}")

    merge_obj = payload.get("merge_candidates")
    merge_candidates: list[object] = merge_obj if isinstance(merge_obj, list) else []
    if merge_candidates:
        lines.extend(["", "Accepted memories that likely say the same thing (merge after the user confirms):"])
        for candidate in merge_candidates:
            if not isinstance(candidate, dict):
                continue
            lines.append(
                f"- Keep '{candidate.get('survivor_title')}' · absorb '{candidate.get('absorbed_title')}' "
                f"(similarity {candidate.get('similarity')}, {candidate.get('reason')})"
            )
            if candidate.get("merge_command"):
                lines.append(f"  Merge:   {candidate.get('merge_command')}")
            if candidate.get("archive_command"):
                lines.append(f"  Archive: {candidate.get('archive_command')}")

    captures = payload.get("captures") if isinstance(payload.get("captures"), list) else []
    unique_captures = [c for c in captures if isinstance(c, dict) and not c.get("duplicate")]
    if unique_captures:
        lines.extend(["", "Captures to review with the user:"])
        for capture in unique_captures[:10]:
            title = str(capture.get("title") or capture.get("path"))
            lines.append(f"- {title} ({capture.get('path')})")
            snippet = str(capture.get("snippet") or "").strip()
            if snippet:
                lines.append(f"  {snippet[:140]}")
            if capture.get("accept_command"):
                lines.append(f"  Accept: {capture.get('accept_command')}")
            if capture.get("delete_command"):
                lines.append(f"  Discard: {capture.get('delete_command')}")

    review_queue = payload.get("review_queue") if isinstance(payload.get("review_queue"), list) else []
    if review_queue:
        lines.extend(["", "Memories needing review:"])
        for item in review_queue:
            if not isinstance(item, dict):
                continue
            lines.append(f"- [{item.get('severity', '?')}] {item.get('title')}")
            if item.get("command"):
                lines.append(f"  {item.get('command')}")

    if not duplicate_groups and not unique_captures and not review_queue:
        lines.extend(["", "Nothing to consolidate. Memory state is clean."])

    lines.extend(["", str(payload.get("safety") or "")])
    return 0, "\n".join(line for line in lines if line is not None)


# ── Reflection: the weekly digest ────────────────────────────────────────
# Consolidation answers "what should I clean up?" on demand. The digest is
# the ritual around it: a bounded, deterministic look back that answers
# "is my memory healthy?" without being asked. Every number comes from
# machinery that already exists (lifecycle windows, merge candidates,
# review issues, capture inbox) — nothing here computes new truth, it
# just tells the story of the week.


def _within_days(stamp: object, days: int, today: date) -> bool:
    text = str(stamp or "")[:10]
    if not text:
        return False
    try:
        return (today - date.fromisoformat(text)).days <= days
    except ValueError:
        return False


def build_digest(
    *,
    records: list[Mapping[str, object]],
    merge_candidates: list[dict[str, object]],
    capture_count: int,
    review_items: list[Mapping[str, object]],
    usage: Mapping[str, object] | None = None,
    days: int = 7,
    today: str | None = None,
    command_target: str | Path = ".",
) -> dict[str, object]:
    """A bounded weekly look at memory health. Read-only, no LLM."""
    now = date.fromisoformat(today) if today else date.today()
    active = [r for r in records if str(r.get("status") or "active") == "active"]

    learned = [
        {"title": str(r.get("title") or ""), "type": str(r.get("memory_type") or "")}
        for r in active
        if _within_days(r.get("date_captured"), days, now)
    ]
    reviewed = [
        r for r in active if _within_days(r.get("reviewed_at"), days, now)
    ]

    due_soon: list[dict[str, str]] = []
    overdue: list[dict[str, str]] = []
    for record in active:
        raw = str(record.get("review_after") or "")[:10]
        if not raw:
            continue
        try:
            due = date.fromisoformat(raw)
        except ValueError:
            continue
        entry = {"title": str(record.get("title") or ""), "review_after": raw}
        if due <= now:
            overdue.append(entry)
        elif (due - now).days <= days:
            due_soon.append(entry)

    return {
        "window_days": days,
        "generated_for": now.isoformat(),
        "active_memories": len(active),
        "learned": learned[:10],
        "learned_count": len(learned),
        "reviewed_count": len(reviewed),
        "overdue": overdue[:10],
        "overdue_count": len(overdue),
        "due_soon": due_soon[:10],
        "due_soon_count": len(due_soon),
        "drifting": merge_candidates[:5],
        "drifting_count": len(merge_candidates),
        "pending_captures": capture_count,
        "needs_review": len(review_items),
        "usage": dict(usage) if usage else {},
        "next_commands": {
            "review": display_command(["link", "review-memory", str(command_target), "--all"]),
            "consolidate": display_command(["link", "consolidate", str(command_target)]),
            "captures": display_command(["link", "capture-inbox", str(command_target)]),
        },
    }


def render_digest_text(payload: Mapping[str, object]) -> str:
    """Render the digest as something worth reading on a Monday."""
    days = payload.get("window_days", 7)
    lines = [
        f"Link memory digest — last {days} days",
        "",
        (f"{payload.get('active_memories', 0)} active "
         f"{'memory' if payload.get('active_memories') == 1 else 'memories'} · "
         f"{payload.get('learned_count', 0)} new · "
         f"{payload.get('reviewed_count', 0)} reviewed"),
    ]

    learned_obj = payload.get("learned")
    learned: list[object] = learned_obj if isinstance(learned_obj, list) else []
    if learned:
        lines.extend(["", "What you taught Link:"])
        for item in learned:
            if isinstance(item, dict):
                lines.append(f"  + {item.get('title')} ({item.get('type')})")
        learned_total = payload.get("learned_count")
        remaining = (learned_total if isinstance(learned_total, int) else 0) - len(learned)
        if remaining > 0:
            lines.append(f"  … and {remaining} more")

    overdue_obj = payload.get("overdue")
    overdue: list[object] = overdue_obj if isinstance(overdue_obj, list) else []
    due_soon_obj = payload.get("due_soon")
    due_soon: list[object] = due_soon_obj if isinstance(due_soon_obj, list) else []
    if overdue or due_soon:
        lines.extend(["", "Aging out of its trust window:"])
        for item in overdue:
            if isinstance(item, dict):
                lines.append(f"  ! {item.get('title')} (due {item.get('review_after')})")
        for item in due_soon:
            if isinstance(item, dict):
                lines.append(f"  · {item.get('title')} (due {item.get('review_after')})")
        lines.append(f"  Confirm what still holds: {_digest_command(payload, 'review')}")

    drifting_obj = payload.get("drifting")
    drifting: list[object] = drifting_obj if isinstance(drifting_obj, list) else []
    if drifting:
        lines.extend(["", "Saying the same thing twice:"])
        for item in drifting:
            if isinstance(item, dict):
                lines.append(
                    f"  ~ '{item.get('survivor_title')}' and '{item.get('absorbed_title')}'"
                )
        lines.append(f"  Merge with review: {_digest_command(payload, 'consolidate')}")

    usage_obj = payload.get("usage")
    usage: Mapping[str, object] = usage_obj if isinstance(usage_obj, Mapping) else {}
    if usage.get("has_data"):
        retrievals = usage.get("retrievals") or 0
        briefs = usage.get("briefs") or 0
        lines.extend(["", f"How memory got used: {retrievals} lookup(s), "
                          f"{briefs} session brief(s)"])
        top_obj = usage.get("top_memories")
        for item in (top_obj if isinstance(top_obj, list) else [])[:3]:
            if isinstance(item, Mapping):
                lines.append(f"  * {item.get('memory')} ({item.get('times')}x)")
        never = usage.get("never_retrieved_count") or 0
        if never:
            lines.append(f"  {never} memory(ies) have never been retrieved — candidates to archive")

    waiting_obj = payload.get("pending_captures")
    waiting = waiting_obj if isinstance(waiting_obj, int) else 0
    if waiting:
        lines.extend(["", f"Waiting for you: {waiting} session capture(s)",
                      f"  {_digest_command(payload, 'captures')}"])

    if not learned and not overdue and not due_soon and not drifting and not waiting:
        lines.extend(["", "Nothing needs you. Memory is current, reviewed, and free of overlap."])
    return "\n".join(lines)


def _digest_command(payload: Mapping[str, object], key: str) -> str:
    commands = payload.get("next_commands")
    if isinstance(commands, Mapping):
        return str(commands.get(key) or "")
    return ""
