"""HTML helpers for Link's local health page."""
from __future__ import annotations

import html
from collections.abc import Callable, Mapping
from pathlib import Path

from .mcp_verify import display_command
from .web_ingest import copy_button
from .web_layout import render_stat_grid


PageLayout = Callable[[str, str], str]


def _dict_list(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _render_issue_list(title: str, items: list[dict[str, object]], empty: str) -> str:
    if not items:
        return f"<section><h2>{html.escape(title)}</h2><p>{html.escape(empty)}</p></section>"
    rows = ""
    for item in items:
        code = str(item.get("code") or item.get("operation") or item.get("label") or "issue")
        message = str(item.get("message") or item.get("description") or item.get("detail") or item.get("command") or "")
        detail = str(item.get("detail") or item.get("marker") or item.get("tool") or "").strip()
        rows += (
            "<li>"
            f"<strong>{html.escape(code)}</strong>"
            f"<span>{html.escape(message)}</span>"
            f"{f'<code>{html.escape(detail)}</code>' if detail else ''}"
            "</li>"
        )
    return f'<section><h2>{html.escape(title)}</h2><ul class="page-list">{rows}</ul></section>'


def _render_commands(commands: list[str]) -> str:
    rows = "".join(
        "<li>"
        f"<code>{html.escape(command)}</code>"
        f"{copy_button(command, 'Copy')}"
        "</li>"
        for command in commands
    )
    return f'<section><h2>Repair Commands</h2><ul class="command-list">{rows}</ul></section>'


def _render_operation_actions(operations: Mapping[str, object]) -> str:
    actions = _dict_list(operations.get("next_actions"))
    if not actions:
        return ""
    rows = ""
    for action in actions:
        command = str(action.get("command") or "").strip()
        label = str(action.get("label") or command or "next action")
        command_html = f"<code>{html.escape(command)}</code>{copy_button(command, 'Copy')}" if command else ""
        rows += (
            "<li>"
            f"<strong>{html.escape(label)}</strong>"
            f"{command_html}"
            "</li>"
        )
    return f'<section><h2>Operation Next Actions</h2><ul class="command-list">{rows}</ul></section>'


def _command_target(status: Mapping[str, object], operations: Mapping[str, object]) -> str:
    raw = str(operations.get("wiki") or status.get("wiki") or "").strip()
    if not raw:
        return ""
    path = Path(raw)
    return str(path.parent if path.name == "wiki" else path)


def _link_command(command_target: str, *parts: str) -> str:
    command = ["link", *parts]
    if command_target:
        command.append(command_target)
    return display_command(command)


def _render_persistent_cache_item(status: Mapping[str, object]) -> str:
    persistent_cache = status.get("persistent_cache")
    if not isinstance(persistent_cache, Mapping):
        return ""
    state = "enabled" if persistent_cache.get("enabled") else "disabled"
    detail = (
        f"{persistent_cache.get('reused_records', 0)}/"
        f"{persistent_cache.get('total_records', 0)} pages reused"
    )
    return (
        "<li><strong>Persistent cache</strong>"
        f"<span>{html.escape(state)}</span>"
        f"<small>{html.escape(detail)}</small></li>"
    )


def _render_fts_item(status: Mapping[str, object]) -> str:
    fts_index = status.get("fts_index")
    if not isinstance(fts_index, Mapping) or not fts_index.get("available"):
        return ""
    state = "persistent" if fts_index.get("persistent") else "memory"
    detail = f"reused={bool(fts_index.get('reused'))}"
    return (
        "<li><strong>FTS index</strong>"
        f"<span>{html.escape(state)}</span>"
        f"<small>{html.escape(detail)}</small></li>"
    )


def _command_for_action(action: Mapping[str, object], command_target: str) -> str:
    command = str(action.get("command") or "").strip()
    if command:
        return command
    tool = str(action.get("tool") or "").strip()
    arguments = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
    if tool == "doctor":
        return _link_command(command_target, "doctor", "--fix") if arguments.get("fix") else _link_command(
            command_target, "doctor"
        )
    if tool == "validate_wiki":
        return _link_command(command_target, "validate")
    if tool == "rebuild_backlinks":
        return _link_command(command_target, "rebuild-backlinks")
    if tool == "migrate_wiki":
        return _link_command(command_target, "migrate")
    if tool == "ingest_status":
        return _link_command(command_target, "ingest-status")
    if tool == "starter_prompts":
        return _link_command(command_target, "prompts")
    if tool == "memory_inbox":
        return _link_command(command_target, "memory-inbox")
    if tool == "backup_wiki":
        return _link_command(command_target, "backup")
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


def _render_primary_next_action(status: Mapping[str, object], operations: Mapping[str, object]) -> str:
    command_target = _command_target(status, operations)
    operation_actions = _dict_list(operations.get("next_actions"))
    status_actions = _dict_list(status.get("next_actions"))
    if operation_actions:
        action = operation_actions[0]
        label = str(action.get("label") or "Review interrupted operation")
        detail = "Interrupted writes should be inspected before more repairs."
    elif status_actions:
        action = status_actions[0]
        label = str(action.get("label") or action.get("tool") or "Run the next health check")
        detail = str(action.get("description") or action.get("detail") or "Run this before relying on Link.")
    elif int(status.get("needs_review_count") or 0):
        action = {"tool": "memory_inbox"}
        label = "Review pending memories"
        detail = "Confirm or archive memories that should not affect recall yet."
    else:
        action = {"tool": "memory_brief", "arguments": {"query": "working with Link"}}
        label = "Ready for agent work"
        detail = "Prime the agent with a brief or query Link for project context."
    command = _command_for_action(action, command_target)
    command_html = f"<code>{html.escape(command)}</code>{copy_button(command, 'Copy')}" if command else ""
    return (
        '<section class="health-next">'
        "<h2>Next Safe Action</h2>"
        f"<p><strong>{html.escape(label)}</strong><span>{html.escape(detail)}</span></p>"
        f"{command_html}"
        "</section>"
    )


def _render_validation_details(validation: Mapping[str, object]) -> str:
    if not validation.get("checked"):
        return "<section><h2>Validation Gate</h2><p>Validation has not been run in this status check.</p></section>"
    error_codes = [str(code) for code in validation.get("error_codes") or [] if str(code)]
    warning_codes = [str(code) for code in validation.get("warning_codes") or [] if str(code)]
    if not error_codes and not warning_codes:
        return "<section><h2>Validation Gate</h2><p>Validation passed with no errors or warnings.</p></section>"
    rows = "".join(
        f"<li><strong>{html.escape(kind)}</strong><span>{html.escape(', '.join(codes))}</span></li>"
        for kind, codes in (("Errors", error_codes), ("Warnings", warning_codes))
        if codes
    )
    return f'<section><h2>Validation Gate</h2><ul class="page-list">{rows}</ul></section>'


def _render_health_cards(status: Mapping[str, object], operations: Mapping[str, object]) -> str:
    validation = status.get("validation") if isinstance(status.get("validation"), dict) else {}
    ready_state = "done" if status.get("ready") else "blocked"
    validation_checked = bool(validation.get("checked"))
    validation_passed = bool(validation.get("passed"))
    validation_state = "done" if validation_checked and validation_passed else ("blocked" if validation_checked else "wait")
    stale_count = int(operations.get("stale_count") or 0)
    failed_count = int(operations.get("failed_count") or 0)
    active_count = int(operations.get("active_count") or 0)
    operations_state = "blocked" if stale_count or failed_count else ("next" if active_count else "done")
    needs_review_count = int(status.get("needs_review_count") or 0)
    memory_state = "next" if needs_review_count else "done"
    validation_detail = (
        f"{int(validation.get('error_count') or 0)} errors · {int(validation.get('warning_count') or 0)} warnings"
        if validation_checked
        else "run lnk health"
    )
    cards = [
        (
            "Readiness",
            "ready" if status.get("ready") else "needs attention",
            ready_state,
            f"{status.get('content_page_count', 0)} content pages",
        ),
        (
            "Validation",
            "passed" if validation_passed else ("failed" if validation_checked else "not checked"),
            validation_state,
            validation_detail,
        ),
        (
            "Operations",
            "clear" if operations_state == "done" else ("active" if operations_state == "next" else "needs review"),
            operations_state,
            f"{stale_count} stale · {active_count} active",
        ),
        (
            "Memory Review",
            "clear" if not needs_review_count else f"{needs_review_count} pending",
            memory_state,
            f"{status.get('active_memory_count', 0)} active memories",
        ),
    ]
    rows = "".join(
        '<article class="health-card" data-state="'
        f'{html.escape(state, quote=True)}">'
        f"<strong>{html.escape(label)}</strong>"
        f"<span>{html.escape(value)}</span>"
        f"<small>{html.escape(detail)}</small>"
        "</article>"
        for label, value, state, detail in cards
    )
    return f'<section class="health-cards" aria-label="Health summary">{rows}</section>'


def render_health_page(
    status: Mapping[str, object],
    operations: Mapping[str, object],
    *,
    layout: PageLayout,
) -> str:
    """Render a human-readable health and readiness page for the local viewer."""
    validation = status.get("validation") if isinstance(status.get("validation"), dict) else {}
    schema = status.get("schema") if isinstance(status.get("schema"), dict) else {}
    ready = "yes" if status.get("ready") else "no"
    validation_label = "passed" if validation.get("passed") else "not checked"
    if validation.get("checked") and not validation.get("passed"):
        validation_label = "failed"
    stats = render_stat_grid([
        (ready, "ready"),
        (status.get("content_page_count", 0), "content pages"),
        (status.get("memory_count", 0), "memories"),
        (status.get("needs_review_count", 0), "review"),
        (operations.get("operation_count", 0), "operations"),
        (validation_label, "validation"),
    ])
    warnings = _dict_list(status.get("warnings"))
    next_actions = _dict_list(status.get("next_actions"))
    operation_items = _dict_list(operations.get("operations"))
    command_target = _command_target(status, operations)
    commands = [
        _link_command(command_target, "status", "--validate"),
        _link_command(command_target, "onboard"),
        _link_command(command_target, "operations"),
        _link_command(command_target, "doctor", "--fix"),
        _link_command(command_target, "validate"),
        _link_command(command_target, "benchmark", "agent memory"),
    ]
    body = (
        '<div class="breadcrumb"><a href="/">Link</a> / health</div>'
        "<h1>Health</h1>"
        '<p class="summary">One local check for readiness, validation, interrupted writes, and repair commands.</p>'
        f"{_render_health_cards(status, operations)}"
        f"{_render_primary_next_action(status, operations)}"
        f"{stats}"
        "<section><h2>Readiness</h2>"
        '<ul class="page-list">'
        f"<li><strong>Search backend</strong><span>{html.escape(str(status.get('search_backend') or 'unknown'))}</span></li>"
        f"{_render_fts_item(status)}"
        f"{_render_persistent_cache_item(status)}"
        f"<li><strong>Schema</strong><span>{html.escape(str(schema.get('status') or 'unknown'))}</span></li>"
        f"<li><strong>Active memories</strong><span>{html.escape(str(status.get('active_memory_count') or 0))}</span></li>"
        f"<li><strong>Interrupted operations</strong><span>{html.escape(str(operations.get('stale_count') or 0))} stale · {html.escape(str(operations.get('active_count') or 0))} active</span></li>"
        "</ul></section>"
        f"{_render_validation_details(validation)}"
        f"{_render_issue_list('Warnings', warnings, 'No readiness warnings.')}"
        f"{_render_issue_list('Interrupted Operations', operation_items, 'No pending, failed, or interrupted Link operations.')}"
        f"{_render_operation_actions(operations)}"
        f"{_render_issue_list('Next Actions', next_actions, 'No repair actions needed.')}"
        f"{_render_commands(commands)}"
    )
    return layout("Health", body)
