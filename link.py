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

import json
import os
import shutil
import subprocess
import sys
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
    memory_review_issues as _core_memory_review_issues,
    propose_memories_from_text as _core_propose_memories_from_text,
    recall_memories as _core_recall_memories,
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
    capture_review_summary as _core_capture_review_summary,
    cli_capture_commands as _core_cli_capture_commands,
    delete_capture_file as _core_delete_capture_file,
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
    render_mcp_verify_text as _core_render_mcp_verify_text,
    set_link_command_override as _core_set_link_command_override,
)
from link_core.mcp_connect import (
    build_mcp_connect_payload as _core_build_mcp_connect_payload,
    supported_agents as _core_supported_agents,
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
)
from link_core.query import (
    query_link as _core_query_link,
)
from link_core.cli_query import (
    render_graph_summary_text as _core_render_graph_summary_text,
    render_query_text as _core_render_query_text,
)
from link_core.cli_runtime import (
    render_demo_text as _core_render_demo_text,
    render_init_text as _core_render_init_text,
    render_mcp_connect_text as _core_render_mcp_connect_text,
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


def _memory_brief(wiki_dir: Path, query: str = "", limit: int = 6, project: str | None = None) -> dict[str, object]:
    return _core_memory_brief(
        _memory_records(wiki_dir),
        query=query,
        limit=limit,
        review_command="review-memory",
        project=project,
        command_target=wiki_dir.parent,
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
) -> list[dict[str, object]]:
    return _core_recall_memories(
        _memory_records(wiki_dir),
        query,
        limit=limit,
        include_archived=include_archived,
        project=project,
    )


def _propose_memories_from_text(
    wiki_dir: Path,
    text: str,
    source: str = "inline",
    limit: int = 10,
    project: str | None = None,
    command_target: str | Path = ".",
) -> dict[str, object]:
    return _core_propose_memories_from_text(
        text,
        _memory_records(wiki_dir),
        source=source,
        limit=limit,
        writes_memory=False,
        project=project,
        command_target=command_target,
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
    allow_conflict: bool = False, project: str | None = None,
    visibility: str | None = None,
    review_after: str | None = None,
    expires_at: str | None = None,
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
        allow_duplicate=allow_duplicate, allow_conflict=allow_conflict,
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


def team_sync(target: Path, remote: str | None = None, json_output: bool = False) -> int:
    target = target.expanduser().resolve()
    payload = _core_build_team_sync_payload(target, remote=remote)
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0
    code, text = _core_render_team_sync_text(payload)
    _print_text(text)
    return code


def share(target: Path, identifier: str, port: int = 3000, host: str = "127.0.0.1", json_output: bool = False) -> int:
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1
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


def rebuild_backlinks(target: Path) -> int:
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1
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
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1
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
    memory_type: str = "note",
    scope: str = "user",
    tags: str | None = None,
    source: str = "manual",
    allow_duplicate: bool = False,
    allow_conflict: bool = False,
    project: str | None = None,
    visibility: str | None = None,
    review_after: str | None = None,
    expires_at: str | None = None,
    json_output: bool = False,
) -> int:
    if not text or not text.strip():
        print("Memory text is required", file=sys.stderr)
        return 1
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
            project=project or _default_project(target),
            visibility=visibility,
            review_after=review_after,
            expires_at=expires_at,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Could not remember: {exc}", file=sys.stderr)
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
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1
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
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1

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
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    root = _resolve_link_root(target)
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1

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
    )
    rel_path = str(capture_record["path"])
    result = _propose_memories_from_text(
        wiki_dir,
        text,
        source=rel_path,
        limit=max(1, min(limit, 10)),
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
) -> int:
    target = target.expanduser().resolve()
    root = _resolve_link_root(target)
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1
    payload = _core_capture_inbox(
        root,
        limit=limit,
        project=project,
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
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    root = _resolve_link_root(target)
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1
    try:
        selection = _core_capture_proposal_selection(
            root,
            capture,
            index=index,
            project=project,
            default_project=_default_project(root),
            propose_memories=lambda notes, rel_path, proposal_limit, project_name: _propose_memories_from_text(
                wiki_dir,
                notes,
                source=rel_path,
                limit=proposal_limit,
                project=project_name,
                command_target=root,
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
    )
    payload = _core_capture_accept_payload(selection, result)
    if result.get("created"):
        _append_log(
            wiki_dir,
            _utc_timestamp(),
            "accept-capture",
            f"Accepted proposal {selection['proposal_index']} from {rel_path}",
            [
                f"Memory: {result['path']}",
                f"Project: {result.get('project') or 'none'}",
            ],
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
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1
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
    capture: str,
    confirm: bool = False,
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    root = _resolve_link_root(target)
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
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
) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1
    project_name = project or _default_project(target)
    results = _recall_memories(
        wiki_dir,
        query,
        limit=limit,
        include_archived=include_archived,
        project=project_name,
    )

    if json_output:
        print(json.dumps({
            "query": query,
            "count": len(results),
            "include_archived": include_archived,
            "project": project_name,
            "memories": results,
        }, indent=2))
        return 0

    code, text = _core_render_recall_text(
        query=query,
        results=results,
        include_archived=include_archived,
        project=project_name,
        target=target,
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
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1

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
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1
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
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1
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
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1
    payload = _core_memory_wins_payload(wiki_dir, limit=limit, project=project)
    return _emit_json_or_text(
        payload,
        json_output,
        lambda data: _core_render_memory_wins_text(data, target=target),
    )


def review_memory(target: Path, identifier: str, note: str | None = None, json_output: bool = False) -> int:
    try:
        result = _mark_memory_reviewed(target, identifier, note=note)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Could not review memory: {exc}", file=sys.stderr)
        return 1

    return _emit_json_or_text(result, json_output, _core_render_review_memory_text)


def explain_memory(target: Path, identifier: str, json_output: bool = False) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1
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
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1
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
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1
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
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1
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
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1
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
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1
    task = _clean_text_input(task, max_len=500)
    project_name = project or _default_project(target)
    status_payload = _core_link_status(wiki_dir, version=LINK_VERSION, include_validation=True)
    brief_payload = _memory_brief(wiki_dir, query=task, limit=limit, project=project_name)
    brief_payload = _core_add_capture_review_to_brief(
        brief_payload,
        _capture_review_summary(target, project=project_name),
    )
    query_text = task or "your current task"
    payload = {
        "target": str(target),
        "wiki": str(wiki_dir),
        "task": task,
        "project": project_name,
        "status": status_payload,
        "brief": brief_payload,
        "commands": {
            "health": _display_command(["link", "health", str(target)]),
            "query": _display_command(["link", "query", query_text, str(target), "--budget", "micro"]),
            "brief": _display_command(["link", "brief", query_text, str(target)]),
            "remember": _display_command(["link", "remember", "<approved memory>", str(target)]),
            "review": _display_command(["link", "memory-inbox", str(target)]),
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


def profile(target: Path, limit: int = 10, project: str | None = None, json_output: bool = False) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
    if not wiki_dir.exists():
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1
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
        print(f"Missing wiki directory: {wiki_dir}", file=sys.stderr)
        return 1
    payload = _memory_audit_payload(target, wiki_dir, limit=limit, project=project)

    if json_output:
        print(json.dumps(payload, indent=2))
        return 0

    code, text = _core_render_memory_audit_text(payload, target=target)
    _print_text(text)
    return code


def _display_command(parts: list[str]) -> str:
    return _core_display_command(parts)


def _configure_link_command_display() -> None:
    if os.environ.get("LINK_CLI_COMMAND"):
        _core_set_link_command_override(None)
    else:
        _core_set_link_command_override([sys.executable, str(ROOT / "link.py")])


def verify_mcp(
    target: Path,
    json_output: bool = False,
    python_cmd: str | None = None,
    import_check: Callable[[str], dict[str, object]] = _core_check_link_mcp_import,
) -> int:
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
    _print_text(text)
    return code


def connect_mcp(
    target: Path,
    agent: str,
    *,
    write: bool = False,
    config_path: str | None = None,
    python_cmd: str | None = None,
    json_output: bool = False,
) -> int:
    target = target.expanduser().resolve()
    wiki_dir = _resolve_wiki_dir(target)
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

    if json_output:
        print(json.dumps(payload, indent=2))
        write_status = payload.get("write") if isinstance(payload.get("write"), dict) else {}
        return 0 if not write or bool(write_status.get("ok")) else 1

    code, text = _core_render_mcp_connect_text(payload)
    _print_text(text)
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


def onboard(
    target: Path,
    *,
    agents: list[str] | None = None,
    all_agents: bool = False,
    write: bool = False,
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
            connections.append(_core_build_mcp_connect_payload(
                target=target,
                wiki_dir=wiki_dir,
                agent=agent,
                expected_version=LINK_VERSION,
                init_command=[sys.executable, str(ROOT / "link.py"), "init", str(target)],
                default_python=sys.executable,
                write=write,
            ))
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


def main(argv: list[str] | None = None) -> int:
    parser = _core_build_cli_parser(default_demo_dir=DEFAULT_DEMO_DIR, default_proof_dir=DEFAULT_PROOF_DIR)
    args = parser.parse_args(argv)
    _configure_link_command_display()
    try:
        return _core_dispatch_cli_command(args, {
            "init": init_wiki,
            "serve": serve_wiki,
            "demo": create_demo,
            "try": try_link,
            "proof": proof,
            "onboard": onboard,
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
            "update-memory": update_memory,
            "set-memory-visibility": set_memory_visibility,
            "recall": recall,
            "query": query,
            "graph-summary": graph_summary,
            "benchmark": benchmark,
            "brief": brief,
            "start": start,
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
