"""HTML page renderers for Link's memory web views."""
from __future__ import annotations

import html
import urllib.parse
from collections.abc import Callable, Mapping

from .web_ingest import copy_button
from .web_layout import render_stat_grid
from .web_memory import (
    MemoryActionHints,
    render_capture_section,
    render_memory_action_commands,
    render_memory_next_actions,
    render_memory_section,
)


PageHref = Callable[[str], str]
PageLayout = Callable[[str, str], str]


def render_brief_page(
    brief: Mapping[str, object],
    query: str,
    *,
    page_href: PageHref,
    action_hints: MemoryActionHints,
    layout: PageLayout,
) -> str:
    profile = _mapping(brief.get("profile"))
    captures = _mapping(brief.get("captures"))
    review = _mapping(brief.get("review"))
    stats = render_stat_grid([
        (profile.get("active_count", 0), "active"),
        (brief.get("relevant_count", 0), "relevant"),
        (review.get("count", 0), "review"),
        (captures.get("count", 0), "captures"),
    ])
    guidance = "".join(
        f"<li>{html.escape(str(item))}</li>"
        for item in _sequence(brief.get("agent_guidance"))
    )
    project = str(brief.get("project") or "")
    project_field = (
        f'<input type="hidden" name="project" value="{html.escape(project, quote=True)}">'
        if project else ""
    )
    brief_prompt = _brief_prompt(query, project)
    query_prompt = str(query or "").strip()
    query_action = (
        copy_button(f"query Link for {query_prompt}", "Copy query prompt")
        if query_prompt else ""
    )
    relevant_memories = _dict_list(brief.get("relevant_memories"))
    body = (
        '<div class="breadcrumb"><a href="/">Link</a> / brief</div>'
        '<h1>Memory Brief</h1>'
        '<div class="memory-profile">'
        '<p class="summary">Startup context for local agents before answering, coding, or planning.</p>'
        '<form class="brief-form" action="/brief" method="get">'
        f'<input type="text" name="q" value="{html.escape(str(query), quote=True)}" placeholder="task or question">'
        f'{project_field}<button type="submit">Brief</button></form>'
        f'<div class="page-actions">{copy_button(brief_prompt, "Copy brief prompt")}{query_action}</div>'
        f'{_project_line(project)}'
        f'{stats}'
        f'<h2>Agent Guidance</h2><ul>{guidance}</ul>'
        f'{render_memory_section("Relevant memories", relevant_memories, "No relevant memories yet.", page_href=page_href, action_hints=action_hints)}'
        f'{_render_empty_brief_actions(query_prompt) if not relevant_memories else ""}'
        f'{render_memory_section("Review queue", _dict_list(review.get("items")), "No memory review items.", page_href=page_href, action_hints=action_hints, href="/inbox", include_issues=True)}'
        f'{render_capture_section(_dict_list(captures.get("items")))}'
        '</div>'
    )
    return layout("Memory Brief", body)


def _render_empty_brief_actions(query: str) -> str:
    query_text = str(query or "").strip()
    proposal_prompt = (
        f"propose memories about {query_text} from Link raw sources"
        if query_text else "propose memories from Link raw sources"
    )
    return (
        '<div class="memory-next"><strong>Teach Link before the next brief</strong>'
        "<ul>"
        '<li><a href="/ingest">Add source material</a> if this context is in notes, docs, or transcripts.</li>'
        '<li><a href="/propose">Review memory proposals</a> before saving durable memory.</li>'
        f"<li>{copy_button(proposal_prompt, 'Copy memory proposal prompt')}</li>"
        "</ul></div>"
    )


def _brief_prompt(query: str, project: str = "") -> str:
    task = str(query or "").strip()
    project_name = str(project or "").strip()
    if task and project_name:
        return f"brief me from Link about {task} for project {project_name}"
    if task:
        return f"brief me from Link about {task}"
    if project_name:
        return f"brief me from Link for project {project_name}"
    return "brief me from Link before we continue"


def _copy_actions(actions: list[tuple[str, str]]) -> str:
    buttons = "".join(copy_button(prompt, label) for prompt, label in actions if prompt)
    return f'<div class="page-actions">{buttons}</div>' if buttons else ""


def _memory_overview_prompt(project: str = "") -> str:
    project_name = str(project or "").strip()
    if project_name:
        return f"what does Link remember about project {project_name}?"
    return "what does Link remember about me?"


def _audit_prompt(project: str = "") -> str:
    project_name = str(project or "").strip()
    if project_name:
        return f"audit Link memory for project {project_name}"
    return "audit Link memory"


def _inbox_prompt(project: str = "") -> str:
    project_name = str(project or "").strip()
    if project_name:
        return f"review Link memory inbox for project {project_name}"
    return "review Link memory inbox"


def _capture_prompt(project: str = "") -> str:
    project_name = str(project or "").strip()
    if project_name:
        return f"review Link raw captures for project {project_name}"
    return "review Link raw captures"


def render_memory_dashboard_page(
    dashboard: Mapping[str, object],
    *,
    page_href: PageHref,
    action_hints: MemoryActionHints,
    layout: PageLayout,
) -> str:
    stats = render_stat_grid([
        (dashboard.get("memory_count", 0), "memories"),
        (dashboard.get("active_count", 0), "active"),
        (dashboard.get("review_count", 0), "review"),
        (dashboard.get("updated_count", 0), "updated"),
        (dashboard.get("capture_count", 0), "captures"),
        (dashboard.get("archived_count", 0), "archived"),
    ])
    counts = ""
    by_type = _mapping(dashboard.get("by_type"))
    by_scope = _mapping(dashboard.get("by_scope"))
    if by_type:
        counts += _counts_line("Types", by_type)
    if by_scope:
        counts += _counts_line("Scopes", by_scope)
    project = str(dashboard.get("project") or "")
    dashboard_actions = _copy_actions([
        (_memory_overview_prompt(project), "Copy profile prompt"),
        (_brief_prompt("", project), "Copy brief prompt"),
        (_audit_prompt(project), "Copy audit prompt"),
    ])
    body = (
        '<div class="breadcrumb"><a href="/">Link</a> / memory</div>'
        '<h1>Memory Dashboard</h1>'
        '<div class="memory-dashboard">'
        '<p class="summary">Read-only command center for what local agents can remember, what needs review, and what changed recently.</p>'
        f'{dashboard_actions}'
        f'{_project_line(project)}'
        f'{stats}'
        f'{render_memory_next_actions(_dict_list(dashboard.get("next_actions")))}'
        f'{counts}'
        f'{render_memory_section("Review needed", _dict_list(dashboard.get("review")), "No memories need review.", page_href=page_href, action_hints=action_hints, href="/inbox", include_issues=True)}'
        f'{render_capture_section(_dict_list(dashboard.get("captures")))}'
        f'{render_memory_section("Recent updates", _dict_list(dashboard.get("recent_updates")), "No memory updates yet.", page_href=page_href, action_hints=action_hints)}'
        f'{render_memory_section("Active memories", _dict_list(dashboard.get("active")), "No active memories yet.", page_href=page_href, action_hints=action_hints, href="/profile")}'
        f'{render_memory_section("Archived memories", _dict_list(dashboard.get("archived")), "No archived memories.", page_href=page_href, action_hints=action_hints)}'
        '</div>'
    )
    return layout("Memory Dashboard", body)


def render_profile_page(
    profile: Mapping[str, object],
    *,
    page_href: PageHref,
    layout: PageLayout,
) -> str:
    stats = render_stat_grid([
        (profile.get("memory_count", 0), "memories"),
        (profile.get("active_count", 0), "active"),
        (profile.get("review_count", 0), "review"),
    ])
    archived = _dict_list(profile.get("archived"))
    project = str(profile.get("project") or "")
    profile_actions = _copy_actions([
        (_memory_overview_prompt(project), "Copy profile prompt"),
        (_brief_prompt("", project), "Copy brief prompt"),
    ])
    body = (
        '<div class="breadcrumb"><a href="/">Link</a> / profile</div>'
        '<h1>Memory Profile</h1>'
        '<div class="memory-profile">'
        '<p class="summary">What Link currently remembers about the user, projects, decisions, and preferences.</p>'
        f'{profile_actions}'
        f'{_project_line(project)}'
        f'{stats}'
        f'{_counts_line("Types", _mapping(profile.get("by_type")))}'
        f'{_counts_line("Scopes", _mapping(profile.get("by_scope")))}'
        f'{_counts_line("Status", _mapping(profile.get("by_status")))}'
        f'{_render_empty_profile_actions(project) if not int(profile.get("memory_count") or 0) else ""}'
        f'{_profile_section("Recent memories", _dict_list(profile.get("recent")), page_href=page_href)}'
        f'{_profile_section("Preferences", _dict_list(profile.get("preferences")), page_href=page_href)}'
        f'{_profile_section("Decisions", _dict_list(profile.get("decisions")), page_href=page_href)}'
        f'{_profile_section("Project context", _dict_list(profile.get("projects")), page_href=page_href)}'
        f'{_profile_section("Archived memories", archived, page_href=page_href) if archived else ""}'
        '</div>'
    )
    return layout("Memory Profile", body)


def _render_empty_profile_actions(project: str) -> str:
    project_name = str(project or "").strip()
    remember_prompt = (
        f"remember that <preference or decision> for project {project_name}"
        if project_name else "remember that <preference or decision>"
    )
    return (
        '<div class="memory-next"><strong>No durable memories yet</strong>'
        "<ul>"
        '<li><a href="/ingest">Add source material</a> when the context belongs in the wiki first.</li>'
        '<li><a href="/propose">Review memory proposals</a> when raw notes contain preferences, decisions, or project facts.</li>'
        f"<li>{copy_button(remember_prompt, 'Copy remember prompt')}</li>"
        "</ul></div>"
    )


def render_memory_audit_page(
    audit: Mapping[str, object],
    *,
    page_href: PageHref,
    action_hints: MemoryActionHints,
    layout: PageLayout,
) -> str:
    profile = _mapping(audit.get("profile"))
    captures = _mapping(audit.get("captures"))
    inbox = _mapping(audit.get("inbox"))
    stats = render_stat_grid([
        (profile.get("memory_count", 0), "memories"),
        (profile.get("active_count", 0), "active"),
        (profile.get("review_count", 0), "review"),
        (captures.get("count", 0), "captures"),
        (captures.get("warning_count", 0), "warnings"),
        (captures.get("read_warning_count", 0), "read warnings"),
    ])
    risk_factors = _dict_list(audit.get("risk_factors"))
    if risk_factors:
        risk_html = "<h2>Needs attention</h2><ul class='memory-issues'>" + "".join(
            f'<li><span class="severity">review</span> {html.escape(str(item.get("code") or ""))}: '
            f'{html.escape(str(item.get("message") or ""))}</li>'
            for item in risk_factors
        ) + "</ul>"
    else:
        risk_html = "<h2>Needs attention</h2><p>No memory audit risks detected.</p>"
    project = str(audit.get("project") or "")
    audit_actions = _copy_actions([
        (_audit_prompt(project), "Copy audit prompt"),
        (_inbox_prompt(project), "Copy review prompt"),
    ])
    body = (
        '<div class="breadcrumb"><a href="/">Link</a> / audit</div>'
        '<h1>Memory Audit</h1>'
        '<div class="memory-profile">'
        '<p class="summary">Read-only health report for local agent memory, review backlog, raw captures, and safe next actions.</p>'
        f'{audit_actions}'
        f'{_project_line(project)}'
        f'<p><strong>Status:</strong> {html.escape(str(audit.get("status") or ""))}</p>'
        f'{stats}'
        f'{risk_html}'
        f'{render_memory_next_actions(_dict_list(audit.get("next_actions")))}'
        f'{render_memory_section("Memory inbox sample", _dict_list(inbox.get("items")), "No memory review items.", page_href=page_href, action_hints=action_hints, href="/inbox", include_issues=True)}'
        f'{render_capture_section(_dict_list(captures.get("items")))}'
        '</div>'
    )
    return layout("Memory Audit", body)


def render_captures_page(inbox: Mapping[str, object], *, layout: PageLayout) -> str:
    warning_count = int(inbox.get("warning_count") or 0)
    stats = render_stat_grid([
        (inbox.get("count", 0), "captures"),
        (warning_count, "warnings"),
        (inbox.get("read_warning_count", 0), "read warnings"),
    ])
    warning_html = ""
    if warning_count:
        warning_html = (
            '<div class="memory-next"><strong>Needs redaction</strong>'
            f'<p>{warning_count} raw capture'
            f'{"s contain" if warning_count != 1 else " contains"} secret-looking values.</p>'
            '<code>python3 link.py redact-capture raw/memory-captures/&lt;capture&gt;.md .</code></div>'
        )
    read_warning_html = ""
    read_warnings = _dict_list(inbox.get("read_warnings"))
    if read_warnings:
        rows = "".join(
            f'<li><code>{html.escape(str(item.get("capture") or ""))}</code> '
            f'{html.escape(str(item.get("error") or "unreadable"))}</li>'
            for item in read_warnings[:50]
        )
        read_warning_html = (
            '<div class="memory-next"><strong>Fix capture access</strong>'
            '<p>Some raw captures could not be read and are not listed for approval.</p>'
            f'<ul>{rows}</ul></div>'
        )
    project = str(inbox.get("project") or "")
    capture_actions = _copy_actions([(_capture_prompt(project), "Copy capture prompt")])
    body = (
        '<div class="breadcrumb"><a href="/">Link</a> / captures</div>'
        '<h1>Raw Capture Inbox</h1>'
        '<div class="memory-profile">'
        '<p class="summary">Saved proposal-only session notes waiting for human review before they become durable memory.</p>'
        f'{capture_actions}'
        f'{_project_line(project)}'
        f'{stats}'
        f'{warning_html}'
        f'{read_warning_html}'
        f'{render_capture_section(_dict_list(inbox.get("captures")))}'
        '</div>'
    )
    return layout("Raw Capture Inbox", body)


def render_inbox_page(
    inbox: Mapping[str, object],
    *,
    page_href: PageHref,
    layout: PageLayout,
) -> str:
    stats = render_stat_grid([(inbox.get("review_count", 0), "review")])
    severity_html = _counts_line("Severity", _mapping(inbox.get("counts_by_severity")))
    items = _dict_list(inbox.get("items"))
    if not items:
        content = "<p>Inbox is clear.</p>"
    else:
        rows = "".join(_render_inbox_item(item, page_href=page_href) for item in items)
        content = f"<ul class='page-list'>{rows}</ul>"
    project = str(inbox.get("project") or "")
    inbox_actions = _copy_actions([(_inbox_prompt(project), "Copy review prompt")])
    body = (
        '<div class="breadcrumb"><a href="/">Link</a> / inbox</div>'
        '<h1>Memory Review Inbox</h1>'
        '<div class="memory-profile">'
        '<p class="summary">Memories that need confirmation, stronger metadata, or cleanup.</p>'
        f'{inbox_actions}'
        f'{_project_line(project)}'
        f'{stats}'
        f'{severity_html}'
        f'{content}'
        '</div>'
    )
    return layout("Memory Review Inbox", body)


def render_memory_log_page(log_payload: Mapping[str, object], *, layout: PageLayout) -> str:
    entries = _dict_list(log_payload.get("entries"))
    if entries:
        rows = "".join(_render_memory_log_item(entry) for entry in entries)
        content = f"<ul class='page-list memory-log-list'>{rows}</ul>"
    else:
        content = (
            "<p>No memory lifecycle events yet.</p>"
            '<p><a class="button-link" href="/propose">Create memory proposals</a></p>'
        )
    body = (
        '<div class="breadcrumb"><a href="/">Link</a> / memory log</div>'
        '<h1>Memory Changelog</h1>'
        '<div class="memory-profile">'
        '<p class="summary">A privacy-safe timeline of memory creates, updates, reviews, archives, restores, forgets, and capture accepts.</p>'
        f'{render_stat_grid([(log_payload.get("count", 0), "shown"), (log_payload.get("total_matching", 0), "matching")])}'
        f'<p>{html.escape(str(log_payload.get("privacy_note") or ""))}</p>'
        f'{content}'
        '</div>'
    )
    return layout("Memory Changelog", body)


def render_memory_wins_page(
    wins_payload: Mapping[str, object],
    *,
    page_href: PageHref,
    layout: PageLayout,
) -> str:
    wins = _dict_list(wins_payload.get("wins"))
    win_cards = "".join(_render_memory_win_card(win) for win in wins)
    recent = _dict_list(wins_payload.get("recent_memories"))
    recent_html = _profile_section("Recent reusable memories", recent, page_href=page_href) if recent else (
        "<h2>Recent reusable memories</h2><p>No active memories yet.</p>"
    )
    prompts = "".join(
        f"<li>{html.escape(str(prompt))} {copy_button(str(prompt), 'Copy prompt')}</li>"
        for prompt in _list(wins_payload.get("prompts"))[:4]
    )
    actions = "".join(
        "<li>"
        f"<strong>{html.escape(str(action.get('label') or 'Next'))}</strong>"
        f"<p>{html.escape(str(action.get('reason') or ''))}</p>"
        f"<code>{html.escape(str(action.get('command') or ''))}</code>"
        f"{copy_button(str(action.get('command') or ''), 'Copy command')}"
        "</li>"
        for action in _dict_list(wins_payload.get("next_actions"))
    )
    body = (
        '<div class="breadcrumb"><a href="/">Link</a> / wins</div>'
        '<h1>Memory Wins</h1>'
        '<div class="memory-profile">'
        '<p class="summary">Local proof signals for what Link memory is carrying. These are computed from the wiki, not telemetry.</p>'
        f'{render_stat_grid([(wins_payload.get("active_count", 0), "active"), (wins_payload.get("reviewed_active_count", 0), "reviewed"), (wins_payload.get("review_count", 0), "review"), (wins_payload.get("project_count", 0), "projects")])}'
        f'<p>{html.escape(str(wins_payload.get("honest_note") or ""))}</p>'
        f'<section class="memory-grid">{win_cards}</section>'
        f'{recent_html}'
        '<h2>Try the value loop</h2>'
        f'<ul class="memory-issues">{prompts}</ul>'
        '<h2>Next safe action</h2>'
        f'<ul class="page-list">{actions}</ul>'
        '</div>'
    )
    return layout("Memory Wins", body)


def render_memory_explanation_page(
    explanation: Mapping[str, object],
    *,
    body_html: str,
    layout: PageLayout,
) -> str:
    memory = _mapping(explanation.get("memory"))
    recall_info = _mapping(explanation.get("recall"))
    review = _mapping(explanation.get("review"))
    provenance = _mapping(explanation.get("provenance"))
    lifecycle = _mapping(explanation.get("lifecycle"))
    graph = _mapping(explanation.get("graph"))
    title = str(memory.get("title") or memory.get("name") or "Memory")
    memory_name = str(memory.get("name") or "")
    graph_href = f"/graph?focus={urllib.parse.quote(memory_name, safe='')}&depth=2" if memory_name else "/graph"
    summary = memory.get("tldr") or memory.get("snippet") or ""
    issues = "".join(
        f'<li><span class="severity">{html.escape(str(issue.get("severity") or ""))}</span> '
        f'{html.escape(str(issue.get("code") or ""))}: {html.escape(str(issue.get("message") or ""))}</li>'
        for issue in _dict_list(review.get("issues"))
    )
    issue_html = (
        f'<h2>Review Issues</h2><ul class="memory-issues">{issues}</ul>'
        if issues else "<h2>Review Issues</h2><p>No detected issues.</p>"
    )
    primary = _mapping(review.get("primary_action"))
    primary_html = ""
    if primary:
        primary_html = (
            f'<p class="summary"><strong>Next:</strong> {html.escape(str(primary.get("label") or ""))} '
            f'- {html.escape(str(primary.get("description") or ""))}</p>'
        )
    action_html = f'<h2>Actions</h2>{primary_html}{render_memory_action_commands(_dict_list(review.get("actions")))}'
    graph_html = (
        '<h2>Graph</h2>'
        f'<p><a class="button-link" href="{html.escape(graph_href, quote=True)}">Open local graph</a></p>'
        f'<p><strong>Forward:</strong> {html.escape(", ".join(str(item) for item in _list(graph.get("forward"))) or "none")}</p>'
        f'<p><strong>Inbound:</strong> {html.escape(", ".join(str(item) for item in _list(graph.get("inbound"))) or "none")}</p>'
        f'<p><strong>Wikilinks:</strong> {html.escape(", ".join(str(item) for item in _list(graph.get("wikilinks"))) or "none")}</p>'
    )
    logs = "".join(
        f'<pre class="log-entry">{html.escape(str(entry))}</pre>'
        for entry in _list(explanation.get("log_entries"))[-5:]
    )
    log_html = f"<h2>Log Entries</h2>{logs}" if logs else "<h2>Log Entries</h2><p>No matching log entries.</p>"
    body = (
        '<div class="breadcrumb"><a href="/">Link</a> / explain memory</div>'
        f'<h1>{html.escape(title)}</h1>'
        f'<p class="summary">{html.escape(str(summary))}</p>'
        '<div class="trust-grid">'
        f'<div><strong>Recall</strong>{html.escape(str(recall_info.get("state") or ""))}<br><small>{html.escape(str(recall_info.get("reason") or ""))}</small></div>'
        f'<div><strong>Review</strong>{html.escape(str(review.get("status") or ""))} · {html.escape(str(review.get("issue_count", 0)))} issues</div>'
        f'<div><strong>Status</strong>{html.escape(str(lifecycle.get("status") or ""))}</div>'
        f'<div><strong>Source</strong>{html.escape(str(provenance.get("source") or "missing"))}</div>'
        f'<div><strong>Captured</strong>{html.escape(str(provenance.get("date_captured") or "missing"))}</div>'
        f'<div><strong>Path</strong>{html.escape(str(provenance.get("path") or ""))}</div>'
        '</div>'
        f'{issue_html}'
        f'{action_html}'
        f'{graph_html}'
        f'{log_html}'
        f'<h2>Memory Body</h2>{body_html}'
    )
    return layout(f"Explain: {title}", body)


def _render_memory_log_item(entry: Mapping[str, object]) -> str:
    paths = _list(entry.get("memory_paths"))
    path_html = ""
    if paths:
        path_html = "<div class='memory-meta'>Memories: " + html.escape(", ".join(str(path) for path in paths)) + "</div>"
    details = _list(entry.get("details"))
    detail_html = ""
    if details:
        detail_html = "<ul class='memory-issues'>" + "".join(
            f"<li>{html.escape(str(detail))}</li>"
            for detail in details[:4]
        ) + "</ul>"
    return (
        "<li>"
        f"<strong>{html.escape(str(entry.get('operation') or 'event'))}</strong>"
        f"<div class='memory-meta'>{html.escape(str(entry.get('timestamp') or ''))} · {html.escape(str(entry.get('category') or 'memory'))}</div>"
        f"<p>{html.escape(str(entry.get('description') or ''))}</p>"
        f"<small>{html.escape(str(entry.get('summary') or ''))}</small>"
        f"{path_html}"
        f"{detail_html}"
        "</li>"
    )


def _render_memory_win_card(win: Mapping[str, object]) -> str:
    prompt = str(win.get("prompt") or "")
    return (
        '<article class="memory-card">'
        f'<h2>{html.escape(str(win.get("label") or ""))}</h2>'
        f'<div class="memory-metric">{html.escape(str(win.get("count") or 0))}</div>'
        f'<p>{html.escape(str(win.get("description") or ""))}</p>'
        f'{copy_button(prompt, "Copy prompt") if prompt else ""}'
        '</article>'
    )


def _render_inbox_item(item: Mapping[str, object], *, page_href: PageHref) -> str:
    name = str(item.get("name") or "")
    summary = item.get("tldr") or item.get("snippet") or ""
    meta = f'{item.get("memory_type", "")} · {item.get("scope", "")} · {item.get("status", "")}'
    issues = "".join(
        f'<li><span class="severity">{html.escape(str(issue.get("severity") or ""))}</span> '
        f'{html.escape(str(issue.get("code") or ""))}: {html.escape(str(issue.get("message") or ""))}</li>'
        for issue in _dict_list(item.get("issues"))
    )
    primary = _mapping(item.get("primary_action"))
    primary_html = ""
    if primary:
        primary_html = (
            f'<p class="summary"><strong>Next:</strong> {html.escape(str(primary.get("label") or ""))} '
            f'- {html.escape(str(primary.get("description") or ""))}</p>'
        )
    return (
        f'<li><a href="{html.escape(page_href(name), quote=True)}">{html.escape(str(item.get("title") or name))}</a>'
        f'<div class="memory-meta">{html.escape(meta)}</div>'
        f'<div class="memory-meta"><a href="/explain-memory?memory={urllib.parse.quote(name, safe="")}">explain</a></div>'
        f'{f"<small>{html.escape(str(summary))}</small>" if summary else ""}'
        f'<ul class="memory-issues">{issues}</ul>'
        f'{primary_html}'
        f'{render_memory_action_commands(_dict_list(item.get("actions")))}</li>'
    )


def _profile_section(
    title: str,
    records: list[dict[str, object]],
    *,
    page_href: PageHref,
    empty: str = "none",
) -> str:
    if not records:
        return f"<h2>{html.escape(title)}</h2><p>{html.escape(empty)}</p>"
    items = ""
    for record in records:
        name = str(record.get("name") or "")
        summary = record.get("tldr") or record.get("snippet") or ""
        meta = f'{record.get("memory_type", "")} · {record.get("scope", "")}'
        items += (
            f'<li><a href="{html.escape(page_href(name), quote=True)}">{html.escape(str(record.get("title") or name))}</a>'
            f'<div class="memory-meta">{html.escape(meta)}</div>'
            f'<div class="memory-meta"><a href="/explain-memory?memory={urllib.parse.quote(name, safe="")}">explain</a></div>'
            f'{f"<small>{html.escape(str(summary))}</small>" if summary else ""}</li>'
        )
    return f"<h2>{html.escape(title)}</h2><ul class='page-list'>{items}</ul>"


def _counts_line(title: str, counts: Mapping[str, object]) -> str:
    if not counts:
        return ""
    parts = ", ".join(
        f"{html.escape(str(name))}: {html.escape(str(count))}"
        for name, count in counts.items()
    )
    return f"<p><strong>{html.escape(title)}:</strong> {parts}</p>"


def _project_line(project: str) -> str:
    return f"<p><strong>Project:</strong> {html.escape(project)}</p>" if project else ""


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _sequence(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _dict_list(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
