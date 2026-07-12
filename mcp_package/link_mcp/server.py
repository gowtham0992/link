#!/usr/bin/env python3
"""
Link MCP Server

Exposes the Link personal knowledge wiki over MCP.
Agents can recall local memory, search/query context, review durable
memories, and traverse the knowledge graph without reading files directly.

Install:
  pip install link-mcp

Usage:
  python -m link_mcp --surface slim                 # recommended agent surface
  python -m link_mcp --wiki /path/wiki --surface slim
  python -m link_mcp --wiki /path/wiki --surface full # compatibility surface

Add to your MCP client config:
  {
    "mcpServers": {
      "link": {
        "command": "python3",
        "args": ["-m", "link_mcp", "--wiki", "~/link/wiki", "--surface", "slim"]
      }
    }
  }
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path

from link_core.version import LINK_VERSION

# ── Resolve wiki directory ────────────────────────────────────────────
# The parser keeps add_help=False and parse_known_args so an agent launch
# config with unexpected args can never crash the server. Handle --help
# explicitly first: without this, `python -m link_mcp --help` would start
# the stdio server and hang silently waiting for MCP messages.
if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
    print(__doc__.strip())
    print(
        "\nOptions:\n"
        "  --wiki PATH        wiki directory (default: ~/link/wiki)\n"
        "  --surface SURFACE  tool surface: slim (recommended) or full\n"
        "  --version          print the link-mcp version and exit\n"
        "  --semantic-setup   one-time semantic model fetch + index build\n"
        "  -h, --help         show this help and exit"
    )
    sys.exit(0)

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--wiki", default=None)
parser.add_argument("--surface", choices=("full", "slim"), default=None)
parser.add_argument("--version", action="store_true")
parser.add_argument("--semantic-setup", action="store_true")
args, _ = parser.parse_known_args()

if args.version:
    print(f"link-mcp {LINK_VERSION}")
    sys.exit(0)

if args.wiki:
    WIKI_DIR = Path(args.wiki).expanduser().resolve()
else:
    WIKI_DIR = Path.home() / "link" / "wiki"

if args.semantic_setup:
    # One-time explicit opt-in for MCP-only installs (no `lnk` CLI): fetch
    # the local embedding model and build the semantic index, then exit.
    # This is the only link-mcp entry point allowed to touch the network.
    from link_core.memory import memory_records as _setup_memory_records
    from link_core.semantic import (
        load_embedder as _setup_load_embedder,
        refresh_memory_index as _setup_refresh_index,
        semantic_model_name as _setup_model_name,
    )

    if not WIKI_DIR.exists():
        print(f"[link-mcp] Wiki not found at {WIKI_DIR}; pass --wiki /path/to/wiki.", file=sys.stderr)
        sys.exit(2)
    print(
        f"[link-mcp] Setting up semantic recall: this may download {_setup_model_name()} "
        "once. Recall itself never uses the network."
    )
    setup_embedder = _setup_load_embedder(allow_download=True)
    if setup_embedder is None:
        print(
            "[link-mcp] Semantic provider unavailable. Install it first: "
            "pip install \"link-mcp[semantic]\"",
            file=sys.stderr,
        )
        sys.exit(2)
    setup_index = _setup_refresh_index(WIKI_DIR.parent, _setup_memory_records(WIKI_DIR), embedder=setup_embedder)
    setup_items = setup_index.get("items") if isinstance(setup_index.get("items"), dict) else {}
    print(f"[link-mcp] Semantic recall ready: indexed {len(setup_items)} memories.")
    sys.exit(0)

MCP_SURFACE = (args.surface or os.environ.get("LINK_MCP_SURFACE") or "slim").strip().lower()
if MCP_SURFACE not in {"full", "slim"}:
    print(
        f"[link-mcp] Invalid surface {MCP_SURFACE!r}. Use --surface full or --surface slim.",
        file=sys.stderr,
    )
    sys.exit(2)

if not WIKI_DIR.exists():
    print(
        f"[link-mcp] Wiki not found at {WIKI_DIR}. "
        "Initialize Link first with `lnk init` or `python3 link.py init`, "
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

def _instructions(surface: str) -> str:
    if surface == "slim":
        return (
            "Link is local personal memory for agents. Use status when "
            "connecting to Link or troubleshooting readiness. Use recall for "
            "substantive questions, session-start briefs, user preferences, "
            "project decisions, wiki search, and graph context; prefer small "
            "or micro budgets before asking for more. Before broad file reads, "
            "grep/search, or asking the user to repeat project context, call "
            "recall first and read recall_capsule before the rest of the packet. Use remember only when "
            "the user explicitly asks or approves durable memory. Use ingest "
            "when the user drops files into raw/ or asks what needs ingest. "
            "Use review for memory inbox, explain, archive, restore, forget, "
            "profile, audit, and log workflows. Use admin for less common "
            "maintenance such as backup, migrate, validate, rebuild, pages, "
            "backlinks, graph export, project seeding, captures, and advanced updates. "
            "If recall returns no useful project context and you are in a repo, "
            "use admin(action='seed_project') before broad file reads. Never "
            "silently save durable memory; propose or review first when unsure."
        )
    return (
        "Link is local personal memory for agents. This full MCP surface is "
        "for compatibility and advanced workflows; new clients should prefer "
        "--surface slim so the model sees one obvious recall tool and one "
        "obvious remember tool. Use link_status when "
        "connecting to Link or troubleshooting setup/readiness. Start with "
        "migrate_wiki if link_status reports a missing or old schema marker. "
        "Use starter_prompts when the user asks what to try after install. "
        "Use ingest_status to check pending raw files, the guided ingest plan, and the next ingest prompt. "
        "Use query_link before broad file reads, grep/search, or asking the user "
        "to repeat project context when the user asks a substantive question that may need "
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
    )


mcp = FastMCP("link", instructions=_instructions(MCP_SURFACE))


def _surface_tool(surface: str):
    def decorator(fn):
        if MCP_SURFACE == surface:
            return mcp.tool()(fn)
        return fn

    return decorator


def _full_tool():
    return _surface_tool("full")


def _slim_tool():
    return _surface_tool("slim")

# ── In-memory indexes (built on first use, invalidated by mtime) ──────
_cache: dict = {}
_cache_mtime: float = 0.0
_cache_checked_at: float = 0.0
CACHE_MTIME_CHECK_INTERVAL_SECONDS = 0.5
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
    recall_memories as _core_recall_memory_results,
    recall_abstention as _core_recall_abstention,
    recent_memories as _core_recent_memories,
    resolve_memory_page as _core_resolve_memory_page,
    set_memory_status as _core_set_memory_status,
    set_memory_visibility as _core_set_memory_visibility,
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
from link_core.consolidate import (
    build_consolidation_plan as _core_build_consolidation_plan,
)
from link_core.semantic import (
    RERANK_CANDIDATES as _CORE_RERANK_CANDIDATES,
    load_reranker as _core_load_reranker,
    rerank_blend as _core_rerank_blend,
    semantic_memory_scores as _core_semantic_memory_scores,
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
from link_core.memory_log import (
    memory_log_payload as _core_memory_log_payload,
)
from link_core.memory_wins import (
    memory_wins_payload as _core_memory_wins_payload,
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
from link_core.project_seed import (
    seed_project_context as _core_seed_project_context,
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
    build_backlinks_from_cache as _core_build_backlinks_from_cache,
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
    global _cache, _cache_mtime, _cache_checked_at
    _core_close_wiki_cache(_cache)
    _cache = {}
    _cache_mtime = 0.0
    _cache_checked_at = 0.0


def _build_cache() -> dict:
    global _cache, _cache_mtime, _cache_checked_at
    now = time.monotonic()
    if (
        _cache
        and CACHE_MTIME_CHECK_INTERVAL_SECONDS > 0
        and now - _cache_checked_at < CACHE_MTIME_CHECK_INTERVAL_SECONDS
    ):
        return _cache

    mtime = _wiki_mtime()
    _cache_checked_at = now
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


def _memory_log(limit: int = 50, include_captures: bool = True) -> dict[str, object]:
    return _core_memory_log_payload(
        WIKI_DIR,
        limit=_parse_limit(limit, default=50),
        include_captures=include_captures,
    )


def _memory_wins(limit: int = 6, project: str = "") -> dict[str, object]:
    limit = _parse_limit(limit, default=6)
    return _core_memory_wins_payload(
        WIKI_DIR,
        limit=limit,
        project=project,
        records=_memory_records(),
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
    clean_query = _clean_text_input(query, max_len=500)
    records = _memory_records()
    payload = _core_memory_brief(
        records, query=clean_query,
        limit=limit, review_command="review_memory", project=project_name,
        command_target=WIKI_DIR.parent,
        semantic_scores=_core_semantic_memory_scores(WIKI_DIR.parent, clean_query, records),
    )
    return _core_add_capture_review_to_brief(
        payload, _capture_review_summary(project=project_name), command_target=WIKI_DIR.parent
    )


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


def _recall_memory_results(
    query: str,
    limit: int = 10,
    include_archived: bool = False,
    project: str = "",
    context_path: str = "",
) -> list[dict[str, object]]:
    query = _clean_text_input(query)
    records = _memory_records()
    reranker = _core_load_reranker()
    fetch = max(limit, _CORE_RERANK_CANDIDATES) if reranker is not None else limit
    results = _core_recall_memory_results(
        records,
        query,
        limit=fetch,
        include_archived=include_archived,
        project=_resolve_project(project),
        context_path=_clean_text_input(context_path, max_len=500) or None,
        semantic_scores=_core_semantic_memory_scores(WIKI_DIR.parent, query, records),
    )
    if reranker is not None:
        results = _core_rerank_blend(query, results, limit=limit, reranker=reranker)
    return results[:limit]


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
    visibility: str = "",
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
        visibility=_clean_text_input(visibility).lower(),
        tags=tags,
    )
    result = _write_mcp_memory_page(
        str(memory_args["text"]),
        title=str(memory_args["title"]),
        memory_type=str(memory_args["memory_type"]),
        scope=str(memory_args["scope"]),
        visibility=str(memory_args["visibility"] or ""),
        tags=memory_args["tags"] if isinstance(memory_args["tags"], str) else "",
        source=str(memory_args["source"]),
        allow_duplicate=allow_duplicate,
        allow_conflict=allow_conflict,
        project=str(memory_args["project"]),
        trigger=str(memory_args.get("trigger") or ""),
        context=str(memory_args.get("context") or ""),
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


def _set_memory_visibility(identifier: str, visibility: str) -> dict[str, object]:
    result = _core_set_memory_visibility(
        WIKI_DIR,
        _clean_text_input(identifier, max_len=300),
        _clean_text_input(visibility, max_len=40),
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


def _write_mcp_memory_page(
    text: str, title: str = "", memory_type: str = "note",
    scope: str = "user", tags: str = "", source: str = "mcp",
    allow_duplicate: bool = False, allow_conflict: bool = False, project: str = "",
    visibility: str = "", review_after: str = "", expires_at: str = "", trigger: str = "",
    applies_when: str = "", supersedes: str = "", context: str = "",
) -> dict[str, object]:
    clean_text = _required_text_input(text, "memory text required", max_len=4000)
    memory_type, scope = _memory_type_scope(memory_type, scope)
    options = _memory_mutation_options(project)

    result = _core_write_memory_page(
        WIKI_DIR, clean_text, title=_clean_text_input(title),
        memory_type=memory_type, scope=scope,
        tags=_clean_text_input(tags, max_len=500), source=_clean_text_input(source, max_len=500),
        visibility=_clean_text_input(visibility, max_len=40) or None,
        review_after=_clean_text_input(review_after, max_len=40) or None,
        expires_at=_clean_text_input(expires_at, max_len=40) or None,
        trigger=_clean_text_input(trigger, max_len=200) or None,
        applies_when=_clean_text_input(applies_when, max_len=200) or None,
        supersedes=_clean_text_input(supersedes, max_len=200) or None,
        context=_clean_text_input(context, max_len=600) or None,
        allow_duplicate=allow_duplicate, allow_conflict=allow_conflict,
        **options,
    )
    if result.get("created"):
        _clear_cache()
    return result


# ── MCP resources and prompts ─────────────────────────────────────────

@mcp.resource(
    "link://instructions",
    name="Link agent instructions",
    description="Short, portable instructions for using Link memory safely in any MCP client.",
    mime_type="text/markdown",
)
def link_instructions_resource() -> str:
    return (
        "# Link Agent Instructions\n\n"
        "Use Link as local, source-backed agent memory.\n\n"
        "1. If readiness is unknown, call `status(include_validation=true)`.\n"
        "2. At the first substantive turn of a session, call `recall(query=\"\", mode=\"brief\", limit=6)`.\n"
        "3. Before broad file reads or asking the user to repeat durable context, call "
        "`recall(query=\"<task>\", budget=\"micro\")` and read `recall_capsule` first.\n"
        "4. Use `ingest(action=\"status\")` when the user adds files to `raw/`.\n"
        "5. Use `remember` only when the user explicitly asks or approves durable memory.\n"
        "6. At session end, use `admin(action=\"session_end\", arguments=\"{...}\")` or `capture_session` "
        "to save proposal-only notes for user review.\n"
        "7. Use `review` for inbox, explain, archive, restore, forget, profile, audit, and log workflows.\n"
        "8. If a brief reports a memory backlog, offer the user a short consolidation pass: "
        "`review(action=\"consolidate\")` returns a read-only plan; apply its accept/discard actions only "
        "after the user approves each one.\n"
        "9. Use `admin` only for maintenance, graph/context expansion, pages, backups, migrations, and captures.\n\n"
        "If Link session hooks are installed for this agent, the startup brief is injected automatically — "
        "skip step 2 and go straight to bounded task recall.\n"
        "Recalled memories carry a `match` field: treat `semantic` matches (paraphrase similarity, capped "
        "confidence) as hints to verify, not facts to act on.\n"
        "Recall results include an `abstention` verdict: when `abstention.recommended` is true, the memory "
        "has nothing reliable on this — tell the user so instead of answering from a weak match. Saying "
        "\"my memory doesn't cover that\" is correct behavior, not failure.\n"
        "When a new memory contradicts an existing one, prefer remember(..., supersedes=\"<old-name>\") "
        "with user approval: the old memory is archived with lineage instead of coexisting.\n"
        "Memories may carry an `applicability` label: `out_of_context` means the memory's declared "
        "conditions do not fit here — do not apply it without asking. Scope situational memories with "
        "`applies_when` (project:/path:/task: conditions).\n"
        "After a notable multi-step task, offer to save a reusable recipe: propose a `procedure` memory "
        "with a short `trigger` phrase, and save only after approval. Approved procedures return from "
        "recall with their steps.\n\n"
        "Never silently save durable memory. Prefer reviewed memories and source-backed wiki pages, and cite "
        "provenance when explaining why Link knows something.\n"
    )


@mcp.resource(
    "link://health",
    name="Link health",
    description="Current Link readiness, validation, schema, and safe next actions.",
    mime_type="application/json",
)
def link_health_resource() -> str:
    return json.dumps(_link_status(include_validation=True), ensure_ascii=False)


@mcp.resource(
    "link://brief",
    name="Link memory brief",
    description="Startup memory brief with relevant user/project memory and review guidance.",
    mime_type="application/json",
)
def link_brief_resource() -> str:
    return json.dumps(_memory_brief(query="", limit=6), ensure_ascii=False)


@mcp.resource(
    "link://profile",
    name="Link memory profile",
    description="Summary of what Link remembers by type, scope, status, tags, and recency.",
    mime_type="application/json",
)
def link_profile_resource() -> str:
    return json.dumps(_memory_profile(limit=10), ensure_ascii=False)


@mcp.resource(
    "link://project",
    name="Link project prompts",
    description="First-run prompts and checks for the configured Link project/wiki.",
    mime_type="application/json",
)
def link_project_resource() -> str:
    project = _core_default_project_for_target(WIKI_DIR.parent)
    return json.dumps(_starter_prompts(project=project), ensure_ascii=False)


@mcp.prompt(
    name="link_start",
    title="Link: start a session",
    description="Begin work with Link's safe readiness and recall loop.",
)
def link_start_prompt(task: str = "") -> str:
    task_text = task.strip() or "<current task>"
    return (
        "Start this session with Link. If readiness is unknown, call status(include_validation=true). "
        "Then call recall(query='', mode='brief', limit=6) once to prime local memory. "
        f"If {task_text!r} may depend on user preferences, project decisions, or prior context, call "
        f"recall(query={task_text!r}, budget='micro') and read recall_capsule before broad file reads. "
        "If recall has no useful project context and you know the project root, call "
        "admin(action='seed_project', arguments='{\"project_root\":\"/absolute/project/path\",\"limit\":12}') once, "
        "then retry recall with a small budget. "
        "Do not write durable memory unless the user explicitly asks or approves it."
    )


@mcp.prompt(
    name="link_brief",
    title="Link: brief before work",
    description="Prime the agent with local Link memory before a task.",
)
def link_brief_prompt(task: str = "") -> str:
    task_text = task.strip() or "<current task>"
    return (
        "Before answering or coding, get compact local context from Link. "
        f"Use recall(query={task_text!r}, budget='small') first. "
        "Treat review warnings as provisional and ask before writing durable memory."
    )


@mcp.prompt(
    name="link_remember",
    title="Link: remember explicit context",
    description="Save only user-approved durable memory.",
)
def link_remember_prompt(memory: str = "") -> str:
    memory_text = memory.strip() or "<memory the user explicitly approved>"
    return (
        "Save this only if the user asked Link to remember it. "
        f"Use remember(text={memory_text!r}) and handle duplicate/conflict responses by updating or reviewing existing memory."
    )


@mcp.prompt(
    name="link_session_end",
    title="Link: end a session",
    description="Capture session notes as proposal-only memory candidates.",
)
def link_session_end_prompt(summary: str = "") -> str:
    summary_text = summary.strip() or "<short session summary or transcript>"
    return (
        "End this session with Link without silently saving durable memory. "
        f"Use admin(action='session_end', arguments='{{\"text\": {json.dumps(summary_text)}, \"limit\": 3}}') "
        "or capture_session with the session notes. Show the returned proposals to the user and only call "
        "remember after the user approves a proposal."
    )


@mcp.prompt(
    name="link_ingest",
    title="Link: ingest raw sources",
    description="Start the guided raw-source ingest workflow.",
)
def link_ingest_prompt(path: str = "") -> str:
    target = path.strip() or "raw/<file>"
    return (
        f"Use ingest(action='status') first, then follow the guided plan for {target}. "
        "If Link reports secret warnings or unreadable files, stop and ask the user to fix or redact them. "
        "After source edits, rebuild indexes and validate before saying ingest is complete."
    )


@mcp.prompt(
    name="link_review",
    title="Link: review memory",
    description="Inspect pending memory review and explain/archive/update safely.",
)
def link_review_prompt(topic: str = "") -> str:
    focus = topic.strip() or "pending memory"
    return (
        f"Use review(action='inbox') to find review work related to {focus}. "
        "Use review(action='explain', identifier='<memory>') before trusting surprising memory. "
        "Archive stale or wrong memory; forget only after explicit user confirmation."
    )


def _admin_arguments(arguments: str) -> dict[str, object]:
    text = _clean_text_input(arguments, max_len=4000) if isinstance(arguments, str) else ""
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"arguments must be a JSON object string: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("arguments must be a JSON object string")
    return payload


def _bool_arg(payload: dict[str, object], name: str, default: bool = False) -> bool:
    value = payload.get(name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _int_arg(payload: dict[str, object], name: str, default: int = 0) -> int:
    try:
        return int(payload.get(name, default))
    except (TypeError, ValueError):
        return default


def _str_arg(payload: dict[str, object], name: str, default: str = "") -> str:
    value = payload.get(name, default)
    return _clean_text_input(value, max_len=4000)


# ── Slim MCP surface ──────────────────────────────────────────────────

@_slim_tool()
def status(include_validation: bool = False) -> str:
    """Check Link readiness and safe next actions.

    Use this first when connecting, troubleshooting, or deciding whether Link
    can be trusted for the current task. It reports schema state, memory/page
    counts, optional validation, interrupted operations, and recommended next
    actions.
    """
    return json.dumps(_link_status(include_validation=include_validation), ensure_ascii=False)


@_slim_tool()
def recall(
    query: str = "",
    budget: str = "small",
    project: str = "",
    mode: str = "auto",
    limit: int = 6,
    context_path: str = "",
) -> str:
    """Retrieve local memory/wiki context through one obvious read tool.

    Use this before substantive answers, coding, planning, or personalized
    work. mode=auto returns a startup memory brief when query is empty and an
    answer-ready query packet when query is present. mode=brief returns the
    memory brief; mode=memory returns focused memory-only recall.
    Pass context_path (the session's working directory) so memories fenced
    with applies_when path: conditions can match; without it they are
    honestly demoted as out_of_context.
    """
    clean_query = _clean_text_input(query, max_len=MAX_TEXT_INPUT)
    clean_mode = (_clean_text_input(mode, max_len=40) or "auto").lower().replace("-", "_")
    clean_budget = (_clean_text_input(budget, max_len=40) or "medium").lower()
    clean_project = _resolve_project(project)
    parsed_limit = _parse_limit(limit, default=6, max_limit=20)

    if clean_mode == "brief" or (clean_mode == "auto" and not clean_query):
        return json.dumps({
            "surface": "slim",
            "tool": "recall",
            "mode": "brief",
            "brief": _memory_brief(query=clean_query, limit=parsed_limit, project=clean_project),
        }, ensure_ascii=False)

    if clean_mode == "memory":
        if not clean_query:
            return json.dumps({"surface": "slim", "tool": "recall", "error": "query required for memory mode"})
        memories = _recall_memory_results(
            clean_query, limit=parsed_limit, project=clean_project, context_path=context_path
        )
        return json.dumps({
            "surface": "slim",
            "tool": "recall",
            "mode": "memory",
            "query": clean_query,
            "project": clean_project,
            "count": len(memories),
            "abstention": _core_recall_abstention(memories),
            "memories": memories,
        }, ensure_ascii=False)

    if not clean_query:
        return json.dumps({"surface": "slim", "tool": "recall", "error": "query required"})
    payload = _query_link(query=clean_query, budget=clean_budget, project=clean_project)
    payload["surface"] = "slim"
    payload["tool"] = "recall"
    payload["mode"] = "query"
    return json.dumps(payload, ensure_ascii=False)


@_slim_tool()
def remember(
    text: str,
    title: str = "",
    memory_type: str = "note",
    scope: str = "user",
    tags: str = "",
    source: str = "mcp",
    project: str = "",
    visibility: str = "",
    review_after: str = "",
    expires_at: str = "",
    trigger: str = "",
    applies_when: str = "",
    supersedes: str = "",
    context: str = "",
    allow_duplicate: bool = False,
    allow_conflict: bool = False,
) -> str:
    """Save explicit user-approved memory.

    Use only when the user asks Link to remember something or approves a memory
    proposal. Duplicate and conflict candidates should be resolved by updating,
    reviewing, or archiving existing memory instead of forcing a new page.
    Use memory_type="procedure" with a short `trigger` phrase for reusable
    how-to memory (steps for a recurring task) the user has approved.
    context: optional surrounding text from the memory's origin (neighboring conversation turns); it helps recall find the memory later but is never part of the claim.
    Field rule: trigger helps recall FIND a recipe; applies_when FENCES a
    memory to a context; scope/project/visibility say whose memory it is;
    supersedes REPLACES an old claim with lineage. When unsure, omit them.
    """
    try:
        result = _write_mcp_memory_page(
            text,
            title=title,
            memory_type=memory_type,
            scope=scope,
            tags=tags,
            source=source,
            allow_duplicate=allow_duplicate,
            allow_conflict=allow_conflict,
            project=project,
            visibility=visibility,
            review_after=review_after,
            expires_at=expires_at,
            trigger=trigger,
            applies_when=applies_when,
            supersedes=supersedes,
            context=context,
        )
    except ValueError as exc:
        return json.dumps({"surface": "slim", "tool": "remember", "created": False, "error": str(exc)})
    result["surface"] = "slim"
    result["tool"] = "remember"
    return json.dumps(result, ensure_ascii=False)


@_slim_tool()
def ingest(action: str = "status", strict: bool = False) -> str:
    """Inspect or validate raw-source ingest state.

    action=status returns the guided ingest plan. action=validate runs the
    validation gate. action=rebuild refreshes index and backlinks after source
    edits. Do not read secret-flagged raw files.
    """
    clean_action = (_clean_text_input(action, max_len=80) or "status").lower().replace("-", "_")
    if clean_action in {"status", "plan"}:
        payload = _ingest_status()
        payload["surface"] = "slim"
        payload["tool"] = "ingest"
        return json.dumps(payload, ensure_ascii=False)
    if clean_action == "validate":
        payload = _validate_wiki(strict=strict)
        payload["surface"] = "slim"
        payload["tool"] = "ingest"
        return json.dumps(payload, ensure_ascii=False)
    if clean_action == "rebuild":
        cache = _core_build_wiki_cache(WIKI_DIR, use_persistent_cache=False)
        try:
            index_result = _core_rebuild_index(WIKI_DIR, cache=cache)
            backlinks = _core_build_backlinks_from_cache(cache)
            _core_atomic_write_json(WIKI_DIR / "_backlinks.json", backlinks)
        finally:
            _core_close_wiki_cache(cache)
        _clear_cache()
        return json.dumps({
            "surface": "slim",
            "tool": "ingest",
            "rebuilt": True,
            "index": index_result,
            "backlink_pages": len(backlinks.get("backlinks", {})),
        }, ensure_ascii=False)
    return json.dumps({
        "surface": "slim",
        "tool": "ingest",
        "error": f"unsupported action: {clean_action}",
        "supported_actions": ["status", "validate", "rebuild"],
    })


@_slim_tool()
def review(
    action: str = "inbox",
    identifier: str = "",
    note: str = "",
    reason: str = "",
    confirm: bool = False,
    project: str = "",
    limit: int = 20,
    include_archived: bool = False,
) -> str:
    """Review, explain, and manage local memory lifecycle.

    Supported actions: inbox, audit, profile, log, wins, explain, reviewed,
    archive, restore, forget, consolidate. Prefer archive over forget unless
    the user asks for permanent deletion. Use consolidate for a read-only plan
    when the capture or review backlog builds up; apply its actions only after
    the user approves each one.
    """
    clean_action = (_clean_text_input(action, max_len=80) or "inbox").lower().replace("-", "_")
    parsed_limit = _parse_limit(limit, default=20, max_limit=50)
    clean_project = _resolve_project(project)
    try:
        if clean_action == "inbox":
            payload = _memory_inbox(limit=parsed_limit, include_archived=include_archived, project=clean_project)
        elif clean_action == "audit":
            payload = _memory_audit(limit=parsed_limit, project=clean_project)
        elif clean_action == "profile":
            payload = _memory_profile(limit=parsed_limit, project=clean_project)
        elif clean_action == "log":
            payload = _memory_log(limit=parsed_limit)
        elif clean_action == "wins":
            payload = _memory_wins(limit=parsed_limit, project=clean_project)
        elif clean_action == "explain":
            payload = _memory_explanation(identifier)
        elif clean_action in {"reviewed", "review", "mark_reviewed"}:
            payload = _mark_memory_reviewed(identifier, note=note)
        elif clean_action == "archive":
            payload = _set_memory_status(identifier, "archived", reason=reason)
        elif clean_action == "restore":
            payload = _set_memory_status(identifier, "active")
        elif clean_action == "forget":
            payload = _forget_memory(identifier, confirm=confirm)
        elif clean_action == "consolidate":
            payload = _core_build_consolidation_plan(
                captures_payload=_capture_inbox(limit=parsed_limit, project=clean_project),
                inbox_payload=_memory_inbox(limit=parsed_limit, project=clean_project),
                command_target=WIKI_DIR.parent,
                project=clean_project,
            )
        else:
            return json.dumps({
                "surface": "slim",
                "tool": "review",
                "error": f"unsupported action: {clean_action}",
                "supported_actions": ["inbox", "audit", "profile", "log", "wins", "explain", "reviewed", "archive", "restore", "forget", "consolidate"],
            })
    except ValueError as exc:
        return json.dumps({"surface": "slim", "tool": "review", "updated": False, "error": str(exc)})
    payload["surface"] = "slim"
    payload["tool"] = "review"
    payload["action"] = clean_action
    return json.dumps(payload, ensure_ascii=False)


@_slim_tool()
def admin(action: str, arguments: str = "{}") -> str:
    """Escape hatch for less common Link maintenance and advanced workflows.

    Pass action plus a JSON object string in arguments. Common actions include:
    backup, migrate, validate, operations, search, context, pages, backlinks,
    graph_summary, graph, rebuild_index, rebuild_backlinks, seed_project, propose_memories,
    capture_session, session_end, capture_inbox, accept_capture, redact_capture,
    delete_capture, update_memory, and set_visibility.
    """
    clean_action = (_clean_text_input(action, max_len=100) or "").lower().replace("-", "_")
    try:
        payload = _admin_arguments(arguments)
        if clean_action in {"status", "health"}:
            return status(include_validation=_bool_arg(payload, "include_validation", False))
        if clean_action in {"backup", "backup_wiki"}:
            return backup_wiki(
                label=_str_arg(payload, "label", "mcp"),
                include_raw=_bool_arg(payload, "include_raw", False),
                list_only=_bool_arg(payload, "list_only", False),
            )
        if clean_action in {"migrate", "migrate_wiki"}:
            return migrate_wiki()
        if clean_action in {"validate", "validate_wiki"}:
            return validate_wiki(strict=_bool_arg(payload, "strict", False))
        if clean_action in {"operations", "link_operations"}:
            return link_operations(limit=_int_arg(payload, "limit", 20))
        if clean_action in {"prompts", "starter_prompts"}:
            return starter_prompts(project=_str_arg(payload, "project"))
        if clean_action in {"search", "search_wiki"}:
            return search_wiki(_str_arg(payload, "query"), limit=_int_arg(payload, "limit", 20))
        if clean_action in {"context", "get_context"}:
            return get_context(_str_arg(payload, "topic"))
        if clean_action in {"pages", "get_pages"}:
            return get_pages(
                category=_str_arg(payload, "category"),
                page_type=_str_arg(payload, "page_type"),
                maturity=_str_arg(payload, "maturity"),
                limit=_int_arg(payload, "limit", 100),
                offset=_int_arg(payload, "offset", 0),
                include_all=_bool_arg(payload, "include_all", False),
            )
        if clean_action in {"backlinks", "get_backlinks"}:
            return get_backlinks(
                _str_arg(payload, "page_name"),
                limit=_int_arg(payload, "limit", 100),
                offset=_int_arg(payload, "offset", 0),
                include_all=_bool_arg(payload, "include_all", False),
            )
        if clean_action in {"graph_summary", "get_graph_summary"}:
            return get_graph_summary(
                topic=_str_arg(payload, "topic"),
                limit=_int_arg(payload, "limit", 40),
                depth=_int_arg(payload, "depth", 1),
                max_edges=_int_arg(payload, "max_edges", 120),
            )
        if clean_action in {"graph", "get_graph"}:
            return get_graph()
        if clean_action == "rebuild_index":
            return rebuild_index()
        if clean_action == "rebuild_backlinks":
            return rebuild_backlinks()
        if clean_action in {"seed_project", "project_seed"}:
            project_root = Path(_str_arg(payload, "project_root") or _str_arg(payload, "path") or ".")
            seed_payload = _core_seed_project_context(
                WIKI_DIR.parent,
                project_root,
                project_name=_str_arg(payload, "project"),
                overwrite=_bool_arg(payload, "overwrite", False),
                dry_run=_bool_arg(payload, "dry_run", False),
                limit=_int_arg(payload, "limit", 12),
                include_git_log=_bool_arg(payload, "include_git_log", True),
                git_log_limit=_int_arg(payload, "git_log_limit", 20),
            )
            seed_payload["surface"] = "slim"
            seed_payload["tool"] = "admin"
            seed_payload["action"] = clean_action
            _clear_cache()
            return json.dumps(seed_payload, ensure_ascii=False)
        if clean_action == "propose_memories":
            return propose_memories(
                _str_arg(payload, "text"),
                source=_str_arg(payload, "source", "mcp"),
                limit=_int_arg(payload, "limit", 10),
                project=_str_arg(payload, "project"),
            )
        if clean_action in {"capture_session", "session_end"}:
            return capture_session(
                _str_arg(payload, "text"),
                title=_str_arg(payload, "title"),
                source=_str_arg(payload, "source", clean_action),
                limit=_int_arg(payload, "limit", 3 if clean_action == "session_end" else 10),
                project=_str_arg(payload, "project"),
            )
        if clean_action == "capture_inbox":
            return capture_inbox(limit=_int_arg(payload, "limit", 20), project=_str_arg(payload, "project"))
        if clean_action == "accept_capture":
            return accept_capture(
                _str_arg(payload, "capture"),
                index=_int_arg(payload, "index", 1),
                title=_str_arg(payload, "title"),
                memory_type=_str_arg(payload, "memory_type"),
                scope=_str_arg(payload, "scope"),
                visibility=_str_arg(payload, "visibility"),
                tags=_str_arg(payload, "tags"),
                project=_str_arg(payload, "project"),
                allow_duplicate=_bool_arg(payload, "allow_duplicate", False),
                allow_conflict=_bool_arg(payload, "allow_conflict", False),
            )
        if clean_action == "redact_capture":
            return redact_capture(_str_arg(payload, "capture"), replacement=_str_arg(payload, "replacement", "[redacted-secret]"))
        if clean_action == "delete_capture":
            return delete_capture(_str_arg(payload, "capture"), confirm=_bool_arg(payload, "confirm", False))
        if clean_action == "update_memory":
            return update_memory(
                _str_arg(payload, "identifier"),
                _str_arg(payload, "memory"),
                source=_str_arg(payload, "source", "mcp"),
                allow_conflict=_bool_arg(payload, "allow_conflict", False),
                project=_str_arg(payload, "project"),
            )
        if clean_action in {"set_visibility", "set_memory_visibility"}:
            return set_memory_visibility(_str_arg(payload, "identifier"), _str_arg(payload, "visibility"))
    except ValueError as exc:
        return json.dumps({"surface": "slim", "tool": "admin", "ok": False, "action": clean_action, "error": str(exc)})
    return json.dumps({
        "surface": "slim",
        "tool": "admin",
        "ok": False,
        "action": clean_action,
        "error": "unsupported action",
        "supported_actions": [
            "backup", "migrate", "validate", "operations", "prompts",
            "search", "context", "pages", "backlinks", "graph_summary", "graph",
            "rebuild_index", "rebuild_backlinks", "seed_project", "propose_memories",
            "capture_session", "session_end", "capture_inbox", "accept_capture", "redact_capture",
            "delete_capture", "update_memory", "set_visibility",
        ],
    })


# ── Full MCP tool surface ─────────────────────────────────────────────

@_full_tool()
def query_link(query: str, budget: str = "medium", project: str = "") -> str:
    """Build a compact answer-ready Link context packet.

    Use this before answering substantive questions that may need local memory,
    wiki knowledge, or both. It returns budgeted memories, ranked wiki results,
    graph-neighborhood context, and why each item was selected so the agent does
    not waste context by reading the whole wiki.
    budget: micro, small, medium, or large.
    """
    return json.dumps(_query_link(query=query, budget=budget, project=project), ensure_ascii=False)


@_full_tool()
def link_status(include_validation: bool = False) -> str:
    """Return a compact Link readiness summary.

    Use this when connecting to Link or troubleshooting setup. It reports the
    wiki path, package version, page/memory counts, missing required paths,
    optional validation summary, and safe next actions.
    """
    return json.dumps(_link_status(include_validation=include_validation), ensure_ascii=False)


@_full_tool()
def link_operations(limit: int = 20) -> str:
    """Inspect interrupted or active local Link write operations.

    Use this when link_status reports pending, failed, or stale operations.
    It returns operation markers with timestamps, affected paths, status, and
    safe next actions so agents can diagnose interrupted writes before repair.
    """
    return json.dumps(_link_operations(limit=limit), ensure_ascii=False)


@_full_tool()
def starter_prompts(project: str = "") -> str:
    """Return first-run Link prompts and local checks.

    Use this when a user asks what to try after installing Link, or when an
    agent needs concise natural-language prompts for readiness, brief, remember,
    query, ingest, and proposal workflows.
    """
    return json.dumps(_starter_prompts(project=project), ensure_ascii=False)


@_full_tool()
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


@_full_tool()
def memory_brief(query: str = "", limit: int = 6, project: str = "") -> str:
    """Prime the agent with local memory before answering or coding.

    Call this at the start of a session or before a user task that may depend
    on preferences, project decisions, or personal context. It returns profile
    counts, relevant memories for the query, review warnings, and rules for
    safe memory use.
    """
    limit = _parse_limit(limit, default=6, max_limit=20)
    return json.dumps(_memory_brief(query=query, limit=limit, project=project), ensure_ascii=False)


@_full_tool()
def validate_wiki(strict: bool = False) -> str:
    """Validate agent-generated wiki pages after ingest or large edits.

    Call rebuild_backlinks first, then validate_wiki before reporting ingest
    complete. The response checks required frontmatter, directory/type
    alignment, required sections, dead wikilinks, and backlink freshness.
    strict=true also fails on warnings such as missing TLDR/Query summaries.
    """
    return json.dumps(_validate_wiki(strict=strict), ensure_ascii=False)


@_full_tool()
def migrate_wiki() -> str:
    """Apply safe Link wiki schema migrations.

    Use this when link_status reports a missing or old schema marker. The
    operation is idempotent and only creates missing canonical wiki directories
    plus the local schema marker; it does not rewrite user pages.
    """
    return json.dumps(_migrate_wiki(), ensure_ascii=False)


@_full_tool()
def ingest_status() -> str:
    """Return raw source ingest state and the next safe action.

    Use this when the user asks to ingest, after they drop files into raw/, or
    when you need the exact next agent prompt and validation commands.
    """
    return json.dumps(_ingest_status(), ensure_ascii=False)


@_full_tool()
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


@_full_tool()
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
    memories = _recall_memory_results(query, limit=limit, include_archived=include_archived, project=project_name)
    return json.dumps({
        "query": query,
        "count": len(memories),
        "include_archived": include_archived,
        "project": project_name,
        "abstention": _core_recall_abstention(memories),
        "memories": memories,
    }, ensure_ascii=False)


@_full_tool()
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


@_full_tool()
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


@_full_tool()
def capture_inbox(limit: int = 20, project: str = "") -> str:
    """List saved raw session captures without changing them.

    Returns saved captures, secret-warning labels, redacted snippets, and the
    next MCP tool calls for accepting, redacting, or deleting a capture.
    """
    limit = _parse_limit(limit, default=20, max_limit=50)
    return json.dumps(_capture_inbox(limit=limit, project=project), ensure_ascii=False)


@_full_tool()
def accept_capture(
    capture: str,
    index: int = 1,
    title: str = "",
    memory_type: str = "",
    scope: str = "",
    visibility: str = "",
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
            visibility=visibility,
            tags=tags,
            project=project,
            allow_duplicate=allow_duplicate,
            allow_conflict=allow_conflict,
        )
    except ValueError as exc:
        return json.dumps({"accepted": False, "error": str(exc)})
    return json.dumps(result, ensure_ascii=False)


@_full_tool()
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


@_full_tool()
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


@_full_tool()
def memory_profile(limit: int = 10, project: str = "") -> str:
    """Summarize what Link currently remembers.

    Use this to inspect the local memory profile before doing personalized work.
    Returns counts by type/scope/status, top tags, recent memories, and focused
    lists for preferences, decisions, and project context.
    """
    limit = _parse_limit(limit, default=10)
    return json.dumps(_memory_profile(limit=limit, project=project), ensure_ascii=False)


@_full_tool()
def memory_audit(limit: int = 10, project: str = "") -> str:
    """Audit local memory health, review backlog, and raw capture state.

    Use this when the user asks what Link knows, what needs attention, or
    whether local agent memory is ready for use.
    """
    return json.dumps(_memory_audit(limit=limit, project=project), ensure_ascii=False)


@_full_tool()
def memory_inbox(limit: int = 20, include_archived: bool = False, project: str = "") -> str:
    """List memories that need user review.

    Use this to surface pending, stale, invalid, or underspecified memories for
    human confirmation. Archived memories are excluded unless include_archived
    is true. Pass project to include broad user/global memory plus that
    project's scoped memories while excluding other explicit projects.
    """
    limit = _parse_limit(limit, default=20)
    return json.dumps(_memory_inbox(limit=limit, include_archived=include_archived, project=project), ensure_ascii=False)


@_full_tool()
def memory_log(limit: int = 50, include_captures: bool = True) -> str:
    """List recent memory lifecycle changes.

    Use this when the user asks what Link remembered, updated, reviewed,
    archived, restored, forgot, or accepted from captures recently. The result
    is metadata from wiki/log.md and does not include raw source or memory
    bodies.
    """
    return json.dumps(_memory_log(limit=limit, include_captures=include_captures), ensure_ascii=False)


@_full_tool()
def memory_wins(limit: int = 6, project: str = "") -> str:
    """Summarize local proof signals for Link memory value.

    Use this when the user asks whether Link is useful, what memory value has
    accumulated, or how to demonstrate the local memory loop. The result is
    based on local wiki metadata only; Link does not track telemetry.
    """
    return json.dumps(_memory_wins(limit=limit, project=project), ensure_ascii=False)


@_full_tool()
def review_memory(identifier: str, note: str = "") -> str:
    """Mark a memory as reviewed after user confirmation."""
    try:
        result = _mark_memory_reviewed(identifier, note=note)
    except ValueError as exc:
        return json.dumps({"updated": False, "error": str(exc)})
    return json.dumps(result, ensure_ascii=False)


@_full_tool()
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


@_full_tool()
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


@_full_tool()
def set_memory_visibility(identifier: str, visibility: str) -> str:
    """Change a memory's sharing visibility.

    Use this after explicit user approval when a memory should move between
    private, project, and team visibility. This updates frontmatter and logs the
    visibility change; it does not expose raw sources or memory bodies in logs.
    """
    try:
        result = _set_memory_visibility(identifier, visibility)
    except ValueError as exc:
        return json.dumps({"updated": False, "error": str(exc)})
    return json.dumps(result, ensure_ascii=False)


@_full_tool()
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


@_full_tool()
def restore_memory(identifier: str) -> str:
    """Restore an archived memory to active status."""
    try:
        result = _set_memory_status(identifier, "active")
    except ValueError as exc:
        return json.dumps({"updated": False, "error": str(exc)})
    return json.dumps(result, ensure_ascii=False)


@_full_tool()
def forget_memory(identifier: str, confirm: bool = False) -> str:
    """Permanently delete a memory after explicit user confirmation.

    Prefer archive_memory for reversible cleanup. Use forget_memory only when
    the user asks Link to permanently forget a memory; the tool refuses to
    delete unless confirm is true and never logs the memory body.
    """
    return json.dumps(_forget_memory(identifier, confirm=confirm), ensure_ascii=False)


@_full_tool()
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
    visibility: str = "",
    review_after: str = "",
    expires_at: str = "",
    trigger: str = "",
    context: str = "",
) -> str:
    """Save a local agent memory as a Markdown page.

    Use only when the user explicitly asks you to remember something. The memory
    is written under wiki/memories/, indexed, logged, and kept local. Strong
    duplicates are refused unless allow_duplicate is true.
    Potential conflicts are refused unless allow_conflict is true.
    memory_type: preference, decision, project, fact, note, or procedure.
    scope: user, project, or global.
    visibility: private, project, or team. Defaults to private for user/global and project for project-scoped memories.
    project: optional project key for project-scoped memories.
    tags: optional comma-separated tags.
    review_after: optional YYYY-MM-DD date when this memory should be checked again.
    context: optional surrounding origin text (max 600 chars); aids recall, never part of the claim.
    expires_at: optional YYYY-MM-DD date when this memory should leave default recall.
    trigger: optional short phrase describing when this memory applies (recommended for procedure).
    """
    try:
        result = _write_mcp_memory_page(
            memory,
            title=title,
            memory_type=memory_type,
            scope=scope,
            tags=tags,
            source=source,
            allow_duplicate=allow_duplicate,
            allow_conflict=allow_conflict,
            project=project,
            visibility=visibility,
            review_after=review_after,
            expires_at=expires_at,
            trigger=trigger,
            context=context,
        )
    except ValueError as exc:
        return json.dumps({"created": False, "error": str(exc)})
    return json.dumps(result, ensure_ascii=False)


@_full_tool()
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


@_full_tool()
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


@_full_tool()
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


@_full_tool()
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


@_full_tool()
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


@_full_tool()
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


@_full_tool()
def rebuild_backlinks() -> str:
    """Rebuild the wiki's backlink index from the parsed wiki cache.

    Call this after ingesting new sources or running lint to ensure
    the graph index is up to date. Updates wiki/_backlinks.json with
    both reverse links (backlinks) and forward links.
    """
    try:
        cache = _core_build_wiki_cache(WIKI_DIR, use_persistent_cache=False)
        try:
            result = _core_build_backlinks_from_cache(cache)
        finally:
            _core_close_wiki_cache(cache)
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
