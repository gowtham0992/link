"""Local proof signals for Link memory value."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from .mcp_verify import display_command
from .memory import (
    is_active_memory,
    memory_records,
    memory_review_issues,
    memory_visible_for_project,
    normalize_project,
    slim_memory,
)


def _link_command(*parts: object, project: str = "") -> str:
    command = ["link", *(str(part) for part in parts if str(part) != "")]
    if project:
        command.extend(["--project", project])
    return display_command(command)


def memory_wins_payload(
    wiki_dir: Path,
    *,
    limit: int = 6,
    project: str | None = None,
    records: Iterable[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Summarize local, non-telemetry signals that Link memory is carrying value."""
    limit = max(1, min(int(limit or 6), 50))
    project_name = normalize_project(project)
    record_list = [
        dict(record)
        for record in (records if records is not None else memory_records(wiki_dir, include_body=False))
        if memory_visible_for_project(record, project_name)
    ]
    active_records = [record for record in record_list if is_active_memory(record)]
    reviewed_active = [
        record
        for record in active_records
        if str(record.get("review_status") or "").lower() == "reviewed"
    ]
    review_records = [
        record for record in record_list
        if memory_review_issues(record)
    ]
    source_backed = [
        record
        for record in active_records
        if str(record.get("source") or "").strip()
    ]
    project_values = {
        normalize_project(str(record.get("project") or ""))
        for record in active_records
        if normalize_project(str(record.get("project") or ""))
    }
    project_context = [
        record
        for record in active_records
        if str(record.get("scope") or "").lower() == "project"
        or normalize_project(str(record.get("project") or ""))
    ]
    guardrails = [
        record
        for record in active_records
        if str(record.get("review_after") or "").strip()
        or str(record.get("expires_at") or "").strip()
    ]
    updated_records = [
        record
        for record in active_records
        if str(record.get("updated_at") or "").strip()
        or _int_value(record.get("update_count")) > 0
    ]
    recent = [_slim(record) for record in _recent(active_records)[:limit]]
    wins = [
        _win(
            "reusable_context",
            "Reusable local context",
            len(active_records),
            "Active memories can appear in briefs, recall, and query packets without scanning the whole wiki.",
            "start with Link before we continue",
        ),
        _win(
            "reviewed_memory",
            "Reviewed memory",
            len(reviewed_active),
            "Reviewed active memories are the highest-trust recall candidates.",
            "what does Link remember about me?",
        ),
        _win(
            "review_gate",
            "Review gate",
            len(review_records),
            "Memories needing confirmation are visible before agents treat them as clean context.",
            "review Link memory inbox",
        ),
        _win(
            "source_grounding",
            "Provenance present",
            len(source_backed),
            "Memories with source metadata make it easier to inspect why Link knows something.",
            "explain the most important Link memory",
        ),
        _win(
            "project_continuity",
            "Project continuity",
            len(project_context),
            "Project-scoped memories help agents resume repo or workstream context across sessions.",
            "brief me from Link for this project",
            extra={"project_count": len(project_values)},
        ),
        _win(
            "freshness_guardrails",
            "Freshness guardrails",
            len(guardrails),
            "Review and expiry dates keep local memory from becoming silent stale state.",
            "audit Link memory",
        ),
        _win(
            "recent_changes",
            "Recent memory changes",
            len(updated_records),
            "Updated memories show where Link has evolved rather than staying as a one-time demo.",
            "what changed in Link memory recently?",
        ),
    ]
    return {
        "schema": "link-memory-wins-v1",
        "project": project_name,
        "memory_count": len(record_list),
        "active_count": len(active_records),
        "reviewed_active_count": len(reviewed_active),
        "review_count": len(review_records),
        "source_backed_count": len(source_backed),
        "project_context_count": len(project_context),
        "project_count": len(project_values),
        "guardrail_count": len(guardrails),
        "updated_count": len(updated_records),
        "wins": wins,
        "recent_memories": recent,
        "prompts": [
            "start with Link before we continue",
            "what does Link remember about me?",
            "what changed in Link memory recently?",
            "review Link memory inbox",
        ],
        "next_actions": _next_actions(
            memory_count=len(record_list),
            active_count=len(active_records),
            review_count=len(review_records),
            project=project_name,
        ),
        "honest_note": (
            "These are local wiki signals, not telemetry. "
            "Link does not track whether an agent used a memory."
        ),
    }


def _int_value(value: object) -> int:
    try:
        return int(str(value or "0").strip() or "0")
    except ValueError:
        return 0


def _recent(records: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    return sorted(
        (dict(record) for record in records),
        key=lambda record: (
            str(record.get("updated_at") or record.get("date_captured") or ""),
            str(record.get("title") or "").lower(),
        ),
        reverse=True,
    )


def _slim(record: Mapping[str, object]) -> dict[str, object]:
    return slim_memory(record)


def _win(
    code: str,
    label: str,
    count: int,
    description: str,
    prompt: str,
    *,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    data: dict[str, object] = {
        "code": code,
        "label": label,
        "count": count,
        "description": description,
        "prompt": prompt,
        "status": "present" if count else "empty",
    }
    if extra:
        data.update(dict(extra))
    return data


def _next_actions(
    *,
    memory_count: int,
    active_count: int,
    review_count: int,
    project: str,
) -> list[dict[str, object]]:
    target = "<link-root>"
    if not memory_count:
        return [
            {
                "label": "Create first memory",
                "reason": "A wins report becomes useful after Link has at least one durable memory.",
                "command": _link_command("remember", "I prefer ...", target, "--type", "preference", "--scope", "user"),
            },
            {
                "label": "Propose from sources",
                "reason": "Use source-backed proposals when raw notes contain preferences or decisions.",
                "command": _link_command("propose-memories", "raw/<source>.md", target),
            },
        ]
    if review_count:
        return [
            {
                "label": "Review memory inbox",
                "reason": "Reviewed memory is safer to reuse across agents.",
                "command": _link_command("memory-inbox", target, project=project),
            }
        ]
    if active_count:
        return [
            {
                "label": "Use the memory",
                "reason": "Ask an agent for a brief before work to see the value loop.",
                "command": _link_command("brief", "current task", target, project=project),
            }
        ]
    return [
        {
            "label": "Restore or create memory",
            "reason": "No active memories are currently available for default recall.",
            "command": _link_command("profile", target, project=project),
        }
    ]
