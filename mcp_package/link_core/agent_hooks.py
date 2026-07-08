"""Agent session-hook configuration helpers for Link.

Hooks let supported agents run the Link memory loop automatically:
a session-start hook injects a bounded memory brief into new sessions,
and a session-end hook stores proposal-only session notes for review.
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
    start_event: str = "SessionStart"
    end_event: str = "SessionEnd"
    # Skip "resume": the resumed context already carries the earlier brief.
    start_matcher: str = "startup|clear|compact"
    restart_hint: str = "Restart the agent; new sessions will start with the Link memory brief."


HOOK_AGENT_CONFIGS: tuple[AgentHookConfig, ...] = (
    AgentHookConfig(
        name="claude-code",
        display_name="Claude Code",
        aliases=("claude-code", "claude", "claude-code-cli"),
        default_settings="~/.claude/settings.json",
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


def _hook_command(python_cmd: str, runtime_script: Path, event: str, target: Path) -> str:
    return display_command([python_cmd, str(runtime_script), "hook", event, str(target)])


def _hook_entry(command: str, timeout: int) -> dict[str, object]:
    return {"type": "command", "command": command, "timeout": timeout}


def _is_link_hook_command(command: object, event: str) -> bool:
    if not isinstance(command, str):
        return False
    return _HOOK_SCRIPT_MARKER in command and f" hook {event}" in command


def _merge_hook_event(
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


def _hooks_snippet(config: AgentHookConfig, start_entry: dict[str, object], end_entry: dict[str, object]) -> str:
    return json.dumps(
        {
            "hooks": {
                config.start_event: [{"matcher": config.start_matcher, "hooks": [start_entry]}],
                config.end_event: [{"hooks": [end_entry]}],
            }
        },
        indent=2,
    )


def _write_hooks(
    path: Path,
    config: AgentHookConfig,
    start_entry: dict[str, object],
    end_entry: dict[str, object],
) -> None:
    settings: dict[str, Any] = {}
    if path.exists() and path.read_text(encoding="utf-8", errors="replace").strip():
        settings = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(settings, dict):
            raise ValueError(f"{path} must contain a JSON object")
    _merge_hook_event(settings, config.start_event, "session-start", start_entry, matcher=config.start_matcher)
    _merge_hook_event(settings, config.end_event, "session-end", end_entry)
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
    start_command = _hook_command(python_cmd, runtime_script, "session-start", target)
    end_command = _hook_command(python_cmd, runtime_script, "session-end", target)
    start_entry = _hook_entry(start_command, SESSION_START_TIMEOUT_SECONDS)
    end_entry = _hook_entry(end_command, SESSION_END_TIMEOUT_SECONDS)
    write_status: dict[str, object] = {"requested": write, "ok": False, "message": "preview only"}
    if write:
        try:
            _write_hooks(path, config, start_entry, end_entry)
            write_status = {"requested": True, "ok": True, "message": f"updated {path}"}
        except Exception as exc:
            write_status = {"requested": True, "ok": False, "message": str(exc)}

    return {
        "agent": config.name,
        "display_name": config.display_name,
        "target": str(target),
        "settings_path": str(path),
        "events": {
            config.start_event: start_command,
            config.end_event: end_command,
        },
        "snippet": _hooks_snippet(config, start_entry, end_entry),
        "write": write_status,
        "behavior": [
            f"{config.start_event}: injects a bounded Link memory brief into new agent sessions.",
            f"{config.end_event}: stores proposal-only session notes locally; durable memory still requires review.",
        ],
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
