"""Text rendering helpers for Link setup-oriented CLI commands."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from .mcp_verify import display_command


def render_init_text(*, target: object, fixes: Sequence[str]) -> tuple[int, str]:
    command_target = str(target)
    lines = [f"Link wiki ready at {target}"]
    if fixes:
        lines.extend(["", "Initialized:"])
        lines.extend(f"  - {item}" for item in fixes)
    lines.extend([
        "",
        "Next:",
        f"  {display_command(['link', 'health', command_target])}",
        f"  {display_command(['link', 'serve', command_target])}",
        "  Drop sources into raw/ and ask your agent: ingest raw/<file> into Link",
    ])
    return 0, "\n".join(lines)


def render_starter_prompts_text(payload: Mapping[str, object]) -> tuple[int, str]:
    lines = [f"Link starter prompts: {payload['target']}"]
    if payload["project"]:
        lines.append(f"Project: {payload['project']}")
    if payload.get("shortcut"):
        lines.extend(["", "Shortcut", f"- {payload['shortcut']}"])
    lines.extend(["", "Ask your agent"])
    prompts = payload.get("prompts", [])
    if isinstance(prompts, Sequence) and not isinstance(prompts, (str, bytes)):
        for item in prompts:
            if isinstance(item, Mapping):
                lines.append(f"- {item['prompt']}")
                lines.append(f"  When: {item['when']}")
    lines.extend(["", "Local checks"])
    for command in payload.get("commands", []):
        lines.append(f"- {command}")
    return 0, "\n".join(lines)


def render_welcome_text(payload: Mapping[str, object]) -> tuple[int, str]:
    """Render a short first-use guide for humans trying Link with an agent."""
    lines = [f"Link welcome: {payload['target']}"]
    if payload["project"]:
        lines.append(f"Project: {payload['project']}")
    lines.extend([
        "",
        "Try these with your agent",
    ])
    steps = payload.get("steps", [])
    if isinstance(steps, Sequence) and not isinstance(steps, (str, bytes)):
        for item in steps:
            if isinstance(item, Mapping):
                lines.append(f"{item.get('step', '-')}. {item.get('prompt', '')}")
                lines.append(f"   Proves: {item.get('proves', '')}")
    lines.extend(["", "Local checks"])
    for command in payload.get("commands", []):
        lines.append(f"- {command}")
    lines.extend(["", "Open"])
    for url in payload.get("urls", []):
        lines.append(f"- {url}")
    return 0, "\n".join(lines)


def render_demo_text(
    *,
    target: object,
    guide_path: object,
    serve_command: str,
    next_command: str,
    query_command: str,
    brief_command: str,
    audit_command: str,
) -> tuple[int, str]:
    return 0, "\n".join([
        f"Link demo created at {target}",
        "",
        "View it:",
        f"  {serve_command}",
        "",
        "Ask an agent what to try next:",
        f"  {next_command}",
        "",
        "Try the value loop:",
        f"  {query_command}",
        f"  {brief_command}",
        f"  {audit_command}",
        "",
        "Guide:",
        f"  {guide_path}",
        "",
        "Then open:",
        "  http://127.0.0.1:3000",
        "  http://127.0.0.1:3000/graph",
    ])


def render_try_text(
    *,
    target: object,
    ready: bool,
    page_count: object,
    memory_count: object,
    search_backend: object,
    query_summary: str,
    brief_summary: str,
    serve_command: str,
    next_command: str,
    health_command: str,
    query_command: str,
    brief_command: str,
    benchmark_command: str,
    url: str,
) -> tuple[int, str]:
    status_text = "ready" if ready else "needs attention"
    return 0 if ready else 1, "\n".join([
        f"Link try: {target}",
        "",
        f"Demo: {status_text} · {page_count} pages · {memory_count} memories · {search_backend}",
        f"Query proof: {query_summary}",
        f"Brief proof: {brief_summary}",
        "",
        "Open the local viewer:",
        f"  {serve_command}",
        f"  {url}",
        "",
        "Ask an agent:",
        "  is Link ready?",
        "  brief me from Link before we continue",
        "  what does Link remember about local personal memory?",
        "",
        "Run the value loop:",
        f"  {query_command}",
        f"  {brief_command}",
        f"  {benchmark_command}",
        f"  {health_command}",
        "",
        "More first-run prompts:",
        f"  {next_command}",
    ])


def render_mcp_connect_text(payload: Mapping[str, object]) -> tuple[int, str]:
    """Render a safe MCP connection plan for a local agent."""
    write_status = payload.get("write") if isinstance(payload.get("write"), Mapping) else {}
    requested = bool(write_status.get("requested"))
    ok = bool(write_status.get("ok"))
    code = 0 if not requested or ok else 1
    lines = [
        f"Link connect: {payload.get('display_name')}",
        "",
        f"Wiki: {payload.get('wiki')}",
        f"Python: {payload.get('python')}",
        f"Config: {payload.get('config_path')}",
        "",
    ]
    if requested:
        lines.append(f"Write: {'updated' if ok else 'failed'}")
        message = write_status.get("message")
        if message:
            lines.append(f"  {message}")
        lines.append("")
    else:
        lines.extend([
            "Preview only. To update the agent config:",
        ])
        actions = payload.get("next_actions", [])
        if isinstance(actions, Sequence) and not isinstance(actions, (str, bytes)):
            for action in actions:
                if isinstance(action, Mapping) and action.get("label") == "write config":
                    lines.append(f"  {action.get('command_text')}")
                    break
        lines.append("")
    lines.append("Config snippet:")
    snippet = str(payload.get("snippet") or "")
    lines.extend(f"  {line}" if line else "" for line in snippet.splitlines())
    lines.extend(["", "Then:"])
    actions = payload.get("next_actions", [])
    if isinstance(actions, Sequence) and not isinstance(actions, (str, bytes)):
        for action in actions:
            if isinstance(action, Mapping) and action.get("label") != "write config":
                lines.append(f"  {action.get('command_text')}")
    restart_hint = payload.get("restart_hint")
    if restart_hint:
        lines.append(f"  {restart_hint}")
    return code, "\n".join(lines)
