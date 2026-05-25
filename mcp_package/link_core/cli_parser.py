"""Argument parser for the Link command-line interface."""
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .memory import MEMORY_SCOPES, MEMORY_TYPES
from .version import LINK_VERSION


DEFAULT_DEMO_DIR = "link-demo"
CliHandler = Callable[..., int]


def build_cli_parser(default_demo_dir: str = DEFAULT_DEMO_DIR) -> argparse.ArgumentParser:
    """Build the Link CLI argument parser."""
    parser = argparse.ArgumentParser(prog="link.py", description="Link command runner")
    parser.add_argument("--version", action="version", version=f"Link {LINK_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="print the Link CLI version")

    init_cmd = sub.add_parser("init", help="create or repair a normal Link wiki")
    init_cmd.add_argument("target", nargs="?", default=".")

    serve_cmd = sub.add_parser("serve", help="start the local Link web viewer")
    serve_cmd.add_argument("target", nargs="?", default=".")
    serve_cmd.add_argument("--port", type=int, default=3000)

    demo = sub.add_parser("demo", help="create a pre-ingested sample Link wiki")
    demo.add_argument("target", nargs="?", default=default_demo_dir)
    demo.add_argument("--force", action="store_true", help="replace an existing Link demo directory")

    try_cmd = sub.add_parser("try", help="create the demo and print the shortest proof loop")
    try_cmd.add_argument("target", nargs="?", default=default_demo_dir)
    try_cmd.add_argument("--force", action="store_true", help="replace an existing Link demo directory")
    try_cmd.add_argument("--serve", action="store_true", help="start the local viewer after printing the proof loop")
    try_cmd.add_argument("--port", type=int, default=3000)
    try_cmd.add_argument("--json", action="store_true", help="print machine-readable try data")

    welcome_cmd = sub.add_parser("welcome", help="print the shortest first-use path for Link")
    welcome_cmd.add_argument("target", nargs="?", default=".")
    welcome_cmd.add_argument("--project", default=None, help="project slug for project-scoped prompt examples")
    welcome_cmd.add_argument("--json", action="store_true", help="print machine-readable welcome data")

    prompts_cmd = sub.add_parser("prompts", aliases=["next"], help="print first-run agent prompts and local checks")
    prompts_cmd.add_argument("target", nargs="?", default=".")
    prompts_cmd.add_argument("--project", default=None, help="project slug for project-scoped prompt examples")
    prompts_cmd.add_argument("--json", action="store_true", help="print machine-readable prompt data")

    status_cmd = sub.add_parser("status", help="show Link readiness, counts, and next actions")
    status_cmd.add_argument("target", nargs="?", default=".")
    status_cmd.add_argument("--validate", action="store_true", help="include the ingest validation gate summary")
    status_cmd.add_argument("--json", action="store_true", help="print machine-readable status")

    health_cmd = sub.add_parser("health", help="show readiness, validation, and interrupted write state")
    health_cmd.add_argument("target", nargs="?", default=".")
    health_cmd.add_argument("--json", action="store_true", help="print machine-readable health status")

    operations_cmd = sub.add_parser("operations", help="inspect interrupted or active Link write operations")
    operations_cmd.add_argument("target", nargs="?", default=".")
    operations_cmd.add_argument("--limit", type=int, default=20, help="maximum operation markers to show")
    operations_cmd.add_argument("--json", action="store_true", help="print machine-readable operation status")

    backup_cmd = sub.add_parser("backup", help="create or list local wiki backup archives")
    backup_cmd.add_argument("target", nargs="?", default=".")
    backup_cmd.add_argument("--label", default="manual", help="short label for the backup filename")
    backup_cmd.add_argument("--include-raw", action="store_true", help="also include raw/ sources and captures")
    backup_cmd.add_argument("--list", action="store_true", dest="list_only", help="list recent backups instead of creating one")
    backup_cmd.add_argument("--json", action="store_true", help="print machine-readable backup status")

    doctor_cmd = sub.add_parser("doctor", help="check a Link wiki for common health issues")
    doctor_cmd.add_argument("target", nargs="?", default=".")
    doctor_cmd.add_argument("--fix", action="store_true", help="repair safe structural and backlink issues")

    migrate_cmd = sub.add_parser("migrate", help="apply safe Link wiki schema migrations")
    migrate_cmd.add_argument("target", nargs="?", default=".")
    migrate_cmd.add_argument("--json", action="store_true", help="print machine-readable migration status")

    validate_cmd = sub.add_parser("validate", help="validate wiki pages before accepting ingest output")
    validate_cmd.add_argument("target", nargs="?", default=".")
    validate_cmd.add_argument("--strict", action="store_true", help="fail on warnings as well as errors")
    validate_cmd.add_argument("--json", action="store_true", help="print machine-readable validation findings")

    ingest_status_cmd = sub.add_parser("ingest-status", help="show raw files pending wiki ingestion")
    ingest_status_cmd.add_argument("target", nargs="?", default=".")
    ingest_status_cmd.add_argument("--json", action="store_true", help="print machine-readable status")

    remember_cmd = sub.add_parser("remember", help="save a local agent memory")
    remember_cmd.add_argument("text", help="memory text to save")
    remember_cmd.add_argument("target", nargs="?", default=".")
    remember_cmd.add_argument("--title", default=None, help="memory page title")
    remember_cmd.add_argument("--type", choices=MEMORY_TYPES, default="note", dest="memory_type")
    remember_cmd.add_argument("--scope", choices=MEMORY_SCOPES, default="user")
    remember_cmd.add_argument("--tags", default=None, help="comma-separated tags")
    remember_cmd.add_argument("--source", default="manual", help="where this memory came from")
    remember_cmd.add_argument("--project", default=None, help="project key for project-scoped memories")
    remember_cmd.add_argument("--allow-duplicate", action="store_true", help="create a new memory even if a strong duplicate exists")
    remember_cmd.add_argument("--allow-conflict", action="store_true", help="create a memory even if it may conflict with an active memory")
    remember_cmd.add_argument("--json", action="store_true", help="print machine-readable status")

    propose_cmd = sub.add_parser("propose-memories", help="propose durable memories from chat or session notes without writing them")
    propose_cmd.add_argument("source_input", help="text or path to a note/session file")
    propose_cmd.add_argument("target", nargs="?", default=".")
    propose_cmd.add_argument("--limit", type=int, default=10)
    propose_cmd.add_argument("--project", default=None, help="project key for duplicate/conflict checks")
    propose_cmd.add_argument("--json", action="store_true", help="print machine-readable proposals")

    capture_cmd = sub.add_parser("capture-session", help="save session notes to raw/ and propose memories")
    capture_cmd.add_argument("source_input", help="text or path to a chat/session note")
    capture_cmd.add_argument("target", nargs="?", default=".")
    capture_cmd.add_argument("--title", default=None, help="title for the raw capture note")
    capture_cmd.add_argument("--limit", type=int, default=10)
    capture_cmd.add_argument("--project", default=None, help="project key for proposal checks")
    capture_cmd.add_argument("--json", action="store_true", help="print machine-readable capture details")

    capture_inbox_cmd = sub.add_parser("capture-inbox", help="list saved raw session captures")
    capture_inbox_cmd.add_argument("target", nargs="?", default=".")
    capture_inbox_cmd.add_argument("--limit", type=int, default=20)
    capture_inbox_cmd.add_argument("--project", default=None, help="include global captures plus this project")
    capture_inbox_cmd.add_argument("--json", action="store_true", help="print machine-readable capture inbox")

    accept_capture_cmd = sub.add_parser("accept-capture", help="accept one proposal from a raw session capture")
    accept_capture_cmd.add_argument("capture", help="raw capture path or filename")
    accept_capture_cmd.add_argument("target", nargs="?", default=".")
    accept_capture_cmd.add_argument("--index", type=int, default=1, help="1-based proposal index to accept")
    accept_capture_cmd.add_argument("--title", default=None, help="override accepted memory title")
    accept_capture_cmd.add_argument("--type", dest="memory_type", choices=MEMORY_TYPES, default=None)
    accept_capture_cmd.add_argument("--scope", choices=MEMORY_SCOPES, default=None)
    accept_capture_cmd.add_argument("--tags", default=None, help="comma-separated tags")
    accept_capture_cmd.add_argument("--project", default=None, help="project key for accepted project memory")
    accept_capture_cmd.add_argument("--allow-duplicate", action="store_true", help="create a new memory even if a strong duplicate exists")
    accept_capture_cmd.add_argument("--allow-conflict", action="store_true", help="create a memory even if it may conflict with an active memory")
    accept_capture_cmd.add_argument("--json", action="store_true", help="print machine-readable acceptance details")

    redact_capture_cmd = sub.add_parser("redact-capture", help="redact secret-looking values from a raw session capture")
    redact_capture_cmd.add_argument("capture", help="raw capture path or filename")
    redact_capture_cmd.add_argument("target", nargs="?", default=".")
    redact_capture_cmd.add_argument("--replacement", default="[redacted-secret]", help="replacement text")
    redact_capture_cmd.add_argument("--json", action="store_true", help="print machine-readable redaction details")

    delete_capture_cmd = sub.add_parser("delete-capture", help="delete a raw session capture after explicit confirmation")
    delete_capture_cmd.add_argument("capture", help="raw capture path or filename")
    delete_capture_cmd.add_argument("target", nargs="?", default=".")
    delete_capture_cmd.add_argument("--confirm", action="store_true", help="required to delete the capture")
    delete_capture_cmd.add_argument("--json", action="store_true", help="print machine-readable deletion details")

    update_memory_cmd = sub.add_parser("update-memory", help="merge new text into an existing memory")
    update_memory_cmd.add_argument("identifier", help="memory page name, title, or path")
    update_memory_cmd.add_argument("text", help="new memory text to merge")
    update_memory_cmd.add_argument("target", nargs="?", default=".")
    update_memory_cmd.add_argument("--source", default="manual", help="where this update came from")
    update_memory_cmd.add_argument("--project", default=None, help="project key for conflict checks")
    update_memory_cmd.add_argument("--allow-conflict", action="store_true", help="update even if the text may conflict with another active memory")
    update_memory_cmd.add_argument("--json", action="store_true", help="print machine-readable status")

    recall_cmd = sub.add_parser("recall", help="search local agent memories")
    recall_cmd.add_argument("query", help="memory query")
    recall_cmd.add_argument("target", nargs="?", default=".")
    recall_cmd.add_argument("--limit", type=int, default=10)
    recall_cmd.add_argument("--include-archived", action="store_true", help="include archived and stale memories")
    recall_cmd.add_argument("--project", default=None, help="include user/global memories plus this project's memories")
    recall_cmd.add_argument("--json", action="store_true", help="print machine-readable results")

    query_cmd = sub.add_parser("query", aliases=["query-link"], help="build a compact answer-ready Link context packet")
    query_cmd.add_argument("query", help="task or question to retrieve memory and wiki context for")
    query_cmd.add_argument("target", nargs="?", default=".")
    query_cmd.add_argument("--budget", choices=("small", "medium", "large"), default="medium")
    query_cmd.add_argument("--project", default=None, help="include user/global memories plus this project's memories")
    query_cmd.add_argument("--json", action="store_true", help="print machine-readable context packet")

    graph_summary_cmd = sub.add_parser("graph-summary", help="show a bounded graph summary for agent context budgets")
    graph_summary_cmd.add_argument("topic", nargs="?", default="", help="optional topic/query for a bounded neighborhood")
    graph_summary_cmd.add_argument("target", nargs="?", default=".")
    graph_summary_cmd.add_argument("--limit", type=int, default=40, help="maximum returned nodes")
    graph_summary_cmd.add_argument("--depth", type=int, default=1, help="neighborhood depth for topic mode")
    graph_summary_cmd.add_argument("--max-edges", type=int, default=120, help="maximum returned edges")
    graph_summary_cmd.add_argument("--json", action="store_true", help="print machine-readable graph summary")

    benchmark_cmd = sub.add_parser("benchmark", help="measure local search, query, and graph performance")
    benchmark_cmd.add_argument("query", nargs="?", default="agent memory", help="query to benchmark")
    benchmark_cmd.add_argument("target", nargs="?", default=".")
    benchmark_cmd.add_argument("--budget", choices=("small", "medium", "large"), default="small")
    benchmark_cmd.add_argument("--project", default=None, help="include user/global memories plus this project's memories")
    benchmark_cmd.add_argument("--json", action="store_true", help="print machine-readable benchmark data")

    brief_cmd = sub.add_parser("brief", help="prime an agent with relevant local memory")
    brief_cmd.add_argument("query", nargs="?", default="", help="optional task or question to retrieve memory for")
    brief_cmd.add_argument("target", nargs="?", default=".")
    brief_cmd.add_argument("--limit", type=int, default=6)
    brief_cmd.add_argument("--project", default=None, help="include user/global memories plus this project's memories")
    brief_cmd.add_argument("--json", action="store_true", help="print machine-readable memory brief")

    profile_cmd = sub.add_parser("profile", help="show what Link remembers")
    profile_cmd.add_argument("target", nargs="?", default=".")
    profile_cmd.add_argument("--limit", type=int, default=10)
    profile_cmd.add_argument("--project", default=None, help="include user/global memories plus this project's memories")
    profile_cmd.add_argument("--json", action="store_true", help="print machine-readable profile")

    audit_cmd = sub.add_parser("memory-audit", help="audit memory health, review backlog, and raw captures")
    audit_cmd.add_argument("target", nargs="?", default=".")
    audit_cmd.add_argument("--limit", type=int, default=10)
    audit_cmd.add_argument("--project", default=None, help="include user/global memories plus this project's memories")
    audit_cmd.add_argument("--json", action="store_true", help="print machine-readable audit")

    archive_cmd = sub.add_parser("archive-memory", help="archive a stale or unwanted memory")
    archive_cmd.add_argument("identifier", help="memory page name, title, or path")
    archive_cmd.add_argument("target", nargs="?", default=".")
    archive_cmd.add_argument("--reason", default=None, help="why this memory is being archived")
    archive_cmd.add_argument("--json", action="store_true", help="print machine-readable status")

    restore_cmd = sub.add_parser("restore-memory", help="restore an archived memory to active status")
    restore_cmd.add_argument("identifier", help="memory page name, title, or path")
    restore_cmd.add_argument("target", nargs="?", default=".")
    restore_cmd.add_argument("--json", action="store_true", help="print machine-readable status")

    forget_cmd = sub.add_parser("forget-memory", help="permanently delete a memory after explicit confirmation")
    forget_cmd.add_argument("identifier", help="memory page name, title, or path")
    forget_cmd.add_argument("target", nargs="?", default=".")
    forget_cmd.add_argument("--confirm", action="store_true", help="required to delete the memory")
    forget_cmd.add_argument("--json", action="store_true", help="print machine-readable status")

    inbox_cmd = sub.add_parser("memory-inbox", help="show memories that need review")
    inbox_cmd.add_argument("target", nargs="?", default=".")
    inbox_cmd.add_argument("--limit", type=int, default=20)
    inbox_cmd.add_argument("--include-archived", action="store_true", help="include archived memories")
    inbox_cmd.add_argument("--project", default=None, help="include user/global memories plus this project's memories")
    inbox_cmd.add_argument("--json", action="store_true", help="print machine-readable inbox")

    review_cmd = sub.add_parser("review-memory", help="mark a memory as reviewed")
    review_cmd.add_argument("identifier", help="memory page name, title, or path")
    review_cmd.add_argument("target", nargs="?", default=".")
    review_cmd.add_argument("--note", default=None, help="optional review note")
    review_cmd.add_argument("--json", action="store_true", help="print machine-readable status")

    explain_cmd = sub.add_parser("explain-memory", help="explain why a memory exists and whether it is recall-ready")
    explain_cmd.add_argument("identifier", help="memory page name, title, or path")
    explain_cmd.add_argument("target", nargs="?", default=".")
    explain_cmd.add_argument("--json", action="store_true", help="print machine-readable explanation")

    rebuild_index_cmd = sub.add_parser("rebuild-index", help="regenerate wiki/index.md from current pages")
    rebuild_index_cmd.add_argument("target", nargs="?", default=".")

    rebuild_cmd = sub.add_parser("rebuild-backlinks", help="rebuild wiki/_backlinks.json")
    rebuild_cmd.add_argument("target", nargs="?", default=".")

    verify_mcp_cmd = sub.add_parser("verify-mcp", help="verify link-mcp import and print MCP config")
    verify_mcp_cmd.add_argument("target", nargs="?", default=".")
    verify_mcp_cmd.add_argument("--json", action="store_true", help="print machine-readable status")
    verify_mcp_cmd.add_argument("--python", default=None, help="Python executable to verify")

    return parser


def dispatch_cli_command(args: Any, handlers: Mapping[str, CliHandler]) -> int:
    """Dispatch parsed Link CLI arguments to runtime-provided handlers."""
    command = args.command
    if command == "version":
        return handlers["version"]()
    if command == "init":
        return handlers["init"](Path(args.target))
    if command == "serve":
        return handlers["serve"](Path(args.target), port=args.port)
    if command == "demo":
        return handlers["demo"](Path(args.target), force=args.force)
    if command == "try":
        return handlers["try"](
            Path(args.target),
            force=args.force,
            serve=args.serve,
            port=args.port,
            json_output=args.json,
        )
    if command == "welcome":
        return handlers["welcome"](Path(args.target), project=args.project, json_output=args.json)
    if command in {"prompts", "next"}:
        return handlers["prompts"](Path(args.target), project=args.project, json_output=args.json)
    if command == "status":
        return handlers["status"](Path(args.target), include_validation=args.validate, json_output=args.json)
    if command == "health":
        return handlers["health"](Path(args.target), json_output=args.json)
    if command == "operations":
        return handlers["operations"](Path(args.target), limit=args.limit, json_output=args.json)
    if command == "backup":
        return handlers["backup"](
            Path(args.target),
            label=args.label,
            include_raw=args.include_raw,
            list_only=args.list_only,
            json_output=args.json,
        )
    if command == "doctor":
        return handlers["doctor"](Path(args.target), fix=args.fix)
    if command == "migrate":
        return handlers["migrate"](Path(args.target), json_output=args.json)
    if command == "validate":
        return handlers["validate"](Path(args.target), strict=args.strict, json_output=args.json)
    if command == "ingest-status":
        return handlers["ingest-status"](Path(args.target), json_output=args.json)
    if command == "remember":
        return handlers["remember"](
            Path(args.target),
            args.text,
            title=args.title,
            memory_type=args.memory_type,
            scope=args.scope,
            tags=args.tags,
            source=args.source,
            project=args.project,
            allow_duplicate=args.allow_duplicate,
            allow_conflict=args.allow_conflict,
            json_output=args.json,
        )
    if command == "propose-memories":
        return handlers["propose-memories"](
            Path(args.target),
            args.source_input,
            limit=args.limit,
            project=args.project,
            json_output=args.json,
        )
    if command == "capture-session":
        return handlers["capture-session"](
            Path(args.target),
            args.source_input,
            title=args.title,
            limit=args.limit,
            project=args.project,
            json_output=args.json,
        )
    if command == "capture-inbox":
        return handlers["capture-inbox"](
            Path(args.target),
            limit=args.limit,
            project=args.project,
            json_output=args.json,
        )
    if command == "accept-capture":
        return handlers["accept-capture"](
            Path(args.target),
            args.capture,
            index=args.index,
            title=args.title,
            memory_type=args.memory_type,
            scope=args.scope,
            tags=args.tags,
            project=args.project,
            allow_duplicate=args.allow_duplicate,
            allow_conflict=args.allow_conflict,
            json_output=args.json,
        )
    if command == "redact-capture":
        return handlers["redact-capture"](
            Path(args.target),
            args.capture,
            replacement=args.replacement,
            json_output=args.json,
        )
    if command == "delete-capture":
        return handlers["delete-capture"](
            Path(args.target),
            args.capture,
            confirm=args.confirm,
            json_output=args.json,
        )
    if command == "update-memory":
        return handlers["update-memory"](
            Path(args.target),
            args.identifier,
            args.text,
            source=args.source,
            allow_conflict=args.allow_conflict,
            project=args.project,
            json_output=args.json,
        )
    if command == "recall":
        return handlers["recall"](
            Path(args.target),
            args.query,
            limit=args.limit,
            json_output=args.json,
            include_archived=args.include_archived,
            project=args.project,
        )
    if command in {"query", "query-link"}:
        return handlers["query"](
            Path(args.target),
            args.query,
            budget=args.budget,
            project=args.project,
            json_output=args.json,
        )
    if command == "graph-summary":
        return handlers["graph-summary"](
            Path(args.target),
            topic=args.topic,
            limit=args.limit,
            depth=args.depth,
            max_edges=args.max_edges,
            json_output=args.json,
        )
    if command == "benchmark":
        return handlers["benchmark"](
            Path(args.target),
            query_text=args.query,
            budget=args.budget,
            project=args.project,
            json_output=args.json,
        )
    if command == "brief":
        return handlers["brief"](Path(args.target), query=args.query, limit=args.limit, project=args.project, json_output=args.json)
    if command == "profile":
        return handlers["profile"](Path(args.target), limit=args.limit, project=args.project, json_output=args.json)
    if command == "memory-audit":
        return handlers["memory-audit"](Path(args.target), limit=args.limit, project=args.project, json_output=args.json)
    if command == "archive-memory":
        return handlers["archive-memory"](Path(args.target), args.identifier, reason=args.reason, json_output=args.json)
    if command == "restore-memory":
        return handlers["restore-memory"](Path(args.target), args.identifier, json_output=args.json)
    if command == "forget-memory":
        return handlers["forget-memory"](Path(args.target), args.identifier, confirm=args.confirm, json_output=args.json)
    if command == "memory-inbox":
        return handlers["memory-inbox"](
            Path(args.target),
            limit=args.limit,
            include_archived=args.include_archived,
            project=args.project,
            json_output=args.json,
        )
    if command == "review-memory":
        return handlers["review-memory"](Path(args.target), args.identifier, note=args.note, json_output=args.json)
    if command == "explain-memory":
        return handlers["explain-memory"](Path(args.target), args.identifier, json_output=args.json)
    if command == "rebuild-index":
        return handlers["rebuild-index"](Path(args.target))
    if command == "rebuild-backlinks":
        return handlers["rebuild-backlinks"](Path(args.target))
    if command == "verify-mcp":
        return handlers["verify-mcp"](Path(args.target), json_output=args.json, python_cmd=args.python)
    raise ValueError(f"unknown command: {command}")
