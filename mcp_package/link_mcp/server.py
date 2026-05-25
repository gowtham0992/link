#!/usr/bin/env python3
"""
Link MCP Server

Exposes the Link personal knowledge wiki as MCP tools.
Agents can search, query context, and traverse the knowledge graph
without reading files directly.

Install:
  pip install link-mcp

Usage:
  python -m link_mcp                      # uses ~/link/wiki/
  python -m link_mcp --wiki /path/wiki    # custom wiki path

Add to your MCP client config:
  {
    "mcpServers": {
      "link": {
        "command": "python3",
        "args": ["-m", "link_mcp"]
      }
    }
  }
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from link_core.version import LINK_VERSION

# ── Resolve wiki directory ────────────────────────────────────────────
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--wiki", default=None)
parser.add_argument("--version", action="store_true")
args, _ = parser.parse_known_args()

if args.version:
    print(f"link-mcp {LINK_VERSION}")
    sys.exit(0)

if args.wiki:
    WIKI_DIR = Path(args.wiki).expanduser().resolve()
else:
    WIKI_DIR = Path.home() / "link" / "wiki"

if not WIKI_DIR.exists():
    print(
        f"[link-mcp] Wiki not found at {WIKI_DIR}. "
        "Initialize Link first with `link init` or `python3 link.py init`, "
        "run an integration installer under integrations/*/install.sh, "
        "or pass --wiki /path/to/wiki.",
        file=sys.stderr,
    )
    sys.exit(1)

# ── Import MCP SDK ────────────────────────────────────────────────────
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("[link-mcp] mcp package not found. Install with: pip install mcp", file=sys.stderr)
    sys.exit(1)

mcp = FastMCP(
    "link",
    instructions=(
        "Link is local personal memory for agents. Use link_status when "
        "connecting to Link or troubleshooting setup/readiness. Start with "
        "migrate_wiki if link_status reports a missing or old schema marker. "
        "Use starter_prompts when the user asks what to try after install. "
        "Use ingest_status to check pending raw files, the guided ingest plan, and the next ingest prompt. "
        "query_link when the user asks a substantive question that may need "
        "both memory and wiki context. Use memory_brief at "
        "session start or before personalized/project work; pass the user's "
        "task as the query when available. Use recall_memory for focused user "
        "preferences, decisions, and project context, memory_profile to inspect "
        "what Link remembers, and memory_inbox to find memories needing review. "
        "Use link_operations if link_status reports pending, failed, or "
        "interrupted local write operations. "
        "explain_memory to audit why a memory exists. Use capture_session for "
        "long chat or session notes that should be stored locally before memory "
        "approval, and capture_inbox to review saved captures before accepting, "
        "redacting, or deleting them; use propose_memories when no raw capture is needed. Use search_wiki to find "
        "specific pages and get_pages for bounded metadata lists; use get_context to retrieve a topic with its full graph "
        "neighborhood. Use get_graph_summary for bounded graph orientation on "
        "large wikis; use get_graph only for explicit full graph exports. After "
        "ingesting sources or substantially editing wiki "
        "pages, call rebuild_index, rebuild_backlinks, then validate_wiki "
        "before saying the "
        "wiki is updated. Use backup_wiki before broad repairs or risky local "
        "wiki edits; raw/ is excluded unless explicitly requested. Only call "
        "remember_memory when the user explicitly asks "
        "you to remember something; if it returns duplicate candidates, use "
        "update_memory on the existing memory instead of forcing a duplicate. "
        "If it returns conflict candidates, ask the user whether to update or "
        "archive the older memory before forcing a conflict. "
        "Use archive_memory instead of deleting stale or wrong memories; use "
        "forget_memory only when the user explicitly asks for permanent deletion."
    ),
)

# ── In-memory indexes (built on first use, invalidated by mtime) ──────
_cache: dict = {}
_cache_mtime: float = 0.0
MAX_TEXT_INPUT = 200
MAX_CAPTURE_INPUT = 12000

from link_core.memory import (
    add_capture_review_to_brief as _core_add_capture_review_to_brief,
    count_values as _core_count_values,
    default_project_for_target as _core_default_project_for_target,
    forget_memory_page as _core_forget_memory_page,
    mark_memory_reviewed as _core_mark_memory_reviewed,
    memory_brief as _core_memory_brief,
    memory_explanation as _core_memory_explanation,
    memory_inbox as _core_memory_inbox,
    memory_profile as _core_memory_profile,
    memory_audit_report as _core_memory_audit_report,
    memory_audit_next_actions as _core_memory_audit_next_actions,
    memory_records as _core_memory_records,
    normalize_project as _core_normalize_project,
    memory_review_issues as _core_memory_review_issues,
    propose_memories_from_text as _core_propose_memories_from_text,
    recall_memories as _core_recall_memories,
    recent_memories as _core_recent_memories,
    resolve_memory_page as _core_resolve_memory_page,
    set_memory_status as _core_set_memory_status,
    slim_memory as _core_slim_memory,
    top_tags as _core_top_tags,
    update_memory_page as _core_update_memory_page,
    write_memory_page as _core_write_memory_page,
)
from link_core.backup import (
    BackupError as _CoreBackupError,
    create_backup as _core_create_backup,
    list_backups as _core_list_backups,
)
from link_core.capture import (
    capture_accept_memory_args as _core_capture_accept_memory_args,
    capture_accept_payload as _core_capture_accept_payload,
    capture_inbox as _core_capture_inbox,
    capture_proposal_selection as _core_capture_proposal_selection,
    capture_records as _core_capture_records,
    capture_review_summary as _core_capture_review_summary,
    delete_capture_file as _core_delete_capture_file,
    mcp_capture_commands as _core_mcp_capture_commands,
    redact_capture_file as _core_redact_capture_file,
    write_session_capture as _core_write_session_capture,
)
from link_core.files import (
    atomic_write_json as _core_atomic_write_json,
)
from link_core.ingest import (
    collect_ingest_status as _core_collect_ingest_status,
)
from link_core.log import (
    append_log as _core_append_log,
    utc_timestamp as _core_utc_timestamp,
)
from link_core.operations import (
    operation_report as _core_operation_report,
)
from link_core.security import (
    clean_text_input as _clean_text_input,
)
from link_core.query import (
    query_link as _core_query_link,
)
from link_core.prompts import (
    starter_prompt_payload as _core_starter_prompt_payload,
)
from link_core.validation import (
    validate_wiki as _core_validate_wiki,
)
from link_core.status import (
    link_status as _core_link_status,
)
from link_core.schema import (
    migrate_wiki as _core_migrate_wiki,
)
from link_core.wiki import (
    build_backlinks as _core_build_backlinks,
    build_wiki_cache as _core_build_wiki_cache,
    close_wiki_cache as _core_close_wiki_cache,
    context_for_topic as _core_context_for_topic,
    graph_data as _core_graph_data,
    graph_summary as _core_graph_summary,
    list_pages as _core_list_pages,
    load_backlinks_index as _core_load_backlinks_index,
    page_link_summary as _core_page_link_summary,
    rebuild_index as _core_rebuild_index,
    search_pages as _core_search_pages,
    wiki_mtime as _core_wiki_mtime,
)


def _required_text_input(value, message: str, max_len: int = MAX_TEXT_INPUT) -> str:
    text = _clean_text_input(value, max_len=max_len)
    if not text:
        raise ValueError(message)
    return text


def _parse_limit(value, default: int = 20, max_limit: int = 50) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(limit, 1), max_limit)


def _pagination_args(
    limit: int,
    offset: int,
    include_all: bool,
    *,
    default_limit: int = 100,
    max_limit: int = 1000,
) -> tuple[int, int, bool]:
    try:
        parsed_offset = int(offset)
    except (TypeError, ValueError):
        parsed_offset = 0
    if isinstance(include_all, bool):
        parsed_include_all = include_all
    else:
        parsed_include_all = str(include_all).strip().lower() in {"1", "true", "yes", "on"}
    return (
        _parse_limit(limit, default=default_limit, max_limit=max_limit),
        max(parsed_offset, 0),
        parsed_include_all,
    )


def _default_project() -> str:
    return _core_default_project_for_target(WIKI_DIR)


def _wiki_mtime() -> float:
    return _core_wiki_mtime(WIKI_DIR)


def _clear_cache() -> None:
    global _cache, _cache_mtime
    _core_close_wiki_cache(_cache)
    _cache = {}
    _cache_mtime = 0.0


def _build_cache() -> dict:
    global _cache, _cache_mtime
    mtime = _wiki_mtime()
    if _cache and mtime == _cache_mtime:
        return _cache

    _core_close_wiki_cache(_cache)
    _cache = _core_build_wiki_cache(WIKI_DIR)
    _cache_mtime = mtime
    return _cache


def _search(q: str, limit: int = 20) -> list[dict]:
    q = _clean_text_input(q)
    limit = _parse_limit(limit)
    if not q:
        return []
    return _core_search_pages(q, _build_cache(), limit=limit)


def _get_context(topic: str) -> dict:
    topic = _clean_text_input(topic)
    return _core_context_for_topic(WIKI_DIR, topic, _build_cache(), empty_error="topic required")


def _utc_timestamp() -> str:
    return _core_utc_timestamp()


def _memory_records() -> list[dict[str, object]]:
    return _core_memory_records(WIKI_DIR)


def _slim_memory(record: dict[str, object]) -> dict[str, object]:
    return _core_slim_memory(record)


def _memory_review_issues(record: dict[str, object]) -> list[dict[str, str]]:
    return _core_memory_review_issues(record, review_command="review_memory")


def _memory_inbox(limit: int = 20, include_archived: bool = False, project: str = "") -> dict[str, object]:
    return _core_memory_inbox(
        _memory_records(),
        limit=limit,
        include_archived=include_archived,
        review_command="review_memory",
        project=project,
        command_target=WIKI_DIR.parent,
    )


def _memory_explanation(identifier: str) -> dict[str, object]:
    return _core_memory_explanation(
        WIKI_DIR,
        identifier,
        records=_memory_records(),
        review_command="review_memory",
        command_target=WIKI_DIR.parent,
    )


def _count_values(records: list[dict[str, object]], field: str) -> dict[str, int]:
    return _core_count_values(records, field)


def _top_tags(records: list[dict[str, object]], limit: int = 12) -> list[dict[str, object]]:
    return _core_top_tags(records, limit=limit)


def _recent_memories(records: list[dict[str, object]]) -> list[dict[str, object]]:
    return _core_recent_memories(records)


def _resolve_project(project: str = "") -> str:
    return _clean_text_input(project) or _default_project()


def _memory_profile(limit: int = 10, project: str = "") -> dict[str, object]:
    return _core_memory_profile(
        _memory_records(),
        limit=limit,
        review_command="review_memory",
        project=_resolve_project(project),
    )


def _memory_brief(query: str = "", limit: int = 6, project: str = "") -> dict[str, object]:
    project_name = _resolve_project(project)
    payload = _core_memory_brief(
        _memory_records(), query=_clean_text_input(query, max_len=500),
        limit=limit, review_command="review_memory", project=project_name,
        command_target=WIKI_DIR.parent,
    )
    return _core_add_capture_review_to_brief(payload, _capture_review_summary(project=project_name))


def _query_link(query: str, budget: str = "medium", project: str = "") -> dict[str, object]:
    project_name = _resolve_project(project)
    return _core_query_link(
        WIKI_DIR,
        _clean_text_input(query, max_len=500),
        _build_cache(),
        _memory_records(),
        budget=budget,
        project=project_name,
        review_command="review_memory",
    )


def _validate_wiki(strict: bool = False) -> dict[str, object]:
    return _core_validate_wiki(WIKI_DIR, strict=bool(strict))


def _package_version() -> str:
    return LINK_VERSION


def _link_status(include_validation: bool = False) -> dict[str, object]:
    return _core_link_status(
        WIKI_DIR,
        version=_package_version(),
        include_validation=include_validation,
    )


def _link_operations(limit: int = 20) -> dict[str, object]:
    return _core_operation_report(WIKI_DIR, limit=_parse_limit(limit, default=20, max_limit=100))


def _starter_prompts(project: str = "") -> dict[str, object]:
    return _core_starter_prompt_payload(WIKI_DIR.parent, project=project or None)


def _migrate_wiki() -> dict[str, object]:
    payload = _core_migrate_wiki(WIKI_DIR)
    _clear_cache()
    return payload


def _ingest_status() -> dict[str, object]:
    return _core_collect_ingest_status(WIKI_DIR.parent)


def _memory_audit(limit: int = 10, project: str = "") -> dict[str, object]:
    parsed_limit = _parse_limit(limit, default=10, max_limit=50)
    project_name = _resolve_project(project)
    profile = _memory_profile(limit=parsed_limit, project=project_name)
    inbox = _memory_inbox(limit=parsed_limit, include_archived=True, project=project_name)
    captures = _capture_review_summary(project=project_name, limit=min(parsed_limit, 10))
    return _core_memory_audit_report(
        profile,
        inbox,
        captures,
        _core_memory_audit_next_actions(
            mode="mcp",
            inbox=inbox,
            captures=captures,
            project=project_name,
        ),
        project=project_name,
    )


def _recall_memories(
    query: str,
    limit: int = 10,
    include_archived: bool = False,
    project: str = "",
) -> list[dict[str, object]]:
    query = _clean_text_input(query)
    return _core_recall_memories(
        _memory_records(),
        query,
        limit=limit,
        include_archived=include_archived,
        project=_resolve_project(project),
    )


def _propose_memories_from_text(
    text: str,
    source: str = "mcp",
    limit: int = 10,
    project: str = "",
) -> dict[str, object]:
    return _core_propose_memories_from_text(
        text,
        _memory_records(),
        source=source,
        limit=limit,
        writes_memory=False,
        project=_resolve_project(project),
    )


def _capture_session(
    text: str,
    title: str = "",
    source: str = "mcp",
    limit: int = 10,
    project: str = "",
) -> dict[str, object]:
    clean_text = _clean_text_input(text, max_len=MAX_CAPTURE_INPUT)
    if not clean_text:
        raise ValueError("session text required")
    clean_source = _clean_text_input(source, max_len=500) or "mcp"
    project_name = _resolve_project(project)
    capture_record = _core_write_session_capture(
        WIKI_DIR.parent,
        text=clean_text,
        source=clean_source,
        title=_clean_text_input(title, max_len=200),
        project=project_name,
        default_source="mcp",
    )
    rel_path = str(capture_record["path"])
    proposals = _propose_memories_from_text(
        clean_text,
        source=rel_path,
        limit=limit,
        project=project_name,
    )
    _append_log(
        str(capture_record["timestamp"]),
        "capture-session",
        f"Captured proposal-only session notes at {rel_path}",
        [
            f"Source input: {clean_source}",
            f"Project: {capture_record['project'] or 'none'}",
            f"Secret warnings: {', '.join(capture_record['secret_warnings']) if capture_record['secret_warnings'] else 'none'}",
            f"Proposals: {proposals['count']}",
        ],
    )
    _clear_cache()
    return {
        "captured": True,
        "path": rel_path,
        "source": clean_source,
        "title": capture_record["title"],
        "project": capture_record["project"],
        "secret_warnings": capture_record["secret_warnings"],
        "proposals": proposals,
    }


def _capture_records(limit: int = 20, project: str = "") -> list[dict[str, object]]:
    root = WIKI_DIR.parent
    return _core_capture_records(
        root,
        limit=limit,
        project=project,
        commands_for=_core_mcp_capture_commands,
    )


def _capture_inbox(limit: int = 20, project: str = "") -> dict[str, object]:
    return _core_capture_inbox(
        WIKI_DIR.parent,
        limit=limit,
        project=project,
        commands_for=_core_mcp_capture_commands,
    )


def _capture_review_summary(project: str = "", limit: int = 3) -> dict[str, object]:
    project_name = _core_normalize_project(project)
    summary = _core_capture_review_summary(
        WIKI_DIR.parent,
        limit=limit,
        project=project_name,
        commands_for=_core_mcp_capture_commands,
    )
    next_action = "capture_inbox()"
    if project_name:
        next_action = f'capture_inbox(project="{project_name}")'
    summary["next_action"] = next_action
    return summary


def _accept_capture(
    capture: str,
    index: int = 1,
    title: str = "",
    memory_type: str = "",
    scope: str = "",
    tags: str = "",
    project: str = "",
    allow_duplicate: bool = False,
    allow_conflict: bool = False,
) -> dict[str, object]:
    root = WIKI_DIR.parent
    selection = _core_capture_proposal_selection(
        root,
        capture,
        index=index,
        project=_clean_text_input(project),
        default_project=_default_project(),
        max_capture_len=500,
        propose_memories=lambda notes, rel_path, proposal_limit, project_name: _propose_memories_from_text(
            notes,
            source=rel_path,
            limit=proposal_limit,
            project=project_name,
        ),
    )
    rel_path = str(selection["capture"])
    proposal_index = int(selection["proposal_index"])
    memory_args = _core_capture_accept_memory_args(
        selection,
        title=_clean_text_input(title),
        memory_type=_clean_text_input(memory_type).lower(),
        scope=_clean_text_input(scope).lower(),
        tags=tags,
    )
    result = _write_memory_page(
        str(memory_args["text"]),
        title=str(memory_args["title"]),
        memory_type=str(memory_args["memory_type"]),
        scope=str(memory_args["scope"]),
        tags=memory_args["tags"] if isinstance(memory_args["tags"], str) else "",
        source=str(memory_args["source"]),
        allow_duplicate=allow_duplicate,
        allow_conflict=allow_conflict,
        project=str(memory_args["project"]),
    )
    payload = _core_capture_accept_payload(selection, result)
    if result.get("created"):
        _append_log(
            _utc_timestamp(),
            "accept-capture",
            f"Accepted proposal {proposal_index} from {rel_path}",
            [
                f"Memory: {result['path']}",
                f"Project: {result.get('project') or 'none'}",
            ],
        )
    return payload


def _redact_capture(capture: str, replacement: str = "[redacted-secret]") -> dict[str, object]:
    root = WIKI_DIR.parent
    payload = _core_redact_capture_file(
        root,
        capture,
        replacement=_clean_text_input(replacement, max_len=100) or "[redacted-secret]",
        max_capture_len=500,
    )
    if payload["redacted"]:
        labels = payload.get("labels") if isinstance(payload.get("labels"), list) else []
        _append_log(
            _utc_timestamp(),
            "redact-capture",
            f"Redacted secret-looking values from {payload['path']}",
            [
                f"Labels: {', '.join(labels)}",
                f"Replacement count: {payload['replacement_count']}",
            ],
        )
    return payload


def _delete_capture(capture: str, confirm: bool = False) -> dict[str, object]:
    root = WIKI_DIR.parent
    payload = _core_delete_capture_file(root, capture, confirm=confirm, max_capture_len=500)
    if not confirm:
        return payload
    _append_log(
        _utc_timestamp(),
        "delete-capture",
        f"Deleted raw capture {payload['path']}",
        ["Deleted file only; capture contents were not logged."],
    )
    return payload


def _append_log(timestamp: str, operation: str, description: str, lines: list[str]) -> None:
    _core_append_log(WIKI_DIR, timestamp, operation, description, lines)


def _resolve_memory_page(identifier: str) -> tuple[Path | None, dict[str, object] | None, str | None]:
    return _core_resolve_memory_page(
        WIKI_DIR,
        identifier,
        records=_memory_records(),
        max_identifier_len=300,
    )


def _rebuild_memory_backlinks() -> bool:
    rebuilt = json.loads(rebuild_backlinks())
    return bool(rebuilt.get("rebuilt"))


def _memory_mutation_options(project: str = "") -> dict[str, object]:
    return {
        "timestamp": _utc_timestamp(),
        "records": _memory_records(),
        "project": _resolve_project(project),
        "log_writer": _append_log,
        "rebuild_backlinks": _rebuild_memory_backlinks,
    }


def _memory_type_scope(memory_type: str, scope: str) -> tuple[str, str]:
    return (
        _clean_text_input(memory_type).lower() or "note",
        _clean_text_input(scope).lower() or "user",
    )


def _set_memory_status(identifier: str, status: str, reason: str = "") -> dict[str, object]:
    result = _core_set_memory_status(
        WIKI_DIR,
        _clean_text_input(identifier, max_len=300),
        status,
        reason=_clean_text_input(reason, max_len=500),
        timestamp=_utc_timestamp(),
        records=_memory_records(),
        log_writer=_append_log,
    )
    if result["updated"]:
        _clear_cache()
    return result


def _forget_memory(identifier: str, confirm: bool = False) -> dict[str, object]:
    result = _core_forget_memory_page(
        WIKI_DIR,
        _clean_text_input(identifier, max_len=300),
        confirm=confirm,
        records=_memory_records(),
        timestamp=_utc_timestamp(),
        log_writer=_append_log,
        rebuild_backlinks=_rebuild_memory_backlinks,
    )
    if result.get("forgotten"):
        _clear_cache()
    return result


def _mark_memory_reviewed(identifier: str, note: str = "") -> dict[str, object]:
    result = _core_mark_memory_reviewed(
        WIKI_DIR,
        _clean_text_input(identifier, max_len=300),
        note=_clean_text_input(note, max_len=500),
        timestamp=_utc_timestamp(),
        records=_memory_records(),
        review_command="review_memory",
        log_writer=_append_log,
    )
    if result["updated"]:
        _clear_cache()
    return result


def _update_memory_page(
    identifier: str,
    text: str,
    source: str = "mcp",
    allow_conflict: bool = False,
    project: str = "",
) -> dict[str, object]:
    clean_text = _required_text_input(text, "memory update text required", max_len=4000)
    clean_source = _clean_text_input(source, max_len=500) or "mcp"
    options = _memory_mutation_options(project)

    result = _core_update_memory_page(
        WIKI_DIR, _clean_text_input(identifier, max_len=300), clean_text,
        source=clean_source, review_command="review_memory",
        allow_conflict=allow_conflict,
        **options,
    )
    _clear_cache()
    return result


def _write_memory_page(
    text: str, title: str = "", memory_type: str = "note",
    scope: str = "user", tags: str = "", source: str = "mcp",
    allow_duplicate: bool = False, allow_conflict: bool = False, project: str = "",
) -> dict[str, object]:
    clean_text = _required_text_input(text, "memory text required", max_len=4000)
    memory_type, scope = _memory_type_scope(memory_type, scope)
    options = _memory_mutation_options(project)

    result = _core_write_memory_page(
        WIKI_DIR, clean_text, title=_clean_text_input(title),
        memory_type=memory_type, scope=scope,
        tags=_clean_text_input(tags, max_len=500), source=_clean_text_input(source, max_len=500),
        allow_duplicate=allow_duplicate, allow_conflict=allow_conflict,
        **options,
    )
    if result.get("created"):
        _clear_cache()
    return result


# ── MCP Tools ─────────────────────────────────────────────────────────

@mcp.tool()
def query_link(query: str, budget: str = "medium", project: str = "") -> str:
    """Build a compact answer-ready Link context packet.

    Use this before answering substantive questions that may need local memory,
    wiki knowledge, or both. It returns budgeted memories, ranked wiki results,
    graph-neighborhood context, and why each item was selected so the agent does
    not waste context by reading the whole wiki.
    budget: small, medium, or large.
    """
    return json.dumps(_query_link(query=query, budget=budget, project=project), ensure_ascii=False)


@mcp.tool()
def link_status(include_validation: bool = False) -> str:
    """Return a compact Link readiness summary.

    Use this when connecting to Link or troubleshooting setup. It reports the
    wiki path, package version, page/memory counts, missing required paths,
    optional validation summary, and safe next actions.
    """
    return json.dumps(_link_status(include_validation=include_validation), ensure_ascii=False)


@mcp.tool()
def link_operations(limit: int = 20) -> str:
    """Inspect interrupted or active local Link write operations.

    Use this when link_status reports pending, failed, or stale operations.
    It returns operation markers with timestamps, affected paths, status, and
    safe next actions so agents can diagnose interrupted writes before repair.
    """
    return json.dumps(_link_operations(limit=limit), ensure_ascii=False)


@mcp.tool()
def starter_prompts(project: str = "") -> str:
    """Return first-run Link prompts and local checks.

    Use this when a user asks what to try after installing Link, or when an
    agent needs concise natural-language prompts for readiness, brief, remember,
    query, ingest, and proposal workflows.
    """
    return json.dumps(_starter_prompts(project=project), ensure_ascii=False)


@mcp.tool()
def backup_wiki(label: str = "mcp", include_raw: bool = False, list_only: bool = False) -> str:
    """Create or list local backup archives for this Link wiki.

    Use before broad repairs or risky local wiki edits. Backups stay under
    .link-backups/ next to the wiki. raw/ is excluded by default because it may
    contain sensitive source material; include_raw should only be true after
    explicit user approval.
    """
    link_root = WIKI_DIR.parent
    if list_only:
        return json.dumps(_core_list_backups(link_root), ensure_ascii=False)
    try:
        result = _core_create_backup(
            link_root,
            label=_clean_text_input(label, max_len=80) or "mcp",
            include_raw=include_raw,
        )
    except (FileNotFoundError, _CoreBackupError) as exc:
        return json.dumps({"created": False, "error": str(exc)}, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def memory_brief(query: str = "", limit: int = 6, project: str = "") -> str:
    """Prime the agent with local memory before answering or coding.

    Call this at the start of a session or before a user task that may depend
    on preferences, project decisions, or personal context. It returns profile
    counts, relevant memories for the query, review warnings, and rules for
    safe memory use.
    """
    limit = _parse_limit(limit, default=6, max_limit=20)
    return json.dumps(_memory_brief(query=query, limit=limit, project=project), ensure_ascii=False)


@mcp.tool()
def validate_wiki(strict: bool = False) -> str:
    """Validate agent-generated wiki pages after ingest or large edits.

    Call rebuild_backlinks first, then validate_wiki before reporting ingest
    complete. The response checks required frontmatter, directory/type
    alignment, required sections, dead wikilinks, and backlink freshness.
    strict=true also fails on warnings such as missing TLDR/Query summaries.
    """
    return json.dumps(_validate_wiki(strict=strict), ensure_ascii=False)


@mcp.tool()
def migrate_wiki() -> str:
    """Apply safe Link wiki schema migrations.

    Use this when link_status reports a missing or old schema marker. The
    operation is idempotent and only creates missing canonical wiki directories
    plus the local schema marker; it does not rewrite user pages.
    """
    return json.dumps(_migrate_wiki(), ensure_ascii=False)


@mcp.tool()
def ingest_status() -> str:
    """Return raw source ingest state and the next safe action.

    Use this when the user asks to ingest, after they drop files into raw/, or
    when you need the exact next agent prompt and validation commands.
    """
    return json.dumps(_ingest_status(), ensure_ascii=False)


@mcp.tool()
def search_wiki(query: str, limit: int = 20) -> str:
    """Search the Link wiki by title, alias, tag, and full-text content.

    Returns ranked results with scores and snippets. Scoring:
    - Exact name match: 20pts
    - Title match: 10pts
    - Alias match: 8pts
    - Tag match: 5pts
    - TLDR match: 3pts
    - Full-text match: 2pts

    Use this to find relevant pages before calling get_context.
    """
    query = _clean_text_input(query)
    limit = _parse_limit(limit)
    if not query:
        return json.dumps({"error": "query required", "query": "", "count": 0, "results": []})

    results = _search(query, limit=limit)
    if not results:
        return json.dumps({"query": query, "count": 0, "results": []})
    # Strip heavy fields for the search response
    slim = [{k: v for k, v in r.items() if k not in ("aliases",)} for r in results]
    return json.dumps({"query": query, "count": len(slim), "results": slim}, ensure_ascii=False)


@mcp.tool()
def recall_memory(query: str, limit: int = 10, include_archived: bool = False, project: str = "") -> str:
    """Search local agent memory pages first.

    Use this when the user asks about preferences, decisions, project context,
    or anything the agent should remember across sessions. Returns only pages
    under wiki/memories/. Archived and stale memories are excluded unless
    include_archived is true.
    """
    query = _clean_text_input(query)
    limit = _parse_limit(limit, default=10)
    if not query:
        return json.dumps({"error": "query required", "query": "", "count": 0, "memories": []})
    project_name = _resolve_project(project)
    memories = _recall_memories(query, limit=limit, include_archived=include_archived, project=project_name)
    return json.dumps({
        "query": query,
        "count": len(memories),
        "include_archived": include_archived,
        "project": project_name,
        "memories": memories,
    }, ensure_ascii=False)


@mcp.tool()
def propose_memories(text: str, source: str = "mcp", limit: int = 10, project: str = "") -> str:
    """Propose durable memories from chat or session notes without writing them.

    Returns conservative memory proposals with type, scope, confidence, reason,
    duplicate candidates, and a suggested follow-up action. Use remember_memory
    or update_memory after the user confirms a proposal.
    """
    clean_text = _clean_text_input(text, max_len=12000)
    if not clean_text:
        return json.dumps({"proposed": False, "error": "text required", "count": 0, "proposals": []})
    source = _clean_text_input(source, max_len=500) or "mcp"
    limit = _parse_limit(limit, default=10, max_limit=20)
    return json.dumps(_propose_memories_from_text(clean_text, source=source, limit=limit, project=project), ensure_ascii=False)


@mcp.tool()
def capture_session(text: str, title: str = "", source: str = "mcp", limit: int = 10, project: str = "") -> str:
    """Save long chat/session notes locally and return memory proposals only.

    Writes a raw note under raw/memory-captures/ and logs the capture, but does
    not create durable memory pages. Use this when the user wants the session
    preserved for review before approving remember_memory or update_memory.
    """
    limit = _parse_limit(limit, default=10, max_limit=20)
    try:
        result = _capture_session(text, title=title, source=source, limit=limit, project=project)
    except ValueError as exc:
        return json.dumps({
            "captured": False,
            "error": str(exc),
            "proposals": {"proposed": False, "count": 0, "proposals": []},
        })
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def capture_inbox(limit: int = 20, project: str = "") -> str:
    """List saved raw session captures without changing them.

    Returns saved captures, secret-warning labels, redacted snippets, and the
    next MCP tool calls for accepting, redacting, or deleting a capture.
    """
    limit = _parse_limit(limit, default=20, max_limit=50)
    return json.dumps(_capture_inbox(limit=limit, project=project), ensure_ascii=False)


@mcp.tool()
def accept_capture(
    capture: str,
    index: int = 1,
    title: str = "",
    memory_type: str = "",
    scope: str = "",
    tags: str = "",
    project: str = "",
    allow_duplicate: bool = False,
    allow_conflict: bool = False,
) -> str:
    """Accept one proposal from a saved raw session capture.

    Recomputes proposals from raw/memory-captures, selects the 1-based index,
    and writes the chosen memory through duplicate/conflict-safe creation.
    """
    try:
        result = _accept_capture(
            capture,
            index=index,
            title=title,
            memory_type=memory_type,
            scope=scope,
            tags=tags,
            project=project,
            allow_duplicate=allow_duplicate,
            allow_conflict=allow_conflict,
        )
    except ValueError as exc:
        return json.dumps({"accepted": False, "error": str(exc)})
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def redact_capture(capture: str, replacement: str = "[redacted-secret]") -> str:
    """Redact secret-looking values from a saved raw session capture.

    Use after capture_session returns secret_warnings and the user approves
    redaction. Logs warning labels and counts only, never secret values.
    """
    try:
        result = _redact_capture(capture, replacement=replacement)
    except ValueError as exc:
        return json.dumps({"redacted": False, "error": str(exc)})
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def delete_capture(capture: str, confirm: bool = False) -> str:
    """Delete a saved raw session capture after explicit user confirmation.

    The tool refuses to delete unless confirm is true. It logs the capture path
    and deletion operation only, never the capture contents.
    """
    try:
        result = _delete_capture(capture, confirm=confirm)
    except ValueError as exc:
        return json.dumps({"deleted": False, "error": str(exc)})
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def memory_profile(limit: int = 10, project: str = "") -> str:
    """Summarize what Link currently remembers.

    Use this to inspect the local memory profile before doing personalized work.
    Returns counts by type/scope/status, top tags, recent memories, and focused
    lists for preferences, decisions, and project context.
    """
    limit = _parse_limit(limit, default=10)
    return json.dumps(_memory_profile(limit=limit, project=project), ensure_ascii=False)


@mcp.tool()
def memory_audit(limit: int = 10, project: str = "") -> str:
    """Audit local memory health, review backlog, and raw capture state.

    Use this when the user asks what Link knows, what needs attention, or
    whether local agent memory is ready for use.
    """
    return json.dumps(_memory_audit(limit=limit, project=project), ensure_ascii=False)


@mcp.tool()
def memory_inbox(limit: int = 20, include_archived: bool = False, project: str = "") -> str:
    """List memories that need user review.

    Use this to surface pending, stale, invalid, or underspecified memories for
    human confirmation. Archived memories are excluded unless include_archived
    is true. Pass project to include broad user/global memory plus that
    project's scoped memories while excluding other explicit projects.
    """
    limit = _parse_limit(limit, default=20)
    return json.dumps(_memory_inbox(limit=limit, include_archived=include_archived, project=project), ensure_ascii=False)


@mcp.tool()
def review_memory(identifier: str, note: str = "") -> str:
    """Mark a memory as reviewed after user confirmation."""
    try:
        result = _mark_memory_reviewed(identifier, note=note)
    except ValueError as exc:
        return json.dumps({"updated": False, "error": str(exc)})
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def explain_memory(identifier: str) -> str:
    """Explain why a memory exists and whether it is ready for recall.

    Returns provenance, review state, lifecycle state, graph links, recent log
    entries, and detected quality issues for one memory.
    """
    try:
        result = _memory_explanation(identifier)
    except ValueError as exc:
        return json.dumps({"found": False, "error": str(exc)})
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def update_memory(
    identifier: str,
    memory: str,
    source: str = "mcp",
    allow_conflict: bool = False,
    project: str = "",
) -> str:
    """Merge new information into an existing active memory.

    Use this when remember_memory returns a duplicate candidate or when the user
    asks to update something Link already remembers. The update is appended to
    the memory body, logged, and marked pending review.
    """
    try:
        result = _update_memory_page(
            identifier,
            memory,
            source=source,
            allow_conflict=allow_conflict,
            project=project,
        )
    except ValueError as exc:
        return json.dumps({"updated": False, "error": str(exc)})
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def archive_memory(identifier: str, reason: str = "") -> str:
    """Archive a memory without deleting its Markdown page.

    Use this when the user says a memory is stale, wrong, or no longer useful.
    The page remains local and inspectable, recall_memory hides it by default,
    and the operation is appended to wiki/log.md.
    """
    try:
        result = _set_memory_status(identifier, "archived", reason=reason)
    except ValueError as exc:
        return json.dumps({"updated": False, "error": str(exc)})
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def restore_memory(identifier: str) -> str:
    """Restore an archived memory to active status."""
    try:
        result = _set_memory_status(identifier, "active")
    except ValueError as exc:
        return json.dumps({"updated": False, "error": str(exc)})
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def forget_memory(identifier: str, confirm: bool = False) -> str:
    """Permanently delete a memory after explicit user confirmation.

    Prefer archive_memory for reversible cleanup. Use forget_memory only when
    the user asks Link to permanently forget a memory; the tool refuses to
    delete unless confirm is true and never logs the memory body.
    """
    return json.dumps(_forget_memory(identifier, confirm=confirm), ensure_ascii=False)


@mcp.tool()
def remember_memory(
    memory: str,
    title: str = "",
    memory_type: str = "note",
    scope: str = "user",
    tags: str = "",
    source: str = "mcp",
    allow_duplicate: bool = False,
    allow_conflict: bool = False,
    project: str = "",
) -> str:
    """Save a local agent memory as a Markdown page.

    Use only when the user explicitly asks you to remember something. The memory
    is written under wiki/memories/, indexed, logged, and kept local. Strong
    duplicates are refused unless allow_duplicate is true.
    Potential conflicts are refused unless allow_conflict is true.
    memory_type: preference, decision, project, fact, or note.
    scope: user, project, or global.
    project: optional project key for project-scoped memories.
    tags: optional comma-separated tags.
    """
    try:
        result = _write_memory_page(
            memory,
            title=title,
            memory_type=memory_type,
            scope=scope,
            tags=tags,
            source=source,
            allow_duplicate=allow_duplicate,
            allow_conflict=allow_conflict,
            project=project,
        )
    except ValueError as exc:
        return json.dumps({"created": False, "error": str(exc)})
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def get_context(topic: str) -> str:
    """Get full context for a topic from the Link wiki.

    Returns the best matching page (full content) plus all related pages
    via graph traversal (inbound links + forward links). This is the
    primary tool for answering questions — one call gives you everything
    needed to synthesize an answer.

    The response includes:
    - primary: the best matching page with full markdown content
    - inbound: pages that link TO this page
    - forward: pages this page links TO
    - relationship field on each page: "primary", "inbound", or "forward"
    """
    result = _get_context(topic)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def get_pages(
    category: str = "",
    page_type: str = "",
    maturity: str = "",
    limit: int = 100,
    offset: int = 0,
    include_all: bool = False,
) -> str:
    """List Link wiki pages with metadata, bounded by default.

    Optional filters:
    - category: "memories", "concepts", "entities", "sources", "comparisons", "explorations"
    - page_type: "memory", "concept", "entity", "source", "comparison", "exploration"
    - maturity: "seed", "growing", "mature", "established"
    - limit: max returned pages, clamped to 1..1000; default 100
    - offset: pagination offset
    - include_all: true only when the user explicitly needs a full metadata export

    Returns pages with: name, title, category, type, tags, aliases, maturity,
    source_count, tldr, date_updated. Does not include full page content.
    Use search_wiki, query_link, or get_context instead of paging through the
    whole wiki when answering a question.
    """
    parsed_limit, parsed_offset, parsed_include_all = _pagination_args(limit, offset, include_all)
    return json.dumps(
        _core_list_pages(
            _build_cache(),
            category=_clean_text_input(category).lower(),
            page_type=_clean_text_input(page_type).lower(),
            maturity=_clean_text_input(maturity).lower(),
            limit=parsed_limit,
            offset=parsed_offset,
            include_all=parsed_include_all,
        ),
        ensure_ascii=False,
    )


@mcp.tool()
def get_backlinks(page_name: str, limit: int = 100, offset: int = 0, include_all: bool = False) -> str:
    """Get pages that link to or from a given wiki page, bounded by default.

    Returns:
    - inbound: pages that link TO this page (who references it)
    - forward: pages this page links TO (what it references)
    - inbound_count / forward_count: total available link counts
    - returned_inbound / returned_forward: returned link counts
    - follow_up: pagination and context actions when truncated

    Useful for understanding a page's position in the knowledge graph.
    Set include_all=true only when the user explicitly asks for a full link
    export.
    """
    backlinks, error = _core_load_backlinks_index(WIKI_DIR / "_backlinks.json", missing_error="backlinks not built — run rebuild_backlinks first")
    if error:
        return json.dumps({"error": error})

    page_name = _clean_text_input(page_name)
    if not page_name:
        return json.dumps({"error": "page_name required", "inbound": [], "forward": []})

    parsed_limit, parsed_offset, parsed_include_all = _pagination_args(limit, offset, include_all)
    return json.dumps(
        _core_page_link_summary(
            backlinks,
            page_name,
            limit=parsed_limit,
            offset=parsed_offset,
            include_all=parsed_include_all,
        ),
        ensure_ascii=False,
    )


@mcp.tool()
def get_graph() -> str:
    """Get the full knowledge graph as nodes and edges.

    Returns:
    - nodes: all wiki pages with id, title, category, type
    - edges: all [[wikilinks]] as {source, target} pairs

    Useful for understanding the overall structure of the wiki,
    finding highly-connected pages, or detecting isolated clusters.

    For large wikis, prefer get_graph_summary first. Use get_graph only when
    the user explicitly needs the full graph export.
    """
    return json.dumps(_core_graph_data(_build_cache()), ensure_ascii=False)


@mcp.tool()
def get_graph_summary(topic: str = "", limit: int = 40, depth: int = 1, max_edges: int = 120) -> str:
    """Get a bounded graph summary for large wikis and agent context budgets.

    Args:
    - topic: optional topic/query. When provided, Link returns a bounded
      neighborhood around matching pages. When omitted, Link returns a
      high-degree overview.
    - limit: maximum nodes to return, clamped to 1..250.
    - depth: graph neighborhood depth for topic mode, clamped to 0..3.
    - max_edges: maximum returned edges among selected nodes, clamped to 0..1000.

    Use this before get_graph when the wiki may contain hundreds or thousands
    of pages. The response includes total graph size, returned node/edge counts,
    why each node was selected, top hubs, and follow-up tool actions.
    """
    return json.dumps(
        _core_graph_summary(
            _build_cache(),
            topic=_clean_text_input(topic, max_len=MAX_TEXT_INPUT),
            limit=limit,
            depth=depth,
            max_edges=max_edges,
        ),
        ensure_ascii=False,
    )


@mcp.tool()
def rebuild_index() -> str:
    """Regenerate wiki/index.md from current Markdown pages.

    Run this after ingesting sources or making large page edits so the
    human-readable wiki catalog reflects all pages grouped by category.
    """
    try:
        result = _core_rebuild_index(WIKI_DIR, cache=_build_cache())
    except OSError as exc:
        return json.dumps({"rebuilt": False, "error": f"Could not rebuild index: {exc}"}, ensure_ascii=False)
    _clear_cache()
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def rebuild_backlinks() -> str:
    """Rebuild the wiki's backlink index by scanning all [[wikilinks]].

    Call this after ingesting new sources or running lint to ensure
    the graph index is up to date. Updates wiki/_backlinks.json with
    both reverse links (backlinks) and forward links.
    """
    try:
        result = _core_build_backlinks(WIKI_DIR)
    except OSError as exc:
        return json.dumps({"rebuilt": False, "error": f"Could not rebuild backlinks: {exc}"}, ensure_ascii=False)
    bl_path = WIKI_DIR / "_backlinks.json"
    _core_atomic_write_json(bl_path, result)

    _clear_cache()

    return json.dumps({"rebuilt": True, "pages_indexed": len(result["backlinks"])})


# ── Entry point ───────────────────────────────────────────────────────

def main():
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
