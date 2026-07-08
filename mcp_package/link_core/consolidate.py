"""Read-only memory consolidation planning for Link.

Consolidation never writes: it detects backlog (pending raw captures and
memories that need review), groups duplicate captures, and prints the exact
review-gated commands to resolve each item with the user. Automatic session
hooks use the same backlog summary to nudge agents to offer consolidation.
"""
from __future__ import annotations

import re
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
    return {
        "project": project or "",
        "backlog": backlog,
        "pending_captures": capture_count,
        "needs_review_memories": needs_review_count,
        "duplicate_groups": duplicate_groups,
        "duplicate_capture_count": duplicate_count,
        "recurring_themes": recurring_themes,
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
