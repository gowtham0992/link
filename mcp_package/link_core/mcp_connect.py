"""MCP client configuration helpers for Link."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .files import atomic_write_json, atomic_write_text
from .mcp_verify import (
    display_command,
    ensure_link_mcp_runtime,
    normalize_command_parts,
    resolve_mcp_python,
)


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
        "args": ["-m", "link_mcp", "--wiki", str(wiki_dir), "--surface", "slim"],
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
        f'args = ["-m", "link_mcp", "--wiki", {json.dumps(str(wiki_dir))}, "--surface", "slim"]',
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


def agent_alias_matches(name: str) -> bool:
    """True when the string names a supported agent (canonical or alias)."""
    normalized = name.strip().lower().replace("_", "-")
    return any(
        normalized == config.name or normalized in config.aliases
        for config in AGENT_CONFIGS
    )


def read_agent_link_server(agent: str, config_path: str | None = None) -> dict[str, object]:
    """Read the Link MCP server an agent is actually configured to run.

    Returns {"agent", "display_name", "config_path", "configured", "python",
    "wiki"}. `configured` is False when the config file or its link server
    entry is missing — the caller should point at `lnk connect`.
    """
    config = _agent_by_name(agent)
    path = _config_path(config.default_config, config_path)
    result: dict[str, object] = {
        "agent": config.name,
        "display_name": config.display_name,
        "config_path": str(path),
        "configured": False,
        "python": None,
        "wiki": None,
    }
    if not path.exists():
        return result
    text = path.read_text(encoding="utf-8", errors="replace")
    command: str | None = None
    args: list[str] = []
    if config.config_format == "codex-toml":
        block = re.search(r"(?ms)^\[mcp_servers\.link\]\r?\n(.*?)(?=^\[|\Z)", text)
        if not block:
            return result
        command_match = re.search(r'(?m)^command\s*=\s*"((?:[^"\\]|\\.)*)"', block.group(1))
        args_match = re.search(r"(?m)^args\s*=\s*(\[.*\])", block.group(1))
        if command_match:
            command = json.loads(f'"{command_match.group(1)}"')
        if args_match:
            try:
                args = [str(item) for item in json.loads(args_match.group(1))]
            except json.JSONDecodeError:
                args = []
    else:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return result
        server = payload.get(config.top_key, {}).get("link") if isinstance(payload, dict) else None
        if not isinstance(server, dict):
            return result
        command = str(server.get("command") or "") or None
        raw_args = server.get("args")
        args = [str(item) for item in raw_args] if isinstance(raw_args, list) else []
    if not command:
        return result
    wiki = None
    for index, item in enumerate(args):
        if item == "--wiki" and index + 1 < len(args):
            wiki = args[index + 1]
            break
    result.update({"configured": True, "python": command, "wiki": wiki})
    return result


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
    runtime_check: Any = ensure_link_mcp_runtime,
) -> dict[str, object]:
    """Build or write an MCP client configuration for a supported local agent.

    Before writing, the chosen Python is verified to actually serve link-mcp
    at Link's version; if it cannot, Link falls back to (or provisions)
    ~/.link-mcp-venv rather than writing a config the agent cannot start.
    """
    config = _agent_by_name(agent)
    resolved_python = resolve_mcp_python(target, wiki_dir, python_cmd, default_python=default_python)
    runtime = runtime_check(resolved_python, expected_version, provision=write)
    runtime_ready = bool(runtime.get("ready"))
    chosen_python = str(runtime.get("python") or resolved_python)
    if runtime_ready and chosen_python != resolved_python:
        resolved_python = chosen_python
        root = wiki_dir.parent if wiki_dir.name == "wiki" else target
        if write:
            try:
                atomic_write_text(root / ".link-mcp-python", resolved_python + "\n")
            except OSError:
                pass
    path = _config_path(config.default_config, config_path)
    snippet = _config_snippet(config, resolved_python, wiki_dir)
    write_status: dict[str, object] = {"requested": write, "ok": False, "message": "preview only"}
    if write and not runtime_ready:
        fix = display_command([resolved_python, "-m", "pip", "install", "--upgrade", f"link-mcp=={expected_version}"])
        write_status = {
            "requested": True,
            "ok": False,
            "message": (
                f"not written: {resolved_python} cannot serve link-mcp {expected_version} "
                f"and provisioning ~/.link-mcp-venv failed. Fix the runtime first: {fix}"
            ),
        }
    elif write:
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
        "mcp_runtime": {
            "ready": runtime_ready,
            "provisioned": bool(runtime.get("provisioned")),
            "link_mcp": runtime.get("status"),
            "notes": runtime.get("notes", []),
        },
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
