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
        f"  {display_command(['lnk', 'health', command_target])}",
        f"  {display_command(['lnk', 'onboard', command_target])}",
        f"  {display_command(['lnk', 'serve', command_target])}",
        "  Open http://127.0.0.1:3000/onboard for the browser checklist",
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


def render_start_text(payload: Mapping[str, object]) -> tuple[int, str]:
    """Render the compact session-start packet for CLI and skill users."""
    status = payload.get("status")
    if not isinstance(status, Mapping):
        raise ValueError("Invalid Link start payload")
    target = payload.get("target")
    task = str(payload.get("task") or "").strip()
    validation = status.get("validation") if isinstance(status.get("validation"), Mapping) else {}
    validation_text = "not checked"
    if isinstance(validation, Mapping) and validation.get("checked"):
        validation_text = "passed" if validation.get("passed") else (
            f"failed ({validation.get('error_count', 0)} errors, {validation.get('warning_count', 0)} warnings)"
        )
    lines = [
        f"Link start: {target}",
        "",
        f"Ready: {'yes' if status.get('ready') else 'no'} · validation {validation_text}",
        (
            f"Pages: {status.get('content_page_count', status.get('page_count', 0))} content · "
            f"Memories: {status.get('active_memory_count', 0)} active · "
            f"Review: {status.get('needs_review_count', 0)}"
        ),
        f"Search backend: {status.get('search_backend', 'unknown')}",
    ]
    if task:
        lines.append(f"Task: {task}")

    brief_text = str(payload.get("brief_text") or "").strip()
    if brief_text:
        lines.extend(["", brief_text])

    context_preview = payload.get("context_preview") if isinstance(payload.get("context_preview"), Mapping) else {}
    capsule = context_preview.get("recall_capsule") if isinstance(context_preview.get("recall_capsule"), Mapping) else {}
    capsule_items = capsule.get("items") if isinstance(capsule.get("items"), Sequence) else []
    if capsule_items and not isinstance(capsule_items, (str, bytes)):
        lines.extend([
            "",
            f"Context preview ({context_preview.get('budget', 'micro')} · ~{capsule.get('estimated_tokens', '?')} tokens)",
        ])
        for item in capsule_items[:3]:
            if not isinstance(item, Mapping):
                continue
            kind = str(item.get("kind") or "context")
            title = str(item.get("title") or item.get("name") or "context")
            summary = " ".join(str(item.get("summary") or "").split())
            lines.append(f"- {title} ({kind})")
            if summary:
                lines.append(f"  {summary[:180]}{'...' if len(summary) > 180 else ''}")

    commands = payload.get("commands") if isinstance(payload.get("commands"), Mapping) else {}
    project_seed = payload.get("project_seed") if isinstance(payload.get("project_seed"), Mapping) else {}
    if not status.get("ready"):
        lines.extend(["", "Needs attention"])
        next_actions = status.get("next_actions")
        if isinstance(next_actions, Sequence) and not isinstance(next_actions, (str, bytes)):
            for item in next_actions[:3]:
                if isinstance(item, Mapping):
                    lines.append(f"- {item.get('label', item.get('tool', 'inspect Link'))}")
        if isinstance(commands, Mapping) and commands.get("health"):
            lines.append(f"- {commands['health']}")
    else:
        lines.extend([
            "",
            "Next",
        ])
        if project_seed.get("recommended"):
            command = project_seed.get("command") or commands.get("seed_project")
            if command:
                lines.append(f"- Seed project context: {command}")
            reason = str(project_seed.get("reason") or "").strip()
            if reason:
                lines.append(f"  {reason}")
            safety = str(project_seed.get("safety") or "").strip()
            if safety:
                lines.append(f"  {safety}")
        if isinstance(commands, Mapping) and commands.get("query"):
            lines.append(f"- Need more context: {commands['query']}")
        if isinstance(commands, Mapping) and commands.get("review"):
            lines.append(f"- Review pending memory: {commands['review']}")
        brief = payload.get("brief") if isinstance(payload.get("brief"), Mapping) else {}
        backlog = brief.get("backlog") if isinstance(brief.get("backlog"), Mapping) else {}
        if backlog.get("backlog"):
            lines.append(
                f"- Memory backlog ({backlog.get('pending_captures', 0)} captures · "
                f"{backlog.get('needs_review_memories', 0)} reviews): offer a consolidation pass — "
                f"{backlog.get('command')}"
            )
        lines.append("- Save memory only after explicit user approval.")
    return 0 if status.get("ready") else 1, "\n".join(lines)


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
    start_command: str,
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
        f"  {start_command}",
        f"  {query_command}",
        f"  {brief_command}",
        f"  {audit_command}",
        "",
        "Guide:",
        f"  {guide_path}",
        "",
        "Then open:",
        "  http://127.0.0.1:3000",
        "  http://127.0.0.1:3000/onboard",
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
    try:
        memory_total = int(memory_count)
    except (TypeError, ValueError):
        memory_total = 0
    memory_label = "memory" if memory_total == 1 else "memories"
    return 0 if ready else 1, "\n".join([
        f"Link try: {target}",
        "",
        "60-second proof complete" if ready else "60-second proof needs attention",
        "",
        "Status",
        f"- Demo: {status_text}",
        f"- Corpus: {page_count} pages · {memory_count} {memory_label}",
        f"- Search: {search_backend}",
        "- Storage: local Markdown wiki + reviewed memory pages",
        "- Privacy: no cloud account, no hosted memory profile, no telemetry",
        "",
        "What Link proved",
        f"1. Query proof: {query_summary}",
        f"2. Brief proof: {brief_summary}",
        "3. Agent path: CLI works now; MCP and skills can use the same local wiki.",
        "",
        "Open the local viewer:",
        f"  {serve_command}",
        f"  {url}",
        f"  {url}/onboard",
        "",
        "Ask an agent:",
        "  is Link ready?",
        "  start with Link before we continue",
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


def render_proof_text(payload: Mapping[str, object]) -> tuple[int, str]:
    """Render the cross-agent continuity proof for humans."""
    target = payload.get("target")
    ready = bool(payload.get("ready"))
    created = bool(payload.get("created"))
    memory = payload.get("memory") if isinstance(payload.get("memory"), Mapping) else {}
    recall = payload.get("recall") if isinstance(payload.get("recall"), Mapping) else {}
    commands = payload.get("commands") if isinstance(payload.get("commands"), Mapping) else {}
    prompts = payload.get("prompts") if isinstance(payload.get("prompts"), Mapping) else {}
    title = str(memory.get("title") or "Cross-agent proof memory")
    memory_status = "created" if memory.get("created") else "already existed"
    if memory.get("reviewed"):
        memory_status += " and reviewed"
    recall_status = "found" if recall.get("found") else "not found"
    lines = [
        f"Link proof: {target}",
        "",
        "Cross-agent memory continuity works" if ready else "Cross-agent memory proof needs attention",
        "",
        "What happened",
        f"1. Workspace: {'created' if created else 'reused'} a throwaway demo wiki (not your real memory).",
        f"2. Memory: {memory_status}: {title}",
        f"3. Recall: {recall_status} through the same bounded recall path used by CLI, skills, and MCP.",
        "",
        "What this means for you",
        "- Save something once; any of your agents can recall it later, from plain local files.",
        "- Ready for real use? Create your durable workspace and wire an agent:",
        f"    {display_command(['lnk', 'onboard'])}",
        "    (this proof workspace is a demo — your memory will live at ~/link)",
        "",
        "Try it with two agents",
        f"Agent A: {prompts.get('agent_a', 'remember that this project uses Link')}",
        f"Agent B: {prompts.get('agent_b', 'start with Link before we continue')}",
        "",
        "No viewer required",
        "- CLI, skills, and MCP read the same local wiki files.",
        "- The web viewer is optional inspection UI.",
        "- No cloud account, no hosted memory profile, no telemetry.",
        "",
        "Copy these checks",
    ]
    for key in ("start", "recall", "mcp", "serve"):
        command = commands.get(key) if isinstance(commands, Mapping) else None
        if command:
            lines.append(f"- {command}")
    if not ready:
        lines.extend(["", "Result: needs attention"])
        return 1, "\n".join(lines)
    lines.extend(["", "Result: proof passed"])
    return 0, "\n".join(lines)


def _first_mapping_items(value: object, limit: int) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value[:limit] if isinstance(item, Mapping)]


def _connection_state(connection: Mapping[str, object]) -> str:
    write_status = connection.get("write") if isinstance(connection.get("write"), Mapping) else {}
    state = "preview"
    if write_status.get("requested"):
        state = "updated" if write_status.get("ok") else "failed"
    session_hooks = connection.get("session_hooks")
    if isinstance(session_hooks, Mapping):
        hooks_write = session_hooks.get("write") if isinstance(session_hooks.get("write"), Mapping) else {}
        if hooks_write.get("requested"):
            state += " · hooks " + ("updated" if hooks_write.get("ok") else "failed")
        elif hooks_write.get("message"):
            state += f" · hooks: {hooks_write.get('message')}"
        else:
            state += " · hooks preview"
    return state


def render_onboard_text(payload: Mapping[str, object]) -> tuple[int, str]:
    """Render the guided first-run path for a normal Link workspace."""
    status = payload.get("status") if isinstance(payload.get("status"), Mapping) else {}
    memory = payload.get("first_memory") if isinstance(payload.get("first_memory"), Mapping) else None
    project_seed = payload.get("project_seed") if isinstance(payload.get("project_seed"), Mapping) else None
    commands = payload.get("commands") if isinstance(payload.get("commands"), Mapping) else {}
    ready = bool(status.get("ready"))
    connections = _first_mapping_items(payload.get("connections"), 12)
    connection_failed = any(_connection_state(connection) == "failed" for connection in connections)
    write_requested_without_agent = bool(payload.get("write_requested")) and not connections
    seed_failed = bool(project_seed) and project_seed.get("status") not in {"ok", "partial", "already_seeded"}
    code = (
        0
        if ready and not connection_failed and not write_requested_without_agent and not payload.get("error") and not seed_failed
        else 1
    )

    lines = [
        f"Link onboard: {payload.get('target')}",
        "",
        "Workspace",
        f"- {'created or repaired' if payload.get('created') or payload.get('fixes') else 'already present'}",
        f"- health: {'ready' if ready else 'needs attention'}",
        f"- pages: {status.get('content_page_count', 0)} content · memories: {status.get('memory_count', 0)}",
    ]
    fixes = payload.get("fixes")
    if isinstance(fixes, Sequence) and not isinstance(fixes, (str, bytes)) and fixes:
        # A fresh workspace reports every scaffolded directory/file — a dozen
        # lines a first-timer doesn't need. Collapse the bulk case to one
        # line; keep a short list of targeted repairs on an existing
        # workspace, where each line is actually meaningful.
        if len(fixes) > 4:
            lines.append(f"- scaffolded a fresh workspace ({len(fixes)} items)")
        else:
            lines.append("- safe repairs:")
            lines.extend(f"  - {item}" for item in fixes)

    lines.extend(["", "First memory"])
    if memory:
        if memory.get("created"):
            lines.append(f"- saved for review: {memory.get('path')}")
        else:
            lines.append(f"- not written: {memory.get('message') or memory.get('reason') or 'needs review'}")
    else:
        lines.append("- none yet. Add one when the agent learns a durable preference or decision.")

    lines.extend(["", "Project seed"])
    if project_seed:
        status_label = project_seed.get("status") or "unknown"
        lines.append(f"- status: {status_label}")
        lines.append(f"- project: {project_seed.get('project_root')}")
        lines.append(f"- included files: {project_seed.get('included_count', 0)}")
        if project_seed.get("wrote"):
            lines.append(f"- source page: {project_seed.get('source_page')}")
        elif project_seed.get("message"):
            lines.append(f"- not written: {project_seed.get('message')}")
        if project_seed.get("blocked_secret_count") or project_seed.get("read_error_count"):
            lines.append(
                "- needs attention: "
                f"{project_seed.get('blocked_secret_count', 0)} secret warning(s), "
                f"{project_seed.get('read_error_count', 0)} read error(s)"
            )
        next_commands = project_seed.get("next_commands")
        if isinstance(next_commands, Sequence) and not isinstance(next_commands, (str, bytes)):
            for command in list(next_commands)[:3]:
                lines.append(f"  {command}")
    else:
        lines.append("- not run. Seed this repo when you want first recall to know the project:")
        if commands.get("seed_project"):
            lines.append(f"  {commands.get('seed_project')}")

    lines.extend(["", "Agent connection"])
    if connections:
        for connection in connections:
            state = _connection_state(connection)
            label = connection.get("display_name") or connection.get("agent") or "agent"
            config_path = connection.get("config_path") or ""
            lines.append(f"- {label}: {state} · {config_path}")
            restart_hint = connection.get("restart_hint")
            if state == "preview":
                actions = _first_mapping_items(connection.get("next_actions"), 4)
                for action in actions:
                    if action.get("label") == "write config":
                        lines.append(f"  Write when ready: {action.get('command_text')}")
                        break
                if connection.get("hooks_command"):
                    lines.append(f"  Make memory automatic (recommended): {connection.get('hooks_command')}")
                if restart_hint:
                    lines.append(f"  After writing: {restart_hint}")
            elif state == "updated":
                runtime = connection.get("mcp_runtime") if isinstance(connection.get("mcp_runtime"), Mapping) else {}
                if runtime.get("provisioned"):
                    lines.append("  MCP runtime: provisioned ~/.link-mcp-venv so the agent can start Link's MCP server.")
                if restart_hint:
                    lines.append(f"  Restart: {restart_hint}")
            elif state == "failed":
                write_status = connection.get("write") if isinstance(connection.get("write"), Mapping) else {}
                lines.append(f"  Error: {write_status.get('message') or 'could not write config'}")
    else:
        if write_requested_without_agent:
            lines.append("- no agent selected; nothing was written. Add --agent codex or --all-agents.")
        else:
            lines.append("- not connected yet. Preview an agent config with:")
            for command in payload.get("agent_examples", []):
                lines.append(f"  {command}")
    hooks_hint = str(payload.get("hooks_hint") or "").strip()
    if hooks_hint:
        lines.extend(["", *hooks_hint.splitlines()])

    prompts = _first_mapping_items(payload.get("prompts"), 4)
    lines.extend(["", "Ask your agent"])
    for item in prompts:
        lines.append(f"- {item.get('prompt')}")
    if commands.get("health"):
        lines.extend(["", "Check"])
        lines.append(f"  {commands.get('health')}")
    if commands.get("serve"):
        lines.extend(["", "Open UI"])
        lines.append(f"  {commands.get('serve')}")
        lines.append(f"  {payload.get('url')}")
    if commands.get("memory_inbox") or commands.get("ingest_status"):
        lines.extend(["", "When there is work to review"])
        for key in ("memory_inbox", "ingest_status"):
            if commands.get(key):
                lines.append(f"  {commands.get(key)}")

    return code, "\n".join(lines)


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
    ]
    runtime = payload.get("mcp_runtime") if isinstance(payload.get("mcp_runtime"), Mapping) else {}
    if runtime:
        link_mcp = runtime.get("link_mcp") if isinstance(runtime.get("link_mcp"), Mapping) else {}
        version = link_mcp.get("version") or "missing"
        if runtime.get("ready") and runtime.get("provisioned"):
            lines.append(f"MCP runtime: ready — provisioned ~/.link-mcp-venv (link-mcp {version})")
        elif runtime.get("ready"):
            lines.append(f"MCP runtime: ready (link-mcp {version})")
        elif not requested:
            lines.append(
                f"MCP runtime: needs attention (link-mcp {version}, need {payload.get('expected_version')}); "
                "--write provisions ~/.link-mcp-venv automatically"
            )
    lines.append("")
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


def render_agent_hooks_text(payload: Mapping[str, object]) -> tuple[int, str]:
    """Render a session-hook configuration plan for a supported local agent."""
    write_status = payload.get("write") if isinstance(payload.get("write"), Mapping) else {}
    requested = bool(write_status.get("requested"))
    ok = bool(write_status.get("ok"))
    code = 0 if not requested or ok else 1
    lines = [
        f"Link session hooks: {payload.get('display_name')}",
        "",
        f"Settings: {payload.get('settings_path')}",
    ]
    behavior = payload.get("behavior")
    if isinstance(behavior, Sequence) and not isinstance(behavior, (str, bytes)):
        lines.append("")
        lines.extend(f"  {item}" for item in behavior)
    runtime_note = str(payload.get("runtime_note") or "").strip()
    if runtime_note:
        lines.extend(["", f"  {runtime_note}"])
    lines.append("")
    if requested:
        lines.append(f"Write: {'updated' if ok else 'failed'}")
        message = write_status.get("message")
        if message:
            lines.append(f"  {message}")
    else:
        lines.append("Preview only. Rerun with --write to update the settings file.")
    lines.extend(["", "Hooks snippet:"])
    snippet = str(payload.get("snippet") or "")
    lines.extend(f"  {line}" if line else "" for line in snippet.splitlines())
    restart_hint = payload.get("restart_hint")
    if restart_hint:
        lines.extend(["", f"  {restart_hint}"])
    return code, "\n".join(lines)


def render_session_start_hook_text(payload: Mapping[str, object]) -> tuple[int, str]:
    """Render the bounded memory-brief context block injected by session-start hooks."""
    status = payload.get("status") if isinstance(payload.get("status"), Mapping) else {}
    target = str(payload.get("target") or "")
    project = str(payload.get("project") or "").strip()
    lines = [
        "Link memory (local, source-backed)"
        + (f" · project {project}" if project else ""),
    ]
    if not status.get("ready"):
        lines.extend([
            "Link is not ready; skipping the memory brief.",
            f"Check with: {display_command(['lnk', 'health', target])}",
        ])
        return 0, "\n".join(lines)

    # Empty workspace: inject two useful lines, not a skeleton of zeros.
    if (
        not int(status.get("active_memory_count") or 0)
        and not int(status.get("content_page_count") or 0)
        and not int(payload.get("capture_count") or 0)
    ):
        lines[0] += " — empty workspace, nothing to recall yet."
        lines.extend([
            "To give day-one recall real project context, seed allowlisted repo docs: "
            f"{display_command(['lnk', 'seed', '.', target])} (source-backed, no durable memory).",
            "Save durable memory only after the user explicitly approves it.",
        ])
        return 0, "\n".join(lines)

    brief_text = str(payload.get("brief_text") or "").strip()
    if brief_text:
        lines.extend(["", brief_text])

    seed_recommended = bool(payload.get("project_seed_recommended"))
    if seed_recommended:
        lines.extend([
            "",
            "No project context or relevant memory yet. To seed source-backed project context "
            f"from this repo's docs, suggest: {display_command(['lnk', 'seed', '.', target])}",
        ])
    backlog = payload.get("backlog") if isinstance(payload.get("backlog"), Mapping) else {}
    if backlog.get("backlog"):
        lines.extend([
            "",
            (
                f"Memory backlog: {backlog.get('pending_captures', 0)} pending captures · "
                f"{backlog.get('needs_review_memories', 0)} memories need review. "
                "Offer the user a short consolidation pass this session; "
                f"{backlog.get('command')} prints a read-only plan with approve/discard commands."
            ),
        ])
    lines.extend([
        "",
        "Use this brief before asking the user to repeat durable context. "
        f"For task-specific context: {display_command(['lnk', 'query', '<topic>', target, '--budget', 'micro'])} "
        "or the Link MCP recall tool. Save durable memory only after explicit user approval.",
    ])
    return 0, "\n".join(lines)
