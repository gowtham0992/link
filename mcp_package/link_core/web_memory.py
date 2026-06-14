"""HTML helpers for Link's local memory web views."""
from __future__ import annotations

import html
import urllib.parse
from collections.abc import Callable, Sequence

from .web_ingest import copy_button


MemoryActionHints = Callable[[dict[str, object]], list[dict[str, object]]]
PageHref = Callable[[str], str]


def memory_dashboard_next_actions(
    *,
    memory_count: int,
    review_count: int,
    updated_count: int,
    archived_count: int,
    capture_count: int = 0,
    capture_warning_count: int = 0,
) -> list[dict[str, str]]:
    """Return web dashboard next actions for current memory/capture state."""
    actions: list[dict[str, str]] = []
    if capture_warning_count:
        actions.append({
            "label": "Redact capture warnings",
            "detail": f"{capture_warning_count} raw capture{'s' if capture_warning_count != 1 else ''} contain secret-looking values.",
            "href": "/captures",
            "command": "python3 link.py redact-capture raw/memory-captures/<capture>.md .",
            "priority": "high",
        })
    if review_count:
        memory_label = "memory" if review_count == 1 else "memories"
        verb = "needs" if review_count == 1 else "need"
        actions.append({
            "label": "Review pending memories",
            "detail": f"{review_count} {memory_label} {verb} confirmation or metadata cleanup.",
            "href": "/inbox",
            "command": "python3 link.py memory-inbox .",
            "priority": "high",
        })
    if updated_count:
        actions.append({
            "label": "Audit recent memory updates",
            "detail": f"{updated_count} memory update{'s' if updated_count != 1 else ''} should be checked for accuracy.",
            "href": "/memory",
            "command": "python3 link.py profile .",
            "priority": "medium",
        })
    if archived_count:
        actions.append({
            "label": "Inspect archived memory",
            "detail": f"{archived_count} archived memory page{'s' if archived_count != 1 else ''} remain inspectable but hidden from default recall.",
            "href": "/profile",
            "command": "python3 link.py profile .",
            "priority": "low",
        })
    if capture_count and not capture_warning_count:
        actions.append({
            "label": "Review raw captures",
            "detail": f"{capture_count} saved raw capture{'s' if capture_count != 1 else ''} can be accepted, redacted, or deleted.",
            "href": "/captures",
            "command": "python3 link.py accept-capture raw/memory-captures/<capture>.md . --index 1",
            "priority": "medium",
        })
    if not memory_count:
        actions.append({
            "label": "Create the first memory",
            "detail": "Save an explicit preference, decision, project fact, or note for local agents.",
            "href": "",
            "command": 'python3 link.py remember "User prefers ..." . --type preference --scope user',
            "priority": "high",
        })
    if not actions:
        actions.append({
            "label": "Memory is recall-ready",
            "detail": "No pending review items or recent updates need attention.",
            "href": "/profile",
            "command": "python3 link.py profile .",
            "priority": "info",
        })
    return actions[:3]


def render_memory_action_button(action: dict[str, object]) -> str:
    kind = str(action.get("kind") or "")
    if kind not in {"review", "archive", "restore"}:
        return ""
    arguments = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
    identifier = str(arguments.get("identifier") or "")
    if not identifier:
        return ""
    labels = {
        "review": "Mark reviewed",
        "archive": "Archive",
        "restore": "Restore",
    }
    return (
        f'<button type="button" data-memory-action="{html.escape(kind, quote=True)}" '
        f'data-memory="{html.escape(identifier, quote=True)}">'
        f'{html.escape(labels[kind])}</button>'
    )


def render_memory_action_commands(actions: Sequence[dict[str, object]]) -> str:
    if not actions:
        return ""
    rows = ""
    for action in actions:
        label = html.escape(str(action.get("label") or ""))
        if action.get("href"):
            label_html = f'<a href="{html.escape(str(action["href"]))}">{label}</a>'
        else:
            label_html = label
        priority = str(action.get("priority") or "")
        priority_html = f'<span class="memory-meta">{html.escape(priority)}</span>' if priority else ""
        button_html = render_memory_action_button(action)
        command = str(action.get("command") or "")
        copy_html = copy_button(command, "Copy command")
        rows += (
            f'<div class="memory-action-row"><span class="memory-action-head"><strong>{label_html}</strong>'
            f'{priority_html}{button_html}</span>'
            f'<code>{html.escape(command)}</code>{copy_html}</div>'
        )
    return f'<div class="memory-actions">{rows}</div>'


def render_memory_card(
    record: dict[str, object],
    *,
    page_href: PageHref,
    action_hints: MemoryActionHints | None = None,
    include_issues: bool = False,
) -> str:
    name = str(record.get("name") or "")
    title = str(record.get("title") or name)
    summary = str(record.get("tldr") or record.get("snippet") or "")
    meta_parts = [
        str(record.get("memory_type") or "note"),
        str(record.get("scope") or "user"),
        f'visibility {record.get("visibility") or "private"}',
        str(record.get("status") or "active"),
    ]
    if record.get("updated_at"):
        meta_parts.append(f'updated {record["updated_at"]}')
    elif record.get("date_captured"):
        meta_parts.append(f'captured {record["date_captured"]}')
    if record.get("review_after"):
        meta_parts.append(f'review after {record["review_after"]}')
    if record.get("expires_at"):
        meta_parts.append(f'expires {record["expires_at"]}')
    meta = " · ".join(part for part in meta_parts if part)
    issues_html = ""
    if include_issues and record.get("issues"):
        issues_html = "<ul class='memory-issues'>" + "".join(
            f'<li><span class="severity">{html.escape(str(issue["severity"]))}</span> '
            f'{html.escape(str(issue["code"]))}: {html.escape(str(issue["message"]))}</li>'
            for issue in record["issues"]
            if isinstance(issue, dict)
        ) + "</ul>"
    actions = render_memory_action_commands(record.get("actions") or (action_hints(record) if action_hints else []))
    summary_html = f'<p class="summary">{html.escape(summary)}</p>' if summary else ""
    page_url = html.escape(page_href(name), quote=True)
    encoded_name = urllib.parse.quote(name, safe="")
    trust_links = (
        '<div class="memory-meta">'
        f'<a href="/explain-memory?memory={encoded_name}">explain</a>'
        ' · '
        f'<a href="/graph?focus={encoded_name}&amp;depth=2">graph</a>'
        "</div>"
    )
    return (
        '<article class="memory-card">'
        f'<h3><a href="{page_url}">{html.escape(title)}</a></h3>'
        f'<div class="memory-meta">{html.escape(meta)}</div>'
        f'{trust_links}'
        f'{summary_html}'
        f'{issues_html}'
        f'{actions}'
        '</article>'
    )


def render_memory_section(
    title: str,
    records: list[dict[str, object]],
    empty: str,
    *,
    page_href: PageHref,
    action_hints: MemoryActionHints | None = None,
    href: str = "",
    include_issues: bool = False,
) -> str:
    heading_link = f'<a href="{html.escape(href)}">view all</a>' if href else ""
    heading = f'<div class="section-heading"><h2>{html.escape(title)}</h2>{heading_link}</div>'
    if not records:
        return heading + f"<p>{html.escape(empty)}</p>"
    cards = "".join(
        render_memory_card(record, page_href=page_href, action_hints=action_hints, include_issues=include_issues)
        for record in records
    )
    return heading + f'<div class="memory-grid">{cards}</div>'


def render_capture_card(capture: dict[str, object]) -> str:
    title = html.escape(str(capture.get("title") or capture.get("path") or "Raw capture"))
    path = html.escape(str(capture.get("path") or ""))
    meta_parts = ["raw capture"]
    if capture.get("project"):
        meta_parts.append(f'project {capture["project"]}')
    if capture.get("date_captured"):
        meta_parts.append(f'captured {capture["date_captured"]}')
    warnings = [str(label) for label in capture.get("secret_warnings") or []]
    if warnings:
        meta_parts.append("secret warnings")
    meta = " · ".join(meta_parts)
    warning_html = ""
    if warnings:
        warning_html = (
            '<p class="summary"><strong>Secret-looking values:</strong> '
            + html.escape(", ".join(warnings))
            + "</p>"
        )
    commands = capture.get("commands") or {}
    actions = "".join(
        f'<div><strong>{html.escape(label)}</strong>'
        f'{copy_button(str(command), "Copy command")}'
        f'<code>{html.escape(str(command))}</code></div>'
        for label, command in (
            ("Accept proposal", commands.get("accept", "")),
            ("Redact", commands.get("redact", "")),
            ("Delete", commands.get("delete", "")),
        )
        if command
    )
    return (
        '<article class="memory-card">'
        f'<h3>{title}</h3>'
        f'<div class="memory-meta">{html.escape(meta)}</div>'
        f'<p class="summary"><code>{path}</code></p>'
        f'{warning_html}'
        f'<div class="memory-actions">{actions}</div>'
        '</article>'
    )


def render_capture_section(captures: list[dict[str, object]]) -> str:
    heading = '<div class="section-heading"><h2>Raw captures</h2></div>'
    if not captures:
        return heading + "<p>No saved raw captures.</p>"
    cards = "".join(render_capture_card(capture) for capture in captures)
    return heading + f'<div class="memory-grid">{cards}</div>'


def render_memory_next_actions(actions: list[dict[str, str]]) -> str:
    items = ""
    for action in actions:
        label = html.escape(action["label"])
        if action.get("href"):
            label_html = f'<a href="{html.escape(action["href"])}">{label}</a>'
        else:
            label_html = label
        items += (
            f'<li><strong>{label_html}</strong>: {html.escape(action["detail"])}'
            f'<br><code>{html.escape(action["command"])}</code>'
            f'{copy_button(action["command"], "Copy command")}</li>'
        )
    return f'<div class="memory-next"><strong>Next actions</strong><ul>{items}</ul></div>'
