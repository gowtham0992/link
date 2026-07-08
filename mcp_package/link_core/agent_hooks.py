"""Agent session-hook configuration helpers for Link.

Hooks let supported agents run the Link memory loop automatically:
a session-start hook injects a bounded memory brief into new sessions,
and a session-end hook stores proposal-only session notes for review.

Supported agents differ in mechanism, so each config records its schema:
- Claude Code: nested hook groups inside `~/.claude/settings.json`;
  session-start stdout becomes model context; SessionEnd gets a transcript.
- Codex: the same nested hook schema in `~/.codex/hooks.json`; stdout becomes
  model context; there is no session-end event (Stop fires per turn, which
  would be too noisy for capture), so only session-start is installed.
- Cursor: a flat `~/.cursor/hooks.json` with `version: 1`; session-start must
  print a JSON envelope with `additional_context`; sessionEnd is fire-and-forget
  and only captures when Cursor provides a readable transcript path.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .files import atomic_write_json
from .mcp_verify import display_command

SESSION_START_TIMEOUT_SECONDS = 30
SESSION_END_TIMEOUT_SECONDS = 60

_HOOK_SCRIPT_MARKER = "link.py"


@dataclass(frozen=True)
class AgentHookConfig:
    name: str
    display_name: str
    aliases: tuple[str, ...]
    default_settings: str
    schema: str = "nested"  # "nested" (Claude Code, Codex) or "flat" (Cursor)
    start_event: str = "SessionStart"
    end_event: str | None = "SessionEnd"
    # Skip "resume": the resumed context already carries the earlier brief.
    start_matcher: str | None = "startup|clear|compact"
    start_emit: str = "text"  # "text" stdout-to-context, or "cursor" JSON envelope
    restart_hint: str = "Restart the agent; new sessions will start with the Link memory brief."


HOOK_AGENT_CONFIGS: tuple[AgentHookConfig, ...] = (
    AgentHookConfig(
        name="claude-code",
        display_name="Claude Code",
        aliases=("claude-code", "claude", "claude-code-cli"),
        default_settings="~/.claude/settings.json",
    ),
    AgentHookConfig(
        name="codex",
        display_name="Codex",
        aliases=("codex",),
        default_settings="~/.codex/hooks.json",
        end_event=None,
        restart_hint=(
            "Restart Codex and approve the hook when Codex asks you to trust it; "
            "new sessions will then start with the Link memory brief."
        ),
    ),
    AgentHookConfig(
        name="cursor",
        display_name="Cursor",
        aliases=("cursor",),
        default_settings="~/.cursor/hooks.json",
        schema="flat",
        start_event="sessionStart",
        end_event="sessionEnd",
        start_matcher=None,
        start_emit="cursor",
    ),
)


def hook_supported_agents() -> tuple[str, ...]:
    """Return canonical agent names that support `lnk connect --hooks`."""
    return tuple(config.name for config in HOOK_AGENT_CONFIGS)


def _find_hook_agent(agent: str) -> AgentHookConfig | None:
    normalized = agent.strip().lower().replace("_", "-")
    for config in HOOK_AGENT_CONFIGS:
        if normalized == config.name or normalized in config.aliases:
            return config
    return None


def supports_agent_hooks(agent: str) -> bool:
    return _find_hook_agent(agent) is not None


def _hook_agent_by_name(agent: str) -> AgentHookConfig:
    config = _find_hook_agent(agent)
    if config is not None:
        return config
    choices = ", ".join(hook_supported_agents())
    raise ValueError(f"session hooks are not supported for agent: {agent}. Try one of: {choices}")


def _settings_path(default_settings: str, override: str | None) -> Path:
    path = Path(override or default_settings).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def _hook_command(
    python_cmd: str,
    runtime_script: Path,
    event: str,
    target: Path,
    emit: str = "text",
) -> str:
    parts = [python_cmd, str(runtime_script), "hook", event, str(target)]
    if emit != "text":
        parts.extend(["--emit", emit])
    return display_command(parts)


def _nested_entry(command: str, timeout: int) -> dict[str, object]:
    return {"type": "command", "command": command, "timeout": timeout}


def _flat_entry(command: str, timeout: int) -> dict[str, object]:
    return {"command": command, "timeout": timeout}


def _is_link_hook_command(command: object, event: str) -> bool:
    if not isinstance(command, str):
        return False
    return _HOOK_SCRIPT_MARKER in command and f" hook {event}" in command


def _merge_nested_event(
    settings: dict[str, Any],
    event_name: str,
    event: str,
    entry: dict[str, object],
    matcher: str | None = None,
) -> None:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks
    groups = hooks.get(event_name)
    if not isinstance(groups, list):
        groups = []
    replaced = False
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_hooks = group.get("hooks")
        if not isinstance(group_hooks, list):
            continue
        for index, existing in enumerate(group_hooks):
            if isinstance(existing, dict) and _is_link_hook_command(existing.get("command"), event):
                group_hooks[index] = dict(entry)
                replaced = True
    if not replaced:
        group: dict[str, object] = {"hooks": [dict(entry)]}
        if matcher:
            group["matcher"] = matcher
        groups.append(group)
    hooks[event_name] = groups


def _merge_flat_event(
    settings: dict[str, Any],
    event_name: str,
    event: str,
    entry: dict[str, object],
) -> None:
    settings.setdefault("version", 1)
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks
    entries = hooks.get(event_name)
    if not isinstance(entries, list):
        entries = []
    replaced = False
    for index, existing in enumerate(entries):
        if isinstance(existing, dict) and _is_link_hook_command(existing.get("command"), event):
            entries[index] = dict(entry)
            replaced = True
    if not replaced:
        entries.append(dict(entry))
    hooks[event_name] = entries


def _event_plan(config: AgentHookConfig, python_cmd: str, runtime_script: Path, target: Path) -> list[dict[str, object]]:
    """Return the ordered event entries this agent should install."""
    make_entry = _nested_entry if config.schema == "nested" else _flat_entry
    plan: list[dict[str, object]] = [
        {
            "event_name": config.start_event,
            "event": "session-start",
            "matcher": config.start_matcher,
            "entry": make_entry(
                _hook_command(python_cmd, runtime_script, "session-start", target, emit=config.start_emit),
                SESSION_START_TIMEOUT_SECONDS,
            ),
        }
    ]
    if config.end_event:
        plan.append({
            "event_name": config.end_event,
            "event": "session-end",
            "matcher": None,
            "entry": make_entry(
                _hook_command(python_cmd, runtime_script, "session-end", target),
                SESSION_END_TIMEOUT_SECONDS,
            ),
        })
    return plan


def _hooks_snippet(config: AgentHookConfig, plan: list[dict[str, object]]) -> str:
    hooks: dict[str, object] = {}
    for item in plan:
        entry = item["entry"]
        if config.schema == "nested":
            group: dict[str, object] = {"hooks": [entry]}
            if item["matcher"]:
                group["matcher"] = item["matcher"]
            hooks[str(item["event_name"])] = [group]
        else:
            hooks[str(item["event_name"])] = [entry]
    payload: dict[str, object] = {"hooks": hooks}
    if config.schema == "flat":
        payload = {"version": 1, "hooks": hooks}
    return json.dumps(payload, indent=2)


def _write_hooks(path: Path, config: AgentHookConfig, plan: list[dict[str, object]]) -> None:
    settings: dict[str, Any] = {}
    if path.exists() and path.read_text(encoding="utf-8", errors="replace").strip():
        settings = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(settings, dict):
            raise ValueError(f"{path} must contain a JSON object")
    for item in plan:
        entry = item["entry"]
        assert isinstance(entry, dict)
        if config.schema == "nested":
            _merge_nested_event(
                settings,
                str(item["event_name"]),
                str(item["event"]),
                entry,
                matcher=item["matcher"] if isinstance(item["matcher"], str) else None,
            )
        else:
            _merge_flat_event(settings, str(item["event_name"]), str(item["event"]), entry)
    atomic_write_json(path, settings)


def build_agent_hooks_payload(
    *,
    target: Path,
    agent: str,
    runtime_script: Path,
    python_cmd: str,
    settings_path: str | None = None,
    write: bool = False,
) -> dict[str, object]:
    """Build or write session-hook configuration for a supported local agent."""
    config = _hook_agent_by_name(agent)
    path = _settings_path(config.default_settings, settings_path)
    plan = _event_plan(config, python_cmd, runtime_script, target)
    write_status: dict[str, object] = {"requested": write, "ok": False, "message": "preview only"}
    if write:
        try:
            _write_hooks(path, config, plan)
            write_status = {"requested": True, "ok": True, "message": f"updated {path}"}
        except Exception as exc:
            write_status = {"requested": True, "ok": False, "message": str(exc)}

    entry_commands = {
        str(item["event_name"]): str(item["entry"]["command"])  # type: ignore[index]
        for item in plan
    }
    behavior = [
        f"{config.start_event}: injects a bounded Link memory brief into new agent sessions.",
    ]
    if config.end_event:
        behavior.append(
            f"{config.end_event}: stores proposal-only session notes locally; durable memory still requires review."
        )
    else:
        behavior.append(
            f"{config.display_name} has no session-end hook event; end sessions with `lnk session-end` "
            "or the MCP session_end action to capture memory proposals."
        )
    if config.name in {"codex", "cursor"}:
        behavior.append(
            f"New: {config.display_name} hook support follows the vendor's documented schema; "
            "if a hook misbehaves, please open an issue."
        )

    return {
        "agent": config.name,
        "display_name": config.display_name,
        "target": str(target),
        "settings_path": str(path),
        "events": entry_commands,
        "snippet": _hooks_snippet(config, plan),
        "write": write_status,
        "behavior": behavior,
        "restart_hint": config.restart_hint,
    }


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
    return "\n".join(parts)


def extract_transcript_text(
    transcript_path: Path,
    *,
    max_chars: int = 6000,
    max_message_chars: int = 800,
) -> str:
    """Extract bounded conversation text from an agent transcript JSONL file.

    Keeps user and assistant text blocks, skips tool calls/results and meta
    entries, and returns the most recent messages within `max_chars`.
    """
    try:
        raw = transcript_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(entry, dict) or entry.get("isMeta"):
            continue
        if entry.get("type") not in {"user", "assistant"}:
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        text = _content_text(message.get("content"))
        if not text:
            continue
        if len(text) > max_message_chars:
            text = text[: max_message_chars].rstrip() + " …"
        role = "User" if entry.get("type") == "user" else "Assistant"
        lines.append(f"{role}: {text}")
    if not lines:
        return ""
    kept: list[str] = []
    total = 0
    for line in reversed(lines):
        cost = len(line) + 2
        if kept and total + cost > max_chars:
            break
        kept.append(line)
        total += cost
    return "\n\n".join(reversed(kept))
