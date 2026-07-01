"""Text rendering helpers for Link admin CLI commands."""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from .mcp_verify import display_command


def render_validate_text(payload: Mapping[str, object], *, wiki_dir: object) -> tuple[int, str]:
    lines = [f"Link validate: {wiki_dir}", ""]
    findings = payload.get("findings", [])
    if isinstance(findings, Sequence) and not isinstance(findings, (str, bytes)) and findings:
        for finding in findings:
            if isinstance(finding, Mapping):
                label = str(finding["severity"]).upper()
                lines.append(f"{label} {finding['path']} [{finding['code']}] {finding['message']}")
    else:
        lines.append("OK wiki pages satisfy the ingest validation gate")
    lines.extend([
        "",
        (
            f"Result: {'passed' if payload['passed'] else 'failed'} "
            f"({payload['error_count']} errors, {payload['warning_count']} warnings)"
        ),
    ])
    return (0 if payload["passed"] else 1), "\n".join(lines)


def render_migrate_text(payload: Mapping[str, object], *, wiki_dir: object) -> tuple[int, str]:
    previous = payload["previous"]
    schema = payload["schema"]
    if not isinstance(previous, Mapping) or not isinstance(schema, Mapping):
        raise ValueError("Invalid migration payload")
    lines = [
        f"Link migrate: {wiki_dir}",
        "",
        f"Previous schema: {previous['status']}",
        f"Current schema: {schema['status']} v{schema.get('version')}",
    ]
    changes = payload.get("changes", [])
    lines.append("")
    if changes:
        lines.append("Changes:")
        lines.extend(f"- {item}" for item in changes)
    else:
        lines.append("Changes: none")
    lines.append("")
    if payload["ok"]:
        lines.append("Result: current")
        return 0, "\n".join(lines)
    lines.append(f"Result: failed ({payload['error']})")
    return 0, "\n".join(lines)


def render_status_text(payload: Mapping[str, object], *, wiki_dir: object, version: str) -> tuple[int, str]:
    command_target = str(_root_from_wiki_dir(wiki_dir))
    lines = [
        f"Link status: {wiki_dir}",
        "",
        f"Version: {payload.get('version') or version}",
        f"Ready: {'yes' if payload['ready'] else 'no'}",
        f"Pages: {payload['page_count']}",
        f"Content pages: {payload.get('content_page_count', payload['page_count'])}",
        (
            f"Memories: {payload['memory_count']} total · "
            f"{payload['active_memory_count']} active · "
            f"{payload['needs_review_count']} need review"
        ),
        f"Search backend: {payload.get('search_backend', 'unknown')}",
    ]
    persistent_cache = payload.get("persistent_cache")
    if isinstance(persistent_cache, Mapping):
        lines.append(
            "Persistent cache: "
            f"{'enabled' if persistent_cache.get('enabled') else 'disabled'} · "
            f"{persistent_cache.get('reused_records', 0)}/{persistent_cache.get('total_records', 0)} pages reused"
        )
    schema = payload.get("schema") or {}
    if isinstance(schema, Mapping):
        schema_status = schema.get("status", "unknown")
        schema_version = schema.get("version")
        if schema_status == "current":
            lines.append(f"Schema: current v{schema_version}")
        else:
            lines.append(f"Schema: {schema_status}")
    missing = payload.get("missing", [])
    if missing:
        lines.append("Missing: " + ", ".join(str(item) for item in missing))
    validation = payload["validation"]
    if not isinstance(validation, Mapping):
        raise ValueError("Invalid status validation payload")
    if validation.get("checked"):
        lines.append(
            "Validation: "
            f"{'passed' if validation.get('passed') else 'failed'} "
            f"({validation.get('error_count', 0)} errors, {validation.get('warning_count', 0)} warnings)"
        )
    else:
        lines.append("Validation: not checked (use --validate)")
    warnings = payload.get("warnings") or []
    if warnings:
        lines.append("Warnings:")
        for warning in warnings:
            if isinstance(warning, Mapping):
                detail = f" ({warning.get('detail')})" if warning.get("detail") else ""
                lines.append(f"- {warning.get('code')}: {warning.get('message')}{detail}")
    lines.extend(["", "Next:"])
    for action in payload["next_actions"]:
        if isinstance(action, Mapping):
            args = action.get("arguments") or {}
            suffix = f" {json.dumps(args, ensure_ascii=False)}" if args else ""
            lines.append(f"- {action['tool']}: {action['label']}{suffix}")
            command = _status_command_for_action(action, command_target)
            if command:
                lines.append(f"  Run: {command}")
    return (0 if payload["ready"] else 1), "\n".join(lines)


def render_backup_list_text(payload: Mapping[str, object]) -> tuple[int, str]:
    lines = [f"Link backups: {payload['backup_dir']}", ""]
    backups = payload.get("backups", [])
    if not backups:
        lines.append("No backups found.")
    for warning in payload.get("warnings") or []:
        if isinstance(warning, Mapping):
            lines.append(f"Warning: could not read backup {warning.get('backup')}: {warning.get('error')}")
    if isinstance(backups, Sequence) and not isinstance(backups, (str, bytes)):
        for item in backups:
            if isinstance(item, Mapping):
                lines.append(f"- {item['name']} ({item['bytes']} bytes)")
    return 0, "\n".join(lines)


def render_backup_created_text(payload: Mapping[str, object], *, include_raw: bool = False) -> tuple[int, str]:
    lines = [
        f"Link backup created: {payload['path']}",
        f"Included: {', '.join(str(item) for item in payload['included'])}",
        f"Files: {payload['file_count']}",
        f"Size: {payload['bytes']} bytes",
    ]
    if not include_raw:
        lines.append("Note: raw/ was excluded by default because it may contain sensitive source material.")
    if payload["pruned"]:
        lines.append("Pruned old backups: " + ", ".join(str(item) for item in payload["pruned"]))
    return 0, "\n".join(lines)


def render_backup_restore_text(payload: Mapping[str, object], *, target: object = ".") -> tuple[int, str]:
    roots = ", ".join(str(item) for item in payload.get("restore_roots", [])) or "none"
    skipped = ", ".join(str(item) for item in payload.get("skipped_roots", []))
    lines = [
        f"Link backup restore: {payload.get('name')}",
        f"Archive: {payload.get('backup')}",
        f"Will restore: {roots}",
        f"Files: {payload.get('file_count', 0)}",
    ]
    if skipped:
        lines.append(f"Skipped: {skipped} ({payload.get('skipped_file_count', 0)} files)")
    if payload.get("restored"):
        safety = payload.get("safety_backup")
        if isinstance(safety, Mapping):
            lines.append(f"Safety backup: {safety.get('path')}")
        integrity = payload.get("integrity")
        if isinstance(integrity, Mapping) and integrity.get("checked"):
            result = "passed" if integrity.get("passed") else "failed"
            lines.append(
                "Integrity: "
                f"{result} "
                f"({integrity.get('error_count', 0)} errors, {integrity.get('warning_count', 0)} warnings)"
            )
        lines.append("Result: restored")
        return 0, "\n".join(lines)
    lines.extend([
        "Result: preview only",
        "",
        "Next:",
        f"  {_link_command(str(target), 'restore-backup', str(payload.get('name') or payload.get('backup')), '--confirm')}",
    ])
    return 0, "\n".join(lines)


def render_rebuild_backlinks_text(*, out_path: object, page_count: int, edge_count: int) -> tuple[int, str]:
    return 0, "\n".join([
        f"Rebuilt {out_path}",
        f"Pages: {page_count}",
        f"Edges: {edge_count}",
    ])


def _root_from_index_path(index_path: object) -> Path:
    path = Path(str(index_path))
    if path.name == "index.md":
        wiki_dir = path.parent
        return wiki_dir.parent if wiki_dir.name == "wiki" else wiki_dir
    if path.name == "wiki":
        return path.parent
    return path.parent


def _root_from_wiki_dir(wiki_dir: object) -> Path:
    path = Path(str(wiki_dir))
    return path.parent if path.name == "wiki" else path


def _link_command(command_target: str, *parts: str) -> str:
    command = ["link", *parts]
    if command_target:
        command.append(command_target)
    return display_command(command)


def _status_command_for_action(action: Mapping[str, object], command_target: str) -> str:
    tool = str(action.get("tool") or "").strip()
    arguments = action.get("arguments") if isinstance(action.get("arguments"), Mapping) else {}
    if tool == "doctor":
        return _link_command(command_target, "doctor", "--fix") if arguments.get("fix") else _link_command(
            command_target, "doctor"
        )
    if tool == "migrate_wiki":
        return _link_command(command_target, "migrate")
    if tool == "validate_wiki":
        return _link_command(command_target, "validate")
    if tool == "rebuild_backlinks":
        return _link_command(command_target, "rebuild-backlinks")
    if tool == "ingest_status":
        return _link_command(command_target, "ingest-status")
    if tool == "starter_prompts":
        return _link_command(command_target, "prompts")
    if tool == "query_link":
        query = str(arguments.get("query") or "").strip()
        if not query or query == "<user task>":
            query = "what should I know before continuing?"
        return _link_command(command_target, "query", query)
    if tool == "memory_brief":
        query = str(arguments.get("query") or "").strip()
        if not query or query == "<user task>":
            query = "working with Link"
        return _link_command(command_target, "brief", query)
    return ""


def render_rebuild_index_text(result: Mapping[str, object], *, index_path: object) -> tuple[int, str]:
    root = _root_from_index_path(index_path)
    link_py = root / "link.py"
    rebuild_command = display_command(["python3", str(link_py), "rebuild-backlinks", str(root)])
    return 0, "\n".join([
        f"Rebuilt {index_path}",
        f"Pages: {result['page_count']}",
        f"Sources: {result['source_count']}",
        f"Memories: {result['memory_count']}",
        f"Next: run {rebuild_command} before validation",
    ])
