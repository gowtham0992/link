"""HTML helpers for Link's local onboarding page."""
from __future__ import annotations

import html
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from .mcp_verify import display_command
from .web_ingest import copy_button
from .web_layout import render_stat_grid


PageLayout = Callable[[str, str], str]


def _command_target(wiki_dir: object, fallback: object) -> str:
    raw = str(wiki_dir or fallback or "").strip()
    if not raw:
        return ""
    path = Path(raw)
    return str(path.parent if path.name == "wiki" else path)


def _command_row(command: str, label: str = "Copy") -> str:
    return (
        "<li>"
        f"{copy_button(command, label)}"
        f"<code>{html.escape(command)}</code>"
        "</li>"
    )


def _agent_cards(target: str, agents: Sequence[str]) -> str:
    cards = ""
    for agent in agents:
        preview = display_command(["link", "onboard", target, "--agent", agent])
        write = display_command(["link", "onboard", target, "--agent", agent, "--write"])
        cards += (
            '<article class="onboard-agent-card">'
            f"<h3>{html.escape(agent)}</h3>"
            "<p>Preview first. Write only when you are ready to update that agent config.</p>"
            '<ul class="command-list">'
            f"{_command_row(preview, 'Copy preview')}"
            f"{_command_row(write, 'Copy write')}"
            "</ul>"
            "</article>"
        )
    return cards


def _prompt_cards(prompts: object) -> str:
    rows = ""
    prompt_items = prompts if isinstance(prompts, list) else []
    for item in prompt_items:
        if not isinstance(item, dict):
            continue
        prompt = str(item.get("prompt") or "")
        when = str(item.get("when") or "")
        label = str(item.get("label") or "Prompt")
        rows += (
            '<article class="proposal-card">'
            f"<h3>{html.escape(label)}</h3>"
            f"{copy_button(prompt, 'Copy prompt')}"
            f'<code class="proposal-command">{html.escape(prompt)}</code>'
            f'<p class="summary">{html.escape(when)}</p>'
            "</article>"
        )
    return rows


def render_onboard_page(
    status: Mapping[str, object],
    operations: Mapping[str, object],
    starter_prompts: Mapping[str, object],
    *,
    target: str,
    agents: Sequence[str],
    layout: PageLayout,
) -> str:
    """Render a guided first-run page for humans setting up Link with agents."""
    command_target = target or _command_target(status.get("wiki"), operations.get("wiki"))
    ready = bool(status.get("ready"))
    validation = status.get("validation") if isinstance(status.get("validation"), Mapping) else {}
    validation_label = "passed" if validation.get("passed") else ("failed" if validation.get("checked") else "not checked")
    health_command = display_command(["link", "health", command_target])
    onboard_command = display_command(["link", "onboard", command_target])
    seed_onboard_command = display_command(["link", "onboard", command_target, "--seed-project", "."])
    seed_command = display_command(["link", "seed", ".", command_target])
    first_memory_command = display_command([
        "link",
        "onboard",
        command_target,
        "--first-memory",
        "I prefer concise release notes",
    ])
    brief_command = display_command(["link", "brief", "working with Link", command_target])
    ingest_command = display_command(["link", "ingest-status", command_target])
    memory_inbox_command = display_command(["link", "memory-inbox", command_target])

    stats = render_stat_grid([
        ("yes" if ready else "no", "ready"),
        (status.get("content_page_count", 0), "content pages"),
        (status.get("memory_count", 0), "memories"),
        (status.get("needs_review_count", 0), "need review"),
        (validation_label, "validation"),
    ])
    setup_cards = (
        '<section class="onboard-steps" aria-label="Link onboarding steps">'
        '<article class="onboard-step" data-state="done"><span>1</span><h2>Check readiness</h2>'
        '<p>Confirm the wiki is usable before trusting recall.</p>'
        f'<ul class="command-list">{_command_row(health_command)}</ul></article>'
        '<article class="onboard-step" data-state="next"><span>2</span><h2>Seed this project</h2>'
        '<p>Run from a repo so the first recall already knows the project. This writes source-backed context, not durable memory.</p>'
        f'<ul class="command-list">{_command_row(seed_onboard_command)}{_command_row(seed_command)}</ul></article>'
        '<article class="onboard-step" data-state="next"><span>3</span><h2>Seed one memory</h2>'
        '<p>Start with one explicit preference or decision. Link saves it for review.</p>'
        f'<ul class="command-list">{_command_row(first_memory_command)}</ul></article>'
        '<article class="onboard-step" data-state="next"><span>4</span><h2>Connect an agent</h2>'
        '<p>MCP and CLI work without the viewer running. The viewer is just the local UI.</p>'
        f'<ul class="command-list">{_command_row(onboard_command)}</ul></article>'
        '<article class="onboard-step" data-state="next"><span>5</span><h2>Start the loop</h2>'
        '<p>Brief before work, ingest sources, then review what should become durable memory.</p>'
        f'<ul class="command-list">{_command_row(brief_command)}{_command_row(ingest_command)}{_command_row(memory_inbox_command)}</ul></article>'
        "</section>"
    )
    agent_cards = _agent_cards(command_target, agents)
    prompt_cards = _prompt_cards(starter_prompts.get("prompts"))
    body = (
        '<div class="breadcrumb"><a href="/">Link</a> / onboard</div>'
        "<h1>Onboard</h1>"
        '<p class="summary">One local checklist for first-run setup: health, project context, first memory, agent wiring, and the daily prompt loop.</p>'
        f"{stats}"
        f"{setup_cards}"
        '<section><div class="section-heading"><h2>Agent Wiring</h2><a href="/prompts">starter prompts</a></div>'
        '<p class="summary">Preview commands are safe. Add <code>--write</code> only when you want Link to update an agent config.</p>'
        f'<div class="onboard-agent-grid">{agent_cards}</div></section>'
        '<section><h2>Ask Your Agent First</h2>'
        '<p class="summary">These are the prompts that make Link feel automatic without hiding what changed.</p>'
        f'<div class="proposal-results">{prompt_cards}</div></section>'
    )
    return layout("Onboard", body)
