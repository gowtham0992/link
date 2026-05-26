#!/usr/bin/env python3
"""Link — local wiki viewer. python serve.py → http://127.0.0.1:3000"""
from __future__ import annotations

import errno
import html
import http.server
import json
import re
import socketserver
import sys
import threading
import time
import urllib.parse
from collections import Counter
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_BUNDLED_CORE = ROOT / "mcp_package"
if (_BUNDLED_CORE / "link_core").exists():
    sys.path.insert(0, str(_BUNDLED_CORE))

from link_core.memory import (
    add_capture_review_to_brief as _core_add_capture_review_to_brief,
    count_values as _core_count_values,
    is_active_memory as _core_is_active_memory,
    memory_action_hints as _core_memory_action_hints,
    memory_brief as _core_memory_brief,
    memory_explanation as _core_memory_explanation,
    memory_inbox as _core_memory_inbox,
    memory_profile as _core_memory_profile,
    memory_audit_report as _core_memory_audit_report,
    memory_audit_next_actions as _core_memory_audit_next_actions,
    memory_records as _core_memory_records,
    memory_review_issues as _core_memory_review_issues,
    memory_duplicate_candidates as _core_memory_duplicate_candidates,
    memory_visible_for_project as _core_memory_visible_for_project,
    mark_memory_reviewed as _core_mark_memory_reviewed,
    normalize_project as _core_normalize_project,
    propose_memories_from_text as _core_propose_memories_from_text,
    set_memory_status as _core_set_memory_status,
    update_memory_page as _core_update_memory_page,
    write_memory_page as _core_write_memory_page,
)
from link_core.frontmatter import (
    parse_frontmatter as _parse_frontmatter,
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
from link_core.markdown import (
    markdown_to_html as _core_markdown_to_html,
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
from link_core.doctor import (
    raw_source_refs as _core_raw_source_refs,
)
from link_core.version import (
    LINK_VERSION,
)
from link_core.web_assets import CSS  # noqa: F401 - kept as serve.CSS for tests and compatibility
from link_core.web_memory import (
    memory_dashboard_next_actions as _core_memory_dashboard_next_actions,
    render_memory_card as _core_render_memory_card,
    render_memory_section as _core_render_memory_section,
)
from link_core.web_memory_pages import (
    render_brief_page as _core_render_brief_page,
    render_captures_page as _core_render_captures_page,
    render_inbox_page as _core_render_inbox_page,
    render_memory_explanation_page as _core_render_memory_explanation_page,
    render_memory_log_page as _core_render_memory_log_page,
    render_memory_audit_page as _core_render_memory_audit_page,
    render_memory_dashboard_page as _core_render_memory_dashboard_page,
    render_memory_wins_page as _core_render_memory_wins_page,
    render_profile_page as _core_render_profile_page,
)
from link_core.web_layout import (
    render_footer_html as _core_render_footer_html,
    render_header_html as _core_render_header_html,
    render_layout as _core_render_layout,
)
from link_core.web_graph import (
    GRAPH_CATEGORY_COLORS as _core_graph_category_colors,
    GRAPH_INITIAL_SUMMARY_EDGE_LIMIT as _core_graph_initial_summary_edge_limit,
    GRAPH_INITIAL_SUMMARY_NODE_LIMIT as _core_graph_initial_summary_node_limit,
    graph_category_options as _core_graph_category_options,
    graph_initial_payload as _core_graph_initial_payload,
    graph_legend_items as _core_graph_legend_items,
    graph_needs_bounded_overview as _core_graph_needs_bounded_overview,
    render_graph_empty_body as _core_render_graph_empty_body,
    render_graph_page_body as _core_render_graph_page_body,
    render_graph_script as _core_render_graph_script,
)
from link_core.web_home import (
    plural_type_label as _core_plural_type_label,
    render_home_page as _core_render_home_page,
)
from link_core.web_health import (
    render_health_page as _core_render_health_page,
)
from link_core.web_ingest import (
    render_ingest_page as _core_render_ingest_page,
)
from link_core.web_http import (
    CONTENT_SECURITY_POLICY as _core_content_security_policy,
    is_allowed_static_file as _core_is_allowed_static_file,
    is_relative_to as _core_is_relative_to,
    LocalRateLimiter as _CoreLocalRateLimiter,
    local_no_store_headers as _core_local_no_store_headers,
    local_security_headers as _core_local_security_headers,
    parse_bounded_int as _core_parse_bounded_int,
    PERMISSIONS_POLICY as _core_permissions_policy,
    resolve_raw_static_path as _core_resolve_raw_static_path,
    safe_resolve as _core_safe_resolve,
    SVG_CONTENT_SECURITY_POLICY as _core_svg_content_security_policy,
    validate_local_browser_source_headers as _core_validate_local_browser_source_headers,
    validate_local_host_header as _core_validate_local_host_header,
)
from link_core.web_proposals import (
    create_raw_source_payload as _core_create_raw_source_payload,
    proposal_source_payload as _core_proposal_source_payload,
    proposal_sources as _core_proposal_sources,
)
from link_core.web_propose import (
    render_propose_page as _core_render_propose_page,
)
from link_core.web_prompts import (
    render_prompts_page as _core_render_prompts_page,
)
from link_core.web_pages import (
    render_all_pages as _core_render_all_pages,
    render_wiki_page as _core_render_wiki_page,
)
from link_core.web_search import (
    render_search_page as _core_render_search_page,
)
from link_core.status import (
    link_status as _core_link_status,
)
from link_core.operations import (
    operation_report as _core_operation_report,
)
from link_core.capture import (
    capture_inbox as _core_capture_inbox,
    capture_records as _core_capture_records,
    capture_review_summary as _core_capture_review_summary,
    cli_capture_commands as _core_cli_capture_commands,
)
from link_core.files import (
    atomic_write_json as _core_atomic_write_json,
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
del _BUNDLED_CORE

WIKI_DIR = ROOT / "wiki"
RAW_DIR = ROOT / "raw"
PORT = 3000
API_VERSION = "1"
MAX_POST_BYTES = 64 * 1024
MAX_QUERY_TEXT = 500
MAX_PROPOSAL_SOURCE_BYTES = 64 * 1024
MAX_RAW_SOURCE_BYTES = 60 * 1024
LOCAL_ACTION_HEADER = "X-Link-Local-Action"
LOCAL_ACTION_VALUES = {"1", "true", "yes"}
MUTATION_RATE_LIMIT = 180
MUTATION_RATE_WINDOW_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 15
CONTENT_SECURITY_POLICY = _core_content_security_policy
PERMISSIONS_POLICY = _core_permissions_policy
SVG_CONTENT_SECURITY_POLICY = _core_svg_content_security_policy
PROPOSAL_SOURCE_SUFFIXES = {
    ".md",
    ".markdown",
    ".txt",
    ".text",
    ".rst",
    ".adoc",
    ".json",
    ".yaml",
    ".yml",
    ".csv",
}
RAW_STATIC_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
}

# ---------------------------------------------------------------------------
# In-memory caches — invalidated on each request by mtime check
# ---------------------------------------------------------------------------
CACHE_MTIME_CHECK_INTERVAL_SECONDS = 0.5
_pages_cache: list | None = None
_pages_cache_mtime: float = 0.0
_pages_cache_checked_at: float = 0.0
_page_index: dict[str, Path] = {}  # stem.lower() → path
_fulltext_index: dict[str, str] = {}  # stem.lower() → full text (for search)
_normalized_fulltext_index: dict[str, str] = {}  # punctuation-normalized full text
_text_words_index: dict[str, set[str]] = {}  # stem.lower() → normalized fulltext words
_meta_words_index: dict[str, set[str]] = {}  # stem.lower() → normalized metadata words
_snippet_index: dict[str, str] = {}  # stem.lower() → pre-extracted first snippet
_token_index: dict[str, set[str]] = {}  # token → set of page stems that contain it
_page_map: dict[str, dict] = {}  # stem.lower() → page dict (for O(1) lookup in search)
_meta_token_index: dict[str, set[str]] = {}  # token → stems with that token in title/alias/tag/tldr
_forward_links_index: dict[str, list[str]] = {}  # page name → canonical outbound wikilinks
_fts_index = None
_search_backend = "token-index"
_cache_read_warnings: list[dict[str, str]] = []
_cache_lock = threading.RLock()
_rate_limiter_lock = threading.Lock()
_mutation_rate_limiter = _CoreLocalRateLimiter(
    max_events=MUTATION_RATE_LIMIT,
    window_seconds=MUTATION_RATE_WINDOW_SECONDS,
)


class ThreadingLocalTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Local-only server that keeps navigation responsive during slow requests."""

    daemon_threads = True
    allow_reuse_address = True


def _invalidate_pages_cache() -> None:
    global _pages_cache, _pages_cache_mtime, _pages_cache_checked_at, _forward_links_index, _fts_index, _search_backend, _cache_read_warnings
    with _cache_lock:
        _core_close_wiki_cache({"fts_index": _fts_index})
        _pages_cache = None
        _pages_cache_mtime = 0.0
        _pages_cache_checked_at = 0.0
        _forward_links_index = {}
        _fts_index = None
        _search_backend = "token-index"
        _cache_read_warnings = []


def _wiki_mtime() -> float:
    return _core_wiki_mtime(WIKI_DIR)


def _get_all_pages(force_check: bool = False) -> list:
    global _pages_cache, _pages_cache_mtime, _pages_cache_checked_at, _page_index, _fulltext_index, _normalized_fulltext_index, _text_words_index, _meta_words_index, _snippet_index, _token_index, _page_map, _meta_token_index, _forward_links_index, _fts_index, _search_backend, _cache_read_warnings
    with _cache_lock:
        now = time.monotonic()
        if (
            _pages_cache is not None
            and not force_check
            and CACHE_MTIME_CHECK_INTERVAL_SECONDS > 0
            and now - _pages_cache_checked_at < CACHE_MTIME_CHECK_INTERVAL_SECONDS
        ):
            return _pages_cache
        mtime = _wiki_mtime()
        _pages_cache_checked_at = now
        if _pages_cache is not None and mtime == _pages_cache_mtime:
            return _pages_cache
        _core_close_wiki_cache({"fts_index": _fts_index})
        cache = _core_build_wiki_cache(WIKI_DIR)
        _pages_cache = cache["pages"]
        _pages_cache_mtime = mtime
        _page_index = cache["page_index"]
        _fulltext_index = cache["fulltext"]
        _normalized_fulltext_index = cache["normalized_fulltext"]
        _text_words_index = cache["text_words_index"]
        _meta_words_index = cache["meta_words_index"]
        _snippet_index = cache["snippet_index"]
        _token_index = cache["token_index"]
        _meta_token_index = cache["meta_token_index"]
        _page_map = cache["page_map"]
        _forward_links_index = cache.get("forward_links_index", {})
        _fts_index = cache.get("fts_index")
        _search_backend = str(cache.get("search_backend") or "token-index")
        _cache_read_warnings = cache.get("read_warnings") if isinstance(cache.get("read_warnings"), list) else []
        return _pages_cache


def _current_wiki_cache() -> dict[str, object]:
    with _cache_lock:
        _get_all_pages()
        return {
            "pages": _pages_cache or [],
            "page_index": _page_index,
            "fulltext": _fulltext_index,
            "normalized_fulltext": _normalized_fulltext_index,
            "text_words_index": _text_words_index,
            "meta_words_index": _meta_words_index,
            "snippet_index": _snippet_index,
            "token_index": _token_index,
            "meta_token_index": _meta_token_index,
            "page_map": _page_map,
            "forward_links_index": _forward_links_index,
            "fts_index": _fts_index,
            "search_backend": _search_backend,
            "read_warning_count": len(_cache_read_warnings),
            "read_warnings": _cache_read_warnings,
        }


def _find_page(name: str) -> Path | None:
    # Ensure cache is warm — _get_all_pages populates _page_index as a side effect
    _get_all_pages()
    return _page_index.get(name.strip().lower())


# Keep _all_pages as alias for API compatibility
def _all_pages() -> list:
    return _get_all_pages()


def _page_list_payload(
    category: str = "",
    page_type: str = "",
    maturity: str = "",
    limit: int = 100,
    offset: int = 0,
    include_all: bool = False,
) -> dict:
    return _core_list_pages(
        _current_wiki_cache(),
        category=category,
        page_type=page_type,
        maturity=maturity,
        limit=limit,
        offset=offset,
        include_all=include_all,
    )


def _load_backlinks_index() -> tuple[dict, str | None]:
    return _core_load_backlinks_index(WIKI_DIR / "_backlinks.json")


def _page_links_payload(
    page_name: str,
    limit: int = 100,
    offset: int = 0,
    include_all: bool = False,
) -> tuple[dict, int]:
    backlinks, error = _load_backlinks_index()
    if error:
        return {"error": error}, 500
    if not page_name.strip():
        return {"error": "page parameter required", "inbound": [], "forward": []}, 400
    return _core_page_link_summary(
        backlinks,
        page_name,
        limit=limit,
        offset=offset,
        include_all=include_all,
    ), 200


def _parse_search_limit(raw: object) -> tuple[int | None, str | None]:
    return _core_parse_bounded_int(raw, "limit", 20, 1, 50)


def _query_text(query: dict[str, list[str]], *names: str, max_len: int = MAX_QUERY_TEXT) -> str:
    for name in names:
        values = query.get(name)
        if values:
            text = _clean_text_input(values[0], max_len=max_len)
            if text:
                return text
    return ""


def _utc_timestamp() -> str:
    return _core_utc_timestamp()


def _append_log(timestamp: str, operation: str, description: str, lines: list[str]) -> None:
    _core_append_log(WIKI_DIR, timestamp, operation, description, lines)


def _page_href(name: str) -> str:
    return "/page/" + urllib.parse.quote(name.strip(), safe="")


def _graph_href(name: str, *, depth: int = 2) -> str:
    return f"/graph?focus={urllib.parse.quote(name.strip(), safe='')}&depth={depth}"


def _proposal_href(raw_path: str) -> str:
    return "/propose?source=" + urllib.parse.quote(raw_path.strip(), safe="")


def _plural_type_label(page_type: str) -> str:
    return _core_plural_type_label(page_type)


def _memory_records() -> list[dict[str, object]]:
    return _core_memory_records(WIKI_DIR, include_body=False)


def _count_values(records: list[dict[str, object]], field: str) -> dict[str, int]:
    return _core_count_values(records, field)


def _is_active_memory(record: dict[str, object]) -> bool:
    return _core_is_active_memory(record)


def _memory_review_issues(record: dict[str, object]) -> list[dict[str, str]]:
    return _core_memory_review_issues(record, review_command="review-memory")


def _project_visible_records(project: str | None = None) -> list[dict[str, object]]:
    project_name = _core_normalize_project(project)
    return [
        record
        for record in _memory_records()
        if _core_memory_visible_for_project(record, project_name)
    ]


def _ingest_status() -> dict[str, object]:
    return _core_collect_ingest_status(WIKI_DIR.parent)


def _memory_inbox(limit: int = 20, include_archived: bool = False, project: str | None = None) -> dict[str, object]:
    return _core_memory_inbox(
        _project_visible_records(project),
        limit=limit,
        include_archived=include_archived,
        review_command="review-memory",
        project=project,
        command_target=WIKI_DIR.parent,
    )


def _slugify(value: str, fallback: str = "memory") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or fallback


def _memory_title(text: str, explicit_title: str | None = None) -> str:
    if explicit_title and explicit_title.strip():
        return explicit_title.strip()
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "Memory")
    first_sentence = re.split(r"(?<=[.!?])\s+", first_line, maxsplit=1)[0].strip()
    if len(first_sentence) <= 70:
        return first_sentence.rstrip(".")
    return first_sentence[:67].rstrip() + "..."


def _memory_duplicate_candidates(
    text: str,
    title: str | None,
    memory_type: str,
    scope: str,
    limit: int = 3,
) -> list[dict[str, object]]:
    return _core_memory_duplicate_candidates(
        _memory_records(),
        text,
        title,
        memory_type,
        scope,
        limit=limit,
    )


def _propose_memories_from_text(
    text: str,
    source: str = "http",
    limit: int = 10,
    project: str | None = None,
) -> dict[str, object]:
    return _core_propose_memories_from_text(
        text,
        _memory_records(),
        source=source,
        limit=limit,
        writes_memory=False,
        project=project,
        command_target=WIKI_DIR.parent,
    )


def _memory_explanation(identifier: str) -> dict[str, object]:
    return _core_memory_explanation(
        WIKI_DIR,
        identifier,
        records=_memory_records(),
        review_command="review-memory",
        command_target=WIKI_DIR.parent,
    )


def _memory_profile(limit: int = 10, project: str | None = None) -> dict[str, object]:
    return _core_memory_profile(_memory_records(), limit=limit, review_command="review-memory", project=project)


def _mark_memory_reviewed(identifier: str, note: str = "") -> dict[str, object]:
    result = _core_mark_memory_reviewed(
        WIKI_DIR,
        _clean_text_input(identifier, max_len=300),
        note=_clean_text_input(note, max_len=500),
        timestamp=_utc_timestamp(),
        records=_memory_records(),
        review_command="review-memory",
        log_writer=_append_log,
    )
    if result["updated"]:
        _invalidate_pages_cache()
    return result


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
        _invalidate_pages_cache()
    return result


def _remember_memory_from_web(payload: dict[str, object]) -> dict[str, object]:
    result = _core_write_memory_page(
        WIKI_DIR,
        _clean_text_input(payload.get("memory") or payload.get("text"), max_len=MAX_POST_BYTES),
        _clean_text_input(payload.get("title"), max_len=160) or None,
        _clean_text_input(payload.get("memory_type") or payload.get("type") or "note", max_len=30),
        _clean_text_input(payload.get("scope") or "user", max_len=30),
        _clean_text_input(payload.get("tags"), max_len=500) or None,
        _clean_text_input(payload.get("source") or "web approval", max_len=500),
        _utc_timestamp(),
        project=_clean_text_input(payload.get("project"), max_len=80) or None,
        visibility=_clean_text_input(payload.get("visibility"), max_len=30) or None,
        review_after=_clean_text_input(payload.get("review_after"), max_len=40) or None,
        expires_at=_clean_text_input(payload.get("expires_at"), max_len=40) or None,
        records=_memory_records(),
        allow_duplicate=False,
        allow_conflict=False,
        log_writer=_append_log,
        rebuild_backlinks=lambda: bool(_rebuild_backlinks_payload().get("rebuilt")),
    )
    if result.get("created"):
        _invalidate_pages_cache()
    return result


def _update_memory_from_web(payload: dict[str, object]) -> dict[str, object]:
    result = _core_update_memory_page(
        WIKI_DIR,
        _clean_text_input(payload.get("memory") or payload.get("identifier"), max_len=300),
        _clean_text_input(payload.get("text"), max_len=MAX_POST_BYTES),
        _clean_text_input(payload.get("source") or "web approval", max_len=500),
        _utc_timestamp(),
        records=_memory_records(),
        review_command="review-memory",
        allow_conflict=False,
        project=_clean_text_input(payload.get("project"), max_len=80) or None,
        log_writer=_append_log,
        rebuild_backlinks=lambda: bool(_rebuild_backlinks_payload().get("rebuilt")),
    )
    if result.get("updated"):
        _invalidate_pages_cache()
    return result


def _memory_activity_key(record: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(record.get("updated_at") or record.get("date_captured") or ""),
        str(record.get("date_captured") or ""),
        str(record.get("title") or "").lower(),
    )


def _memory_action_hints(record: dict[str, object]) -> list[dict[str, object]]:
    hints: list[dict[str, object]] = []
    for action in _core_memory_action_hints(record, review_command="review-memory"):
        item = {
            "kind": str(action.get("kind") or ""),
            "label": str(action.get("label") or ""),
            "href": "",
            "command": str(action.get("command") or ""),
            "description": str(action.get("description") or ""),
            "priority": str(action.get("priority") or ""),
            "arguments": action.get("arguments") if isinstance(action.get("arguments"), dict) else {},
        }
        if action.get("kind") == "explain":
            name = str(record.get("name") or "")
            item["href"] = f"/explain-memory?memory={urllib.parse.quote(name, safe='')}"
        hints.append(item)
    return hints


def _memory_with_actions(record: dict[str, object]) -> dict[str, object]:
    item = dict(record)
    item["actions"] = _memory_action_hints(record)
    return item


def _memory_dashboard_next_actions(
    memory_count: int,
    review_count: int,
    updated_count: int,
    archived_count: int,
    capture_count: int = 0,
    capture_warning_count: int = 0,
) -> list[dict[str, str]]:
    return _core_memory_dashboard_next_actions(
        memory_count=memory_count,
        review_count=review_count,
        updated_count=updated_count,
        archived_count=archived_count,
        capture_count=capture_count,
        capture_warning_count=capture_warning_count,
    )


def _capture_records(limit: int = 12, project: str | None = None) -> list[dict[str, object]]:
    root = WIKI_DIR.parent
    return _core_capture_records(
        root,
        limit=limit,
        project=project,
        commands_for=lambda rel_path: _core_cli_capture_commands(rel_path, root),
    )


def _capture_inbox(limit: int = 20, project: str | None = None) -> dict[str, object]:
    return _core_capture_inbox(
        WIKI_DIR.parent,
        limit=limit,
        project=project,
        commands_for=lambda rel_path: _core_cli_capture_commands(rel_path, WIKI_DIR.parent),
    )


def _capture_review_summary(project: str | None = None, limit: int = 3) -> dict[str, object]:
    project_name = _core_normalize_project(project)
    summary = _core_capture_review_summary(
        WIKI_DIR.parent,
        limit=limit,
        project=project_name,
        commands_for=lambda rel_path: _core_cli_capture_commands(rel_path, WIKI_DIR.parent),
    )
    project_query = f"?project={urllib.parse.quote(project_name, safe='')}" if project_name else ""
    project_arg = f' --project "{project_name}"' if project_name else ""
    summary["href"] = f"/captures{project_query}"
    summary["command"] = f'python3 link.py capture-inbox "{WIKI_DIR.parent}"{project_arg}'
    return summary


def _memory_brief(query: str = "", limit: int = 6, project: str | None = None) -> dict[str, object]:
    limit = max(1, min(limit, 20))
    project_name = _core_normalize_project(project)
    payload = _core_memory_brief(
        _memory_records(), query=query, limit=limit,
        review_command="review-memory", project=project_name,
        command_target=WIKI_DIR.parent,
    )
    return _core_add_capture_review_to_brief(
        payload,
        _capture_review_summary(project=project_name, limit=min(limit, 10)),
    )


def _memory_dashboard(limit: int = 12, project: str | None = None) -> dict[str, object]:
    limit = max(1, min(limit, 50))
    project_name = _core_normalize_project(project)
    records = _project_visible_records(project_name)
    active_records = [record for record in records if _is_active_memory(record)]
    archived_records = [
        record for record in records
        if str(record.get("status") or "").lower() == "archived"
    ]
    recent_active = sorted(active_records, key=_memory_activity_key, reverse=True)
    recent_updates = sorted(
        [record for record in records if str(record.get("updated_at") or "").strip()],
        key=lambda record: (
            str(record.get("updated_at") or ""),
            str(record.get("title") or "").lower(),
        ),
        reverse=True,
    )
    archived = sorted(archived_records, key=_memory_activity_key, reverse=True)
    inbox = _memory_inbox(limit=limit, project=project_name)
    review_count = inbox["review_count"]
    updated_count = len(recent_updates)
    archived_count = len(archived_records)
    captures = _capture_records(limit=limit, project=project_name)
    capture_warning_count = sum(1 for capture in captures if capture["warning_count"])
    return {
        "memory_count": len(records),
        "active_count": len(active_records),
        "review_count": review_count,
        "archived_count": archived_count,
        "updated_count": updated_count,
        "capture_count": len(captures),
        "capture_warning_count": capture_warning_count,
        "project": project_name,
        "by_type": _count_values(records, "memory_type"),
        "by_scope": _count_values(records, "scope"),
        "counts_by_severity": inbox["counts_by_severity"],
        "next_actions": _memory_dashboard_next_actions(
            memory_count=len(records),
            review_count=review_count,
            updated_count=updated_count,
            archived_count=archived_count,
            capture_count=len(captures),
            capture_warning_count=capture_warning_count,
        ),
        "active": [_memory_with_actions(record) for record in recent_active[:limit]],
        "review": [_memory_with_actions(record) for record in inbox["items"][:limit]],
        "recent_updates": [_memory_with_actions(record) for record in recent_updates[:limit]],
        "archived": [_memory_with_actions(record) for record in archived[:limit]],
        "captures": captures,
    }


def _memory_audit(limit: int = 10, project: str | None = None) -> dict[str, object]:
    limit = max(1, min(limit, 50))
    project_name = _core_normalize_project(project)
    profile = _memory_profile(limit=limit, project=project_name)
    inbox = _memory_inbox(limit=limit, include_archived=True, project=project_name)
    captures = _capture_review_summary(project=project_name, limit=min(limit, 10))
    payload = _core_memory_audit_report(profile, inbox, captures, [], project=project_name)
    payload["next_actions"] = _core_memory_audit_next_actions(
        mode="web",
        inbox=inbox,
        captures=captures,
        risk_factors=payload["risk_factors"],
        project=str(payload["project"]),
        root=WIKI_DIR.parent,
    )
    return payload


def _memory_log(limit: int = 50, include_captures: bool = True) -> dict[str, object]:
    return _core_memory_log_payload(
        WIKI_DIR,
        limit=max(1, min(limit, 200)),
        include_captures=include_captures,
    )


def _memory_wins(limit: int = 6, project: str | None = None) -> dict[str, object]:
    return _core_memory_wins_payload(
        WIKI_DIR,
        limit=max(1, min(limit, 50)),
        project=project,
        records=_memory_records(),
    )


def _json_for_script(data) -> str:
    """Serialize JSON for direct embedding inside a <script> tag."""
    return (
        json.dumps(data, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _safe_resolve(path: Path) -> Path | None:
    return _core_safe_resolve(path)


def _is_relative_to(path: Path, root: Path) -> bool:
    return _core_is_relative_to(path, root)


def _is_allowed_static_file(path: Path) -> bool:
    root = Path(__file__).parent.resolve()
    link_root = WIKI_DIR.parent.resolve()
    return _core_is_allowed_static_file(
        path,
        RAW_DIR,
        (
            link_root / "logo.svg",
            link_root / "logo.png",
            root / "logo.svg",
            root / "logo.png",
        ),
        RAW_STATIC_TYPES,
    )


def _brand_file(name: str) -> Path:
    link_asset = WIKI_DIR.parent / name
    if link_asset.exists():
        return link_asset
    return Path(__file__).parent / name


def _resolve_raw_static_path(url_fragment: str) -> tuple[Path | None, str | None]:
    return _core_resolve_raw_static_path(RAW_DIR, url_fragment, RAW_STATIC_TYPES)


def _proposal_sources(limit: int = 50) -> dict[str, object]:
    return _core_proposal_sources(
        RAW_DIR,
        suffixes=PROPOSAL_SOURCE_SUFFIXES,
        max_bytes=MAX_PROPOSAL_SOURCE_BYTES,
        limit=limit,
    )


def _proposal_source_payload(source_path: str) -> tuple[dict[str, object], int]:
    return _core_proposal_source_payload(
        RAW_DIR,
        source_path,
        suffixes=PROPOSAL_SOURCE_SUFFIXES,
        max_bytes=MAX_PROPOSAL_SOURCE_BYTES,
    )


def _create_raw_source_payload(payload: dict[str, object]) -> tuple[dict[str, object], int]:
    return _core_create_raw_source_payload(
        WIKI_DIR.parent,
        WIKI_DIR,
        payload,
        max_bytes=MAX_RAW_SOURCE_BYTES,
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _md_to_html(md):
    return _core_markdown_to_html(md, page_href=_page_href)


# ---------------------------------------------------------------------------
# CSS + layout
# ---------------------------------------------------------------------------

def _header_html():
    return _core_render_header_html()


def _footer_html():
    return _core_render_footer_html()


def _layout(title, body, page_class: str = ""):
    return _core_render_layout(title, body, page_class=page_class)


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def _render_home():
    return _core_render_home_page(
        _get_all_pages(),
        starter_prompts=_starter_prompts_payload(),
        page_href=_page_href,
        layout=_layout,
    )


def _starter_prompts_payload(project: str | None = None) -> dict[str, object]:
    return _core_starter_prompt_payload(WIKI_DIR, project=project)


def _render_prompts(project: str | None = None):
    return _core_render_prompts_page(_starter_prompts_payload(project=project), layout=_layout)


def _render_more():
    links = [
        ("/prompts", "Prompts", "Starter prompts and copyable next-step commands."),
        ("/propose", "Propose", "Turn notes into review-only memory candidates."),
        ("/audit", "Audit", "Review memory health, backlog, captures, and safe next actions."),
        ("/inbox", "Inbox", "Confirm, update, archive, or explain memories needing review."),
        ("/captures", "Captures", "Inspect saved raw session captures before accepting them."),
        ("/profile", "Profile", "See what Link remembers by type, scope, status, and recency."),
        ("/wins", "Wins", "Show local proof signals for what Link memory is carrying."),
        ("/memory-log", "Memory Log", "See recent memory lifecycle changes without opening raw log text."),
        ("/page/log", "Log", "Read the append-only wiki operation log."),
        ("/all", "All Pages", "Browse grouped wiki pages with filters and pagination."),
    ]
    cards = "".join(
        '<article class="memory-card">'
        f'<h2><a href="{html.escape(href, quote=True)}">{html.escape(title)}</a></h2>'
        f'<p>{html.escape(description)}</p>'
        "</article>"
        for href, title, description in links
    )
    return _layout(
        "More",
        '<div class="breadcrumb"><a href="/">Link</a> / more</div>'
        "<h1>More Tools</h1>"
        '<p class="summary">Advanced Link views for prompts, proposal review, audit, captures, and full wiki browsing.</p>'
        f'<section class="memory-grid">{cards}</section>',
    )


def _render_page(page_path):
    text = page_path.read_text(encoding="utf-8", errors="replace")
    meta, body = _parse_frontmatter(text)
    body_html = _md_to_html(body)

    title = meta.get("title", "")
    if not title:
        m = re.search(r"^#\s+(.+)", body, re.MULTILINE)
        title = m.group(1) if m else page_path.stem

    rel = page_path.relative_to(WIKI_DIR)
    cat = rel.parts[0] if len(rel.parts) > 1 else ""
    raw_refs = _core_raw_source_refs(body) if cat == "sources" else []
    proposal_prompt = f"propose memories from {raw_refs[0]}" if raw_refs else ""
    query_prompt = f"query Link for {title}"
    return _core_render_wiki_page(
        str(title),
        category=cat,
        meta=meta,
        body_html=body_html,
        layout=_layout,
        graph_href=_graph_href(page_path.stem),
        proposal_href=_proposal_href(raw_refs[0]) if raw_refs else "",
        proposal_prompt=proposal_prompt,
        query_prompt=query_prompt,
        related_pages=_related_pages_for(page_path.stem),
    )


def _related_pages_for(page_name: str, max_items: int = 8) -> list[dict[str, str]]:
    """Return a compact inbound/forward page list for the wiki page footer."""
    with _cache_lock:
        pages = _get_all_pages()
        page_by_name = {str(page.get("name") or ""): page for page in pages}
        backlinks, _ = _load_backlinks_index()
        inbound = list(backlinks.get("backlinks", {}).get(page_name, []))
        forward = list(_forward_links_index.get(page_name) or backlinks.get("forward", {}).get(page_name, []))
    related: list[dict[str, str]] = []
    seen = {page_name}
    for relationship, names in (("links here", inbound), ("links out", forward)):
        for name in names:
            if name in seen or name not in page_by_name:
                continue
            seen.add(name)
            page = page_by_name[name]
            related.append({
                "name": name,
                "title": str(page.get("title") or name),
                "href": _page_href(name),
                "relationship": relationship,
            })
            if len(related) >= max_items:
                return related
    return related


def _render_all(query: dict[str, list[str]] | None = None):
    query = query or {}
    pages = _get_all_pages()
    total = len(pages)
    limit_raw = query.get("limit", ["250"])[0]
    offset_raw = query.get("offset", ["0"])[0]
    limit, limit_error = _core_parse_bounded_int(limit_raw, "limit", 250, 1, 500)
    offset, offset_error = _core_parse_bounded_int(offset_raw, "offset", 0, 0, 1000000)
    error = limit_error or offset_error
    if error:
        limit = 250
        offset = 0
    assert limit is not None
    assert offset is not None
    sorted_pages = sorted(pages, key=lambda x: x["title"])
    type_counts = Counter(str(page.get("type") or page.get("category") or "root") for page in sorted_pages)
    active_type = _query_text(query, "type", "page_type", max_len=80).lower()
    visible_pages = [
        page for page in sorted_pages
        if not active_type or str(page.get("type") or page.get("category") or "root").lower() == active_type
    ]
    total = len(visible_pages)
    window = visible_pages[offset:offset + limit]
    return _core_render_all_pages(
        window,
        total=total,
        limit=limit,
        offset=offset,
        page_href=_page_href,
        layout=_layout,
        error=error or "",
        type_counts=type_counts,
        active_type=active_type,
    )


def _render_memory_card(record: dict[str, object], include_issues: bool = False) -> str:
    return _core_render_memory_card(
        record,
        page_href=_page_href,
        action_hints=_memory_action_hints,
        include_issues=include_issues,
    )


def _render_memory_section(title: str, records: list[dict[str, object]], empty: str, href: str = "", include_issues: bool = False) -> str:
    return _core_render_memory_section(
        title,
        records,
        empty,
        page_href=_page_href,
        action_hints=_memory_action_hints,
        href=href,
        include_issues=include_issues,
    )


def _render_brief(query: str = "", project: str | None = None):
    return _core_render_brief_page(
        _memory_brief(query=query, limit=8, project=project),
        query,
        page_href=_page_href,
        action_hints=_memory_action_hints,
        layout=_layout,
    )


def _render_memory_dashboard(project: str | None = None):
    return _core_render_memory_dashboard_page(
        _memory_dashboard(limit=8, project=project),
        page_href=_page_href,
        action_hints=_memory_action_hints,
        layout=_layout,
    )


def _render_profile(project: str | None = None):
    return _core_render_profile_page(_memory_profile(limit=12, project=project), page_href=_page_href, layout=_layout)


def _render_memory_audit(project: str | None = None):
    return _core_render_memory_audit_page(
        _memory_audit(limit=10, project=project),
        page_href=_page_href,
        action_hints=_memory_action_hints,
        layout=_layout,
    )


def _render_captures(project: str | None = None):
    return _core_render_captures_page(_capture_inbox(limit=50, project=project), layout=_layout)


def _render_propose(project: str | None = None, source: str | None = None):
    return _core_render_propose_page(
        _clean_text_input(project, max_len=80),
        _clean_text_input(source, max_len=500),
        layout=_layout,
    )


def _render_ingest():
    return _core_render_ingest_page(_ingest_status(), page_href=_page_href, layout=_layout)


def _render_inbox(project: str | None = None):
    return _core_render_inbox_page(_memory_inbox(limit=50, project=project), page_href=_page_href, layout=_layout)


def _render_memory_log():
    return _core_render_memory_log_page(_memory_log(limit=100), layout=_layout)


def _render_memory_wins(project: str | None = None):
    return _core_render_memory_wins_page(
        _memory_wins(limit=8, project=project),
        page_href=_page_href,
        layout=_layout,
    )


def _render_explain_memory(identifier: str):
    try:
        explanation = _memory_explanation(identifier)
    except ValueError as exc:
        return _layout("Memory Explanation", f'<h1>Memory not found</h1><p>{html.escape(str(exc))}</p>')
    return _core_render_memory_explanation_page(
        explanation,
        body_html=_md_to_html(str(explanation.get("body") or "")),
        layout=_layout,
    )


def _render_graph(query: dict[str, list[str]] | None = None):
    query = query or {}
    focus = _query_text(query, "focus", "page", "node", max_len=300)
    graph_search = _query_text(query, "q", "search", max_len=200)
    graph_category = _query_text(query, "type", "category", max_len=80) or "all"
    graph_size = _query_text(query, "size", max_len=80) or "category"
    if graph_size not in {"category", "degree"}:
        graph_size = "category"
    graph_labels = _query_text(query, "labels", "label", max_len=80) or "sparse"
    if graph_labels not in {"sparse", "neighbors", "all"}:
        graph_labels = "sparse"
    focus_depth, focus_depth_error = _core_parse_bounded_int(query.get("depth", ["2"])[0], "depth", 2, 0, 3)
    if focus_depth_error:
        focus_depth = 2
    assert focus_depth is not None
    full_graph = _get_graph_data()
    summary_graph = None
    summary_topic = focus or graph_search
    if summary_topic:
        summary = _get_graph_summary(
            topic=summary_topic,
            limit=_core_graph_initial_summary_node_limit,
            depth=focus_depth if focus else 1,
            max_edges=_core_graph_initial_summary_edge_limit,
        )
        summary_graph = {
            "nodes": summary.get("nodes", []),
            "edges": summary.get("edges", []),
        }
    elif _core_graph_needs_bounded_overview(full_graph):
        summary = _get_graph_summary(
            limit=_core_graph_initial_summary_node_limit,
            depth=1,
            max_edges=_core_graph_initial_summary_edge_limit,
        )
        summary_graph = {
            "nodes": summary.get("nodes", []),
            "edges": summary.get("edges", []),
        }
    graph_view = _core_graph_initial_payload(full_graph, summary_graph=summary_graph)
    visible_nodes = graph_view["nodes"]
    visible_edges = graph_view["edges"]
    node_count = int(graph_view["node_count"])
    edge_count = int(graph_view["edge_count"])
    total_node_count = int(graph_view["total_node_count"])
    total_edge_count = int(graph_view["total_edge_count"])
    graph_mode = str(graph_view["graph_mode"])
    graph_note = str(graph_view["graph_note"])
    nodes_json = _json_for_script(visible_nodes)
    edges_json = _json_for_script(visible_edges)

    if node_count == 0:
        body = _core_render_graph_empty_body()
        return _layout("Knowledge Graph", body)

    cat_colors = _core_graph_category_colors
    category_options = _core_graph_category_options(visible_nodes)

    graph_js = _core_render_graph_script(
        nodes_json=nodes_json,
        edges_json=edges_json,
        cat_colors_json=_json_for_script(cat_colors),
        graph_mode_json=_json_for_script(graph_mode),
        focus_id_json=_json_for_script(focus or None),
        focus_depth=focus_depth,
        search_json=_json_for_script(graph_search),
        category_json=_json_for_script(graph_category),
        size_json=_json_for_script(graph_size),
        label_json=_json_for_script(graph_labels),
        total_node_count=total_node_count,
        total_edge_count=total_edge_count,
    )

    body = _core_render_graph_page_body(
        graph_js=graph_js,
        node_count=node_count,
        edge_count=edge_count,
        total_node_count=total_node_count,
        total_edge_count=total_edge_count,
        graph_mode=graph_mode,
        graph_note=graph_note,
        category_options=category_options,
        legend_items=_core_graph_legend_items(cat_colors),
        focus_label=focus,
        focus_depth=focus_depth,
        search_label=graph_search,
        category_label=graph_category,
        size_label=graph_size,
        label_label=graph_labels,
    )
    return _layout("Knowledge Graph", body, page_class="graph-page")


def _render_search(query, page_type: str = ""):
    q = query.lower().strip()
    results = _search_pages(q, limit=120) if q else []
    return _core_render_search_page(
        query,
        results,
        page_href=_page_href,
        layout=_layout,
        limit=30,
        active_type=page_type.lower().strip(),
    )


# ---------------------------------------------------------------------------
# Agent search helpers
# ---------------------------------------------------------------------------

def _search_pages(q: str, limit: int = 20) -> list:
    """Search pages by title, alias, tag, and full-text body.
    Uses token index to pre-filter candidates, snippet index for zero file I/O.
    """
    with _cache_lock:
        return _core_search_pages(q, _current_wiki_cache(), limit=limit)


def _query_link(query: str, budget: str = "medium", project: str | None = None) -> dict[str, object]:
    with _cache_lock:
        return _core_query_link(
            WIKI_DIR,
            query,
            _current_wiki_cache(),
            _memory_records(),
            budget=budget,
            project=project,
            review_command="review-memory",
        )


def _get_context(topic: str) -> dict:
    """Return everything an agent needs to answer a question about a topic.
    Finds the best matching page, then returns:
    - The page's full content
    - Its backlinks (pages that reference it)
    - Its forward links (pages it references)
    - Related pages (shared tags or backlink overlap)
    """
    with _cache_lock:
        return _core_context_for_topic(WIKI_DIR, topic, _current_wiki_cache())


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------

def _build_backlinks() -> dict[str, dict[str, list[str]]]:
    """Scan all wiki pages for [[wikilinks]] and build graph indexes.
    Returns {"backlinks": {target: [sources]}, "forward": {source: [targets]}}.
    """
    return _core_build_backlinks(WIKI_DIR)


def _get_graph_data() -> dict:
    """Return graph nodes and edges for visualization.
    Uses in-memory fulltext index — no separate rglob scan.
    """
    with _cache_lock:
        return _core_graph_data(_current_wiki_cache())


def _get_graph_summary(topic: str = "", limit: int = 40, depth: int = 1, max_edges: int = 120) -> dict:
    """Return bounded graph context for agents and large local wikis."""
    with _cache_lock:
        return _core_graph_summary(
            _current_wiki_cache(),
            topic=topic,
            limit=limit,
            depth=depth,
            max_edges=max_edges,
        )


def _rebuild_backlinks_payload() -> dict[str, object]:
    try:
        result = _build_backlinks()
    except OSError as exc:
        return {"rebuilt": False, "error": f"Could not rebuild backlinks: {exc}"}
    bl_path = WIKI_DIR / "_backlinks.json"
    _core_atomic_write_json(bl_path, result)
    # Invalidate pages cache so next request picks up the new backlinks mtime.
    _invalidate_pages_cache()
    return {"rebuilt": True, "pages": len(result.get("backlinks", {}))}


def _rebuild_index_payload() -> dict[str, object]:
    try:
        with _cache_lock:
            result = _core_rebuild_index(WIKI_DIR, cache=_current_wiki_cache())
    except OSError as exc:
        return {"rebuilt": False, "error": f"Could not rebuild index: {exc}"}
    _invalidate_pages_cache()
    return result


def _validate_wiki_payload(strict: bool = False) -> dict[str, object]:
    return _core_validate_wiki(WIKI_DIR, strict=strict)


def _link_status_payload(include_validation: bool = False) -> dict[str, object]:
    payload = _core_link_status(
        WIKI_DIR,
        version=LINK_VERSION,
        include_validation=include_validation,
    )
    payload["api_version"] = API_VERSION
    return payload


def _operations_payload() -> dict[str, object]:
    payload = _core_operation_report(WIKI_DIR)
    payload["api_version"] = API_VERSION
    return payload


def _health_payload() -> dict[str, object]:
    status = _link_status_payload(include_validation=True)
    operations = _operations_payload()
    return {
        "api_version": API_VERSION,
        "ready": bool(status.get("ready")),
        "status": status,
        "operations": operations,
    }


def _api_discovery_payload() -> dict[str, object]:
    return {
        "api_version": API_VERSION,
        "name": "Link local HTTP API",
        "description": "Loopback-only API for Link local agent memory.",
        "local_only": True,
        "recommended": {
            "readiness": "/api/health",
            "agent_context": "/api/query-link?q=<query>&budget=small",
            "graph_overview": "/api/graph-summary?limit=40&depth=1",
            "ingest_guidance": "/api/ingest-status",
        },
        "endpoints": {
            "read": [
                "/api/health",
                "/api/status?validate=true",
                "/api/prompts",
                "/api/ingest-status",
                "/api/page-list",
                "/api/query-link",
                "/api/memory-brief",
                "/api/memory-dashboard",
                "/api/memory-audit",
                "/api/memory-profile",
                "/api/memory-inbox",
                "/api/wins",
                "/api/memory-log",
                "/api/capture-inbox",
                "/api/explain-memory",
                "/api/validate",
                "/api/search",
                "/api/context",
                "/api/graph-summary",
                "/api/graph",
                "/api/page-links",
                "/api/operations",
            ],
            "write": [
                "/api/raw-source",
                "/api/propose-memories",
                "/api/remember-memory",
                "/api/update-memory",
                "/api/review-memory",
                "/api/archive-memory",
                "/api/restore-memory",
                "/api/rebuild-backlinks",
                "/api/rebuild-index",
            ],
        },
        "write_header": {"X-Link-Local-Action": "true"},
    }


def _render_health():
    return _core_render_health_page(
        _link_status_payload(include_validation=True),
        _operations_payload(),
        layout=_layout,
    )


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(http.server.BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.request.settimeout(REQUEST_TIMEOUT_SECONDS)

    def do_HEAD(self):
        """HEAD requests: send headers only, no body."""
        self._head_only = True
        try:
            self.do_GET()
        finally:
            self._head_only = False

    def do_OPTIONS(self):
        self._head_only = False
        if not self._require_allowed_host():
            return
        self._json(
            {"error": "CORS preflight is not supported; Link is localhost-only"},
            status=405,
            headers={"Allow": "GET, HEAD, POST"},
        )

    def do_PUT(self):
        self._method_not_allowed()

    def do_PATCH(self):
        self._method_not_allowed()

    def do_DELETE(self):
        self._method_not_allowed()

    def do_TRACE(self):
        self._method_not_allowed()

    def do_CONNECT(self):
        self._method_not_allowed()

    def do_POST(self):
        self._head_only = False
        if not self._require_allowed_host():
            return
        if not self._require_mutation_rate_limit():
            return
        parsed = urllib.parse.urlparse(self.path)
        self._handle_api_post(parsed.path)

    def _handle_api_post(self, path: str) -> None:
        if path == "/api/rebuild-index":
            self._handle_rebuild_post(_rebuild_index_payload)
            return
        if path == "/api/rebuild-backlinks":
            self._handle_rebuild_post(_rebuild_backlinks_payload)
            return
        if path == "/api/raw-source":
            if not self._require_local_action_header({"created": False}):
                return
            payload = self._read_json_or_reply({"created": False})
            if payload is None:
                return
            result, http_status = _create_raw_source_payload(payload)
            self._json(result, status=http_status)
            return
        if path == "/api/propose-memories":
            payload = self._read_json_or_reply({"proposed": False, "count": 0, "proposals": []})
            if payload is None:
                return
            text = _clean_text_input(payload.get("text"), max_len=MAX_POST_BYTES)
            if not text.strip():
                self._json({"proposed": False, "error": "text required", "count": 0, "proposals": []}, status=400)
                return
            source = _clean_text_input(payload.get("source") or "http", max_len=500) or "http"
            limit, limit_error = _parse_search_limit(str(payload.get("limit", "10")))
            if limit_error:
                self._json({"proposed": False, "error": limit_error, "count": 0, "proposals": []}, status=400)
                return
            result = _propose_memories_from_text(
                text,
                source=source,
                limit=min(limit, 20),
                project=_clean_text_input(payload.get("project"), max_len=80),
            )
            self._json(result)
            return
        if path in {"/api/remember-memory", "/api/update-memory"}:
            if not self._require_local_action_header({"saved": False}):
                return
            payload = self._read_json_or_reply({"saved": False})
            if payload is None:
                return
            try:
                if path == "/api/remember-memory":
                    result = _remember_memory_from_web(payload)
                    http_status = 200 if result.get("created") else 409
                    self._json({"saved": bool(result.get("created")), **result}, status=http_status)
                else:
                    result = _update_memory_from_web(payload)
                    http_status = 200 if result.get("updated") else 409
                    self._json({"saved": bool(result.get("updated")), **result}, status=http_status)
            except ValueError as exc:
                self._json({"saved": False, "error": str(exc)}, status=400)
            return
        if path in {"/api/review-memory", "/api/archive-memory", "/api/restore-memory"}:
            if not self._require_local_action_header():
                return
            payload = self._read_json_or_reply({"updated": False})
            if payload is None:
                return
            identifier = _clean_text_input(payload.get("memory") or payload.get("identifier"), max_len=300)
            if not identifier:
                self._json({"updated": False, "error": "memory required"}, status=400)
                return
            try:
                if path == "/api/review-memory":
                    result = _mark_memory_reviewed(
                        identifier,
                        note=_clean_text_input(payload.get("note"), max_len=500),
                    )
                elif path == "/api/archive-memory":
                    result = _set_memory_status(
                        identifier,
                        "archived",
                        reason=_clean_text_input(payload.get("reason"), max_len=500),
                    )
                else:
                    result = _set_memory_status(identifier, "active")
            except ValueError as exc:
                self._json({"updated": False, "error": str(exc)}, status=404)
                return
            self._json(result)
            return
        self._json({"error": "POST endpoint not found"}, status=404)

    def do_GET(self):
        self._head_only = getattr(self, '_head_only', False)
        if not self._require_allowed_host():
            return
        parsed = urllib.parse.urlparse(self.path)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query)
        if path == "/logo.svg":
            self._file(_brand_file("logo.svg"), "image/svg+xml")
        elif path == "/logo.png":
            self._file(_brand_file("logo.png"), "image/png")
        elif path.startswith("/raw/"):
            raw_path, content_type = _resolve_raw_static_path(path[5:])
            if raw_path and content_type:
                self._file(raw_path, content_type)
            else:
                self._err("file")
        elif path in ("/", ""):
            self._ok(_render_home())
        elif path == "/health":
            self._ok(_render_health())
        elif path == "/ingest":
            self._ok(_render_ingest())
        elif path == "/brief":
            self._ok(_render_brief(
                query=_query_text(query, "q", "query"),
                project=_query_text(query, "project", max_len=80),
            ))
        elif path == "/propose":
            self._ok(_render_propose(
                project=_query_text(query, "project", max_len=80),
                source=_query_text(query, "source", max_len=500),
            ))
        elif path == "/prompts":
            self._ok(_render_prompts(project=_query_text(query, "project", max_len=80)))
        elif path == "/more":
            self._ok(_render_more())
        elif path == "/memory":
            self._ok(_render_memory_dashboard(project=_query_text(query, "project", max_len=80)))
        elif path == "/audit":
            self._ok(_render_memory_audit(project=_query_text(query, "project", max_len=80)))
        elif path == "/inbox":
            self._ok(_render_inbox(project=_query_text(query, "project", max_len=80)))
        elif path == "/captures":
            self._ok(_render_captures(project=_query_text(query, "project", max_len=80)))
        elif path == "/explain-memory":
            identifier = _query_text(query, "memory", "name", max_len=300)
            self._ok(_render_explain_memory(identifier))
        elif path == "/profile":
            self._ok(_render_profile(project=_query_text(query, "project", max_len=80)))
        elif path == "/wins":
            self._ok(_render_memory_wins(project=_query_text(query, "project", max_len=80)))
        elif path == "/memory-log":
            self._ok(_render_memory_log())
        elif path == "/all":
            self._ok(_render_all(query))
        elif path == "/graph":
            self._ok(_render_graph(query))
        elif path == "/search":
            self._ok(_render_search(_query_text(query, "q"), page_type=_query_text(query, "type", "page_type", max_len=80)))
        elif path.startswith("/page/"):
            page = _find_page(urllib.parse.unquote(path[6:]))
            if page: self._ok(_render_page(page))
            else: self._err(urllib.parse.unquote(path[6:]))
        elif path == "/api" or path.startswith("/api/"):
            self._handle_api_get(path, query)
        else:
            self._err("page")

    def _handle_api_get(self, path: str, query: dict[str, list[str]]) -> None:
        if path in {"/api", "/api/"}:
            self._json(_api_discovery_payload())
        elif path == "/api/pages":
            self._json(_all_pages())
        elif path == "/api/page-list":
            limit, limit_error = _core_parse_bounded_int(query.get("limit", ["100"])[0], "limit", 100, 1, 1000)
            offset, offset_error = _core_parse_bounded_int(query.get("offset", ["0"])[0], "offset", 0, 0, 1000000)
            error = limit_error or offset_error
            if error:
                self._json({"error": error}, status=400)
            else:
                assert limit is not None
                assert offset is not None
                self._json(_page_list_payload(
                    category=query.get("category", [""])[0],
                    page_type=query.get("type", [""])[0] or query.get("page_type", [""])[0],
                    maturity=query.get("maturity", [""])[0],
                    limit=limit,
                    offset=offset,
                    include_all=query.get("all", ["false"])[0].lower() in {"1", "true", "yes"},
                ))
        elif path == "/api/status":
            include_validation = query.get("validate", ["false"])[0].lower() in {"1", "true", "yes"}
            self._json(_link_status_payload(include_validation=include_validation))
        elif path == "/api/health":
            self._json(_health_payload())
        elif path == "/api/operations":
            self._json(_operations_payload())
        elif path == "/api/prompts":
            self._json(_starter_prompts_payload(project=_query_text(query, "project", max_len=80)))
        elif path == "/api/ingest-status":
            self._json(_ingest_status())
        elif path == "/api/backlinks":
            data, error = _load_backlinks_index()
            if error:
                self._json({"error": error}, status=500)
            else:
                self._json(data)
        elif path == "/api/page-links":
            limit, limit_error = _core_parse_bounded_int(query.get("limit", ["100"])[0], "limit", 100, 1, 1000)
            offset, offset_error = _core_parse_bounded_int(query.get("offset", ["0"])[0], "offset", 0, 0, 1000000)
            error = limit_error or offset_error
            if error:
                self._json({"error": error}, status=400)
            else:
                assert limit is not None
                assert offset is not None
                payload, status = _page_links_payload(
                    query.get("page", [""])[0] or query.get("page_name", [""])[0],
                    limit=limit,
                    offset=offset,
                    include_all=query.get("all", ["false"])[0].lower() in {"1", "true", "yes"},
                )
                self._json(payload, status=status)
        elif path == "/api/rebuild-backlinks":
            self._json({"error": "use POST with JSON body: {}"}, status=405)
        elif path == "/api/rebuild-index":
            self._json({"error": "use POST with JSON body: {}"}, status=405)
        elif path == "/api/validate":
            strict = query.get("strict", ["false"])[0].lower() in {"1", "true", "yes"}
            payload = _validate_wiki_payload(strict=strict)
            self._json(payload, status=200 if payload.get("passed") else 422)
        elif path in {"/api/graph", "/api/graph-summary", "/api/search", "/api/context"}:
            self._handle_knowledge_api_get(path, query)
        elif path in {
            "/api/memory-profile",
            "/api/memory-dashboard",
            "/api/memory-brief",
            "/api/query-link",
            "/api/memory-audit",
            "/api/memory-inbox",
            "/api/wins",
            "/api/memory-log",
            "/api/capture-inbox",
        }:
            self._handle_memory_api_get(path, query)
        elif path == "/api/proposal-sources":
            limit = self._query_limit_or_reply(query, "50", {"sources": []})
            if limit is not None:
                self._json(_proposal_sources(limit=min(limit, 100)))
        elif path == "/api/proposal-source":
            source_path = query.get("path", [""])[0]
            payload, status = _proposal_source_payload(source_path)
            self._json(payload, status=status)
        elif path == "/api/raw-source":
            self._json({"error": "use POST with JSON body: {\"text\": \"...\"}"}, status=405)
        elif path == "/api/propose-memories":
            self._json({"error": "use POST with JSON body: {\"text\": \"...\"}"}, status=405)
        elif path in {"/api/review-memory", "/api/archive-memory", "/api/restore-memory"}:
            self._json({"error": "use POST with JSON body: {\"memory\": \"...\"}"}, status=405)
        elif path == "/api/explain-memory":
            identifier = _query_text(query, "memory", "name", max_len=300)
            if not identifier:
                self._json({"found": False, "error": "memory parameter required"}, status=400)
            else:
                try:
                    self._json(_memory_explanation(identifier))
                except ValueError as exc:
                    self._json({"found": False, "error": str(exc)}, status=404)
        else:
            self._err("page")

    def _handle_knowledge_api_get(self, path: str, query: dict[str, list[str]]) -> None:
        if path == "/api/graph":
            self._json(_get_graph_data())
        elif path == "/api/graph-summary":
            limit, limit_error = _core_parse_bounded_int(query.get("limit", ["40"])[0], "limit", 40, 1, 250)
            depth, depth_error = _core_parse_bounded_int(query.get("depth", ["1"])[0], "depth", 1, 0, 3)
            max_edges, edge_error = _core_parse_bounded_int(query.get("max_edges", ["120"])[0], "max_edges", 120, 0, 1000)
            error = limit_error or depth_error or edge_error
            if error:
                self._json({"error": error}, status=400)
            else:
                assert limit is not None
                assert depth is not None
                assert max_edges is not None
                self._json(_get_graph_summary(
                    topic=_query_text(query, "topic", "q"),
                    limit=limit,
                    depth=depth,
                    max_edges=max_edges,
                ))
        elif path == "/api/search":
            q = _query_text(query, "q")
            limit = self._query_limit_or_reply(query, "20", {"results": []})
            if limit is None:
                return
            if not q:
                self._json({"error": "q parameter required", "results": []}, status=400)
            else:
                results = _search_pages(q, limit=limit)
                self._json({"query": q, "count": len(results), "results": results})
        elif path == "/api/context":
            topic = _query_text(query, "topic", "q")
            if not topic:
                self._json({"error": "topic parameter required"}, status=400)
            else:
                self._json(_get_context(topic))

    def _handle_memory_api_get(self, path: str, query: dict[str, list[str]]) -> None:
        if path == "/api/memory-profile":
            limit = self._query_limit_or_reply(query, "10")
            if limit is not None:
                self._json(_memory_profile(limit=limit, project=_query_text(query, "project", max_len=80)))
        elif path == "/api/memory-dashboard":
            limit = self._query_limit_or_reply(query, "12")
            if limit is not None:
                self._json(_memory_dashboard(limit=limit, project=_query_text(query, "project", max_len=80)))
        elif path == "/api/memory-brief":
            limit = self._query_limit_or_reply(query, "6")
            if limit is not None:
                self._json(_memory_brief(
                    query=_query_text(query, "q", "query"),
                    limit=limit,
                    project=_query_text(query, "project", max_len=80),
                ))
        elif path == "/api/query-link":
            query_text = _query_text(query, "q", "query")
            if not query_text.strip():
                self._json({"found": False, "error": "query parameter required", "context_packet": []}, status=400)
            else:
                self._json(_query_link(
                    query=query_text,
                    budget=query.get("budget", ["medium"])[0],
                    project=_query_text(query, "project", max_len=80),
                ))
        elif path == "/api/memory-audit":
            limit = self._query_limit_or_reply(query, "10")
            if limit is not None:
                self._json(_memory_audit(limit=limit, project=_query_text(query, "project", max_len=80)))
        elif path == "/api/memory-inbox":
            limit = self._query_limit_or_reply(query, "20")
            if limit is not None:
                include_archived = query.get("include_archived", ["false"])[0].lower() in {"1", "true", "yes"}
                self._json(_memory_inbox(
                    limit=limit,
                    include_archived=include_archived,
                    project=_query_text(query, "project", max_len=80),
                ))
        elif path == "/api/wins":
            limit = self._query_limit_or_reply(query, "6")
            if limit is not None:
                self._json(_memory_wins(limit=limit, project=_query_text(query, "project", max_len=80)))
        elif path == "/api/memory-log":
            limit = self._query_limit_or_reply(query, "50")
            if limit is not None:
                include_captures = query.get("include_captures", ["true"])[0].lower() not in {"0", "false", "no"}
                self._json(_memory_log(limit=limit, include_captures=include_captures))
        elif path == "/api/capture-inbox":
            limit = self._query_limit_or_reply(query, "20")
            if limit is not None:
                self._json(_capture_inbox(
                    limit=limit,
                    project=_query_text(query, "project", max_len=80),
                ))

    def _ok(self, body: str):
        encoded = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._security_headers()
        self.send_header("Content-Length", str(len(encoded)))
        self._no_store_headers()
        self.end_headers()
        if not getattr(self, '_head_only', False):
            self.wfile.write(encoded)

    def _err(self, name: str):
        encoded = _layout("Not Found", f"<h1>Not found</h1><p>No page: {html.escape(name)}</p>").encode()
        self.send_response(404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._security_headers()
        self.send_header("Content-Length", str(len(encoded)))
        self._no_store_headers()
        self.end_headers()
        if not getattr(self, '_head_only', False):
            self.wfile.write(encoded)

    def _json(self, data, status: int = 200, headers=None):
        encoded = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._security_headers()
        self._no_store_headers()
        for key, value in (headers or {}).items():
            self.send_header(str(key), str(value))
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        if not getattr(self, '_head_only', False):
            self.wfile.write(encoded)

    def _require_allowed_host(self) -> bool:
        allowed, error = _core_validate_local_host_header(self.headers.get("Host", ""))
        if allowed:
            return True
        self._json({"error": error}, status=403)
        return False

    def _require_local_action_header(self, error_payload: dict[str, object] | None = None) -> bool:
        value = self.headers.get(LOCAL_ACTION_HEADER, "").strip().lower()
        if value in LOCAL_ACTION_VALUES:
            allowed, error = _core_validate_local_browser_source_headers(
                self.headers.get("Origin", ""),
                self.headers.get("Referer", ""),
            )
            if allowed:
                return True
            payload = dict(error_payload or {"updated": False})
            payload["error"] = error
            self._json(payload, status=403)
            return False
        payload = dict(error_payload or {"updated": False})
        payload["error"] = f"{LOCAL_ACTION_HEADER} header required for local mutations"
        self._json({
            **payload,
        }, status=403)
        return False

    def _require_mutation_rate_limit(self) -> bool:
        client_host = self.client_address[0] if self.client_address else "local"
        with _rate_limiter_lock:
            allowed, retry_after = _mutation_rate_limiter.check(client_host)
        if allowed:
            return True
        self._json(
            {
                "error": "local mutation rate limit exceeded",
                "retry_after_seconds": retry_after,
            },
            status=429,
            headers={"Retry-After": str(retry_after)},
        )
        return False

    def _method_not_allowed(self) -> None:
        self._head_only = False
        if not self._require_allowed_host():
            return
        self._json(
            {"error": "method not allowed; Link supports GET, HEAD, and POST"},
            status=405,
            headers={"Allow": "GET, HEAD, POST"},
        )

    def _read_json_or_reply(self, error_payload: dict[str, object]) -> dict | None:
        payload, error, status = self._read_json_body()
        if error:
            self._json({**error_payload, "error": error}, status=status)
            return None
        assert payload is not None
        return payload

    def _handle_rebuild_post(self, payload_builder: Callable[[], dict[str, object]]) -> None:
        if not self._require_local_action_header({"rebuilt": False}):
            return
        if self._read_json_or_reply({"rebuilt": False}) is None:
            return
        self._json(payload_builder())

    def _query_limit_or_reply(
        self,
        query: dict[str, list[str]],
        default: str,
        error_payload: dict[str, object] | None = None,
    ) -> int | None:
        limit, error = _parse_search_limit(query.get("limit", [default])[0])
        if error:
            self._json({**(error_payload or {}), "error": error}, status=400)
            return None
        assert limit is not None
        return limit

    def _read_json_body(self) -> tuple[dict | None, str | None, int]:
        content_type = self.headers.get("Content-Type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            return None, "Content-Type must be application/json", 415
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            return None, "Content-Length required", 411
        try:
            length = int(raw_length)
        except ValueError:
            return None, "invalid Content-Length", 400
        if length < 0:
            return None, "invalid Content-Length", 400
        if length > MAX_POST_BYTES:
            return None, f"request body too large; max {MAX_POST_BYTES} bytes", 413
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, "invalid JSON body", 400
        if not isinstance(payload, dict):
            return None, "JSON body must be an object", 400
        return payload, None, 200

    def _security_headers(self, content_security_policy: str = CONTENT_SECURITY_POLICY):
        for key, value in _core_local_security_headers(API_VERSION, content_security_policy):
            self.send_header(key, value)

    def _no_store_headers(self):
        for key, value in _core_local_no_store_headers():
            self.send_header(key, value)

    def _file(self, fpath, content_type):
        fpath = _safe_resolve(fpath)
        if not fpath or not _is_allowed_static_file(fpath):
            self._err("file")
            return
        if fpath.exists() and fpath.is_file():
            data = fpath.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            if content_type == "image/svg+xml":
                self._security_headers(content_security_policy=SVG_CONTENT_SECURITY_POLICY)
            else:
                self._security_headers()
            self._no_store_headers()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if not getattr(self, '_head_only', False):
                self.wfile.write(data)
        else:
            self._err("file")

    def log_message(self, *a): pass


def _parse_serve_args(argv: list[str], default_port: int = PORT, default_root: Path = ROOT) -> tuple[int, Path]:
    port = default_port
    root = default_root
    for index, arg in enumerate(argv):
        if arg in {"--host", "--bind"} or arg.startswith("--host=") or arg.startswith("--bind="):
            raise SystemExit("Link serve is local-only; host/bind options are not supported.")
        if arg == "--port":
            if index + 1 >= len(argv):
                raise SystemExit("--port requires a value")
            try:
                port = int(argv[index + 1])
            except ValueError as exc:
                raise SystemExit("--port must be an integer") from exc
        elif arg.startswith("--port="):
            try:
                port = int(arg.split("=", 1)[1])
            except ValueError as exc:
                raise SystemExit("--port must be an integer") from exc
        elif arg == "--root":
            if index + 1 >= len(argv):
                raise SystemExit("--root requires a value")
            root = Path(argv[index + 1]).expanduser().resolve()
        elif arg.startswith("--root="):
            root = Path(arg.split("=", 1)[1]).expanduser().resolve()
    if port < 1 or port > 65535:
        raise SystemExit("--port must be between 1 and 65535")
    return port, root


def _parse_serve_port(argv: list[str], default: int = PORT) -> int:
    port, _ = _parse_serve_args(argv, default_port=default, default_root=ROOT)
    return port


def _serve_bind_error_message(exc: OSError, port: int) -> str:
    if exc.errno in {errno.EADDRINUSE, 48, 98}:
        next_port = port + 1 if port < 65535 else 3000
        return (
            f"Link could not start because 127.0.0.1:{port} is already in use.\n"
            f"Try another port, for example: python serve.py --port {next_port}"
        )
    return f"Link could not start local server on 127.0.0.1:{port}: {exc}"


def main():
    global PORT, WIKI_DIR, RAW_DIR
    PORT, root = _parse_serve_args(sys.argv[1:], default_port=PORT, default_root=ROOT)
    WIKI_DIR = root / "wiki"
    RAW_DIR = root / "raw"
    try:
        with ThreadingLocalTCPServer(("127.0.0.1", PORT), Handler) as s:
            print(f"  Link → http://127.0.0.1:{PORT}")
            print("  Local-only: bound to 127.0.0.1; no public host mode.")
            print("  No auth: do not expose this server without your own authentication layer.")
            try: s.serve_forever()
            except KeyboardInterrupt: print("\n  stopped.")
    except OSError as exc:
        print(_serve_bind_error_message(exc, PORT), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
