#!/usr/bin/env python3
"""Small Link command runner.

Usage:
  python link.py init [target]
  python link.py serve [target]
  python link.py demo [target]
  python link.py try [target]
  python link.py proof [target]
  python link.py onboard [target]
  python link.py seed [project-dir] [target]
  python link.py welcome [target]
  python link.py prompts [target]
  python link.py status [target]
  python link.py health [target]
  python link.py operations [target]
  python link.py backup [target]
  python link.py restore-backup <backup-name-or-path> [target]
  python link.py compliance-export [target]
  python link.py team-sync [target]
  python link.py share <page-or-memory> [target]
  python link.py snapshot [target]
  python link.py doctor [target]
  python link.py migrate [target]
  python link.py validate [target]
  python link.py ingest-status [target]
  python link.py import-obsidian <vault> [target]
  python link.py remember "memory text" [target]
  python link.py propose-memories <file-or-text> [target]
  python link.py session-end <file-or-text> [target]
  python link.py capture-inbox [target]
  python link.py update-memory <name-or-title> "new memory text" [target]
  python link.py query "task or question" [target]
  python link.py graph-summary ["topic"] [target]
  python link.py benchmark ["query"] [target]
  python link.py brief ["task or question"] [target]
  python link.py recall "query" [target]
  python link.py profile [target]
  python link.py wins [target]
  python link.py memory-audit [target]
  python link.py archive-memory <name-or-title> [target]
  python link.py restore-memory <name-or-title> [target]
  python link.py forget-memory <name-or-title> [target] --confirm
  python link.py memory-inbox [target]
  python link.py memory-log [target]
  python link.py review-memory <name-or-title> [target]
  python link.py explain-memory <name-or-title> [target]
  python link.py rebuild-index [target]
  python link.py rebuild-backlinks [target]
  python link.py verify-mcp [target]
  python link.py connect <agent> [target]
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Collection
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parent
DEFAULT_DEMO_DIR = "link-demo"
DEFAULT_PROOF_DIR = "link-proof"
PROOF_MARKER = ".link-proof"
PROOF_MEMORY_TITLE = "Cross-agent Link proof"
PROOF_MEMORY_TEXT = (
    "For the Link cross-agent proof, remember that local agent memory should be "
    "available to every connected agent through the same local Markdown wiki."
)
SECRET_NAME_PATTERNS = (
    ".env",
    ".env.*",
    ".envrc",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "*.token",
    ".mcpregistry_*",
    "*.key",
    "*.pem",
    "*.p8",
    "*.p12",
    "*.jks",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
    "service-account*.json",
)
SKIP_SCAN_DIRS = {
    ".git",
    ".link-backups",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "dist",
    "build",
    ".venv",
    "venv",
    "node_modules",
}
SKIP_SCAN_SUFFIXES = {
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".pyc",
    ".tar",
    ".webp",
    ".whl",
    ".zip",
}
_BUNDLED_CORE = ROOT / "mcp_package"
if (_BUNDLED_CORE / "link_core").exists():
    sys.path.insert(0, str(_BUNDLED_CORE))

from link_core.memory import (
    classify_memory_segment as _core_classify_memory_segment,
    list_recipes as _core_list_recipes,
    render_recipes_text as _core_render_recipes_text,
    is_existing_memory_echo as _core_is_existing_memory_echo,
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
    is_active_memory as _core_is_active_memory,
    memory_merge_candidates as _core_memory_merge_candidates,
    memory_review_issues as _core_memory_review_issues,
    parse_time_expression as _core_parse_time_expression,
    proposal_fingerprint as _core_proposal_fingerprint,
    propose_memories_from_text as _core_propose_memories_from_text,
    recall_memories as _core_recall_memories,
    recall_abstention as _core_recall_abstention,
    recent_memories as _core_recent_memories,
    resolve_memory_page as _core_resolve_memory_page,
    set_memory_status as _core_set_memory_status,
    set_memory_visibility as _core_set_memory_visibility,
    top_tags as _core_top_tags,
    update_memory_page as _core_update_memory_page,
    write_memory_page as _core_write_memory_page,
)
from link_core.backup import (
    BackupError as _CoreBackupError,
    RestoreError as _CoreRestoreError,
    create_backup as _core_create_backup,
    list_backups as _core_list_backups,
    restore_backup as _core_restore_backup,
)
from link_core.audit_export import (
    build_compliance_export as _core_build_compliance_export,
    render_compliance_export_text as _core_render_compliance_export_text,
    write_compliance_export as _core_write_compliance_export,
)
from link_core.memory_log import (
    memory_log_payload as _core_memory_log_payload,
)
from link_core.memory_wins import (
    memory_wins_payload as _core_memory_wins_payload,
)
from link_core.team_sync import (
    build_team_sync_payload as _core_build_team_sync_payload,
    render_team_sync_text as _core_render_team_sync_text,
)
from link_core.share import (
    render_share_text as _core_render_share_text,
    share_page_payload as _core_share_page_payload,
)
from link_core.snapshot import (
    export_snapshot as _core_export_snapshot,
    render_snapshot_text as _core_render_snapshot_text,
)
from link_core.benchmark import (
    build_benchmark_payload as _core_build_benchmark_payload,
    render_benchmark_text as _core_render_benchmark_text,
)
from link_core.demo import (
    DemoError as _CoreDemoError,
    copy_runtime_files as _core_copy_runtime_files,
    create_demo_workspace as _core_create_demo_workspace,
)
from link_core.doctor import (
    apply_doctor_fixes as _core_apply_doctor_fixes,
    build_doctor_report as _core_build_doctor_report,
    required_paths as _core_required_paths,
    render_doctor_report as _core_render_doctor_report,
)
from link_core.cli_parser import (
    build_cli_parser as _core_build_cli_parser,
    dispatch_cli_command as _core_dispatch_cli_command,
)
from link_core.cli_admin import (
    render_backup_created_text as _core_render_backup_created_text,
    render_backup_list_text as _core_render_backup_list_text,
    render_backup_restore_text as _core_render_backup_restore_text,
    render_migrate_text as _core_render_migrate_text,
    render_rebuild_backlinks_text as _core_render_rebuild_backlinks_text,
    render_rebuild_index_text as _core_render_rebuild_index_text,
    render_status_text as _core_render_status_text,
    render_validate_text as _core_render_validate_text,
)
from link_core.cli_memory import (
    render_brief_text as _core_render_brief_text,
    render_explain_memory_text as _core_render_explain_memory_text,
    render_forget_memory_text as _core_render_forget_memory_text,
    render_memory_audit_text as _core_render_memory_audit_text,
    render_memory_inbox_text as _core_render_memory_inbox_text,
    render_memory_log_text as _core_render_memory_log_text,
    render_memory_status_text as _core_render_memory_status_text,
    render_memory_wins_text as _core_render_memory_wins_text,
    render_profile_text as _core_render_profile_text,
    render_propose_memories_text as _core_render_propose_memories_text,
    render_recall_text as _core_render_recall_text,
    render_review_memory_text as _core_render_review_memory_text,
    render_remember_text as _core_render_remember_text,
    render_set_memory_visibility_text as _core_render_set_memory_visibility_text,
    render_update_memory_text as _core_render_update_memory_text,
)
from link_core.capture import (
    capture_accept_memory_args as _core_capture_accept_memory_args,
    capture_accept_payload as _core_capture_accept_payload,
    capture_inbox as _core_capture_inbox,
    capture_proposal_selection as _core_capture_proposal_selection,
    capture_records as _core_capture_records,
    capture_proposal_fingerprints as _core_capture_proposal_fingerprints,
    capture_review_summary as _core_capture_review_summary,
    cli_capture_commands as _core_cli_capture_commands,
    dedup_pending_captures as _core_dedup_pending_captures,
    delete_capture_file as _core_delete_capture_file,
    find_conversation_capture as _core_find_conversation_capture,
    load_dismissed_fingerprints as _core_load_dismissed_fingerprints,
    pending_proposal_fingerprints as _core_pending_proposal_fingerprints,
    render_accept_capture_text as _core_render_accept_capture_text,
    render_capture_session_text as _core_render_capture_session_text,
    render_capture_inbox_text as _core_render_capture_inbox_text,
    render_delete_capture_text as _core_render_delete_capture_text,
    render_redact_capture_text as _core_render_redact_capture_text,
    render_session_end_text as _core_render_session_end_text,
    redact_capture_file as _core_redact_capture_file,
    write_session_capture as _core_write_session_capture,
)
from link_core.files import (
    atomic_write_json as _core_atomic_write_json,
    atomic_write_text as _core_atomic_write_text,
)
from link_core.guard import (
    guard_reminder as _core_guard_reminder,
    render_guard_text as _core_render_guard_text,
    recently_guarded as _core_recently_guarded,
    render_switch_nudge as _core_render_switch_nudge,
    switch_intent as _core_switch_intent,
)
from link_core.handoff import (
    clear_handoff as _core_clear_handoff,
    handoff_brief_block as _core_handoff_brief_block,
    pending_handoffs as _core_pending_handoffs,
    write_handoff as _core_write_handoff,
)
from link_core.importers import (
    collect_import_units as _core_collect_import_units,
)
from link_core.agent_instructions import (
    instruction_file_status as _core_instruction_file_status,
    refresh_instruction_file as _core_refresh_instruction_file,
)
from link_core.usage import (
    record_retrieval as _core_record_retrieval,
    usage_summary as _core_usage_summary,
)
from link_core.sync import (
    SyncError as _core_sync_error,
    sync_init as _core_sync_init,
    sync_status as _core_sync_status,
    sync_workspace as _core_sync_workspace,
    team_config as _core_team_config,
    team_init as _core_team_init,
    team_sync_workspace as _core_team_sync_workspace,
)
from link_core.ingest import (
    collect_ingest_status as _core_collect_ingest_status,
    render_ingest_status_text as _core_render_ingest_status_text,
)
from link_core.log import (
    append_log as _core_append_log,
    utc_timestamp as _core_utc_timestamp,
)
from link_core.mcp_verify import (
    build_mcp_verify_status as _core_build_mcp_verify_status,
    check_link_mcp_import as _core_check_link_mcp_import,
    display_command as _core_display_command,
    provision_link_extras as _core_provision_link_extras,
    python_is_externally_managed as _core_python_is_externally_managed,
    render_mcp_verify_text as _core_render_mcp_verify_text,
    resolve_mcp_python as _core_resolve_mcp_python,
    set_link_command_override as _core_set_link_command_override,
)
from link_core.mcp_connect import (
    build_mcp_connect_payload as _core_build_mcp_connect_payload,
    detect_installed_agents as _core_detect_installed_agents,
    read_agent_link_server as _core_read_agent_link_server,
    supported_agents as _core_supported_agents,
)
from link_core.agent_hooks import (
    build_agent_hooks_payload as _core_build_agent_hooks_payload,
    extract_transcript_text as _core_extract_transcript_text,
    hook_supported_agents as _core_hook_supported_agents,
    supports_agent_hooks as _core_supports_agent_hooks,
)
from link_core.consolidate import (
    build_consolidation_plan as _core_build_consolidation_plan,
    build_digest as _core_build_digest,
    render_digest_text as _core_render_digest_text,
    render_consolidate_text as _core_render_consolidate_text,
)
from link_core.semantic import (
    RERANK_CANDIDATES as _CORE_RERANK_CANDIDATES,
    load_reranker as _core_load_reranker,
    rerank_blend as _core_rerank_blend,
    build_semantic_status as _core_build_semantic_status,
    load_embedder as _core_load_semantic_embedder,
    refresh_memory_index as _core_refresh_semantic_index,
    render_semantic_status_text as _core_render_semantic_status_text,
    semantic_memory_scores as _core_semantic_memory_scores,
    semantic_provider as _core_semantic_provider,
)
from link_core.obsidian import (
    import_obsidian_vault as _core_import_obsidian_vault,
    render_import_obsidian_text as _core_render_import_obsidian_text,
)
from link_core.project_seed import (
    render_seed_project_text as _core_render_seed_project_text,
    seed_project_context as _core_seed_project_context,
)
from link_core.operations import (
    operation_report as _core_operation_report,
    recover_operation as _core_recover_operation,
    render_operation_recovery_text as _core_render_operation_recovery_text,
    render_operations_text as _core_render_operations_text,
)
from link_core.schema import (
    migrate_wiki as _core_migrate_wiki,
)
from link_core.security import (
    clean_text_input as _clean_text_input,
    injected_instruction_warnings as _core_injected_instruction_warnings,
)
from link_core.query import (
    query_link as _core_query_link,
)
from link_core.cli_query import (
    render_graph_summary_text as _core_render_graph_summary_text,
    render_query_text as _core_render_query_text,
)
from link_core.cli_runtime import (
    render_agent_hooks_text as _core_render_agent_hooks_text,
    render_demo_text as _core_render_demo_text,
    render_init_text as _core_render_init_text,
    render_mcp_connect_text as _core_render_mcp_connect_text,
    render_session_start_hook_text as _core_render_session_start_hook_text,
    render_onboard_text as _core_render_onboard_text,
    render_proof_text as _core_render_proof_text,
    render_start_text as _core_render_start_text,
    render_starter_prompts_text as _core_render_starter_prompts_text,
    render_try_text as _core_render_try_text,
    render_welcome_text as _core_render_welcome_text,
)
from link_core.prompts import (
    starter_prompt_payload as _core_starter_prompt_payload,
    welcome_payload as _core_welcome_payload,
)
from link_core.validation import (
    validate_wiki as _core_validate_wiki,
)
from link_core.version import (
    LINK_VERSION,
    workspace_runtime_is_older as _core_workspace_runtime_is_older,
)
from link_core.cli_style import (
    style_cli_text as _core_style_cli_text,
)
from link_core.status import (
    link_status as _core_link_status,
)
from link_core.wiki import (
    build_backlinks_from_cache as _core_build_backlinks_from_cache,
    build_wiki_cache as _core_build_wiki_cache,
    close_wiki_cache as _core_close_wiki_cache,
    graph_summary as _core_graph_summary,
    rebuild_index as _core_rebuild_index,
)
del _BUNDLED_CORE



def _build_backlinks(wiki_dir: Path) -> dict[str, dict[str, list[str]]]:
    cache = _core_build_wiki_cache(wiki_dir, use_persistent_cache=False)
    try:
        return _core_build_backlinks_from_cache(cache, body_only=False)
    finally:
        _core_close_wiki_cache(cache)


def _wiki_pages(wiki_dir: Path) -> list[Path]:
    return sorted(
        md for md in wiki_dir.rglob("*.md")
        if not md.name.startswith(".")
    )


def _missing_wiki_error(wiki_dir: Path) -> int:
    """Explain a missing wiki with a next step instead of a dead end."""
    print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
    print(
        "Point Link at your workspace (for example: "
        f"{_display_command(['lnk', 'status', str(Path.home() / 'link')])}) "
        f"or create one here with {_display_command(['lnk', 'init', '.'])}.",
        file=sys.stderr,
    )
    return 1


def _resolve_wiki_dir(target: Path) -> Path:
    target = target.expanduser().resolve()
    if target.name == "wiki" and (target / "index.md").exists():
        return target
    return target / "wiki"


def _resolve_link_root(target: Path) -> Path:
    target = target.expanduser().resolve()
    if target.name == "wiki" and (target / "index.md").exists():
        return target.parent
    return target


def _default_project(target: Path) -> str:
    return _core_default_project_for_target(target)


def _utc_timestamp() -> str:
    return _core_utc_timestamp()


def _memory_records(wiki_dir: Path) -> list[dict[str, object]]:
    return _core_memory_records(wiki_dir)


def _memory_review_issues(record: dict[str, object]) -> list[dict[str, str]]:
    return _core_memory_review_issues(record, review_command="review-memory")


def _memory_inbox(
    wiki_dir: Path,
    limit: int = 20,
    include_archived: bool = False,
    project: str | None = None,
) -> dict[str, object]:
    root = wiki_dir.parent
    return _core_memory_inbox(
        _memory_records(wiki_dir),
        limit=limit,
        include_archived=include_archived,
        review_command="review-memory",
        project=project,
        command_target=root,
    )


def _memory_explanation(wiki_dir: Path, identifier: str) -> dict[str, object]:
    return _core_memory_explanation(
        wiki_dir,
        identifier,
        records=_memory_records(wiki_dir),
        review_command="review-memory",
        backlinks_body_only=False,
        command_target=wiki_dir.parent,
    )


def _count_values(records: list[dict[str, object]], field: str) -> dict[str, int]:
    return _core_count_values(records, field)


def _top_tags(records: list[dict[str, object]], limit: int = 12) -> list[dict[str, object]]:
    return _core_top_tags(records, limit=limit)


def _emit_json_or_text(
    payload: dict[str, object],
    json_output: bool,
    renderer: Callable[[dict[str, object]], tuple[int, str]],
    *,
    json_code: int = 0,
) -> int:
    if json_output:
        print(json.dumps(payload, indent=2))
        return json_code
    code, text = renderer(payload)
    _print_text(text)
    return code


def _print_text(text: object) -> None:
    print(_core_style_cli_text(str(text)))


def _recent_memories(records: list[dict[str, object]]) -> list[dict[str, object]]:
    return _core_recent_memories(records)


def _memory_profile(wiki_dir: Path, limit: int = 10, project: str | None = None) -> dict[str, object]:
    return _core_memory_profile(
        _memory_records(wiki_dir),
        limit=limit,
        review_command="review-memory",
        project=project,
    )


def _memory_brief(
    wiki_dir: Path, query: str = "", limit: int = 6, project: str | None = None,
    context_path: str | None = None,
) -> dict[str, object]:
    records = _memory_records(wiki_dir)
    return _core_memory_brief(
        records,
        query=query,
        limit=limit,
        review_command="review-memory",
        project=project,
        command_target=wiki_dir.parent,
        semantic_scores=_core_semantic_memory_scores(wiki_dir.parent, query, records),
        context_path=context_path,
    )


def _query_link(wiki_dir: Path, query: str, budget: str = "medium", project: str | None = None) -> dict[str, object]:
    cache = _core_build_wiki_cache(wiki_dir)
    try:
        return _core_query_link(
            wiki_dir,
            query,
            cache,
            _memory_records(wiki_dir),
            budget=budget,
            project=project,
            review_command="review-memory",
        )
    finally:
        _core_close_wiki_cache(cache)


def _recall_memories(
    wiki_dir: Path,
    query: str,
    limit: int = 10,
    include_archived: bool = False,
    project: str | None = None,
    as_of: str | None = None,
    memory_type: str | None = None,
) -> list[dict[str, object]]:
    records = _memory_records(wiki_dir)
    # Rerank tier (optional): over-fetch candidates and let a local
    # cross-encoder blend into the final order. Explicit recall only —
    # hooks and briefs never take this path.
    reranker = _core_load_reranker()
    fetch = max(limit, _CORE_RERANK_CANDIDATES) if reranker is not None else limit
    results = _core_recall_memories(
        records,
        query,
        limit=fetch,
        include_archived=include_archived,
        project=project,
        semantic_scores=_core_semantic_memory_scores(wiki_dir.parent, query, records),
        context_path=str(Path.cwd()),
        as_of=as_of,
        memory_type=memory_type,
    )
    if reranker is not None:
        results = _core_rerank_blend(query, results, limit=limit, reranker=reranker)
    return results[:limit]


def _propose_memories_from_text(
    wiki_dir: Path,
    text: str,
    source: str = "inline",
    limit: int = 10,
    project: str | None = None,
    command_target: str | Path = ".",
    exclude_fingerprints: Collection[str] = (),
    curated: bool = False,
) -> dict[str, object]:
    return _core_propose_memories_from_text(
        text, _memory_records(wiki_dir), source=source, limit=limit,
        writes_memory=False, project=project, command_target=command_target,
        exclude_fingerprints=exclude_fingerprints, curated=curated,
    )


def _append_log(wiki_dir: Path, timestamp: str, operation: str, description: str, lines: list[str]) -> None:
    _core_append_log(wiki_dir, timestamp, operation, description, lines)


def _resolve_memory_page(wiki_dir: Path, identifier: str) -> tuple[Path | None, dict[str, object] | None, str | None]:
    return _core_resolve_memory_page(wiki_dir, identifier, records=_memory_records(wiki_dir))


def _memory_runtime(target: Path) -> tuple[Path, list[dict[str, object]]]:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        raise FileNotFoundError(f"missing wiki directory: {wiki_dir}")
    return wiki_dir, _memory_records(wiki_dir)


def _log_writer_for(wiki_dir: Path) -> Callable[[str, str, str, list[str]], None]:
    return lambda ts, operation, description, lines: _append_log(
        wiki_dir,
        ts,
        operation,
        description,
        lines,
    )


def _rebuild_memory_backlinks(wiki_dir: Path) -> bool:
    try:
        backlinks = _build_backlinks(wiki_dir)
    except OSError as exc:
        print(f"Could not rebuild backlinks: {exc}", file=sys.stderr)
        return False
    _core_atomic_write_json(wiki_dir / "_backlinks.json", backlinks)
    return True


def _memory_mutation_options(
    wiki_dir: Path,
    records: list[dict[str, object]],
    timestamp: str | None,
    project: str | None = None,
) -> dict[str, object]:
    return {
        "timestamp": timestamp or _utc_timestamp(),
        "records": records,
        "project": project,
        "log_writer": _log_writer_for(wiki_dir),
        "rebuild_backlinks": lambda: _rebuild_memory_backlinks(wiki_dir),
    }


def _required_memory_text(text: str, message: str) -> str:
    clean_text = text.strip()
    if not clean_text:
        raise ValueError(message)
    return clean_text


def _set_memory_status(
    target: Path,
    identifier: str,
    status: str,
    reason: str | None = None,
    timestamp: str | None = None,
) -> dict[str, object]:
    wiki_dir, records = _memory_runtime(target)
    return _core_set_memory_status(
        wiki_dir,
        identifier,
        status,
        reason=reason,
        timestamp=timestamp or _utc_timestamp(),
        records=records,
        log_writer=_log_writer_for(wiki_dir),
    )


def _set_memory_visibility(
    target: Path,
    identifier: str,
    visibility: str,
    timestamp: str | None = None,
) -> dict[str, object]:
    wiki_dir, records = _memory_runtime(target)
    return _core_set_memory_visibility(
        wiki_dir,
        identifier,
        visibility,
        timestamp=timestamp or _utc_timestamp(),
        records=records,
        log_writer=_log_writer_for(wiki_dir),
    )


def _mark_memory_reviewed(
    target: Path,
    identifier: str,
    note: str | None = None,
    timestamp: str | None = None,
) -> dict[str, object]:
    wiki_dir, records = _memory_runtime(target)
    return _core_mark_memory_reviewed(
        wiki_dir,
        identifier,
        note=note,
        timestamp=timestamp or _utc_timestamp(),
        records=records,
        review_command="review-memory",
        log_writer=_log_writer_for(wiki_dir),
    )


def _update_memory_page(
    target: Path,
    identifier: str,
    text: str,
    source: str = "manual",
    timestamp: str | None = None,
    allow_conflict: bool = False,
    project: str | None = None,
) -> dict[str, object]:
    wiki_dir, records = _memory_runtime(target)
    clean_text = _required_memory_text(text, "memory update text required")
    options = _memory_mutation_options(wiki_dir, records, timestamp, project)

    return _core_update_memory_page(
        wiki_dir, identifier, clean_text, source=source,
        review_command="review-memory", allow_conflict=allow_conflict,
        **options,
    )


def _write_memory_page(
    target: Path, text: str, title: str | None = None,
    memory_type: str = "note", scope: str = "user",
    tags: str | None = None, source: str = "manual",
    timestamp: str | None = None, allow_duplicate: bool = False,
    allow_conflict: bool = False, allow_secret: bool = False,
    project: str | None = None,
    visibility: str | None = None,
    review_after: str | None = None,
    expires_at: str | None = None,
    trigger: str | None = None,
    applies_when: str | None = None,
    supersedes: str | None = None,
    context: str | None = None,
) -> dict[str, object]:
    wiki_dir, records = _memory_runtime(target)
    clean_text = _required_memory_text(text, "memory text required")
    options = _memory_mutation_options(wiki_dir, records, timestamp, project)
    return _core_write_memory_page(
        wiki_dir, clean_text, title=title, memory_type=memory_type,
        scope=scope, tags=tags, source=source,
        visibility=visibility,
        review_after=review_after,
        expires_at=expires_at,
        trigger=trigger,
        applies_when=applies_when,
        supersedes=supersedes,
        context=context,
        allow_duplicate=allow_duplicate, allow_conflict=allow_conflict,
        allow_secret=allow_secret,
        **options,
    )


def _collect_ingest_status(target: Path) -> dict[str, object]:
    return _core_collect_ingest_status(target, skip_dirs=SKIP_SCAN_DIRS)


def _required_paths(target: Path) -> list[Path]:
    return _core_required_paths(target)


def _apply_doctor_fixes(target: Path) -> list[str]:
    return _core_apply_doctor_fixes(target)


def doctor(target: Path, fix: bool = False) -> int:
    report = _core_build_doctor_report(
        target,
        fix=fix,
        skip_dirs=SKIP_SCAN_DIRS,
        secret_name_patterns=SECRET_NAME_PATTERNS,
        skip_suffixes=SKIP_SCAN_SUFFIXES,
    )
    _print_text(_core_render_doctor_report(report))
    return 0 if report.healthy else 1


def validate(target: Path, strict: bool = False, json_output: bool = False) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    payload = _core_validate_wiki(wiki_dir, strict=strict)
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0 if payload["passed"] else 1

    code, text = _core_render_validate_text(payload, wiki_dir=wiki_dir)
    _print_text(text)
    return code


def migrate(target: Path, json_output: bool = False) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    payload = _core_migrate_wiki(wiki_dir)
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0 if payload["ok"] else 1

    code, text = _core_render_migrate_text(payload, wiki_dir=wiki_dir)
    _print_text(text)
    return code


def status(target: Path, include_validation: bool = False, json_output: bool = False) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    payload = _core_link_status(wiki_dir, version=LINK_VERSION, include_validation=include_validation)
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0 if payload["ready"] else 1

    code, text = _core_render_status_text(payload, wiki_dir=wiki_dir, version=LINK_VERSION)
    _print_text(text)
    return code


def _health_exit_code(payload: dict[str, object]) -> int:
    operations_payload = payload.get("operations")
    operation_count = 0
    if isinstance(operations_payload, dict):
        operation_count = int(operations_payload.get("operation_count") or 0)
    return 0 if payload.get("ready") and operation_count == 0 else 1


def _render_health_text(payload: dict[str, object]) -> str:
    status_payload = payload.get("status") if isinstance(payload.get("status"), dict) else {}
    operations_payload = payload.get("operations") if isinstance(payload.get("operations"), dict) else {}
    validation = status_payload.get("validation") if isinstance(status_payload.get("validation"), dict) else {}
    warnings = status_payload.get("warnings") if isinstance(status_payload.get("warnings"), list) else []
    operation_count = int(operations_payload.get("operation_count") or 0)
    stale_count = int(operations_payload.get("stale_count") or 0)
    failed_count = int(operations_payload.get("failed_count") or 0)
    active_count = int(operations_payload.get("active_count") or 0)
    validation_text = "not checked"
    if validation.get("checked"):
        validation_text = "passed" if validation.get("passed") else (
            f"failed ({validation.get('error_count', 0)} errors, {validation.get('warning_count', 0)} warnings)"
        )
    lines = [
        f"Link health: {status_payload.get('wiki')}",
        "",
        f"Version: {status_payload.get('version', LINK_VERSION)}",
        f"Ready: {'yes' if payload.get('ready') else 'no'}",
        f"Pages: {status_payload.get('page_count', 0)}",
        f"Memories: {status_payload.get('memory_count', 0)} total · {status_payload.get('needs_review_count', 0)} need review",
        f"Search backend: {status_payload.get('search_backend', 'unknown')}",
        f"Validation: {validation_text}",
        f"Operations: {operation_count} total · {stale_count} stale · {failed_count} failed · {active_count} active",
    ]
    if warnings:
        lines.extend(["", "Warnings:"])
        for warning in warnings[:8]:
            if isinstance(warning, dict):
                lines.append(f"- {warning.get('code', 'warning')}: {warning.get('message', '')}")
                if warning.get("detail"):
                    lines.append(f"  {warning.get('detail')}")
    actions = operations_payload.get("next_actions") if operation_count else status_payload.get("next_actions")
    if isinstance(actions, list) and actions:
        lines.extend(["", "Next:"])
        for action in actions[:5]:
            if not isinstance(action, dict):
                continue
            command = action.get("command")
            if command:
                lines.append(f"- {command}")
            else:
                label = action.get("label") or action.get("tool") or "next action"
                tool = action.get("tool")
                lines.append(f"- {label}" + (f" ({tool})" if tool else ""))
    return "\n".join(str(line) for line in lines)


def health(target: Path, json_output: bool = False) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    status_payload = _core_link_status(wiki_dir, version=LINK_VERSION, include_validation=True)
    operations_payload = _core_operation_report(wiki_dir, limit=20)
    payload = {
        "version": LINK_VERSION,
        "ready": bool(status_payload.get("ready")) and not operations_payload.get("operation_count"),
        "status": status_payload,
        "operations": operations_payload,
    }
    code = _health_exit_code(payload)
    if json_output:
        print(json.dumps(payload, indent=2))
        return code
    _print_text(_render_health_text(payload))
    return code


def operations(
    target: Path,
    limit: int = 20,
    recover: str | None = None,
    confirm: bool = False,
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if recover:
        payload = _core_recover_operation(wiki_dir, recover, confirm=confirm)
        code, text = _core_render_operation_recovery_text(payload, target=target)
        if json_output:
            print(json.dumps(payload, indent=2))
            return code
        _print_text(text)
        return code
    payload = _core_operation_report(wiki_dir, limit=limit)
    code, text = _core_render_operations_text(payload)
    if json_output:
        print(json.dumps(payload, indent=2))
        return code
    _print_text(text)
    return code


def backup(
    target: Path,
    *,
    label: str = "manual",
    include_raw: bool = False,
    list_only: bool = False,
    json_output: bool = False,
) -> int:
    target = _resolve_link_root(target)
    if list_only:
        payload = _core_list_backups(target)
        if json_output:
            print(json.dumps(payload, indent=2))
            return 0
        code, text = _core_render_backup_list_text(payload)
        _print_text(text)
        return code

    try:
        payload = _core_create_backup(target, label=label, include_raw=include_raw)
    except (FileNotFoundError, _CoreBackupError) as exc:
        if json_output:
            print(json.dumps({"created": False, "error": str(exc)}, indent=2))
        else:
            print(str(exc), file=sys.stderr)
        return 1

    if json_output:
        print(json.dumps(payload, indent=2))
        return 0

    code, text = _core_render_backup_created_text(payload, include_raw=include_raw)
    _print_text(text)
    return code


def restore_backup(
    target: Path,
    backup: str,
    *,
    include_raw: bool = False,
    confirm: bool = False,
    safety_backup: bool = True,
    json_output: bool = False,
) -> int:
    target = _resolve_link_root(target)
    try:
        payload = _core_restore_backup(
            target,
            backup,
            include_raw=include_raw,
            confirm=confirm,
            safety_backup=safety_backup,
        )
    except (FileNotFoundError, _CoreBackupError, _CoreRestoreError) as exc:
        if json_output:
            print(json.dumps({"restored": False, "error": str(exc)}, indent=2))
        else:
            print(str(exc), file=sys.stderr)
        return 1

    if json_output:
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("restored") or payload.get("confirmation_required") else 1

    code, text = _core_render_backup_restore_text(payload, target=target)
    _print_text(text)
    return code


def compliance_export(
    target: Path,
    output: str | None = None,
    project: str | None = None,
    limit: int = 100,
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    payload = _core_build_compliance_export(
        wiki_dir,
        version=LINK_VERSION,
        project=project or _default_project(target),
        limit=limit,
    )
    if output:
        output_path = Path(output).expanduser()
        _core_write_compliance_export(output_path, payload)
        if json_output:
            print(json.dumps({"wrote": str(output_path), "export": payload}, indent=2))
            return 0
        code, text = _core_render_compliance_export_text(payload, output=str(output_path))
        _print_text(text)
        return code
    print(json.dumps(payload, indent=2))
    return 0


def team_sync(
    target: Path,
    remote: str | None = None,
    init: bool = False,
    team_dir: str | None = None,
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    root = _resolve_link_root(target)
    wiki_dir = _resolve_wiki_dir(target)
    try:
        if init:
            if not wiki_dir.exists():
                return _missing_wiki_error(wiki_dir)
            chosen = Path(team_dir).expanduser() if team_dir else root.parent / f"{root.name}-team"
            payload: dict[str, object] = _core_team_init(root, chosen, remote=remote)
            if json_output:
                print(json.dumps(payload, indent=2))
                return 0
            lines = [f"Team workspace ready: {payload.get('team_dir')}"]
            if payload.get("remote"):
                lines.append(f"Shared remote: {payload.get('remote')}")
            else:
                lines.append("Add the shared remote your team pushes to: "
                             + _shell_words_for_target("team-sync", target, "--init", "--remote", "<git-url>"))
            lines.append("Only memories you mark visibility: team are ever shared.")
            lines.append(f"Daily: {_shell_words_for_target('team-sync', target)}")
            _print_text("\n".join(lines))
            return 0
        if _core_team_config(root):
            if not wiki_dir.exists():
                return _missing_wiki_error(wiki_dir)
            payload = _core_team_sync_workspace(
                root, wiki_dir,
                regenerate=lambda: (_core_rebuild_index(wiki_dir), _rebuild_backlinks_quiet(wiki_dir)),
            )
            if json_output:
                print(json.dumps(payload, indent=2))
                return 0
            exported_obj = payload.get("exported")
            exported: list[object] = exported_obj if isinstance(exported_obj, list) else []
            imported_obj = payload.get("imported")
            imported: list[object] = imported_obj if isinstance(imported_obj, list) else []
            conflicts_obj = payload.get("conflicts")
            conflicts: list[object] = conflicts_obj if isinstance(conflicts_obj, list) else []
            parts = []
            if exported:
                parts.append(f"shared {len(exported)}")
            if imported:
                parts.append(f"imported {len(imported)}")
            _print_text("Team sync: " + (", ".join(parts) if parts else "already up to date"))
            for name in imported:
                _print_text(f"  new from the team: {name}")
            if conflicts:
                _print_text(f"  {len(conflicts)} memory(ies) differ from the team version — kept yours:")
                for name in conflicts:
                    _print_text(f"    {name} (edit and re-share, or adopt the team version deliberately)")
            return 0
    except _core_sync_error as exc:
        print(f"Team sync failed: {exc}", file=sys.stderr)
        return 1
    # Unconfigured and not initializing: keep the read-only guidance plan.
    payload = _core_build_team_sync_payload(target, remote=remote)
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0
    code, text = _core_render_team_sync_text(payload)
    _print_text(text)
    if code == 0:
        _print_text("\nOr let Link run the whole loop: "
                    + _shell_words_for_target("team-sync", target, "--init", "--remote", "<git-url>"))
    return code


def share(target: Path, identifier: str, port: int = 3000, host: str = "127.0.0.1", json_output: bool = False) -> int:
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    payload = _core_share_page_payload(wiki_dir, identifier, host=host, port=port)
    return _emit_json_or_text(payload, json_output, _core_render_share_text, json_code=0 if payload.get("found") else 1)


def snapshot(
    target: Path,
    output: str = "link-snapshot",
    include_memories: bool = False,
    include_private_memories: bool = False,
    allow_sensitive: bool = False,
    force: bool = False,
    title: str = "Link",
    json_output: bool = False,
) -> int:
    wiki_dir = _resolve_wiki_dir(target)
    payload = _core_export_snapshot(
        wiki_dir,
        Path(output),
        include_memories=include_memories,
        include_private_memories=include_private_memories,
        allow_sensitive=allow_sensitive,
        force=force,
        title=title,
    )
    return _emit_json_or_text(
        payload,
        json_output,
        _core_render_snapshot_text,
        json_code=0 if payload.get("created") else 1,
    )


def ingest_status(target: Path, json_output: bool = False) -> int:
    target = target.expanduser().resolve()
    status = _collect_ingest_status(target)

    if json_output:
        print(json.dumps(status, indent=2))
        return 0 if status["has_raw_dir"] and status["has_wiki_dir"] else 1

    _print_text(_core_render_ingest_status_text(str(target), status))
    return 0 if status["has_raw_dir"] and status["has_wiki_dir"] else 1


def import_obsidian(
    target: Path,
    vault: Path,
    overwrite: bool = False,
    dry_run: bool = False,
    limit: int | None = None,
    json_output: bool = False,
) -> int:
    try:
        payload = _core_import_obsidian_vault(
            target,
            vault,
            overwrite=overwrite,
            dry_run=dry_run,
            limit=limit,
        )
    except ValueError as exc:
        if json_output:
            print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        else:
            print(f"Could not import Obsidian vault: {exc}", file=sys.stderr)
        return 1
    return _emit_json_or_text(payload, json_output, _core_render_import_obsidian_text)


def stale(target: Path, *, repo: Path = Path(".")) -> int:
    """Report memories that name repository paths git no longer has.

    Read-only by design. A memory that mentions something that moved is a
    question for a person, not a rewrite to apply automatically, so findings
    are printed and the review gate stays where it is.
    """
    from link_core.staleness import StalenessChecker, describe_findings

    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    repo_dir = Path(repo).expanduser().resolve()
    # Archived and expired memories are already out of the way; questioning
    # them would only add noise to a report that must stay quiet by default.
    records = [record for record in _core_memory_records(wiki_dir) if _core_is_active_memory(record)]
    checker = StalenessChecker(repo_dir)
    flagged = 0
    for record in records:
        text = f"{record.get('body') or ''}\n{record.get('context') or ''}"
        findings = checker.findings(text)
        if not findings:
            continue
        flagged += 1
        print(f"{record.get('name') or record.get('path')}")
        for line in describe_findings(findings):
            print(f"  {line}")
    checked = len(records)
    if not flagged:
        print(f"No stale repository references in {checked} active memories ({repo_dir}).")
        return 0
    print(
        f"\n{flagged} of {checked} active memories name paths that moved in {repo_dir}."
        "\nNothing was changed. Review each one and update or archive it."
    )
    return 0


def rebuild_backlinks(target: Path) -> int:
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    try:
        backlinks = _build_backlinks(wiki_dir)
    except OSError as exc:
        print(f"Could not rebuild backlinks: {exc}", file=sys.stderr)
        return 1
    out_path = wiki_dir / "_backlinks.json"
    _core_atomic_write_json(out_path, backlinks)
    page_count = len(_wiki_pages(wiki_dir))
    edge_count = sum(len(targets) for targets in backlinks["forward"].values())
    code, text = _core_render_rebuild_backlinks_text(
        out_path=out_path,
        page_count=page_count,
        edge_count=edge_count,
    )
    _print_text(text)
    return code


def rebuild_index(target: Path) -> int:
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    try:
        result = _core_rebuild_index(wiki_dir)
    except OSError as exc:
        print(f"Could not rebuild index: {exc}", file=sys.stderr)
        return 1
    code, text = _core_render_rebuild_index_text(result, index_path=wiki_dir / "index.md")
    _print_text(text)
    return code


def remember(
    target: Path,
    text: str,
    title: str | None = None,
    memory_type: str | None = None,
    scope: str = "user",
    tags: str | None = None,
    source: str = "manual",
    allow_duplicate: bool = False,
    allow_conflict: bool = False,
    allow_secret: bool = False,
    project: str | None = None,
    visibility: str | None = None,
    review_after: str | None = None,
    expires_at: str | None = None,
    trigger: str | None = None,
    applies_when: str | None = None,
    supersedes: str | None = None,
    context: str | None = None,
    json_output: bool = False,
) -> int:
    if not text or not text.strip():
        print("Memory text is required", file=sys.stderr)
        return 1
    if memory_type is None:
        # "I prefer X" saved as a generic note gets the wrong trust window
        # and misses preference-scoped conflict checks. When the user didn't
        # choose a type, use the same cues the capture pipeline trusts.
        classified = _core_classify_memory_segment(text.strip().splitlines()[0])
        memory_type = str(classified["memory_type"]) if classified else "note"
    try:
        result = _write_memory_page(
            target,
            text,
            title=title,
            memory_type=memory_type,
            scope=scope,
            tags=tags,
            source=source,
            allow_duplicate=allow_duplicate,
            allow_conflict=allow_conflict,
            allow_secret=allow_secret,
            project=project or _default_project(target),
            visibility=visibility,
            review_after=review_after,
            expires_at=expires_at,
            trigger=trigger,
            applies_when=applies_when,
            supersedes=supersedes,
            context=context,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Could not remember: {exc}", file=sys.stderr)
        if "missing wiki directory" in str(exc):
            print(
                f"No workspace yet? Create one with {_display_command(['lnk', 'onboard'])} "
                f"(builds {_default_workspace()}), then pathless commands find it automatically.",
                file=sys.stderr,
            )
        return 1

    return _emit_json_or_text(
        result,
        json_output,
        lambda payload: _core_render_remember_text(payload, target=target),
    )


def _read_proposal_input(target: Path, value: str) -> tuple[str, str]:
    raw = value.strip()
    if raw == "-":
        return sys.stdin.read(), "stdin"
    candidates = [Path(raw).expanduser()]
    target_path = target.expanduser()
    if not Path(raw).is_absolute():
        candidates.append((target_path / raw).expanduser())
    for candidate in candidates:
        try:
            is_file = candidate.exists() and candidate.is_file()
        except OSError:
            is_file = False
        if is_file:
            return candidate.read_text(encoding="utf-8", errors="replace"), str(candidate)
    return value, "inline"


def propose_memories(
    target: Path,
    source_input: str,
    limit: int = 10,
    project: str | None = None,
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    text, source = _read_proposal_input(target, source_input)
    if not text.strip():
        print("Memory proposal input is required", file=sys.stderr)
        return 1
    result = _propose_memories_from_text(
        wiki_dir,
        text,
        source=source,
        limit=max(1, min(limit, 20)),
        project=project or _default_project(target),
        command_target=target,
    )

    if json_output:
        print(json.dumps(result, indent=2))
        return 0

    code, text = _core_render_propose_memories_text(result)
    _print_text(text)
    return code


def capture_session(
    target: Path,
    source_input: str,
    title: str | None = None,
    limit: int = 10,
    project: str | None = None,
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    root = _resolve_link_root(target)
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)

    text, source = _read_proposal_input(root, source_input)
    if not text.strip():
        print("Session capture input is required", file=sys.stderr)
        return 1

    project_name = project or _default_project(root)
    capture_record = _core_write_session_capture(
        root,
        text=text,
        source=source,
        title=title,
        project=project_name,
        default_source="inline",
        path_source=True,
    )
    rel_path = str(capture_record["path"])
    result = _propose_memories_from_text(
        wiki_dir,
        text,
        source=rel_path,
        limit=max(1, min(limit, 20)),
        project=project_name,
        command_target=root,
    )
    payload = {
        "captured": True,
        "path": rel_path,
        "source_input": source,
        "title": capture_record["title"],
        "project": capture_record["project"],
        "secret_warnings": capture_record["secret_warnings"],
        "proposals": result,
    }
    _append_log(
        wiki_dir,
        str(capture_record["timestamp"]),
        "capture-session",
        f"Captured proposal-only session notes at {rel_path}",
        [
            f"Source input: {source}",
            f"Project: {capture_record['project'] or 'none'}",
            f"Secret warnings: {', '.join(capture_record['secret_warnings']) if capture_record['secret_warnings'] else 'none'}",
            f"Proposals: {result['count']}",
        ],
    )

    if json_output:
        print(json.dumps(payload, indent=2))
        return 0

    _print_text(_core_render_capture_session_text(payload))
    return 0


def session_end(
    target: Path,
    source_input: str,
    title: str | None = None,
    limit: int = 3,
    project: str | None = None,
    proposal_text: str | None = None,
    decision_trail: list[str] | None = None,
    conversation_id: str | None = None,
    exclude_fingerprints: Collection[str] = (),
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    root = _resolve_link_root(target)
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)

    text, source = _read_proposal_input(root, source_input)
    if not text.strip():
        print("Session-end input is required", file=sys.stderr)
        return 1

    project_name = project or _default_project(root)
    capture_record = _core_write_session_capture(
        root,
        text=text,
        source=source,
        title=title or "Session end",
        project=project_name,
        default_source="session-end",
        path_source=True,
        proposal_text=proposal_text,
        decision_trail=decision_trail,
        conversation_id=conversation_id,
    )
    rel_path = str(capture_record["path"])
    # The raw capture keeps the full session for review context, but memory
    # proposals are mined from proposal_text when given (the user's turns only)
    # so the assistant's prose is never proposed as the user's preference.
    result = _propose_memories_from_text(
        wiki_dir,
        proposal_text if proposal_text is not None else text,
        source=rel_path,
        limit=max(1, min(limit, 10)),
        project=project_name,
        command_target=root,
        exclude_fingerprints=exclude_fingerprints,
    )
    payload = {
        "captured": True,
        "path": rel_path,
        "source_input": source,
        "title": capture_record["title"],
        "project": capture_record["project"],
        "secret_warnings": capture_record["secret_warnings"],
        "proposals": result,
    }
    _append_log(
        wiki_dir,
        str(capture_record["timestamp"]),
        "session-end",
        f"Captured proposal-only session end notes at {rel_path}",
        [
            f"Source input: {source}",
            f"Project: {capture_record['project'] or 'none'}",
            f"Secret warnings: {', '.join(capture_record['secret_warnings']) if capture_record['secret_warnings'] else 'none'}",
            f"Proposals: {result['count']}",
        ],
    )

    if json_output:
        print(json.dumps(payload, indent=2))
        return 0

    _print_text(_core_render_session_end_text(payload))
    return 0


def _capture_records(target: Path, limit: int = 20, project: str | None = None) -> list[dict[str, object]]:
    root = _resolve_link_root(target)
    return _core_capture_records(
        root,
        limit=limit,
        project=project,
        commands_for=lambda rel_path: _core_cli_capture_commands(rel_path, root),
    )


def capture_inbox(
    target: Path,
    limit: int = 20,
    project: str | None = None,
    json_output: bool = False,
    proposal_limit: int = 3,
) -> int:
    target = target.expanduser().resolve()
    root = _resolve_link_root(target)
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    payload = _core_capture_inbox(
        root,
        limit=limit,
        project=project,
        proposal_limit=max(1, min(proposal_limit, 50)),
        commands_for=lambda rel_path: _core_cli_capture_commands(rel_path, root),
    )
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0

    _print_text(_core_render_capture_inbox_text(payload))
    return 0


def _capture_review_summary(target: Path, project: str | None = None, limit: int = 3) -> dict[str, object]:
    root = _resolve_link_root(target)
    summary = _core_capture_review_summary(
        root,
        limit=limit,
        project=project,
        commands_for=lambda rel_path: _core_cli_capture_commands(rel_path, root),
    )
    summary["next_action"] = f'python3 link.py capture-inbox "{root}"'
    if summary["project"]:
        summary["next_action"] = f'python3 link.py capture-inbox "{root}" --project "{summary["project"]}"'
    return summary


def _accept_capture_all(
    target: Path, root: Path, wiki_dir: Path, capture: str,
    *, project: str | None, json_output: bool,
) -> int:
    """Accept every proposal in one capture; duplicates and conflicts are
    skipped and reported, never forced. The review gate stays - this is a
    faster hand, not a bypass."""
    try:
        selection = _core_capture_proposal_selection(
            root, capture, index=1, project=project,
            default_project=_default_project(root),
            propose_memories=lambda notes, rel_path, proposal_limit, project_name, curated=False: _propose_memories_from_text(
                wiki_dir, notes, source=rel_path, limit=50,
                project=project_name, command_target=root,
                exclude_fingerprints=set(_core_load_dismissed_fingerprints(root)),
                curated=curated,
            ),
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    proposals_obj = selection.get("proposals")
    items = proposals_obj.get("proposals") if isinstance(proposals_obj, dict) else []
    items = [item for item in items if isinstance(item, dict)]
    created, skipped = [], []
    for position, proposal in enumerate(items, start=1):
        pseudo = dict(selection)
        pseudo["proposal"] = proposal
        pseudo["proposal_index"] = position
        args = _core_capture_accept_memory_args(pseudo)
        result = _write_memory_page(
            target, str(args["text"]), title=str(args["title"]),
            memory_type=str(args["memory_type"]), scope=str(args["scope"]),
            visibility=str(args["visibility"] or "") or None,
            tags=args["tags"] if isinstance(args["tags"], str) else None,
            source=str(args["source"]), allow_duplicate=False, allow_conflict=False,
            project=str(args["project"]),
            trigger=str(args.get("trigger") or "") or None,
            context=str(args.get("context") or "") or None,
        )
        if result.get("created"):
            created.append(str(result.get("name")))
        else:
            reason = "conflict" if result.get("conflict") else "duplicate"
            skipped.append({"index": position, "title": str(args["title"]), "reason": reason})
    cleared = False
    if created and not skipped:
        capture_path = selection.get("capture_path")
        if isinstance(capture_path, Path) and capture_path.is_file():
            capture_path.unlink()
            cleared = True
    if created:
        _append_log(
            wiki_dir, _core_utc_timestamp(), "accept-capture",
            f"Accepted {len(created)} proposal(s) from {selection['capture']}",
            [f"- {name}" for name in created],
        )
    if json_output:
        print(json.dumps({
            "accepted": created, "skipped": skipped, "capture_cleared": cleared,
        }, indent=2))
        return 0
    _print_text(f"Accepted {len(created)} of {len(items)} proposal(s)")
    for name in created:
        _print_text(f"  + {name}")
    for item in skipped:
        _print_text(f"  \u00b7 skipped #{item['index']} ({item['reason']}): {item['title']}")
    if skipped:
        _print_text("\nSkipped items need a human call: accept individually with --index N"
                    " (add --allow-duplicate/--allow-conflict only after checking).")
    if cleared:
        _print_text("Capture cleared - everything it offered is now memory.")
    return 0


def accept_capture(
    target: Path,
    capture: str,
    index: int = 1,
    title: str | None = None,
    memory_type: str | None = None,
    scope: str | None = None,
    tags: str | None = None,
    project: str | None = None,
    visibility: str | None = None,
    allow_duplicate: bool = False,
    allow_conflict: bool = False,
    accept_all: bool = False,
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    root = _resolve_link_root(target)
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    if accept_all:
        return _accept_capture_all(target, root, wiki_dir, capture, project=project, json_output=json_output)
    try:
        selection = _core_capture_proposal_selection(
            root,
            capture,
            index=index,
            project=project,
            default_project=_default_project(root),
            # Exclude dismissed proposals exactly like inbox previews do, so
            # "accept proposal 1" targets the same item the user saw listed.
            propose_memories=lambda notes, rel_path, proposal_limit, project_name, curated=False: _propose_memories_from_text(
                wiki_dir,
                notes,
                source=rel_path,
                limit=proposal_limit,
                project=project_name,
                command_target=root,
                exclude_fingerprints=set(_core_load_dismissed_fingerprints(root)),
                curated=curated,
            ),
        )
    except ValueError as exc:
        message = str(exc)
        if message.startswith("capture not found:"):
            message = f"Capture not found under {root}: {capture}"
        elif message == "capture has no notes":
            message = f"Capture has no notes: {capture}"
        elif message.startswith("proposal index"):
            message = message[:1].upper() + message[1:]
        elif message.startswith("capture has"):
            message = message[:1].upper() + message[1:]
        print(message, file=sys.stderr)
        return 1

    rel_path = str(selection["capture"])
    memory_args = _core_capture_accept_memory_args(
        selection,
        title=title,
        memory_type=memory_type,
        scope=scope,
        visibility=visibility,
        tags=tags,
    )
    result = _write_memory_page(
        target,
        str(memory_args["text"]),
        title=str(memory_args["title"]),
        memory_type=str(memory_args["memory_type"]),
        scope=str(memory_args["scope"]),
        visibility=str(memory_args["visibility"] or "") or None,
        tags=memory_args["tags"] if isinstance(memory_args["tags"], str) else None,
        source=str(memory_args["source"]),
        allow_duplicate=allow_duplicate,
        allow_conflict=allow_conflict,
        project=str(memory_args["project"]),
        trigger=str(memory_args.get("trigger") or "") or None,
        context=str(memory_args.get("context") or "") or None,
    )
    payload = _core_capture_accept_payload(selection, result)
    if result.get("created"):
        # A capture is proposal-only staging. Once its accepted claim is a
        # memory, the file only earns its inbox slot if it still offers
        # something fresh — otherwise the user would have to delete what
        # they already handled (found in the cold walk).
        try:
            capture_path = selection.get("capture_path")
            if isinstance(capture_path, Path) and capture_path.is_file():
                remaining = _core_capture_proposal_fingerprints(
                    capture_path.read_text(encoding="utf-8", errors="replace"),
                    project=str(memory_args["project"]) or None,
                )
                accepted_now = {
                    _core_proposal_fingerprint(str(record.get("tldr") or record.get("snippet") or ""))
                    for record in _memory_records(wiki_dir)
                }
                covered = accepted_now | set(_core_load_dismissed_fingerprints(root))
                if remaining and remaining <= covered:
                    capture_path.unlink()
                    payload["capture_cleared"] = True
        except OSError:
            pass
        _append_log(
            wiki_dir,
            _utc_timestamp(),
            "accept-capture",
            f"Accepted proposal {selection['proposal_index']} from {rel_path}",
            [
                f"Memory: {result['path']}",
                f"Project: {result.get('project') or 'none'}",
            ] + (["Capture cleared: nothing left to review."] if payload.get("capture_cleared") else []),
        )

    if json_output:
        print(json.dumps(payload, indent=2))
        return 0 if payload["accepted"] else 1

    code, text = _core_render_accept_capture_text(payload, target=target)
    _print_text(text)
    return code


def redact_capture(
    target: Path,
    capture: str,
    replacement: str = "[redacted-secret]",
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    root = _resolve_link_root(target)
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    try:
        payload = _core_redact_capture_file(
            root,
            capture,
            replacement=replacement,
        )
    except ValueError:
        print(f"Capture not found under {root}: {capture}", file=sys.stderr)
        return 1

    if payload["redacted"]:
        labels = payload.get("labels") if isinstance(payload.get("labels"), list) else []
        _append_log(
            wiki_dir,
            _utc_timestamp(),
            "redact-capture",
            f"Redacted secret-looking values from {payload['path']}",
            [
                f"Labels: {', '.join(labels)}",
                f"Replacement count: {payload['replacement_count']}",
            ],
        )
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0

    _print_text(_core_render_redact_capture_text(payload))
    return 0


def delete_capture(
    target: Path,
    capture: str | None,
    confirm: bool = False,
    delete_all: bool = False,
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    root = _resolve_link_root(target)
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    if delete_all:
        records = _core_capture_records(root, limit=500)
        if not records:
            _print_text("No pending captures.")
            return 0
        if not confirm:
            _print_text(
                f"Would delete {len(records)} pending capture(s) from {root}, "
                "recording their dismissals so the same proposals never return. "
                "Re-run with --confirm."
            )
            return 0
        deleted = []
        for record in records:
            try:
                _core_delete_capture_file(root, str(record.get("path")), confirm=True)
                deleted.append(str(record.get("path")))
            except ValueError:
                continue
        if json_output:
            print(json.dumps({"deleted": deleted, "count": len(deleted)}, indent=2))
        else:
            _print_text(f"Deleted {len(deleted)} capture(s); dismissals recorded.")
        return 0
    if not capture:
        print("delete-capture needs a capture filename, or --all --confirm", file=sys.stderr)
        return 1
    try:
        payload = _core_delete_capture_file(root, capture, confirm=confirm)
    except ValueError:
        print(f"Capture not found under {root}: {capture}", file=sys.stderr)
        return 1

    if not confirm:
        if json_output:
            print(json.dumps(payload, indent=2))
        else:
            _, text = _core_render_delete_capture_text(payload, target=target)
            _print_text(text)
        return 1

    _append_log(
        wiki_dir,
        _utc_timestamp(),
        "delete-capture",
        f"Deleted raw capture {payload['path']}",
        ["Deleted file only; capture contents were not logged."],
    )
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0
    code, text = _core_render_delete_capture_text(payload, target=target)
    _print_text(text)
    return code


def dedup_captures(
    target: Path,
    confirm: bool = False,
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    root = _resolve_link_root(target)
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    accepted = {
        _core_proposal_fingerprint(str(record.get("tldr") or record.get("snippet") or ""))
        for record in _memory_records(wiki_dir)
    }
    payload = _core_dedup_pending_captures(root, accepted_fingerprints=accepted, apply=confirm)
    if confirm and payload["removed"]:
        _append_log(
            wiki_dir,
            _utc_timestamp(),
            "dedup-captures",
            f"Removed {len(payload['removed'])} redundant capture(s) from the review inbox",
            [f"Removed: {path}" for path in payload["removed"][:20]],
        )
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0
    removable = payload["removable"] if isinstance(payload["removable"], list) else []
    kept_count = payload["kept_count"]
    lines = ["Capture inbox dedup"]
    if not removable:
        lines.append(f"Nothing redundant: {kept_count} capture(s), each offers something new.")
        _print_text("\n".join(lines))
        return 0
    verb = "Removed" if confirm else "Would remove"
    lines.append(f"{verb} {len(removable)} capture(s); keeping {kept_count} with fresh proposals.")
    for item in removable:
        if isinstance(item, dict):
            reason = "no proposals" if item.get("reason") == "no_proposals" else "everything already covered"
            lines.append(f"  - {item.get('path')} ({reason})")
    if not confirm:
        lines.extend(["", "Apply:", f"  {_shell_words_for_target('dedup-captures', target, '--confirm')}"])
    _print_text("\n".join(lines))
    return 0


def _shell_words_for_target(command: str, target: Path, *flags: str) -> str:
    return _core_display_command(["link", command, str(target), *flags])


def update_memory(
    target: Path,
    identifier: str,
    text: str,
    source: str = "manual",
    allow_conflict: bool = False,
    project: str | None = None,
    json_output: bool = False,
) -> int:
    if not text or not text.strip():
        print("Memory update text is required", file=sys.stderr)
        return 1
    try:
        result = _update_memory_page(
            target,
            identifier,
            text,
            source=source,
            allow_conflict=allow_conflict,
            project=project or _default_project(target),
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Could not update memory: {exc}", file=sys.stderr)
        return 1

    return _emit_json_or_text(
        result,
        json_output,
        lambda payload: _core_render_update_memory_text(payload, target=target),
    )


def set_memory_visibility(
    target: Path,
    identifier: str,
    visibility: str,
    json_output: bool = False,
) -> int:
    try:
        result = _set_memory_visibility(target, identifier, visibility)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Could not set memory visibility: {exc}", file=sys.stderr)
        return 1

    return _emit_json_or_text(
        result,
        json_output,
        lambda payload: _core_render_set_memory_visibility_text(payload, target=target),
    )


def recall(
    target: Path,
    query: str,
    limit: int = 10,
    json_output: bool = False,
    include_archived: bool = False,
    project: str | None = None,
    as_of: str | None = None,
    memory_type: str | None = None,
) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    project_name = project or _default_project(target)
    # Temporal recall in plain language: "what did we decide last quarter"
    # resolves to the exact as-of date and the topic is ranked without the
    # date words. An explicit --as-of always wins.
    search_query = query
    temporal = None if as_of else _core_parse_time_expression(query)
    if temporal and temporal.get("as_of"):
        as_of = str(temporal["as_of"])
        search_query = str(temporal["residual_query"]) or query
    try:
        results = _recall_memories(
            wiki_dir,
            search_query,
            limit=limit,
            include_archived=include_archived,
            project=project_name,
            as_of=as_of,
            memory_type=memory_type,
        )
    except ValueError as exc:
        print(f"Could not recall: {exc}", file=sys.stderr)
        return 1

    _core_record_retrieval(
        _resolve_link_root(target), "recall",
        [str(item.get("name") or "") for item in results], project=project_name or "",
    )

    if json_output:
        print(json.dumps({
            "query": query,
            "count": len(results),
            "include_archived": include_archived,
            "project": project_name,
            "as_of": as_of or "",
            "temporal": temporal or {},
            "abstention": _core_recall_abstention(results),
            "memories": results,
        }, indent=2))
        return 0

    if temporal and temporal.get("as_of"):
        _print_text(
            f"Temporal recall: \"{temporal['phrase']}\" -> as of {as_of} "
            f"(what was active then, not what is true now)\n"
        )
    elif temporal and temporal.get("unresolved_event"):
        _print_text(
            f"Note: \"{temporal['unresolved_event']}\" names an event, not a date — "
            f"searching by topic. Use --as-of YYYY-MM-DD to pin the moment.\n"
        )

    code, text = _core_render_recall_text(
        query=query,
        results=results,
        include_archived=include_archived,
        project=project_name,
        target=target,
        store_count=len(_memory_records(wiki_dir)) if not results else -1,
    )
    _print_text(text)
    return code


def archive_memory(target: Path, identifier: str, reason: str | None = None, json_output: bool = False) -> int:
    try:
        result = _set_memory_status(target, identifier, "archived", reason=reason)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Could not archive memory: {exc}", file=sys.stderr)
        return 1

    return _emit_json_or_text(
        result,
        json_output,
        lambda payload: _core_render_memory_status_text(payload, action="archive", target=target),
    )


def restore_memory(target: Path, identifier: str, json_output: bool = False) -> int:
    try:
        result = _set_memory_status(target, identifier, "active")
    except (FileNotFoundError, ValueError) as exc:
        print(f"Could not restore memory: {exc}", file=sys.stderr)
        return 1

    return _emit_json_or_text(
        result,
        json_output,
        lambda payload: _core_render_memory_status_text(payload, action="restore", target=target),
    )


def forget_memory(target: Path, identifier: str, confirm: bool = False, json_output: bool = False) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)

    def rebuild_memory_backlinks() -> bool:
        backlinks = _build_backlinks(wiki_dir)
        _core_atomic_write_json(wiki_dir / "_backlinks.json", backlinks)
        return True

    result = _core_forget_memory_page(
        wiki_dir,
        identifier,
        confirm=confirm,
        records=_memory_records(wiki_dir),
        timestamp=_utc_timestamp(),
        log_writer=lambda ts, operation, description, lines: _append_log(
            wiki_dir,
            ts,
            operation,
            description,
            lines,
        ),
        rebuild_backlinks=rebuild_memory_backlinks,
    )
    if json_output:
        print(json.dumps(result, indent=2))
        return 0 if result.get("forgotten") else 1

    code, text = _core_render_forget_memory_text(result, identifier=identifier, target=target)
    if not result.get("found"):
        print(text, file=sys.stderr)
    else:
        _print_text(text)
    return code


def memory_inbox(
    target: Path,
    limit: int = 20,
    include_archived: bool = False,
    project: str | None = None,
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    inbox = _memory_inbox(wiki_dir, limit=limit, include_archived=include_archived, project=project)

    return _emit_json_or_text(
        inbox,
        json_output,
        lambda payload: _core_render_memory_inbox_text(
            payload,
            target=target,
            include_archived=include_archived,
        ),
    )


def memory_log(target: Path, limit: int = 50, include_captures: bool = True, json_output: bool = False) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    payload = _core_memory_log_payload(wiki_dir, limit=limit, include_captures=include_captures)
    return _emit_json_or_text(
        payload,
        json_output,
        lambda data: _core_render_memory_log_text(data, target=target),
    )


def memory_wins(target: Path, limit: int = 6, project: str | None = None, json_output: bool = False) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    payload = _core_memory_wins_payload(
        wiki_dir, limit=limit, project=project,
        usage=_core_usage_summary(
            _resolve_link_root(target), days=30,
            records=[r for r in _memory_records(wiki_dir) if str(r.get("status") or "active") == "active"],
        ),
    )
    return _emit_json_or_text(
        payload,
        json_output,
        lambda data: _core_render_memory_wins_text(data, target=target),
    )


def review_memory(
    target: Path,
    identifier: str | None,
    note: str | None = None,
    review_all: bool = False,
    confirm: bool = False,
    json_output: bool = False,
) -> int:
    if review_all:
        return _review_all_pending(target, note=note, confirm=confirm, json_output=json_output)
    if not identifier:
        print("Memory identifier is required (or pass --all).", file=sys.stderr)
        return 1
    try:
        result = _mark_memory_reviewed(target, identifier, note=note)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Could not review memory: {exc}", file=sys.stderr)
        return 1

    return _emit_json_or_text(result, json_output, _core_render_review_memory_text)


def _review_all_pending(
    target: Path, note: str | None, confirm: bool, json_output: bool,
) -> int:
    """Bulk review: the human confirms the whole pending/due list at once.

    Still deliberate — the dry run lists exactly which memories will be
    marked reviewed, and nothing happens without --confirm.
    """
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    due: list[dict[str, object]] = []
    for record in _memory_records(wiki_dir):
        if str(record.get("status") or "active") != "active":
            continue
        codes = {issue["code"] for issue in _core_memory_review_issues(record)}
        if codes & {"pending_review", "review_due"}:
            due.append(record)
    if not due:
        payload: dict[str, object] = {"reviewed": [], "count": 0, "confirmed": confirm}
        if json_output:
            print(json.dumps(payload, indent=2))
        else:
            _print_text("Nothing pending: every active memory is reviewed and inside its trust window.")
        return 0
    if not confirm:
        lines = [f"{len(due)} memories would be marked reviewed:"]
        lines.extend(f"  - {record.get('title')} ({record.get('memory_type')})" for record in due)
        lines.extend(["", "Only proceed if the human confirmed each one is still accurate.",
                      f"Apply: {_shell_words_for_target('review-memory', target, '--all', '--confirm')}"])
        if json_output:
            print(json.dumps({"reviewed": [], "count": len(due), "confirmed": False,
                              "pending": [str(r.get("name")) for r in due]}, indent=2))
        else:
            _print_text("\n".join(lines))
        return 1
    reviewed: list[str] = []
    for record in due:
        try:
            _mark_memory_reviewed(target, str(record.get("name")), note=note)
            reviewed.append(str(record.get("name")))
        except (FileNotFoundError, ValueError) as exc:
            print(f"Could not review {record.get('name')}: {exc}", file=sys.stderr)
    if json_output:
        print(json.dumps({"reviewed": reviewed, "count": len(reviewed), "confirmed": True}, indent=2))
    else:
        _print_text(f"Marked {len(reviewed)} memories reviewed; trust windows re-armed.")
    return 0


def explain_memory(target: Path, identifier: str, json_output: bool = False) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    try:
        explanation = _memory_explanation(wiki_dir, identifier)
    except ValueError as exc:
        print(f"Could not explain memory: {exc}", file=sys.stderr)
        return 1

    if json_output:
        print(json.dumps(explanation, indent=2))
        return 0

    code, text = _core_render_explain_memory_text(explanation)
    _print_text(text)
    return code


def query(
    target: Path,
    query_text: str,
    budget: str = "medium",
    project: str | None = None,
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    query_text = _clean_text_input(query_text, max_len=500)
    project_name = project or _default_project(target)
    payload = _query_link(wiki_dir, query_text, budget=budget, project=project_name)
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0
    code, text = _core_render_query_text(payload, query_text=query_text, command_target=str(target))
    _print_text(text)
    return code


def graph_summary(
    target: Path,
    topic: str = "",
    limit: int = 40,
    depth: int = 1,
    max_edges: int = 120,
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    topic = _clean_text_input(topic, max_len=500)
    cache = _core_build_wiki_cache(wiki_dir)
    payload = _core_graph_summary(
        cache,
        topic=topic,
        limit=limit,
        depth=depth,
        max_edges=max_edges,
    )
    _core_close_wiki_cache(cache)
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0

    code, text = _core_render_graph_summary_text(payload, topic=topic)
    _print_text(text)
    return code


def benchmark(
    target: Path,
    query_text: str = "agent memory",
    budget: str = "small",
    project: str | None = None,
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    query_text = _clean_text_input(query_text, max_len=500)
    project_name = project or _default_project(target)
    payload = _core_build_benchmark_payload(
        target,
        wiki_dir,
        query_text=query_text,
        budget=budget,
        project=project_name,
        review_command="review-memory",
    )
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0

    _print_text(_core_render_benchmark_text(payload))
    return 0


def brief(
    target: Path,
    query: str = "",
    limit: int = 6,
    project: str | None = None,
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    query = _clean_text_input(query, max_len=500)
    project_name = project or _default_project(target)
    payload = _memory_brief(wiki_dir, query=query, limit=limit, project=project_name)
    payload = _core_add_capture_review_to_brief(
        payload,
        _capture_review_summary(target, project=project_name),
    )

    if json_output:
        print(json.dumps(payload, indent=2))
        return 0

    code, text = _core_render_brief_text(payload, query=query, project=project_name)
    _print_text(text)
    return code


def start(
    target: Path,
    task: str = "",
    limit: int = 6,
    project: str | None = None,
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    task = _clean_text_input(task, max_len=500)
    project_name = project or _default_project(target)
    status_payload = _core_link_status(wiki_dir, version=LINK_VERSION, include_validation=True)
    brief_payload = _memory_brief(wiki_dir, query=task, limit=limit, project=project_name)
    brief_payload = _core_add_capture_review_to_brief(
        brief_payload,
        _capture_review_summary(target, project=project_name),
        command_target=_resolve_link_root(target),
    )
    query_text = task or "your current task"
    relevant_obj = brief_payload.get("relevant_memories")
    relevant_list: list[object] = relevant_obj if isinstance(relevant_obj, list) else []
    # The push path: memory reached the agent without it deciding anything.
    # Recording it is what turns "your agents have memory" into a number.
    _core_record_retrieval(
        _resolve_link_root(target), "brief",
        [str(item.get("name") or "") for item in relevant_list if isinstance(item, dict)],
        project=project_name or "",
    )
    relevant_count = int(brief_payload.get("relevant_count") or len(relevant_list))
    project_seed_recommended = bool(status_payload.get("ready")) and not relevant_count and not int(
        status_payload.get("content_page_count") or 0
    )
    seed_command = _display_command(["link", "seed", ".", str(target)])
    context_preview: dict[str, object] | None = None
    if task and int(status_payload.get("content_page_count") or 0):
        preview_payload = _query_link(wiki_dir, task, budget="micro", project=project_name)
        if preview_payload.get("found"):
            context_preview = {
                "query": preview_payload.get("query", task),
                "budget": preview_payload.get("budget", "micro"),
                "recall_capsule": preview_payload.get("recall_capsule", {}),
                "follow_up": preview_payload.get("follow_up", []),
            }
    payload = {
        "target": str(target),
        "wiki": str(wiki_dir),
        "task": task,
        "project": project_name,
        "status": status_payload,
        "brief": brief_payload,
        "context_preview": context_preview or {},
        "commands": {
            "health": _display_command(["link", "health", str(target)]),
            "query": _display_command(["link", "query", query_text, str(target), "--budget", "micro"]),
            "brief": _display_command(["link", "brief", query_text, str(target)]),
            "remember": _display_command(["link", "remember", "<approved memory>", str(target)]),
            "review": _display_command(["link", "memory-inbox", str(target)]),
            "seed_project": seed_command,
        },
        "project_seed": {
            "recommended": project_seed_recommended,
            "reason": (
                "No source-backed project context or relevant memory found in this startup packet."
                if project_seed_recommended
                else ""
            ),
            "command": seed_command,
            "safety": (
                "Run from the project repo. Link reads allowlisted project docs/rules, "
                "secret-scans them, and writes source-backed wiki context without creating durable memory."
            ),
        },
        "agent_loop": [
            "Use this brief before asking the user to repeat durable context.",
            "Use query for task-specific context when this brief is not enough.",
            "Save memory only after explicit user approval.",
        ],
    }
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0 if status_payload["ready"] else 1

    _, brief_text = _core_render_brief_text(brief_payload, query=task, project=project_name)
    text_payload = {**payload, "brief_text": brief_text}
    code, text = _core_render_start_text(text_payload)
    _print_text(text)
    return code


def _read_hook_stdin() -> dict[str, object]:
    """Read the agent hook event JSON from stdin, if one was piped in."""
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        raw = sys.stdin.read()
    except OSError:
        return {}
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def semantic(target: Path, setup: bool = False, rebuild: bool = False, json_output: bool = False) -> int:
    """Show, set up, or rebuild the optional local semantic recall layer."""
    target = target.expanduser().resolve()
    root = _resolve_link_root(target)
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    records = _memory_records(wiki_dir)
    # The index embeds every memory (archived included — they stay inert in
    # default recall but let --include-archived benefit from semantic
    # matching), so the "Indexed X of Y" denominator must be the total,
    # not the active count: 16-of-6 was nonsense.
    total_count = len(records)
    action_error = ""
    action_result = ""
    if setup or rebuild:
        if setup and not json_output:
            _print_text(
                "Setting up semantic recall: this may download the local embedding model once. "
                "Recall itself never uses the network."
            )
        embedder = _core_load_semantic_embedder(allow_download=setup)
        if embedder is None and setup and _core_python_is_externally_managed():
            # PEP 668 (e.g. the Homebrew runtime python): a direct pip install
            # here would be refused, so provision Link's managed venv and run
            # the setup under it — same venv the MCP server uses.
            if not json_output:
                _print_text(
                    f"{sys.executable} cannot host the semantic extras (externally managed). "
                    "Provisioning ~/.link-mcp-venv with them instead..."
                )
            outcome = _core_provision_link_extras(sys.executable, LINK_VERSION)
            for note in outcome.get("notes", []):
                if not json_output:
                    _print_text(f"  {note}")
            if outcome.get("ready"):
                rerun = [str(outcome["python"]), str(ROOT / "link.py"), "semantic", str(root), "--setup"]
                if json_output:
                    rerun.append("--json")
                return subprocess.run(rerun, check=False).returncode
            action_error = (
                "Could not provision the semantic extras into ~/.link-mcp-venv. "
                "Create it by hand: python3 -m venv ~/.link-mcp-venv && "
                f'~/.link-mcp-venv/bin/python -m pip install "link-mcp[semantic,semantic-quality,rerank]=={LINK_VERSION}" '
                f"then rerun: ~/.link-mcp-venv/bin/python {ROOT / 'link.py'} semantic {root} --setup"
            )
        elif embedder is None:
            install_hint = f'{sys.executable} -m pip install "link-mcp[semantic]"'
            action_error = (
                f"Semantic provider unavailable for {sys.executable}. Install it first: {install_hint}"
                if setup
                else "Semantic model not available offline. Run: lnk semantic --setup"
            )
            mcp_python = _core_resolve_mcp_python(target, wiki_dir, None, default_python=sys.executable)
            if mcp_python != sys.executable:
                action_error += (
                    f"\nYour Link MCP Python is {mcp_python}. If you installed the extra there, "
                    f"set it up through the MCP runtime instead: "
                    f"{mcp_python} -m link_mcp --semantic-setup --wiki {wiki_dir}"
                )
        else:
            index = _core_refresh_semantic_index(root, records, embedder=embedder)
            items = index.get("items") if isinstance(index.get("items"), dict) else {}
            action_result = f"Indexed {len(items)} memories."
            if setup:
                # The rerank tier shares the fastembed dependency; setup is the
                # one sanctioned moment to fetch its model too. Never required:
                # a missing reranker just means retrieval-order results.
                reranker = _core_load_reranker(allow_download=True)
                if reranker is not None:
                    action_result += " Rerank tier ready: explicit recall now blends a local cross-encoder."
            if setup and _core_semantic_provider() == "fastembed":
                action_result += (
                    " Quality tier active: expect a ~5s model load per short-lived CLI command; "
                    "the MCP server loads it once and stays fast. Prefer instant CLI recall? "
                    "Set LINK_SEMANTIC_PROVIDER=model2vec (fast tier)."
                )
    payload = _core_build_semantic_status(
        root,
        memory_count=total_count,
        command_target=root,
        python_cmd=sys.executable,
        externally_managed=_core_python_is_externally_managed(),
    )
    if action_result:
        payload["action_result"] = action_result
    if action_error:
        payload["action_error"] = action_error
    if json_output:
        print(json.dumps(payload, indent=2))
        return 1 if action_error else 0
    code, text = _core_render_semantic_status_text(payload)
    if action_result:
        _print_text(action_result)
    if action_error:
        print(action_error, file=sys.stderr)
        code = 1
    _print_text(text)
    return code


def recipes(target: Path, project: str | None = None, limit: int = 50, json_output: bool = False) -> int:
    """List saved procedure memories with their triggers."""
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    project_name = project or _default_project(target)
    items = _core_list_recipes(_memory_records(wiki_dir), project=project_name, limit=limit)
    if json_output:
        print(json.dumps({"count": len(items), "project": project_name, "recipes": items}, indent=2))
        return 0
    code, text = _core_render_recipes_text(items, target=target)
    _print_text(text)
    return code


def consolidate(target: Path, limit: int = 50, project: str | None = None, json_output: bool = False) -> int:
    """Print a read-only consolidation plan for capture and review backlogs."""
    target = target.expanduser().resolve()
    root = _resolve_link_root(target)
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    captures_payload = _core_capture_inbox(
        root,
        limit=max(1, min(limit, 50)),
        project=project,
        commands_for=lambda rel_path: _core_cli_capture_commands(rel_path, root),
    )
    inbox_payload = _memory_inbox(wiki_dir, limit=max(1, min(limit, 50)), project=project)
    payload = _core_build_consolidation_plan(
        captures_payload=captures_payload,
        inbox_payload=inbox_payload,
        command_target=root,
        project=project,
        merge_candidates=_core_memory_merge_candidates(_memory_records(wiki_dir)),
    )
    return _emit_json_or_text(payload, json_output, _core_render_consolidate_text)


def _hook_project_dir(hook_event: dict[str, object]) -> str:
    """Return the project directory the hook fired in, across agent schemas."""
    hook_cwd = str(hook_event.get("cwd") or "").strip()
    if hook_cwd:
        return hook_cwd
    roots = hook_event.get("workspace_roots")
    if isinstance(roots, list) and roots and isinstance(roots[0], str) and roots[0].strip():
        return roots[0].strip()
    return ""


def _emit_session_start(text: str, emit: str) -> None:
    if emit == "cursor":
        print(json.dumps({"additional_context": text}))
        return
    print(text)


def _hook_session_start(
    target: Path, hook_event: dict[str, object], limit: int, project: str | None, emit: str
) -> int:
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        _emit_session_start(
            f"Link: wiki missing at {wiki_dir}; run {_display_command(['lnk', 'init', str(target)])} to restore it.",
            emit,
        )
        return 0
    project_name = project
    if not project_name:
        project_dir = _hook_project_dir(hook_event)
        if project_dir:
            project_name = _default_project(Path(project_dir))
    if not project_name:
        project_name = _default_project(target)
    status_payload = _core_link_status(wiki_dir, version=LINK_VERSION, include_validation=False)
    brief_payload = _memory_brief(
        wiki_dir, query="", limit=limit, project=project_name,
        context_path=_hook_project_dir(hook_event) or None,
    )
    brief_payload = _core_add_capture_review_to_brief(
        brief_payload,
        _capture_review_summary(target, project=project_name),
        command_target=_resolve_link_root(target),
    )
    relevant_count = int(brief_payload.get("relevant_count") or len(brief_payload.get("relevant_memories") or []))
    project_seed_recommended = bool(status_payload.get("ready")) and not relevant_count and not int(
        status_payload.get("content_page_count") or 0
    )
    # A waiting handoff outranks everything: it is the reason this session
    # exists. Pushed at the very top, never behind a tool call.
    handoff_block = _core_handoff_brief_block(
        _core_pending_handoffs(_resolve_link_root(target), project=project_name),
        clear_command=_display_command(["lnk", "handoffs", str(_resolve_link_root(target)), "--clear", "<file>"]),
    )
    _, brief_text = _core_render_brief_text(brief_payload, query="", project=project_name)
    captures_payload = brief_payload.get("captures") if isinstance(brief_payload.get("captures"), dict) else {}
    _, text = _core_render_session_start_hook_text({
        "target": str(target),
        "project": project_name,
        "status": status_payload,
        "brief_text": brief_text,
        "capture_count": int(captures_payload.get("count") or 0),
        "project_seed_recommended": project_seed_recommended,
        "backlog": brief_payload.get("backlog") or {},
    })
    if handoff_block:
        text = handoff_block + "\n\n" + text
    _emit_session_start(text, emit)
    return 0


def _session_end_hook_state_path(target: Path) -> Path:
    return _resolve_link_root(target) / ".link-cache" / "session-end-hook.hash"


def _session_notes_fingerprint(notes: str) -> str:
    normalized = " ".join(notes.split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _hook_session_end(
    target: Path, hook_event: dict[str, object], limit: int, project: str | None,
    explain: bool = False,
) -> int:
    trail: list[str] = []

    def _trace(message: str) -> None:
        trail.append(message)
        if explain:
            print(f"[session-end] {message}")

    transcript_value = str(hook_event.get("transcript_path") or "").strip()
    if not transcript_value:
        _trace("no transcript_path in the hook event; nothing to capture.")
        return 0
    transcript_path = Path(transcript_value).expanduser()
    extraction_stats: dict[str, int] = {}
    notes = _core_extract_transcript_text(transcript_path, stats=extraction_stats)
    _trace(
        f"Read the session: kept {extraction_stats.get('kept_messages', 0)} messages, "
        f"dropped {extraction_stats.get('dropped_link_output', 0)} carrying Link's own injected output (echo guard, layer 1)."
    )
    if len(notes.strip()) < 200:
        _trace("skipped: under 200 characters of conversation — nothing memory-worthy in a trivial session.")
        return 0
    # Memory proposals come from the user's own turns only. The assistant's
    # prose is help, not the user's preferences; mining it would attribute the
    # assistant's words to the user (found in dogfooding). The raw capture below
    # still keeps the full transcript for review context.
    # Mine from a head+tail window so an opening standing rule ("from now on…")
    # survives even in a long session, where a recency-only window would drop it.
    user_notes = _core_extract_transcript_text(
        transcript_path, roles=("user",), max_chars=9000, keep_head=True
    )
    _trace("Mined memory only from your own turns — the assistant's prose is never proposed as your preference.")
    # Skip duplicate firings for the same conversation content (e.g. /clear
    # immediately followed by exit, or repeated end events).
    state_path = _session_end_hook_state_path(target)
    fingerprint = _session_notes_fingerprint(notes)
    try:
        if state_path.exists() and state_path.read_text(encoding="utf-8").strip() == fingerprint:
            _trace("skipped: identical conversation content was already captured (duplicate end event).")
            return 0
    except OSError:
        pass
    project_name = project
    if not project_name:
        project_dir = _hook_project_dir(hook_event)
        if project_dir:
            project_name = _default_project(Path(project_dir))
    # Only store a capture when the user's turns produced memory-worthy
    # candidates; otherwise every session would add review-inbox noise.
    wiki_dir = _resolve_wiki_dir(target)
    root = _resolve_link_root(target)
    proposal_limit = max(1, min(limit, 10))
    preview = _propose_memories_from_text(
        wiki_dir,
        user_notes,
        source="agent-session-hook",
        limit=proposal_limit,
        project=project_name,
        command_target=root,
    )
    proposals = preview.get("proposals") if isinstance(preview.get("proposals"), list) else []
    _trace(f"extraction found {len(proposals)} memory proposal(s).")
    # Echo guard, second layer: a proposal that merely restates an existing
    # active memory — a strong duplicate, or a framing-diluted restatement
    # caught by containment — is Link hearing itself through the agent.
    # Automatic capture keeps only fresh or conflicting proposals; deliberate
    # refinements still flow through manual `lnk session-end`.
    records = _memory_records(wiki_dir)
    # A conversation is its transcript: the same chat continued across hours
    # keeps one identity, so its capture refreshes instead of stacking. Hashed
    # so capture files carry no machine-specific paths.
    conversation_id = hashlib.sha256(str(transcript_path).encode("utf-8")).hexdigest()[:16]
    dismissed = set(_core_load_dismissed_fingerprints(root))
    pending = _core_pending_proposal_fingerprints(root, exclude_conversation=conversation_id)
    fresh = []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        title = str(proposal.get("title") or "")[:60]
        if proposal.get("duplicate_candidates"):
            _trace(f"dropped '{title}': strong duplicate of an existing memory.")
            continue
        if _core_is_existing_memory_echo(records, str(proposal.get("memory") or "")):
            _trace(f"dropped '{title}': restates an existing memory (echo guard, layer 2).")
            continue
        fingerprint = _core_proposal_fingerprint(str(proposal.get("memory") or ""))
        if fingerprint in dismissed:
            _trace(f"dropped '{title}': you already dismissed this proposal.")
            continue
        if fingerprint in pending:
            _trace(f"dropped '{title}': already waiting for review in {pending[fingerprint]}.")
            continue
        injection_labels = _core_injected_instruction_warnings(str(proposal.get("memory") or ""))
        if injection_labels:
            # Kept, never censored — but the trail says what shape it has so
            # the reviewer knows to check whether they actually said it.
            _trace(
                f"flagged '{title}': {injection_labels[0]} — looks like an injected "
                "instruction; verify you actually said this before accepting."
            )
        fresh.append(proposal)
    if not fresh:
        _trace("no fresh proposals left; no capture stored.")
        return 0
    if _core_find_conversation_capture(root, conversation_id) is not None:
        _trace("Refreshed this conversation's existing capture in place — one conversation, one review item.")
    _trace(f"Stored a proposal-only capture with {len(fresh)} fresh proposal(s) for your review.")
    code = session_end(
        target,
        notes,
        title="Agent session notes" + (f" — {project_name}" if project_name else ""),
        limit=proposal_limit,
        project=project_name,
        proposal_text=user_notes,
        decision_trail=trail,
        conversation_id=conversation_id,
        exclude_fingerprints=dismissed | set(pending),
    )
    if code == 0:
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(fingerprint, encoding="utf-8")
        except OSError:
            pass
    return code



def _hook_prompt_check(target: Path, hook_event: dict[str, object], project: str | None) -> int:
    """Per-prompt guard: speak only when a saved constraint strongly
    overlaps the request. Silence is the normal, correct output."""
    prompt = str(hook_event.get("prompt") or hook_event.get("user_prompt") or "")
    if not prompt.strip():
        return 0
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return 0
    project_name = project or _default_project(target)
    reminder = _core_guard_reminder(
        _memory_records(wiki_dir), prompt, project=project_name,
    )
    if reminder is not None:
        root = _resolve_link_root(target)
        # Cooldown: the same constraint never repeats within a stretch of
        # work - one reminder is a guard, ten is a nag.
        if _core_recently_guarded(root, str(reminder.get("name") or "")):
            return 0
        _core_record_retrieval(
            root, "guard", [str(reminder.get("name") or "")],
            project=project_name or "",
        )
        print(_core_render_guard_text(reminder))
        return 0
    # No constraint in play - but a stop/switch announcement is the moment
    # the handoff should suggest itself.
    if _core_switch_intent(prompt):
        print(_core_render_switch_nudge())
    return 0


def run_agent_hook(
    target: Path, event: str, limit: int = 5, project: str | None = None, emit: str = "text",
    explain: bool = False,
) -> int:
    """Run an installed agent session hook; never fail the agent session."""
    target = target.expanduser().resolve()
    hook_event = _read_hook_stdin()
    try:
        if event == "session-start":
            return _hook_session_start(target, hook_event, limit, project, emit)
        if event == "session-end":
            return _hook_session_end(target, hook_event, limit, project, explain=explain)
        if event == "prompt-check":
            return _hook_prompt_check(target, hook_event, project)
        print(f"Unknown hook event: {event}", file=sys.stderr)
    except Exception as exc:
        print(f"Link {event} hook failed: {exc}", file=sys.stderr)
    return 0


def profile(target: Path, limit: int = 10, project: str | None = None, json_output: bool = False) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    project_name = project or _default_project(target)
    profile_data = _memory_profile(wiki_dir, limit=limit, project=project_name)

    if json_output:
        print(json.dumps(profile_data, indent=2))
        return 0

    code, text = _core_render_profile_text(profile_data, target=target, project=project_name)
    _print_text(text)
    return code


def _memory_audit_payload(target: Path, wiki_dir: Path, limit: int = 10, project: str | None = None) -> dict[str, object]:
    project_name = project or _default_project(target)
    profile_data = _memory_profile(wiki_dir, limit=limit, project=project_name)
    inbox = _memory_inbox(wiki_dir, limit=limit, include_archived=True, project=project_name)
    captures = _capture_review_summary(target, project=project_name, limit=min(limit, 10))
    payload = _core_memory_audit_report(profile_data, inbox, captures, [], project=project_name)
    payload["next_actions"] = _core_memory_audit_next_actions(
        mode="cli",
        inbox=inbox,
        captures=captures,
        risk_factors=payload["risk_factors"],
        project=str(payload["project"]),
        root=_resolve_link_root(target),
    )
    return payload


def memory_audit(target: Path, limit: int = 10, project: str | None = None, json_output: bool = False) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    payload = _memory_audit_payload(target, wiki_dir, limit=limit, project=project)

    if json_output:
        print(json.dumps(payload, indent=2))
        return 0

    code, text = _core_render_memory_audit_text(payload, target=target)
    _print_text(text)
    return code


def _display_command(parts: list[str]) -> str:
    return _core_display_command(parts)


def _lnk_on_path_runs_this_runtime() -> bool:
    """True when a `lnk` on PATH is a shim for this very runtime.

    Homebrew installs the runtime under .../Cellar/link/<ver>/libexec and a
    `lnk` shim in bin — users should see `lnk` in every generated command,
    never the interpreter + Cellar path leaking into the product's own
    suggested next steps.
    """
    if "/Cellar/link/" in str(ROOT):
        return True
    lnk = shutil.which("lnk")
    if not lnk:
        return False
    try:
        shim = Path(lnk).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return str(ROOT / "link.py") in shim


def _configure_link_command_display() -> None:
    if os.environ.get("LINK_CLI_COMMAND"):
        _core_set_link_command_override(None)
    elif _lnk_on_path_runs_this_runtime():
        _core_set_link_command_override(None)
    else:
        _core_set_link_command_override([sys.executable, str(ROOT / "link.py")])


def verify_mcp(
    target: Path,
    json_output: bool = False,
    python_cmd: str | None = None,
    import_check: Callable[[str], dict[str, object]] = _core_check_link_mcp_import,
    agent: str | None = None,
) -> int:
    agent_note: str | None = None
    if agent:
        # Verify what the agent is actually configured to run, not a guess.
        if str(target) == ".":
            target = _default_workspace()
        server = _core_read_agent_link_server(agent)
        if not server.get("configured"):
            message = (
                f"{server.get('display_name')} has no Link MCP server configured "
                f"({server.get('config_path')}).\n"
                "Write one with: "
                + _display_command(["lnk", "connect", str(server.get("agent")), str(target), "--write"])
            )
            if json_output:
                print(json.dumps({"ready": False, "agent": server}, indent=2))
            else:
                _print_text(message)
            return 1
        python_cmd = str(server.get("python"))
        configured_wiki = server.get("wiki")
        if configured_wiki:
            wiki_path = Path(str(configured_wiki)).expanduser()
            target = wiki_path.parent if wiki_path.name == "wiki" else wiki_path
        agent_note = (
            f"Verifying the Link server {server.get('display_name')} is configured to run "
            f"({server.get('config_path')})."
        )
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    status = _core_build_mcp_verify_status(
        target=target,
        wiki_dir=wiki_dir,
        init_command=[sys.executable, str(ROOT / "link.py"), "init", str(target)],
        expected_version=LINK_VERSION,
        python_cmd=python_cmd,
        default_python=sys.executable,
        import_check=import_check,
    )

    if json_output:
        print(json.dumps(status, indent=2))
        return 0 if status["ready"] else 1

    code, text = _core_render_mcp_verify_text(status)
    if agent_note:
        _print_text(agent_note + "\n")
    _print_text(text)
    return code


def connect_mcp(
    target: Path,
    agent: str,
    *,
    write: bool = False,
    config_path: str | None = None,
    python_cmd: str | None = None,
    hooks: bool = False,
    hooks_settings: str | None = None,
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if hooks and not _core_supports_agent_hooks(agent):
        supported = ", ".join(_core_hook_supported_agents())
        print(f"--hooks is not supported for {agent}. Session hooks are available for: {supported}", file=sys.stderr)
        return 1
    payload = _core_build_mcp_connect_payload(
        target=target,
        wiki_dir=wiki_dir,
        agent=agent,
        expected_version=LINK_VERSION,
        init_command=[sys.executable, str(ROOT / "link.py"), "init", str(target)],
        python_cmd=python_cmd,
        default_python=sys.executable,
        config_path=config_path,
        write=write,
    )
    hooks_payload: dict[str, object] | None = None
    if hooks:
        runtime_script = target / "link.py"
        runtime_note = ""
        if runtime_script.exists():
            # A workspace runtime copied before session hooks existed would
            # make every installed hook fail with an argparse error, and an
            # older runtime silently runs old capture behavior after upgrades.
            stale_version = _core_workspace_runtime_is_older(target, LINK_VERSION)
            if not (target / "link_core" / "agent_hooks.py").exists():
                if write:
                    _copy_runtime_files(target)
                    runtime_note = f"Refreshed the Link runtime at {target}: it predated session hooks."
                else:
                    runtime_note = (
                        f"The Link runtime at {target} predates session hooks; "
                        "--write will refresh it automatically (or run "
                        f"{_display_command(['lnk', 'init', str(target)])} first)."
                    )
            elif stale_version:
                if write:
                    _copy_runtime_files(target)
                    runtime_note = (
                        f"Refreshed the Link runtime at {target}: "
                        f"{stale_version} → {LINK_VERSION} (hooks run the workspace copy)."
                    )
                else:
                    runtime_note = (
                        f"The Link runtime at {target} is {stale_version} but installed Link is "
                        f"{LINK_VERSION}; --write will refresh it (or run "
                        f"{_display_command(['lnk', 'init', str(target)])})."
                    )
        else:
            runtime_script = ROOT / "link.py"
        hooks_payload = _core_build_agent_hooks_payload(
            target=target,
            agent=agent,
            runtime_script=runtime_script,
            python_cmd=sys.executable,
            settings_path=hooks_settings,
            write=write,
        )
        if runtime_note:
            hooks_payload["runtime_note"] = runtime_note
        payload["session_hooks"] = hooks_payload

    if json_output:
        print(json.dumps(payload, indent=2))
        write_status = payload.get("write") if isinstance(payload.get("write"), dict) else {}
        ok = not write or bool(write_status.get("ok"))
        if write and hooks_payload is not None:
            hooks_write = hooks_payload.get("write") if isinstance(hooks_payload.get("write"), dict) else {}
            ok = ok and bool(hooks_write.get("ok"))
        return 0 if ok else 1

    code, text = _core_render_mcp_connect_text(payload)
    _print_text(text)
    if hooks_payload is not None:
        hooks_code, hooks_text = _core_render_agent_hooks_text(hooks_payload)
        print()
        _print_text(hooks_text)
        code = code or hooks_code
    return code


def _copy_runtime_files(target: Path) -> None:
    _core_copy_runtime_files(ROOT, target)


def init_wiki(target: Path) -> int:
    target = target.expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    _copy_runtime_files(target)
    fixes = _apply_doctor_fixes(target)

    code, text = _core_render_init_text(target=target, fixes=fixes)
    _print_text(text)
    return code


def _onboard_agent_names(agents: list[str] | None, all_agents: bool) -> list[str]:
    requested: list[str] = list(_core_supported_agents()) if all_agents else []
    requested.extend(agents or [])
    return list(dict.fromkeys(agent.strip() for agent in requested if agent and agent.strip()))


def import_memory(
    target: Path,
    *,
    source: str,
    file_path: str | None = None,
    project: str | None = None,
    json_output: bool = False,
) -> int:
    """Bring memory home from another tool, as reviewable proposals."""
    target = target.expanduser().resolve()
    root = _resolve_link_root(target)
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    try:
        units = _core_collect_import_units(
            source, file_path=Path(file_path) if file_path else None,
        )
    except ValueError as exc:
        print(f"Could not import: {exc}", file=sys.stderr)
        return 1
    if not units:
        _print_text(
            f"Nothing to import from {source}: no memory surface found for it on this machine."
        )
        return 0

    records = _memory_records(wiki_dir)
    exclude = set(_core_load_dismissed_fingerprints(root)) | set(_core_pending_proposal_fingerprints(root))
    results: list[dict[str, object]] = []
    total_proposals = 0
    for unit in units:
        preview = _core_propose_memories_from_text(
            unit["text"], records, source=f"import:{source}", limit=50,
            project=project, command_target=root,
            exclude_fingerprints=exclude, curated=True,
        )
        proposals = preview.get("proposals") if isinstance(preview.get("proposals"), list) else []
        if not proposals:
            results.append({"label": unit["label"], "origin": unit["origin"], "proposals": 0, "capture": ""})
            continue
        capture = _core_write_session_capture(
            root,
            text=unit["text"],
            source=f"import:{source} \u00b7 {unit['origin']}",
            title=unit["label"],
            project=project,
            source_type="import",
        )
        total_proposals += len(proposals)
        results.append({
            "label": unit["label"], "origin": unit["origin"],
            "proposals": len(proposals), "capture": str(capture.get("path") or ""),
            "secret_warnings": capture.get("secret_warnings") or [],
        })

    if json_output:
        print(json.dumps({
            "source": source, "units": results, "total_proposals": total_proposals,
        }, indent=2))
        return 0

    _print_text(f"Import from {source}: {len(units)} surface(s) scanned\n")
    for item in results:
        count = int(str(item["proposals"]))
        if count:
            _print_text(f"  + {item['label']}: {count} candidate memory(ies) -> {item['capture']}")
        else:
            _print_text(f"  \u00b7 {item['label']}: nothing new (all duplicates of what Link already has)")
    if total_proposals:
        _print_text(
            f"\n{total_proposals} candidate(s) are waiting as proposals - nothing is saved yet."
            f"\nReview them: {_display_command(['lnk', 'capture-inbox', str(root)])}"
        )
    else:
        _print_text("\nNothing new to review - your Link memory already covers these files.")
    return 0


def handoff(
    target: Path,
    *,
    note: str,
    task: str | None = None,
    next_steps: list[str] | None = None,
    project: str | None = None,
    source: str = "cli",
    json_output: bool = False,
) -> int:
    """Write a session handoff packet for the next session, any agent."""
    target = target.expanduser().resolve()
    root = _resolve_link_root(target)
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    try:
        record = _core_write_handoff(
            root, note, task=task, next_steps=next_steps,
            source=source, project=project or _default_project(target),
        )
    except ValueError as exc:
        print(f"Could not write handoff: {exc}", file=sys.stderr)
        return 1
    if json_output:
        print(json.dumps(record, indent=2))
        return 0
    _print_text(
        f"Handoff written: {record['path']}\n"
        f"Expires: {record['expires_at']}\n\n"
        "The next session on ANY connected agent opens with it - session-start\n"
        "hooks and the MCP first response both carry it. Nothing to remember."
    )
    return 0


def handoffs(target: Path, *, clear: str | None = None, json_output: bool = False) -> int:
    """List pending handoffs, or clear one after resuming it."""
    target = target.expanduser().resolve()
    root = _resolve_link_root(target)
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    if clear:
        try:
            result = _core_clear_handoff(root, clear)
        except ValueError as exc:
            print(f"Could not clear: {exc}", file=sys.stderr)
            return 1
        _print_text(f"Handoff cleared: {result['path']}")
        return 0
    pending = _core_pending_handoffs(root)
    if json_output:
        print(json.dumps({"count": len(pending), "handoffs": pending}, indent=2))
        return 0
    if not pending:
        _print_text("No pending handoffs. Write one before switching agents: "
                    + _display_command(["lnk", "handoff", "'where I left off'", str(root)]))
        return 0
    _print_text(f"Pending handoffs ({len(pending)}):\n")
    for item in pending:
        _print_text(f"  {item['path']}\n    {item['title']} \u00b7 from {item['source']} \u00b7 {item['created_at']}")
    _print_text("\nClear after resuming: " + _display_command(["lnk", "handoffs", str(root), "--clear", "<file>"]))
    return 0


def digest(target: Path, days: int = 7, json_output: bool = False) -> int:
    """Weekly reflection: what changed, what is aging, what is drifting."""
    target = target.expanduser().resolve()
    root = _resolve_link_root(target)
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    records = _memory_records(wiki_dir)
    captures = _core_capture_inbox(root, limit=50)
    inbox = _memory_inbox(wiki_dir, limit=50)
    inbox_items = inbox.get("items") if isinstance(inbox.get("items"), list) else []
    payload = _core_build_digest(
        records=records,
        merge_candidates=_core_memory_merge_candidates(records),
        capture_count=int(captures.get("count") or 0),
        review_items=[item for item in inbox_items if isinstance(item, dict)],
        usage=_core_usage_summary(
            root, days=max(1, min(days, 365)),
            records=[r for r in records if str(r.get("status") or "active") == "active"],
        ),
        days=max(1, min(days, 365)),
        command_target=root,
    )
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0
    _print_text(_core_render_digest_text(payload))
    return 0


def sync(
    target: Path,
    *,
    init: bool = False,
    remote: str | None = None,
    status: bool = False,
    json_output: bool = False,
) -> int:
    """Sync memory between machines through the user's own git remote."""
    target = target.expanduser().resolve()
    root = _resolve_link_root(target)
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        return _missing_wiki_error(wiki_dir)
    try:
        if init:
            payload: dict[str, object] = _core_sync_init(root, remote=remote)
            if json_output:
                print(json.dumps(payload, indent=2))
                return 0
            lines = ["Sync repo ready" if payload.get("remote") else "Sync repo created (no remote yet)"]
            lines.append(f"Branch: {payload.get('branch')}")
            if payload.get("remote"):
                lines.append(f"Remote: {payload.get('remote')}")
            else:
                lines.append("Add your private remote: " + _shell_words_for_target("sync", target, "--init", "--remote", "<git-url>"))
            lines.append("raw/ captures and the runtime never sync; reviewed memory does.")
            lines.append(f"Daily: {_shell_words_for_target('sync', target)}")
            _print_text("\n".join(lines))
            return 0
        if status:
            payload = _core_sync_status(root)
            if json_output:
                print(json.dumps(payload, indent=2))
                return 0
            if not payload.get("ready"):
                _print_text(f"Sync not ready: {payload.get('reason')}")
                return 1
            _print_text(
                f"Branch {payload.get('branch')} -> {payload.get('remote')}\n"
                f"Local changes: {'yes' if payload.get('dirty') else 'no'} · "
                f"ahead {payload.get('ahead')} · behind {payload.get('behind')}"
            )
            return 0
        payload = _core_sync_workspace(
            root, wiki_dir,
            regenerate=lambda: (_core_rebuild_index(wiki_dir), _rebuild_backlinks_quiet(wiki_dir)),
        )
        if json_output:
            print(json.dumps(payload, indent=2))
            return 0 if payload.get("synced") else 1
        if not payload.get("synced"):
            findings_obj = payload.get("secret_findings")
            findings: list[object] = findings_obj if isinstance(findings_obj, list) else []
            lines = ["Sync stopped before push — secrets never leave this machine."]
            for finding in findings:
                if isinstance(finding, dict):
                    lines.append(f"  {finding.get('path')}: {finding.get('label')}")
            lines.append(str(payload.get("message") or ""))
            _print_text("\n".join(lines))
            return 1
        parts = []
        if payload.get("committed"):
            parts.append("committed local changes")
        pulled = int(str(payload.get("pulled") or 0))
        if pulled:
            parts.append(f"pulled {pulled} commit(s)")
        if payload.get("pushed"):
            parts.append("pushed")
        lines = ["Synced: " + (", ".join(parts) if parts else "already up to date")]
        both_obj = payload.get("both_versions")
        both: list[object] = both_obj if isinstance(both_obj, list) else []
        if both:
            lines.append(f"{len(both)} memory conflict(s) kept as both versions — review and merge:")
            for item in both:
                if isinstance(item, dict):
                    lines.append(f"  {item.get('path')}  +  {item.get('local_copy')}")
            lines.append(f"  {_shell_words_for_target('consolidate', target)}")
        _print_text("\n".join(lines))
        return 0
    except _core_sync_error as exc:
        print(f"Sync failed: {exc}", file=sys.stderr)
        return 1


def _rebuild_backlinks_quiet(wiki_dir: Path) -> None:
    try:
        _core_atomic_write_json(wiki_dir / "_backlinks.json", _build_backlinks(wiki_dir))
    except OSError:
        pass


def setup(
    target: Path,
    *,
    preview: bool = False,
    no_semantic: bool = False,
    json_output: bool = False,
) -> int:
    """One command for install day and every upgrade after it.

    Detects every agent installed on this machine, then runs the same
    onboard machinery for all of them at once: workspace create/repair,
    runtime refresh, MCP provisioning, session hooks. Idempotent — after
    `brew upgrade`, re-running it refreshes everything in one step.
    """
    detected = _core_detect_installed_agents()
    hookable = [name for name in detected if _core_supports_agent_hooks(name)]
    if not json_output:
        if detected:
            display = ", ".join(detected)
            _print_text(f"Detected agents: {display}")
            if not preview:
                _print_text("Wiring MCP" + (" + session hooks" if hookable else "") + " for all of them.\n")
        else:
            _print_text(
                "No agent configs detected (looked for Claude Code, Codex, Cursor, "
                "Windsurf, Zed, Kiro, Gemini CLI). Setting up the workspace; connect "
                "an agent later with: lnk onboard --agent <name> --write --hooks\n"
            )
    code = onboard(
        target,
        agents=detected or None,
        write=bool(detected) and not preview,
        hooks=bool(hookable) and not preview,
        json_output=json_output,
    )
    # Instruction files rot the same way MCP configs do — a steering file
    # from an older Link can name tools the configured server no longer
    # exposes, sending the agent back to grep. Same idempotent treatment:
    # refresh any Link-owned section that no longer matches the template.
    # Refresh-only: files Link never wrote are never created here.
    refreshed_instructions: list[str] = []
    stale_instructions: list[str] = []
    if code == 0:
        for agent in detected:
            status = _core_instruction_file_status(agent)
            if not status.get("present") or not status.get("stale"):
                continue
            if preview:
                stale_instructions.append(str(status.get("path")))
                continue
            result = _core_refresh_instruction_file(agent)
            if result.get("refreshed"):
                refreshed_instructions.append(str(result.get("path")))
    if not json_output:
        for path in stale_instructions:
            _print_text(f"Instruction file is stale (would refresh): {path}")
        for path in refreshed_instructions:
            _print_text(f"Refreshed Link instructions: {path}")
    if code == 0 and not preview and not no_semantic:
        # Meaning-based recall by default: the measured gap between the
        # lexical default (hit@1 0.589) and the fast tier (0.703) is the
        # single biggest quality difference a new install feels, and the
        # cost is one ~30 MB local model fetched during this explicit
        # command - recall itself never touches the network. Opt out with
        # --no-semantic. Only the managed-venv path auto-installs; a
        # user-managed python keeps the hint (we never pip-install into
        # an environment we do not own).
        try:
            from link_core.semantic import model_available, provider_installed
            if not (provider_installed() and model_available()):
                venv_python = Path.home() / ".link-mcp-venv" / "bin" / "python"
                if provider_installed() or venv_python.exists() or _core_python_is_externally_managed():
                    if not json_output:
                        _print_text(
                            "\nSetting up meaning-based recall (fast tier, one-time ~30 MB "
                            "local model download; recall never uses the network; skip with "
                            "--no-semantic)..."
                        )
                    if provider_installed():
                        semantic(target, setup=True, json_output=json_output)
                    else:
                        # Fast tier ONLY for the default path: the quality and
                        # rerank tiers (~200 MB more) stay explicit opt-ins via
                        # lnk semantic --setup.
                        outcome = _core_provision_link_extras(
                            sys.executable, LINK_VERSION, extras=("semantic",),
                        )
                        for note in outcome.get("notes", []):
                            if not json_output:
                                _print_text(f"  {note}")
                        if outcome.get("ready"):
                            subprocess.run(
                                [str(outcome["python"]), str(ROOT / "link.py"),
                                 "semantic", str(_resolve_link_root(target)), "--setup"],
                                check=False,
                            )
        except Exception as exc:
            if not json_output:
                _print_text(f"  (meaning-based recall setup skipped: {exc})")
    if code == 0 and not json_output:
        extras: list[str] = []
        try:
            from link_core.semantic import model_available, provider_installed
            if not (provider_installed() and model_available()):
                extras.append("Meaning-based recall (one-time local model download):  lnk semantic --setup")
        except Exception:
            pass
        if sys.platform == "darwin" and not Path("/Applications/LinkBar.app").exists():
            extras.append("Menu-bar review gate:  brew install --cask gowtham0992/link/linkbar")
        if extras:
            _print_text("\nOptional, when you want them:")
            for extra in extras:
                _print_text(f"  {extra}")
        _print_text("\nUpgrades stay this easy: brew upgrade, then lnk setup again.")
    return code


def onboard(
    target: Path,
    *,
    agents: list[str] | None = None,
    all_agents: bool = False,
    write: bool = False,
    hooks: bool = False,
    first_memory: str | None = None,
    seed_project: str | None = None,
    project: str | None = None,
    port: int = 3000,
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    if port < 1 or port > 65535:
        print("--port must be between 1 and 65535")
        return 1

    created = not (target / "wiki").exists()
    target.mkdir(parents=True, exist_ok=True)
    _copy_runtime_files(target)
    fixes = _apply_doctor_fixes(target)
    wiki_dir = _resolve_wiki_dir(target)

    memory_result: dict[str, object] | None = None
    if first_memory and first_memory.strip():
        try:
            memory_result = _write_memory_page(
                target,
                first_memory,
                memory_type="preference",
                scope="project" if project else "user",
                tags="onboarding",
                source="onboard",
                project=project,
            )
        except (FileNotFoundError, ValueError) as exc:
            memory_result = {
                "created": False,
                "message": str(exc),
            }

    seed_result: dict[str, object] | None = None
    if seed_project is not None:
        try:
            seed_result = _core_seed_project_context(
                target,
                Path(seed_project),
                project_name=project,
                overwrite=False,
                dry_run=False,
                include_git_log=True,
            )
            seed_project_root = Path(seed_project).expanduser().resolve()
            status_value = str(seed_result.get("status") or "")
            if status_value == "already_seeded":
                seed_result["next_commands"] = [
                    _display_command(["link", "seed", str(seed_project_root), str(target), "--overwrite"]),
                    _display_command(["link", "query", "what is this project about?", str(target), "--budget", "small"]),
                    _display_command(["link", "health", str(target)]),
                ]
            elif status_value == "needs_attention":
                seed_result["next_commands"] = [
                    "redact blocked project files, then rerun: "
                    + _display_command(["link", "seed", str(seed_project_root), str(target)])
                ]
            elif status_value == "empty":
                seed_result["next_commands"] = [
                    "add README.md, AGENTS.md, CLAUDE.md, .cursorrules, or agent rule files, then rerun seed"
                ]
            else:
                seed_result["next_commands"] = [
                    _display_command(["link", "query", "what is this project about?", str(target), "--budget", "small"]),
                    _display_command(["link", "brief", f"working on {seed_result.get('project_title') or 'this project'}", str(target)]),
                    _display_command(["link", "health", str(target)]),
                ]
        except (OSError, ValueError) as exc:
            seed_result = {
                "status": "needs_attention",
                "project_root": str(Path(seed_project).expanduser()),
                "target": str(target),
                "message": str(exc),
                "wrote": False,
                "included_count": 0,
                "blocked_secret_count": 0,
                "read_error_count": 1,
                "next_commands": [_display_command(["link", "seed", seed_project, str(target)])],
            }

    connections: list[dict[str, object]] = []
    for agent in _onboard_agent_names(agents, all_agents):
        try:
            connection = _core_build_mcp_connect_payload(
                target=target,
                wiki_dir=wiki_dir,
                agent=agent,
                expected_version=LINK_VERSION,
                init_command=[sys.executable, str(ROOT / "link.py"), "init", str(target)],
                default_python=sys.executable,
                write=write,
            )
            if hooks and _core_supports_agent_hooks(agent):
                connection["session_hooks"] = _core_build_agent_hooks_payload(
                    target=target,
                    agent=agent,
                    runtime_script=(target / "link.py") if (target / "link.py").exists() else ROOT / "link.py",
                    python_cmd=sys.executable,
                    write=write,
                )
            elif hooks:
                connection["session_hooks"] = {
                    "agent": agent,
                    "write": {"requested": False, "ok": False,
                              "message": "session hooks are not available for this agent yet"},
                }
            connections.append(connection)
        except ValueError as exc:
            connections.append({
                "agent": agent,
                "display_name": agent,
                "config_path": "",
                "write": {"requested": write, "ok": False, "message": str(exc)},
                "next_actions": [],
            })

    status_payload = _core_link_status(wiki_dir, version=LINK_VERSION, include_validation=True)
    starter_payload = _core_starter_prompt_payload(target, project=project)
    prompts = starter_payload.get("prompts", [])
    if first_memory and isinstance(prompts, list):
        prompts = [
            {
                **item,
                "prompt": f"remember that {first_memory.strip()}",
            }
            if isinstance(item, dict) and item.get("label") == "Save explicit memory"
            else item
            for item in prompts
        ]
    commands = {
        "health": _display_command(["link", "health", str(target)]),
        "serve": _display_command(["link", "serve", str(target), "--port", str(port)]),
        "seed_project": _display_command(["link", "seed", ".", str(target)]),
        "memory_inbox": _display_command(["link", "memory-inbox", str(target)]),
        "ingest_status": _display_command(["link", "ingest-status", str(target)]),
        "brief": _display_command(["link", "brief", "working with Link", str(target)]),
    }
    payload: dict[str, object] = {
        "target": str(target),
        "created": created,
        "fixes": fixes,
        "status": status_payload,
        "first_memory": memory_result,
        "project_seed": seed_result,
        "connections": connections,
        "write_requested": write,
        "prompts": prompts,
        "commands": commands,
        "agent_examples": [
            _display_command(["link", "onboard", str(target), "--agent", agent])
            for agent in ("codex", "claude-code", "cursor")
        ],
        "url": f"http://127.0.0.1:{port}",
    }

    if json_output:
        print(json.dumps(payload, indent=2, default=str))
        failed = any(
            isinstance(connection.get("write"), dict)
            and connection["write"].get("requested")
            and not connection["write"].get("ok")
            for connection in connections
        )
        return 0 if status_payload.get("ready") and not failed else 1

    code, text = _core_render_onboard_text(payload)
    _print_text(text)
    return code


def seed_project(
    target: Path,
    project_root: Path,
    *,
    project_name: str | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
    limit: int = 12,
    include_git_log: bool = True,
    git_log_limit: int = 20,
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    project_root = project_root.expanduser().resolve()
    if limit < 0:
        print("--limit must be 0 or greater")
        return 1
    if git_log_limit < 0:
        print("--git-log-limit must be 0 or greater")
        return 1

    target.mkdir(parents=True, exist_ok=True)
    _copy_runtime_files(target)
    _apply_doctor_fixes(target)
    payload = _core_seed_project_context(
        target,
        project_root,
        project_name=project_name,
        overwrite=overwrite,
        dry_run=dry_run,
        limit=limit,
        include_git_log=include_git_log,
        git_log_limit=git_log_limit,
    )
    status_value = str(payload.get("status") or "")
    if status_value == "already_seeded":
        payload["next_commands"] = [
            _display_command(["link", "seed", str(project_root), str(target), "--overwrite"]),
            _display_command(["link", "query", "what is this project about?", str(target), "--budget", "small"]),
            _display_command(["link", "health", str(target)]),
        ]
    elif status_value == "needs_attention":
        payload["next_commands"] = [
            "redact blocked project files, then rerun: "
            + _display_command(["link", "seed", str(project_root), str(target)])
        ]
    elif status_value == "empty":
        payload["next_commands"] = [
            "add README.md, AGENTS.md, CLAUDE.md, .cursorrules, or agent rule files, then rerun seed"
        ]
    else:
        payload["next_commands"] = [
            _display_command(["link", "query", "what is this project about?", str(target), "--budget", "small"]),
            _display_command(["link", "brief", f"working on {payload.get('project_title') or 'this project'}", str(target)]),
            _display_command(["link", "health", str(target)]),
        ]
    if json_output:
        print(json.dumps(payload, indent=2, default=str))
        return 0 if payload.get("status") in {"ok", "partial", "already_seeded"} else 1

    code, text = _core_render_seed_project_text(payload)
    _print_text(text)
    return code


def starter_prompts(target: Path, project: str | None = None, json_output: bool = False) -> int:
    payload = _core_starter_prompt_payload(target, project=project)
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0

    code, text = _core_render_starter_prompts_text(payload)
    _print_text(text)
    return code


def welcome(target: Path, project: str | None = None, json_output: bool = False) -> int:
    payload = _core_welcome_payload(target, project=project)
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0

    code, text = _core_render_welcome_text(payload)
    _print_text(text)
    return code


def serve_wiki(target: Path, port: int = 3000) -> int:
    target = target.expanduser().resolve()
    if port < 1 or port > 65535:
        print("--port must be between 1 and 65535")
        return 1
    serve_path = ROOT / "serve.py"
    if not serve_path.exists():
        serve_path = target / "serve.py"
    if not serve_path.exists():
        print(f"Link viewer missing: {serve_path}")
        print("")
        print("Next:")
        print(f"  {_display_command(['link', 'init', str(target)])}")
        return 1
    if not (target / "wiki").exists():
        print(f"Link wiki missing: {target / 'wiki'}")
        print("")
        print("Next:")
        print(f"  {_display_command(['link', 'init', str(target)])}")
        return 1
    try:
        return subprocess.run(
            [sys.executable, str(serve_path), "--root", str(target), "--port", str(port)]
        ).returncode
    except KeyboardInterrupt:
        return 130


def create_demo(target: Path, force: bool = False) -> int:
    target = target.expanduser().resolve()
    try:
        _core_create_demo_workspace(target, source_root=ROOT, force=force)
    except _CoreDemoError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    code, text = _core_render_demo_text(
        target=target,
        guide_path=target / "START_HERE.md",
        serve_command=_display_command(["python3", str(target / "link.py"), "serve", str(target)]),
        next_command=_display_command(["python3", str(target / "link.py"), "next", str(target)]),
        start_command=_display_command([
            "python3",
            str(target / "link.py"),
            "start",
            str(target),
            "--task",
            "working on agent memory",
        ]),
        query_command=_display_command([
            "python3",
            str(target / "link.py"),
            "query",
            "why does Link help agents?",
            str(target),
            "--budget",
            "small",
        ]),
        brief_command=_display_command([
            "python3",
            str(target / "link.py"),
            "brief",
            "working on agent memory",
            str(target),
        ]),
        audit_command=_display_command(["python3", str(target / "link.py"), "memory-audit", str(target)]),
    )
    _print_text(text)
    return code


def _try_summary_from_query(payload: dict[str, object]) -> str:
    wiki = payload.get("wiki") if isinstance(payload.get("wiki"), dict) else {}
    memory = payload.get("memory") if isinstance(payload.get("memory"), dict) else {}
    primary = wiki.get("primary") or "no primary page"
    memory_items = memory.get("items") if isinstance(memory.get("items"), list) else []
    page_count = len(payload.get("context_packet") or []) if isinstance(payload.get("context_packet"), list) else 0
    memory_count = len(memory_items)
    memory_label = "memory" if memory_count == 1 else "memories"
    context_label = "item" if page_count == 1 else "items"
    return f"{primary} · {memory_count} {memory_label} · {page_count} context {context_label}"


def _try_summary_from_brief(payload: dict[str, object]) -> str:
    memories = payload.get("relevant_memories") if isinstance(payload.get("relevant_memories"), list) else []
    review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
    review_count = review.get("count", 0)
    memory_count = len(memories)
    memory_label = "memory" if memory_count == 1 else "memories"
    review_label = "item" if review_count == 1 else "items"
    return f"{memory_count} relevant {memory_label} · {review_count} review {review_label}"


def _proof_recall_found(payload: dict[str, object], title: str) -> bool:
    title_lc = title.lower()
    memory = payload.get("memory") if isinstance(payload.get("memory"), dict) else {}
    items = memory.get("items") if isinstance(memory.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        haystack = " ".join(
            str(item.get(key) or "")
            for key in ("title", "name", "summary", "why_selected", "text")
        ).lower()
        if title_lc in haystack or "cross-agent" in haystack:
            return True
    return title_lc in json.dumps(payload, ensure_ascii=False).lower()


def proof(
    target: Path,
    *,
    force: bool = False,
    serve: bool = False,
    port: int = 3000,
    json_output: bool = False,
) -> int:
    """Create a concrete cross-agent continuity proof workspace."""
    target = target.expanduser().resolve()
    created = not (target / "wiki").exists()
    if target.exists() and any(target.iterdir()) and (force or created):
        marker = target / PROOF_MARKER
        if not marker.exists():
            print(f"{target} does not look like a Link proof directory; refusing to overwrite it.", file=sys.stderr)
            return 1
        if force:
            shutil.rmtree(target)
            created = True
    target.mkdir(parents=True, exist_ok=True)
    _core_atomic_write_text(target / PROOF_MARKER, "Link proof directory\n")
    _copy_runtime_files(target)
    _apply_doctor_fixes(target)

    wiki_dir = _resolve_wiki_dir(target)
    try:
        memory_result = _write_memory_page(
            target,
            PROOF_MEMORY_TEXT,
            title=PROOF_MEMORY_TITLE,
            memory_type="note",
            scope="user",
            tags="proof,cross-agent",
            source="lnk proof",
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Could not create proof memory: {exc}", file=sys.stderr)
        return 1

    reviewed = False
    if memory_result.get("created") and memory_result.get("name"):
        try:
            review_result = _mark_memory_reviewed(
                target,
                str(memory_result["name"]),
                note="Reviewed automatically because the user explicitly ran lnk proof.",
            )
            reviewed = str(review_result.get("review_status") or "").lower() == "reviewed"
        except (FileNotFoundError, ValueError):
            reviewed = False
    memory_result = {**memory_result, "reviewed": reviewed}
    _core_rebuild_index(wiki_dir)
    backlinks = _build_backlinks(wiki_dir)
    _core_atomic_write_json(wiki_dir / "_backlinks.json", backlinks)

    query_text = "cross-agent proof local memory"
    recall_payload = _query_link(wiki_dir, query_text, budget="micro")
    status_payload = _core_link_status(wiki_dir, version=LINK_VERSION, include_validation=True)
    recall_found = _proof_recall_found(recall_payload, PROOF_MEMORY_TITLE)
    ready = bool(status_payload.get("ready")) and recall_found
    command_target = str(target)
    payload = {
        "target": command_target,
        "created": created,
        "ready": ready,
        "status": status_payload,
        "memory": memory_result,
        "recall": {
            "query": query_text,
            "found": recall_found,
            "budget": "micro",
            "estimated_tokens": recall_payload.get("estimated_tokens"),
            "recall_capsule": recall_payload.get("recall_capsule"),
        },
        "prompts": {
            "agent_a": "remember that I want Link memory shared across my local agents",
            "agent_b": "start with Link before we continue, then tell me what Link remembers about cross-agent proof",
        },
        "commands": {
            "start": _display_command(["link", "start", command_target, "--task", "cross-agent proof"]),
            "recall": _display_command(["link", "query", query_text, command_target, "--budget", "micro"]),
            "mcp": _display_command(["link", "connect", "codex", command_target]),
            "serve": _display_command(["link", "serve", command_target, "--port", str(port)]),
        },
        "url": f"http://127.0.0.1:{port}",
    }
    if json_output:
        print(json.dumps(payload, indent=2))
        if serve:
            return serve_wiki(target, port=port)
        return 0 if ready else 1

    code, text = _core_render_proof_text(payload)
    _print_text(text)
    if serve:
        return serve_wiki(target, port=port)
    return code


def try_link(
    target: Path,
    *,
    force: bool = False,
    serve: bool = False,
    port: int = 3000,
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    created = False
    if force or not (target / "wiki").exists():
        try:
            _core_create_demo_workspace(target, source_root=ROOT, force=force)
        except _CoreDemoError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        created = True

    wiki_dir = _resolve_wiki_dir(target)
    status_payload = _core_link_status(wiki_dir, version=LINK_VERSION, include_validation=True)
    query_payload = _query_link(wiki_dir, "why does Link help agents?", budget="small")
    brief_payload = _memory_brief(wiki_dir, "working on agent memory", limit=6)
    payload = {
        "target": str(target),
        "created": created,
        "ready": bool(status_payload.get("ready")),
        "status": status_payload,
        "query": query_payload,
        "brief": brief_payload,
        "commands": {
            "serve": _display_command(["link", "serve", str(target), "--port", str(port)]),
            "next": _display_command(["link", "next", str(target)]),
            "health": _display_command(["link", "health", str(target)]),
            "query": _display_command(["link", "query", "why does Link help agents?", str(target), "--budget", "small"]),
            "brief": _display_command(["link", "brief", "working on agent memory", str(target)]),
            "benchmark": _display_command(["link", "benchmark", "agent memory", str(target)]),
        },
        "url": f"http://127.0.0.1:{port}",
    }
    if json_output:
        print(json.dumps(payload, indent=2))
        if serve:
            return serve_wiki(target, port=port)
        return 0 if payload["ready"] else 1

    code, text = _core_render_try_text(
        target=target,
        ready=payload["ready"],
        page_count=status_payload.get("page_count", 0),
        memory_count=status_payload.get("memory_count", 0),
        search_backend=status_payload.get("search_backend", "unknown"),
        query_summary=_try_summary_from_query(query_payload),
        brief_summary=_try_summary_from_brief(brief_payload),
        serve_command=payload["commands"]["serve"],
        next_command=payload["commands"]["next"],
        health_command=payload["commands"]["health"],
        query_command=payload["commands"]["query"],
        brief_command=payload["commands"]["brief"],
        benchmark_command=payload["commands"]["benchmark"],
        url=payload["url"],
    )
    _print_text(text)
    if serve:
        return serve_wiki(target, port=port)
    return code


# Commands that CONSUME an existing workspace. When one of these is run with
# the default target (.) in a directory that has no Link wiki, fall back to
# the default workspace (LINK_WORKSPACE or ~/link) instead of dead-ending —
# `lnk onboard` creates ~/link and the very next thing every new user types
# is `lnk remember "..."` with no path. Creator commands (init, demo, try,
# proof, onboard) are excluded on purpose: they must act where they are told.
_WORKSPACE_COMMANDS = {
    "remember", "recall", "recipes", "query", "query-link", "brief", "start",
    "session-end", "end", "propose-memories", "capture-session",
    "capture-inbox", "accept-capture", "redact-capture", "delete-capture",
    "dedup-captures", "update-memory", "set-memory-visibility",
    "memory-inbox", "memory-log",
    "review-memory", "explain-memory", "memory-audit", "archive-memory",
    "restore-memory", "forget-memory", "consolidate", "profile", "wins",
    "semantic", "status", "sync", "digest", "import", "handoff", "handoffs", "health", "doctor", "validate", "operations",
    "backup", "restore-backup", "ingest-status", "serve", "share",
    "snapshot", "graph-summary", "benchmark", "team-sync",
    "compliance-export", "migrate", "rebuild-index", "rebuild-backlinks", "stale",
    "verify-mcp", "connect",
}


def _default_workspace() -> Path:
    return Path(os.environ.get("LINK_WORKSPACE") or (Path.home() / "link")).expanduser()


def _normalize_review_all_args(args) -> None:
    """With --all there is no identifier: a lone positional is the target.

    `lnk review-memory --all ~/link` parsed the workspace as an identifier
    and the command silently reviewed the default workspace instead (found
    in dogfooding). Must run before the default-workspace fallback rewrites
    the target.
    """
    if (
        getattr(args, "command", "") == "review-memory"
        and getattr(args, "review_all", False)
        and getattr(args, "identifier", None)
        and getattr(args, "target", ".") == "."
    ):
        args.target = args.identifier
        args.identifier = None


def _apply_default_workspace(args) -> None:
    if getattr(args, "command", "") not in _WORKSPACE_COMMANDS:
        return
    if getattr(args, "target", None) != ".":
        return
    if (Path.cwd() / "wiki").exists():
        return
    workspace = _default_workspace()
    if (workspace / "wiki").exists():
        args.target = str(workspace)
        print(
            f"Workspace: {workspace} (no Link wiki in the current directory; "
            "pass a path or set LINK_WORKSPACE to change)",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    # Short-lived CLI: prefer the instant-load semantic tier so interactive
    # commands never pay a multi-second model load. Explicit provider wins;
    # the MCP server (its own entry point) still prefers the quality tier.
    os.environ.setdefault("LINK_SEMANTIC_SURFACE", "cli")
    # A bare `lnk` is most people's first keystroke — greet, don't error.
    effective_argv = sys.argv[1:] if argv is None else argv
    if not effective_argv:
        _print_text("\n".join([
            "Link — local, source-backed memory for AI agents.",
            "",
            "  lnk proof     see cross-agent memory work (~1 second, throwaway)",
            "  lnk try       build a full demo wiki you can explore",
            "  lnk setup     make it yours: wire every agent you have, one command",
            "  lnk status    is my workspace healthy?",
            "  lnk --help    everything else, grouped by task",
            "",
            "Docs: https://gowtham0992.github.io/link/",
        ]))
        return 0
    parser = _core_build_cli_parser(default_demo_dir=DEFAULT_DEMO_DIR, default_proof_dir=DEFAULT_PROOF_DIR)
    args = parser.parse_args(argv)
    _normalize_review_all_args(args)
    _apply_default_workspace(args)
    _configure_link_command_display()
    try:
        return _core_dispatch_cli_command(args, {
            "init": init_wiki,
            "serve": serve_wiki,
            "demo": create_demo,
            "try": try_link,
            "proof": proof,
            "onboard": onboard,
            "setup": setup,
            "sync": sync,
            "digest": digest,
            "handoff": handoff,
            "handoffs": handoffs,
            "import": import_memory,
            "seed": seed_project,
            "welcome": welcome,
            "prompts": starter_prompts,
            "status": status,
            "health": health,
            "operations": operations,
            "backup": backup,
            "restore-backup": restore_backup,
            "compliance-export": compliance_export,
            "team-sync": team_sync,
            "share": share,
            "snapshot": snapshot,
            "doctor": doctor,
            "migrate": migrate,
            "validate": validate,
            "ingest-status": ingest_status,
            "import-obsidian": import_obsidian,
            "remember": remember,
            "propose-memories": propose_memories,
            "capture-session": capture_session,
            "session-end": session_end,
            "capture-inbox": capture_inbox,
            "accept-capture": accept_capture,
            "redact-capture": redact_capture,
            "delete-capture": delete_capture,
            "dedup-captures": dedup_captures,
            "update-memory": update_memory,
            "set-memory-visibility": set_memory_visibility,
            "recall": recall,
            "query": query,
            "graph-summary": graph_summary,
            "benchmark": benchmark,
            "brief": brief,
            "start": start,
            "hook": run_agent_hook,
            "consolidate": consolidate,
            "recipes": recipes,
            "semantic": semantic,
            "profile": profile,
            "wins": memory_wins,
            "memory-audit": memory_audit,
            "archive-memory": archive_memory,
            "restore-memory": restore_memory,
            "forget-memory": forget_memory,
            "memory-inbox": memory_inbox,
            "memory-log": memory_log,
            "review-memory": review_memory,
            "explain-memory": explain_memory,
            "rebuild-index": rebuild_index,
            "rebuild-backlinks": rebuild_backlinks,
            "stale": stale,
            "verify-mcp": verify_mcp,
            "connect": connect_mcp,
            "version": lambda: print(f"Link {LINK_VERSION}") or 0,
        })
    except ValueError as exc:
        parser.error(str(exc))
        return 2
    finally:
        _core_set_link_command_override(None)


if __name__ == "__main__":
    raise SystemExit(main())
