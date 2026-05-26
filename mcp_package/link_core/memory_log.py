"""Memory timeline helpers for Link."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping

from .log import read_log_entries


MEMORY_OPERATIONS = {
    "accept-capture",
    "archive-memory",
    "forget-memory",
    "remember",
    "restore-memory",
    "review-memory",
    "update-memory",
}
CAPTURE_OPERATIONS = {
    "capture-session",
    "delete-capture",
    "redact-capture",
}
MEMORY_PATH_RE = re.compile(r"(?:wiki/)?memories/([A-Za-z0-9._-]+\.md)")


def memory_log_payload(
    wiki_dir: Path,
    *,
    limit: int = 50,
    include_captures: bool = True,
) -> dict[str, object]:
    """Return recent memory lifecycle events from the local operation log."""
    try:
        parsed_limit = int(limit)
    except (TypeError, ValueError):
        parsed_limit = 50
    limit = max(1, min(parsed_limit, 200))
    operations = set(MEMORY_OPERATIONS)
    if include_captures:
        operations.update(CAPTURE_OPERATIONS)
    entries = []
    for entry in read_log_entries(wiki_dir, limit=1000):
        normalized = _memory_log_entry(entry)
        if normalized["operation"] in operations or normalized["memory_paths"]:
            entries.append(normalized)
    recent = entries[-limit:]
    return {
        "schema": "link-memory-log-v1",
        "wiki": str(wiki_dir),
        "count": len(recent),
        "total_matching": len(entries),
        "limit": limit,
        "include_captures": include_captures,
        "entries": recent,
        "privacy_note": "Memory bodies and raw capture contents are not included; this is lifecycle metadata from wiki/log.md.",
        "next_actions": [
            {
                "label": "Inspect memory review queue",
                "command": "link memory-inbox",
                "reason": "Review pending, stale, expired, or underspecified memories before relying on them.",
            },
            {
                "label": "Explain a changed memory",
                "command": "link explain-memory <memory-name>",
                "reason": "Open provenance, review status, graph links, and matching log entries for one memory.",
            },
        ],
    }


def _memory_log_entry(entry: Mapping[str, object]) -> dict[str, object]:
    operation = str(entry.get("operation") or "").strip()
    details = [
        str(item).strip()
        for item in entry.get("details", [])
        if str(item).strip()
    ] if isinstance(entry.get("details"), list) else []
    memory_paths = _memory_paths(entry, details)
    category = "capture" if operation in CAPTURE_OPERATIONS else "memory"
    details = _safe_details(operation, details)
    return {
        "timestamp": str(entry.get("timestamp") or ""),
        "operation": operation,
        "category": category,
        "description": str(entry.get("description") or ""),
        "memory_paths": memory_paths,
        "details": details,
        "summary": _summary(operation, str(entry.get("description") or ""), memory_paths),
    }


def _memory_paths(entry: Mapping[str, object], details: list[str]) -> list[str]:
    text = "\n".join([str(entry.get("description") or ""), *details])
    paths: list[str] = []
    for match in MEMORY_PATH_RE.finditer(text):
        path = f"wiki/memories/{match.group(1)}"
        if path not in paths:
            paths.append(path)
    return paths


def _safe_details(operation: str, details: list[str]) -> list[str]:
    if operation in CAPTURE_OPERATIONS:
        return [
            detail for detail in details
            if not detail.lower().startswith("source input:")
        ][:8]
    prefixes = (
        "created: memories/",
        "updated: memories/",
        "reviewed: memories/",
        "memory: wiki/memories/",
        "memory: memories/",
        "previous ",
        "new ",
        "type:",
        "scope:",
        "project:",
        "reason:",
        "review ",
        "update count:",
        "title:",
        "deleted memory page",
    )
    safe = [
        detail for detail in details
        if detail.lower().startswith(prefixes) or "memories/" in detail.lower()
    ]
    return safe[:8]


def _summary(operation: str, description: str, memory_paths: list[str]) -> str:
    target = memory_paths[0] if memory_paths else description
    if operation == "remember":
        return f"Created memory: {target}"
    if operation == "accept-capture":
        return f"Accepted capture proposal into memory: {target}"
    if operation == "update-memory":
        return f"Updated memory and returned it to review: {target}"
    if operation == "review-memory":
        return f"Marked memory reviewed: {target}"
    if operation == "archive-memory":
        return f"Archived memory: {target}"
    if operation == "restore-memory":
        return f"Restored memory: {target}"
    if operation == "forget-memory":
        return f"Permanently forgot memory: {target}"
    if operation == "capture-session":
        return f"Captured proposal-only notes: {description}"
    if operation == "redact-capture":
        return f"Redacted a raw capture: {description}"
    if operation == "delete-capture":
        return f"Deleted a raw capture: {description}"
    return description
