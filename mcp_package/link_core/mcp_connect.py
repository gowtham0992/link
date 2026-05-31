"""MCP client configuration helpers for Link."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .files import atomic_write_json, atomic_write_text
from .mcp_verify import display_command, normalize_command_parts, resolve_mcp_python


@dataclass(frozen=True)
class AgentMcpConfig:
    name: str
    display_name: str
    aliases: tuple[str, ...]
    default_config: str
    config_format: str
    top_key: str = "mcpServers"
    include_type: bool = False
    include_disabled: bool = False
    restart_hint: str = "Restart the agent, then ask: is Link ready?"


AGENT_CONFIGS: tuple[AgentMcpConfig, ...] = (
    AgentMcpConfig(
        name="codex",
        display_name="Codex",
        aliases=("codex",),
        default_config="~/.codex/config.toml",
        config_format="codex-toml",
    ),
    AgentMcpConfig(
        name="kiro",
        display_name="Kiro",
        aliases=("kiro",),
        default_config="~/.kiro/settings/mcp.json",
        config_format="json",
        include_disabled=True,
    ),
    AgentMcpConfig(
        name="claude-code",
        display_name="Claude Code",
        aliases=("claude-code", "claude", "claude-code-cli"),
        default_config="~/.claude.json",
        config_format="json",
    ),
    AgentMcpConfig(
        name="cursor",
        display_name="Cursor",
        aliases=("cursor",),
        default_config="~/.cursor/mcp.json",
        config_format="json",
    ),
    AgentMcpConfig(
        name="antigravity",
        display_name="Antigravity / Gemini CLI",
        aliases=("antigravity", "gemini", "gemini-cli"),
        default_config="~/.gemini/settings.json",
        config_format="json",
    ),
    AgentMcpConfig(
        name="vscode",
        display_name="VS Code",
        aliases=("vscode", "vs-code", "visual-studio-code"),
        default_config=".vscode/mcp.json",
        config_format="json",
        top_key="servers",
        include_type=True,
    ),
    AgentMcpConfig(
        name="copilot",
        display_name="GitHub Copilot in VS Code",
        aliases=("copilot", "github-copilot"),
        default_config=".vscode/mcp.json",
        config_format="json",
        top_key="servers",
        include_type=True,
    ),
)


def supported_agents() -> tuple[str, ...]:
    """Return canonical agent names supported by `lnk connect`."""
    return tuple(config.name for config in AGENT_CONFIGS)


def _agent_by_name(agent: str) -> AgentMcpConfig:
    normalized = agent.strip().lower().replace("_", "-")
    for config in AGENT_CONFIGS:
        if normalized == config.name or normalized in config.aliases:
            return config
    choices = ", ".join(supported_agents())
    raise ValueError(f"unsupported agent for lnk connect: {agent}. Try one of: {choices}")


def _config_path(default_config: str, override: str | None) -> Path:
    path = Path(override or default_config).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def _server_config(config: AgentMcpConfig, python_cmd: str, wiki_dir: Path) -> dict[str, object]:
    server: dict[str, object] = {
        "command": python_cmd,
        "args": ["-m", "link_mcp", "--wiki", str(wiki_dir)],
    }
    if config.include_type:
        server["type"] = "stdio"
    if config.include_disabled:
        server["disabled"] = False
    return server


def _json_config(config: AgentMcpConfig, python_cmd: str, wiki_dir: Path) -> dict[str, object]:
    return {
        config.top_key: {
            "link": _server_config(config, python_cmd, wiki_dir),
        }
    }


def _codex_toml_snippet(python_cmd: str, wiki_dir: Path) -> str:
    return "\n".join([
        "[mcp_servers.link]",
        f"command = {json.dumps(python_cmd)}",
        f'args = ["-m", "link_mcp", "--wiki", {json.dumps(str(wiki_dir))}]',
    ])


def _config_snippet(config: AgentMcpConfig, python_cmd: str, wiki_dir: Path) -> str:
    if config.config_format == "codex-toml":
        return _codex_toml_snippet(python_cmd, wiki_dir)
    return json.dumps(_json_config(config, python_cmd, wiki_dir), indent=2)


def _write_json_config(path: Path, config: AgentMcpConfig, python_cmd: str, wiki_dir: Path) -> None:
    payload: dict[str, Any] = {}
    if path.exists() and path.read_text(encoding="utf-8", errors="replace").strip():
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(payload, dict):
            raise ValueError(f"{path} must contain a JSON object")
    existing = payload.get(config.top_key)
    if not isinstance(existing, dict):
        existing = {}
    existing["link"] = _server_config(config, python_cmd, wiki_dir)
    payload[config.top_key] = existing
    atomic_write_json(path, payload)


def _write_codex_config(path: Path, python_cmd: str, wiki_dir: Path) -> None:
    block = _codex_toml_snippet(python_cmd, wiki_dir) + "\n"
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    pattern = re.compile(r"(?ms)^\[mcp_servers\.link\]\r?\n.*?(?=^\[|\Z)")
    if pattern.search(text):
        text = pattern.sub(block, text)
        if not text.endswith("\n"):
            text += "\n"
    else:
        text = text.rstrip() + ("\n\n" if text.strip() else "") + block
    atomic_write_text(path, text)


def _write_config(path: Path, config: AgentMcpConfig, python_cmd: str, wiki_dir: Path) -> None:
    if config.config_format == "codex-toml":
        _write_codex_config(path, python_cmd, wiki_dir)
        return
    _write_json_config(path, config, python_cmd, wiki_dir)


def build_mcp_connect_payload(
    *,
    target: Path,
    wiki_dir: Path,
    agent: str,
    expected_version: str,
    init_command: list[str],
    python_cmd: str | None = None,
    default_python: str,
    config_path: str | None = None,
    write: bool = False,
) -> dict[str, object]:
    """Build or write an MCP client configuration for a supported local agent."""
    config = _agent_by_name(agent)
    resolved_python = resolve_mcp_python(target, wiki_dir, python_cmd, default_python=default_python)
    path = _config_path(config.default_config, config_path)
    snippet = _config_snippet(config, resolved_python, wiki_dir)
    write_status: dict[str, object] = {"requested": write, "ok": False, "message": "preview only"}
    if write:
        try:
            _write_config(path, config, resolved_python, wiki_dir)
            write_status = {"requested": True, "ok": True, "message": f"updated {path}"}
        except Exception as exc:
            write_status = {"requested": True, "ok": False, "message": str(exc)}

    connect_command = ["lnk", "connect", config.name, str(target)]
    if config_path:
        connect_command.extend(["--config", str(path)])
    if python_cmd:
        connect_command.extend(["--python", resolved_python])
    connect_command.append("--write")

    return {
        "agent": config.name,
        "display_name": config.display_name,
        "target": str(target),
        "wiki": str(wiki_dir),
        "python": resolved_python,
        "expected_version": expected_version,
        "config_path": str(path),
        "config_format": config.config_format,
        "config": _json_config(config, resolved_python, wiki_dir) if config.config_format == "json" else None,
        "snippet": snippet,
        "write": write_status,
        "next_actions": [
            {
                "label": "write config",
                "command": connect_command,
                "command_text": display_command(connect_command),
            },
            {
                "label": "verify MCP runtime",
                "command": ["lnk", "verify-mcp", str(target), "--python", resolved_python],
                "command_text": display_command(["lnk", "verify-mcp", str(target), "--python", resolved_python]),
            },
            {
                "label": "create wiki if missing",
                "command": normalize_command_parts(init_command),
                "command_text": display_command(init_command),
            },
        ],
        "restart_hint": config.restart_hint,
    }
