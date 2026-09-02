"""Argument parser for the Link command-line interface."""
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .memory import MEMORY_SCOPES, MEMORY_TYPES, MEMORY_VISIBILITIES
from .version import LINK_VERSION


DEFAULT_DEMO_DIR = "link-demo"
DEFAULT_PROOF_DIR = "link-proof"
CliHandler = Callable[..., int]


COMMAND_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Start here", (
        "try", "setup", "onboard", "init", "demo", "proof", "welcome", "prompts", "import",
    )),
    ("Memory — the core loop", (
        "remember", "recall", "recipes", "query", "brief", "start", "handoff", "handoffs",
        "session-end", "semantic",
    )),
    ("Review & governance", (
        "memory-inbox", "review-memory", "explain-memory", "consolidate", "digest",
        "capture-inbox", "accept-capture", "delete-capture", "dedup-captures",
        "redact-capture", "capture-session", "propose-memories", "update-memory",
        "archive-memory", "restore-memory", "forget-memory",
        "set-memory-visibility", "memory-log", "memory-audit",
    )),
    ("Agents & automation", (
        "connect", "hook", "verify-mcp",
    )),
    ("Workspace & health", (
        "status", "health", "doctor", "validate", "migrate", "backup",
        "restore-backup", "operations", "seed", "ingest", "ingest-status",
        "import-obsidian",
    )),
    ("Sharing & viewing", (
        "sync", "serve", "share", "snapshot", "graph-summary", "team-sync",
        "compliance-export",
    )),
    ("Utilities", (
        "version", "benchmark", "wins", "profile", "rebuild-index",
        "rebuild-backlinks", "query-link", "stale",
    )),
)


class _GroupedCommandHelp(argparse.RawDescriptionHelpFormatter):
    """Hide the flat 60-command listing; the grouped epilog carries it."""

    def _format_action(self, action):
        if isinstance(action, argparse._SubParsersAction):
            return ""
        return super()._format_action(action)


def _grouped_epilog() -> str:
    lines = ["commands:"]
    for group, names in COMMAND_GROUPS:
        lines.append(f"\n  {group}:")
        lines.append("    " + ", ".join(names))
    lines.append("\nRun `link.py <command> --help` for that command's options.")
    return "\n".join(lines)


def build_cli_parser(
    default_demo_dir: str = DEFAULT_DEMO_DIR,
    default_proof_dir: str = DEFAULT_PROOF_DIR,
) -> argparse.ArgumentParser:
    """Build the Link CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="link.py",
        description="Link — local, review-gated memory for AI agents. New? Run: link.py try",
        epilog=_grouped_epilog(),
        formatter_class=_GroupedCommandHelp,
    )
    parser.add_argument("--version", action="version", version=f"Link {LINK_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

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

    proof_cmd = sub.add_parser("proof", help="prove cross-agent memory continuity in a local demo workspace")
    proof_cmd.add_argument("target", nargs="?", default=default_proof_dir)
    proof_cmd.add_argument("--force", action="store_true", help="replace an existing Link proof workspace")
    proof_cmd.add_argument("--serve", action="store_true", help="start the local viewer after printing the proof")
    proof_cmd.add_argument("--port", type=int, default=3000)
    proof_cmd.add_argument("--json", action="store_true", help="print machine-readable proof data")

    import_cmd = sub.add_parser("import", help="bring memory home from other tools (claude-code, cursor, codex, or any text file) as reviewable proposals")
    import_cmd.add_argument("import_source", metavar="source", choices=["claude-code", "cursor", "codex", "file"], help="where to import from")
    import_cmd.add_argument("target", nargs="?", default=".")
    import_cmd.add_argument("--file", default=None, dest="import_file", help="path to a text/markdown file (required for source 'file'; e.g. ChatGPT memories pasted into a file)")
    import_cmd.add_argument("--project", default=None, help="project slug for the imported proposals")
    import_cmd.add_argument("--json", action="store_true", help="print machine-readable import results")

    handoff_cmd = sub.add_parser("handoff", help="write a session handoff so the next agent (any agent) resumes where you left off")
    handoff_cmd.add_argument("note", help="where you left off - standalone, the next session cannot ask what you meant")
    handoff_cmd.add_argument("target", nargs="?", default=".")
    handoff_cmd.add_argument("--task", default=None, help="short task title for the handoff")
    handoff_cmd.add_argument("--next", action="append", default=[], dest="next_steps", help="an explicit next step; repeatable")
    handoff_cmd.add_argument("--project", default=None)
    handoff_cmd.add_argument("--from", default="cli", dest="source", help="which agent/session is handing off")
    handoff_cmd.add_argument("--json", action="store_true")

    handoffs_cmd = sub.add_parser("handoffs", help="list pending session handoffs, or clear one")
    handoffs_cmd.add_argument("target", nargs="?", default=".")
    handoffs_cmd.add_argument("--clear", default=None, help="handoff filename to clear after resuming it")
    handoffs_cmd.add_argument("--json", action="store_true")

    digest_cmd = sub.add_parser("digest", help="weekly reflection: what you taught Link, what is aging, what is drifting")
    digest_cmd.add_argument("target", nargs="?", default=".")
    digest_cmd.add_argument("--days", type=int, default=7, help="look-back window in days (default 7)")
    digest_cmd.add_argument("--json", action="store_true", help="print machine-readable digest")

    sync_cmd = sub.add_parser("sync", help="sync memory between machines through your own git remote (no server)")
    sync_cmd.add_argument("target", nargs="?", default=".")
    sync_cmd.add_argument("--init", action="store_true", dest="sync_init", help="turn the workspace into a sync repo (idempotent)")
    sync_cmd.add_argument("--remote", default=None, help="git remote URL to sync through (with --init)")
    sync_cmd.add_argument("--status", action="store_true", dest="sync_status", help="show sync state without syncing")
    sync_cmd.add_argument("--json", action="store_true", help="print machine-readable sync details")

    setup_cmd = sub.add_parser("setup", help="one command for install day and every upgrade: workspace + every detected agent, wired")
    setup_cmd.add_argument("target", nargs="?", default="~/link")
    setup_cmd.add_argument("--preview", action="store_true", help="show what would be configured without writing agent configs")
    setup_cmd.add_argument("--no-semantic", action="store_true", dest="no_semantic", help="skip the default meaning-based recall setup (fast tier, one-time ~30 MB local model download)")
    setup_cmd.add_argument("--json", action="store_true", help="print machine-readable setup details")

    onboard_cmd = sub.add_parser("onboard", help="set up a real Link workspace and print the agent-first next steps")
    onboard_cmd.add_argument("target", nargs="?", default="~/link")
    onboard_cmd.add_argument("--agent", action="append", default=[], help="agent config to preview or write; repeatable")
    onboard_cmd.add_argument("--all-agents", action="store_true", help="preview or write all supported agent configs")
    onboard_cmd.add_argument("--write", action="store_true", help="update selected agent config files")
    onboard_cmd.add_argument(
        "--hooks",
        action="store_true",
        help="also configure session hooks for selected agents that support them (Claude Code, Codex, Cursor)",
    )
    onboard_cmd.add_argument("--first-memory", default=None, help="seed one explicit memory for review")
    onboard_cmd.add_argument(
        "--seed-project",
        nargs="?",
        const=".",
        default=None,
        help="seed source-backed project context from this directory during onboarding",
    )
    onboard_cmd.add_argument("--project", default=None, help="project slug for prompts and first memory")
    onboard_cmd.add_argument("--port", type=int, default=3000, help="local viewer port to print")
    onboard_cmd.add_argument("--json", action="store_true", help="print machine-readable onboarding data")

    seed_cmd = sub.add_parser("seed", help="seed Link with source-backed context from this project")
    seed_cmd.add_argument("project", nargs="?", default=".", help="project directory to inspect")
    seed_cmd.add_argument("target", nargs="?", default="~/link", help="Link workspace to seed")
    seed_cmd.add_argument("--project-name", default=None, help="display name/project slug for the generated seed")
    seed_cmd.add_argument("--overwrite", action="store_true", help="replace the generated seed source if it already exists")
    seed_cmd.add_argument("--dry-run", action="store_true", help="show what would be seeded without writing files")
    seed_cmd.add_argument("--limit", type=int, default=12, help="maximum allowlisted project files to inspect")
    seed_cmd.add_argument("--no-git-log", action="store_true", help="do not include recent git commit summaries")
    seed_cmd.add_argument("--git-log-limit", type=int, default=20, help="maximum recent git commits to include")
    seed_cmd.add_argument("--json", action="store_true", help="print machine-readable seed status")

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
    operations_cmd.add_argument("--recover", metavar="MARKER", help="recover an interrupted operation from its snapshot")
    operations_cmd.add_argument("--confirm", action="store_true", help="required to apply an operation recovery snapshot")
    operations_cmd.add_argument("--json", action="store_true", help="print machine-readable operation status")

    backup_cmd = sub.add_parser("backup", help="create or list local wiki backup archives")
    backup_cmd.add_argument("target", nargs="?", default=".")
    backup_cmd.add_argument("--label", default="manual", help="short label for the backup filename")
    backup_cmd.add_argument("--include-raw", action="store_true", help="also include raw/ sources and captures")
    backup_cmd.add_argument("--list", action="store_true", dest="list_only", help="list recent backups instead of creating one")
    backup_cmd.add_argument("--json", action="store_true", help="print machine-readable backup status")

    restore_backup_cmd = sub.add_parser("restore-backup", help="preview or restore a local Link backup archive")
    restore_backup_cmd.add_argument("backup", help="backup filename from .link-backups/ or path to a .tar.gz archive")
    restore_backup_cmd.add_argument("target", nargs="?", default=".")
    restore_backup_cmd.add_argument("--include-raw", action="store_true", help="also restore raw/ if the archive contains it")
    restore_backup_cmd.add_argument("--confirm", action="store_true", help="required to replace local files")
    restore_backup_cmd.add_argument("--no-safety-backup", action="store_true", help="skip creating a pre-restore safety backup")
    restore_backup_cmd.add_argument("--json", action="store_true", help="print machine-readable restore status")

    compliance_cmd = sub.add_parser("compliance-export", help="export a redacted audit packet for security or team review")
    compliance_cmd.add_argument("target", nargs="?", default=".")
    compliance_cmd.add_argument("--output", default=None, help="write JSON to this file instead of stdout")
    compliance_cmd.add_argument("--project", default=None, help="filter project-scoped memory context")
    compliance_cmd.add_argument("--limit", type=int, default=100, help="maximum memories/log entries to include")
    compliance_cmd.add_argument("--json", action="store_true", help="print machine-readable export status after writing --output")

    team_sync_cmd = sub.add_parser("team-sync", help="share visibility:team memories with your team through a git remote (no server)")
    team_sync_cmd.add_argument("target", nargs="?", default=".")
    team_sync_cmd.add_argument("--init", action="store_true", dest="team_init", help="set up the shared team workspace (idempotent)")
    team_sync_cmd.add_argument("--remote", default=None, help="shared git remote URL (with --init)")
    team_sync_cmd.add_argument("--dir", default=None, dest="team_dir", help="where the team workspace lives (default: sibling of the workspace)")
    team_sync_cmd.add_argument("--json", action="store_true", help="print machine-readable team sync details")

    share_cmd = sub.add_parser("share", help="print a local viewer permalink for a page or memory")
    share_cmd.add_argument("identifier", help="page name, title, path, alias, or search query")
    share_cmd.add_argument("target", nargs="?", default=".")
    share_cmd.add_argument("--port", type=int, default=3000, help="local viewer port to include in the URL")
    share_cmd.add_argument("--host", default="127.0.0.1", help="local viewer host to include in the URL")
    share_cmd.add_argument("--json", action="store_true", help="print machine-readable share details")

    snapshot_cmd = sub.add_parser("snapshot", help="export a static read-only HTML snapshot")
    snapshot_cmd.add_argument("target", nargs="?", default=".")
    snapshot_cmd.add_argument("--output", default="link-snapshot", help="directory to write the snapshot into")
    snapshot_cmd.add_argument("--include-memories", action="store_true", help="include memory pages intentionally")
    snapshot_cmd.add_argument("--include-private-memories", action="store_true", help="include visibility: private memory pages too")
    snapshot_cmd.add_argument("--allow-sensitive", action="store_true", help="export even if wiki pages contain secret-looking values")
    snapshot_cmd.add_argument("--force", action="store_true", help="replace a non-empty output directory")
    snapshot_cmd.add_argument("--title", default="Link", help="snapshot title")
    snapshot_cmd.add_argument("--json", action="store_true", help="print machine-readable snapshot status")

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

    ingest_cmd = sub.add_parser("ingest", help="plan or apply deterministic ingestion for a supported structured source")
    ingest_cmd.add_argument("source", help="source path under the Link workspace raw/ directory")
    ingest_cmd.add_argument("target", nargs="?", default=".")
    ingest_cmd.add_argument("--adapter", required=True, help="structured source adapter name")
    ingest_cmd.add_argument("--exclude", action="append", default=[], help="adapter-specific group to exclude; repeatable")
    ingest_cmd.add_argument("--apply", action="store_true", help="apply the plan after staging and validation")
    ingest_cmd.add_argument("--replace-unmanaged", action="store_true", help="replace existing outputs not yet owned by this adapter")
    ingest_cmd.add_argument("--prune", action="store_true", help="delete managed outputs no longer produced by the adapter")
    ingest_cmd.add_argument("--json", action="store_true", help="print machine-readable plan or result")

    ingest_status_cmd = sub.add_parser("ingest-status", help="show raw files pending wiki ingestion")
    ingest_status_cmd.add_argument("target", nargs="?", default=".")
    ingest_status_cmd.add_argument("--json", action="store_true", help="print machine-readable status")

    obsidian_cmd = sub.add_parser("import-obsidian", help="copy Obsidian Markdown notes into raw/ for Link ingest")
    obsidian_cmd.add_argument("vault", help="path to the Obsidian vault folder")
    obsidian_cmd.add_argument("target", nargs="?", default=".")
    obsidian_cmd.add_argument("--overwrite", action="store_true", help="replace previously imported raw notes")
    obsidian_cmd.add_argument("--dry-run", action="store_true", help="show what would be imported without writing files")
    obsidian_cmd.add_argument("--limit", type=int, default=None, help="maximum notes to scan/import")
    obsidian_cmd.add_argument("--json", action="store_true", help="print machine-readable import status")

    remember_cmd = sub.add_parser(
        "remember",
        help="save a local agent memory",
        epilog=(
            "one rule for the knobs: finding it -> --trigger · fencing it -> --applies-when · "
            "owning it -> --scope/--project/--visibility · replacing it -> --supersedes (name or title) · "
            "aging it -> --review-after/--expires-at. When in doubt, use none; every knob can be added later."
        ),
    )
    remember_cmd.add_argument("text", help="memory text to save")
    remember_cmd.add_argument("target", nargs="?", default=".")
    remember_cmd.add_argument("--title", default=None, help="memory page title")
    remember_cmd.add_argument("--type", choices=MEMORY_TYPES, default=None, dest="memory_type",
                              help="memory type; inferred from the text's cues when omitted (falls back to note)")
    remember_cmd.add_argument("--scope", choices=MEMORY_SCOPES, default="user")
    remember_cmd.add_argument("--visibility", choices=MEMORY_VISIBILITIES, default=None, help="sharing intent: private, project, or team")
    remember_cmd.add_argument("--tags", default=None, help="comma-separated tags")
    remember_cmd.add_argument("--source", default="manual", help="where this memory came from")
    remember_cmd.add_argument("--project", default=None, help="project key for project-scoped memories")
    remember_cmd.add_argument("--review-after", default=None, help="YYYY-MM-DD date when this memory should be checked again")
    remember_cmd.add_argument("--expires-at", default=None, help="YYYY-MM-DD date when this memory should leave default recall")
    remember_cmd.add_argument("--trigger", default=None, help="short phrase describing when this memory applies (recommended for --type procedure)")
    remember_cmd.add_argument("--applies-when", default=None, dest="applies_when", help='scoping conditions, e.g. "project:link, task:cutting a release, path:*repo*" (OR semantics)')
    remember_cmd.add_argument("--supersedes", default=None, help="name of the active memory this one replaces; the old memory is archived with lineage")
    remember_cmd.add_argument("--context", default=None, help="surrounding text from the memory's origin; helps recall find it, never part of the claim (600 chars max)")
    remember_cmd.add_argument("--allow-duplicate", action="store_true", help="create a new memory even if a strong duplicate exists")
    remember_cmd.add_argument("--allow-secret", action="store_true", help="save even if the text looks like a credential (memory is plain files read by every agent)")
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

    session_end_cmd = sub.add_parser("session-end", aliases=["end"], help="end a session by saving proposal-only notes and memory candidates")
    session_end_cmd.add_argument("source_input", help="text, path, or '-' for stdin session notes")
    session_end_cmd.add_argument("target", nargs="?", default=".")
    session_end_cmd.add_argument("--title", default=None, help="title for the raw session-end note")
    session_end_cmd.add_argument("--limit", type=int, default=3, help="maximum memory proposals to return")
    session_end_cmd.add_argument("--project", default=None, help="project key for proposal checks")
    session_end_cmd.add_argument("--json", action="store_true", help="print machine-readable session-end details")

    capture_inbox_cmd = sub.add_parser("capture-inbox", help="list saved raw session captures")
    capture_inbox_cmd.add_argument("target", nargs="?", default=".")
    capture_inbox_cmd.add_argument("--limit", type=int, default=20)
    capture_inbox_cmd.add_argument("--project", default=None, help="include global captures plus this project")
    capture_inbox_cmd.add_argument("--json", action="store_true", help="print machine-readable capture inbox")
    capture_inbox_cmd.add_argument("--proposals", type=int, default=3, dest="proposal_limit",
                                   help="proposal previews per capture (1-50; accept can reach them all regardless)")

    accept_capture_cmd = sub.add_parser("accept-capture", help="accept one proposal from a raw session capture")
    accept_capture_cmd.add_argument("capture", help="raw capture path or filename")
    accept_capture_cmd.add_argument("target", nargs="?", default=".")
    accept_capture_cmd.add_argument("--index", type=int, default=1, help="1-based proposal index to accept")
    accept_capture_cmd.add_argument("--all", action="store_true", dest="accept_all", help="accept every proposal in this capture (duplicates and conflicts are skipped and reported)")
    accept_capture_cmd.add_argument("--title", default=None, help="override accepted memory title")
    accept_capture_cmd.add_argument("--type", dest="memory_type", choices=MEMORY_TYPES, default=None)
    accept_capture_cmd.add_argument("--scope", choices=MEMORY_SCOPES, default=None)
    accept_capture_cmd.add_argument("--visibility", choices=MEMORY_VISIBILITIES, default=None, help="sharing intent for the accepted memory")
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
    delete_capture_cmd.add_argument("capture", nargs="?", default=None, help="raw capture path or filename (omit with --all to clear every pending capture)")
    delete_capture_cmd.add_argument("target", nargs="?", default=".")
    delete_capture_cmd.add_argument("--confirm", action="store_true", help="required to delete the capture")
    delete_capture_cmd.add_argument("--all", action="store_true", dest="delete_all", help="delete every pending capture (dismissals recorded, so their proposals never return)")
    delete_capture_cmd.add_argument("--json", action="store_true", help="print machine-readable deletion details")

    dedup_captures_cmd = sub.add_parser("dedup-captures", help="collapse review-inbox captures that offer nothing new")
    dedup_captures_cmd.add_argument("target", nargs="?", default=".")
    dedup_captures_cmd.add_argument("--confirm", action="store_true", help="delete the redundant captures (dry-run without it)")
    dedup_captures_cmd.add_argument("--json", action="store_true", help="print machine-readable dedup details")

    update_memory_cmd = sub.add_parser("update-memory", help="merge new text into an existing memory")
    update_memory_cmd.add_argument("identifier", help="memory page name, title, or path")
    update_memory_cmd.add_argument("text", help="new memory text to merge")
    update_memory_cmd.add_argument("target", nargs="?", default=".")
    update_memory_cmd.add_argument("--source", default="manual", help="where this update came from")
    update_memory_cmd.add_argument("--project", default=None, help="project key for conflict checks")
    update_memory_cmd.add_argument("--allow-conflict", action="store_true", help="update even if the text may conflict with another active memory")
    update_memory_cmd.add_argument("--json", action="store_true", help="print machine-readable status")

    visibility_cmd = sub.add_parser("set-memory-visibility", help="change a memory sharing visibility")
    visibility_cmd.add_argument("identifier", help="memory page name, title, or path")
    visibility_cmd.add_argument("visibility", choices=MEMORY_VISIBILITIES, help="new visibility: private, project, or team")
    visibility_cmd.add_argument("target", nargs="?", default=".")
    visibility_cmd.add_argument("--json", action="store_true", help="print machine-readable status")

    recall_cmd = sub.add_parser("recall", help="search local agent memories")
    recall_cmd.add_argument("query", help="memory query")
    recall_cmd.add_argument("target", nargs="?", default=".")
    recall_cmd.add_argument("--limit", type=int, default=10)
    recall_cmd.add_argument("--include-archived", action="store_true", help="include archived and stale memories")
    recall_cmd.add_argument("--as-of", default=None, dest="as_of", help="YYYY-MM-DD: recall what was active on that date (temporal recall)")
    recall_cmd.add_argument("--type", choices=MEMORY_TYPES, default=None, dest="memory_type", help="only recall memories of this type")
    recall_cmd.add_argument("--project", default=None, help="include user/global memories plus this project's memories")
    recall_cmd.add_argument("--json", action="store_true", help="print machine-readable results")

    query_cmd = sub.add_parser("query", aliases=["query-link"], help="build a compact answer-ready Link context packet")
    query_cmd.add_argument("query", help="task or question to retrieve memory and wiki context for")
    query_cmd.add_argument("target", nargs="?", default=".")
    query_cmd.add_argument("--budget", choices=("micro", "small", "medium", "large"), default="medium")
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
    benchmark_cmd.add_argument("--budget", choices=("micro", "small", "medium", "large"), default="small")
    benchmark_cmd.add_argument("--project", default=None, help="include user/global memories plus this project's memories")
    benchmark_cmd.add_argument("--json", action="store_true", help="print machine-readable benchmark data")

    brief_cmd = sub.add_parser("brief", help="prime an agent with relevant local memory")
    brief_cmd.add_argument("query", nargs="?", default="", help="optional task or question to retrieve memory for")
    brief_cmd.add_argument("target", nargs="?", default=".")
    brief_cmd.add_argument("--limit", type=int, default=6)
    brief_cmd.add_argument("--project", default=None, help="include user/global memories plus this project's memories")
    brief_cmd.add_argument("--json", action="store_true", help="print machine-readable memory brief")

    start_cmd = sub.add_parser("start", help="start a session with Link readiness and a memory brief")
    start_cmd.add_argument("target", nargs="?", default=".")
    start_cmd.add_argument("--task", default="", help="optional task or question to retrieve memory for")
    start_cmd.add_argument("--limit", type=int, default=6)
    start_cmd.add_argument("--project", default=None, help="include user/global memories plus this project's memories")
    start_cmd.add_argument("--json", action="store_true", help="print machine-readable startup packet")

    hook_cmd = sub.add_parser("hook", help="run an agent session hook (invoked by installed agent hooks)")
    hook_cmd.add_argument("event", choices=["session-start", "session-end", "prompt-check"], help="agent session lifecycle event")
    hook_cmd.add_argument("target", nargs="?", default=".")
    hook_cmd.add_argument("--limit", type=int, default=5, help="maximum memories in the session-start brief")
    hook_cmd.add_argument("--project", default=None, help="include user/global memories plus this project's memories")
    hook_cmd.add_argument(
        "--explain",
        action="store_true",
        help="session-end: print the decision trail (what was dropped as echo/noise and why)",
    )
    hook_cmd.add_argument(
        "--emit",
        choices=["text", "cursor"],
        default="text",
        help="session-start output envelope: plain text (Claude Code, Codex) or Cursor additional_context JSON",
    )

    semantic_cmd = sub.add_parser("semantic", help="show or set up optional local semantic recall")
    semantic_cmd.add_argument("target", nargs="?", default=".")
    semantic_cmd.add_argument("--setup", action="store_true", help="fetch the local embedding model once and build the index")
    semantic_cmd.add_argument("--rebuild", action="store_true", help="rebuild the semantic index offline")
    semantic_cmd.add_argument("--json", action="store_true", help="print machine-readable semantic status")

    recipes_cmd = sub.add_parser("recipes", help="list saved procedure memories (recipes) with their triggers")
    recipes_cmd.add_argument("target", nargs="?", default=".")
    recipes_cmd.add_argument("--project", default=None, help="include user/global recipes plus this project's recipes")
    recipes_cmd.add_argument("--limit", type=int, default=50)
    recipes_cmd.add_argument("--json", action="store_true", help="print machine-readable recipes")

    consolidate_cmd = sub.add_parser("consolidate", help="print a read-only plan for the capture and review backlog")
    consolidate_cmd.add_argument("target", nargs="?", default=".")
    consolidate_cmd.add_argument("--limit", type=int, default=50, help="maximum captures and review items to include")
    consolidate_cmd.add_argument("--project", default=None, help="restrict the plan to one project's captures and memories")
    consolidate_cmd.add_argument("--json", action="store_true", help="print machine-readable consolidation plan")

    profile_cmd = sub.add_parser("profile", help="show what Link remembers")
    profile_cmd.add_argument("target", nargs="?", default=".")
    profile_cmd.add_argument("--limit", type=int, default=10)
    profile_cmd.add_argument("--project", default=None, help="include user/global memories plus this project's memories")
    profile_cmd.add_argument("--json", action="store_true", help="print machine-readable profile")

    wins_cmd = sub.add_parser("wins", help="show local proof signals for what Link memory is carrying")
    wins_cmd.add_argument("target", nargs="?", default=".")
    wins_cmd.add_argument("--limit", type=int, default=6)
    wins_cmd.add_argument("--project", default=None, help="include user/global memories plus this project's memories")
    wins_cmd.add_argument("--json", action="store_true", help="print machine-readable memory wins")

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

    memory_log_cmd = sub.add_parser("memory-log", help="show recent memory lifecycle events from wiki/log.md")
    memory_log_cmd.add_argument("target", nargs="?", default=".")
    memory_log_cmd.add_argument("--limit", type=int, default=50)
    memory_log_cmd.add_argument("--no-captures", action="store_true", help="hide raw capture lifecycle events")
    memory_log_cmd.add_argument("--json", action="store_true", help="print machine-readable memory log")

    review_cmd = sub.add_parser("review-memory", help="mark a memory as reviewed")
    review_cmd.add_argument("identifier", nargs="?", default=None, help="memory page name, title, or path (omit with --all)")
    review_cmd.add_argument("target", nargs="?", default=".")
    review_cmd.add_argument("--all", action="store_true", dest="review_all", help="review every memory that is pending or due (lists first; requires --confirm)")
    review_cmd.add_argument("--confirm", action="store_true", help="required with --all to actually mark them reviewed")
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

    stale_cmd = sub.add_parser(
        "stale",
        help="list memories that name repository paths git no longer has",
    )
    stale_cmd.add_argument("target", nargs="?", default=".", help="Link workspace")
    stale_cmd.add_argument(
        "--repo", default=".",
        help="repository to check the memories against (default: current directory)",
    )
    stale_cmd.add_argument("--json", action="store_true", help="machine-readable report")

    verify_mcp_cmd = sub.add_parser(
        "verify-mcp",
        help="verify link-mcp import and print MCP config; pass an agent name to check what that agent is configured to run",
    )
    verify_mcp_cmd.add_argument(
        "target", nargs="?", default=".",
        help="workspace path, or an agent name (codex, claude-code, cursor, ...) to verify that agent's written config",
    )
    verify_mcp_cmd.add_argument("extra_target", nargs="?", default=None, help="workspace path when the first argument is an agent name")
    verify_mcp_cmd.add_argument("--json", action="store_true", help="print machine-readable status")
    verify_mcp_cmd.add_argument("--python", default=None, help="Python executable to verify")

    connect_cmd = sub.add_parser("connect", help="print or write MCP config for a local agent")
    connect_cmd.add_argument("agent", help="agent to connect: codex, kiro, claude-code, cursor, antigravity, vscode, copilot")
    connect_cmd.add_argument("target", nargs="?", default=".")
    connect_cmd.add_argument("--write", action="store_true", help="update the detected agent config file")
    connect_cmd.add_argument("--config", default=None, help="override the agent config file path")
    connect_cmd.add_argument("--python", default=None, help="Python executable for the MCP server")
    connect_cmd.add_argument(
        "--hooks",
        action="store_true",
        help="also configure session hooks so new sessions start with the Link brief (Claude Code, Codex, Cursor)",
    )
    connect_cmd.add_argument(
        "--hooks-settings",
        default=None,
        dest="hooks_settings",
        help="override the hooks settings file, e.g. .claude/settings.json inside a repo for project-scoped hooks",
    )
    connect_cmd.add_argument("--json", action="store_true", help="print machine-readable connection plan")

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
    if command == "proof":
        return handlers["proof"](
            Path(args.target),
            force=args.force,
            serve=args.serve,
            port=args.port,
            json_output=args.json,
        )
    if command == "import":
        return handlers["import"](
            Path(args.target), source=args.import_source,
            file_path=args.import_file, project=args.project, json_output=args.json,
        )
    if command == "handoff":
        return handlers["handoff"](
            Path(args.target), note=args.note, task=args.task,
            next_steps=args.next_steps, project=args.project,
            source=args.source, json_output=args.json,
        )
    if command == "handoffs":
        return handlers["handoffs"](Path(args.target), clear=args.clear, json_output=args.json)
    if command == "digest":
        return handlers["digest"](Path(args.target), days=args.days, json_output=args.json)
    if command == "sync":
        return handlers["sync"](
            Path(args.target),
            init=args.sync_init,
            remote=args.remote,
            status=args.sync_status,
            json_output=args.json,
        )
    if command == "setup":
        return handlers["setup"](
            Path(args.target),
            preview=args.preview,
            no_semantic=args.no_semantic,
            json_output=args.json,
        )
    if command == "onboard":
        return handlers["onboard"](
            Path(args.target),
            agents=args.agent,
            all_agents=args.all_agents,
            write=args.write,
            hooks=args.hooks,
            first_memory=args.first_memory,
            seed_project=args.seed_project,
            project=args.project,
            port=args.port,
            json_output=args.json,
        )
    if command == "seed":
        return handlers["seed"](
            Path(args.target),
            Path(args.project),
            project_name=args.project_name,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
            limit=args.limit,
            include_git_log=not args.no_git_log,
            git_log_limit=args.git_log_limit,
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
        return handlers["operations"](
            Path(args.target),
            limit=args.limit,
            recover=args.recover,
            confirm=args.confirm,
            json_output=args.json,
        )
    if command == "backup":
        return handlers["backup"](
            Path(args.target),
            label=args.label,
            include_raw=args.include_raw,
            list_only=args.list_only,
            json_output=args.json,
        )
    if command == "restore-backup":
        return handlers["restore-backup"](
            Path(args.target),
            args.backup,
            include_raw=args.include_raw,
            confirm=args.confirm,
            safety_backup=not args.no_safety_backup,
            json_output=args.json,
        )
    if command == "compliance-export":
        return handlers["compliance-export"](
            Path(args.target),
            output=args.output,
            project=args.project,
            limit=args.limit,
            json_output=args.json,
        )
    if command == "team-sync":
        return handlers["team-sync"](
            Path(args.target), remote=args.remote, init=args.team_init,
            team_dir=args.team_dir, json_output=args.json,
        )
    if command == "share":
        return handlers["share"](
            Path(args.target),
            args.identifier,
            port=args.port,
            host=args.host,
            json_output=args.json,
        )
    if command == "snapshot":
        return handlers["snapshot"](
            Path(args.target),
            output=args.output,
            include_memories=args.include_memories,
            include_private_memories=args.include_private_memories,
            allow_sensitive=args.allow_sensitive,
            force=args.force,
            title=args.title,
            json_output=args.json,
        )
    if command == "doctor":
        return handlers["doctor"](Path(args.target), fix=args.fix)
    if command == "migrate":
        return handlers["migrate"](Path(args.target), json_output=args.json)
    if command == "validate":
        return handlers["validate"](Path(args.target), strict=args.strict, json_output=args.json)
    if command == "ingest":
        return handlers["ingest"](
            Path(args.target),
            Path(args.source),
            adapter=args.adapter,
            excludes=args.exclude,
            apply=args.apply,
            replace_unmanaged=args.replace_unmanaged,
            prune=args.prune,
            json_output=args.json,
        )
    if command == "ingest-status":
        return handlers["ingest-status"](Path(args.target), json_output=args.json)
    if command == "import-obsidian":
        return handlers["import-obsidian"](
            Path(args.target),
            Path(args.vault),
            overwrite=args.overwrite,
            dry_run=args.dry_run,
            limit=args.limit,
            json_output=args.json,
        )
    if command == "remember":
        return handlers["remember"](
            Path(args.target),
            args.text,
            title=args.title,
            memory_type=args.memory_type,
            scope=args.scope,
            visibility=args.visibility,
            tags=args.tags,
            source=args.source,
            project=args.project,
            review_after=args.review_after,
            expires_at=args.expires_at,
            trigger=args.trigger,
            applies_when=args.applies_when,
            supersedes=args.supersedes,
            context=args.context,
            allow_duplicate=args.allow_duplicate,
            allow_conflict=args.allow_conflict,
            allow_secret=args.allow_secret,
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
    if command in {"session-end", "end"}:
        return handlers["session-end"](
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
            proposal_limit=args.proposal_limit,
        )
    if command == "accept-capture":
        return handlers["accept-capture"](
            Path(args.target),
            args.capture,
            index=args.index,
            title=args.title,
            memory_type=args.memory_type,
            scope=args.scope,
            visibility=args.visibility,
            tags=args.tags,
            project=args.project,
            allow_duplicate=args.allow_duplicate,
            allow_conflict=args.allow_conflict,
            accept_all=args.accept_all,
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
        # With --all the capture positional is meaningless, so a lone
        # positional is the TARGET: `delete-capture w --all` must hit ./w,
        # never fall back to the default workspace (that misparse pointed a
        # destructive bulk delete at the real ~/link once - in a test, but
        # once is the wrong number of times).
        capture_arg = args.capture
        target_arg = args.target
        if args.delete_all and capture_arg:
            # a capture name is meaningless with --all; the positional the
            # user typed is the target, even if the workspace fallback
            # already rewrote args.target behind our back
            target_arg, capture_arg = capture_arg, None
        return handlers["delete-capture"](
            Path(target_arg),
            capture_arg,
            confirm=args.confirm,
            delete_all=args.delete_all,
            json_output=args.json,
        )
    if command == "dedup-captures":
        return handlers["dedup-captures"](
            Path(args.target),
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
    if command == "set-memory-visibility":
        return handlers["set-memory-visibility"](
            Path(args.target),
            args.identifier,
            args.visibility,
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
            as_of=args.as_of,
            memory_type=args.memory_type,
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
    if command == "start":
        return handlers["start"](
            Path(args.target),
            task=args.task,
            limit=args.limit,
            project=args.project,
            json_output=args.json,
        )
    if command == "hook":
        return handlers["hook"](
            Path(args.target),
            args.event,
            limit=args.limit,
            project=args.project,
            emit=args.emit,
            explain=args.explain,
        )
    if command == "recipes":
        return handlers["recipes"](Path(args.target), project=args.project, limit=args.limit, json_output=args.json)
    if command == "consolidate":
        return handlers["consolidate"](Path(args.target), limit=args.limit, project=args.project, json_output=args.json)
    if command == "semantic":
        return handlers["semantic"](Path(args.target), setup=args.setup, rebuild=args.rebuild, json_output=args.json)
    if command == "profile":
        return handlers["profile"](Path(args.target), limit=args.limit, project=args.project, json_output=args.json)
    if command == "wins":
        return handlers["wins"](Path(args.target), limit=args.limit, project=args.project, json_output=args.json)
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
    if command == "memory-log":
        return handlers["memory-log"](
            Path(args.target),
            limit=args.limit,
            include_captures=not args.no_captures,
            json_output=args.json,
        )
    if command == "review-memory":
        return handlers["review-memory"](
            Path(args.target), args.identifier, note=args.note,
            review_all=args.review_all, confirm=args.confirm, json_output=args.json,
        )
    if command == "explain-memory":
        return handlers["explain-memory"](Path(args.target), args.identifier, json_output=args.json)
    if command == "rebuild-index":
        return handlers["rebuild-index"](Path(args.target))
    if command == "rebuild-backlinks":
        return handlers["rebuild-backlinks"](Path(args.target))
    if command == "stale":
        return handlers["stale"](Path(args.target), repo=Path(args.repo), json_output=bool(args.json))
    if command == "verify-mcp":
        from .mcp_connect import agent_alias_matches

        if agent_alias_matches(str(args.target)):
            return handlers["verify-mcp"](
                Path(args.extra_target or "."),
                json_output=args.json,
                python_cmd=args.python,
                agent=str(args.target),
            )
        return handlers["verify-mcp"](Path(args.target), json_output=args.json, python_cmd=args.python)
    if command == "connect":
        return handlers["connect"](
            Path(args.target),
            args.agent,
            write=args.write,
            config_path=args.config,
            python_cmd=args.python,
            hooks=args.hooks,
            hooks_settings=args.hooks_settings,
            json_output=args.json,
        )
    raise ValueError(f"unknown command: {command}")
