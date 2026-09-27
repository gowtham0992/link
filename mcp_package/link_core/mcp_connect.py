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
    # Extra fixed keys some clients require on each server entry
    # (e.g. Zed's context_servers need "source": "custom").
    extra_entry_keys: tuple[tuple[str, str], ...] = ()
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
        name="windsurf",
        display_name="Windsurf",
        aliases=("windsurf", "codeium"),
        default_config="~/.codeium/windsurf/mcp_config.json",
        config_format="json",
    ),
    AgentMcpConfig(
        name="zed",
        display_name="Zed",
        aliases=("zed",),
        default_config="~/.config/zed/settings.json",
        config_format="json",
        top_key="context_servers",
        extra_entry_keys=(("source", "custom"),),
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


def detect_installed_agents(home: Path | None = None) -> list[str]:
    """Agents whose config footprint exists on this machine.

    Powers `lnk setup`: one command wires every agent the user actually
    has, instead of asking them to name each one. Only agents with a
    global (home-relative) config participate — project-scoped configs
    (.vscode) need explicit intent.
    """
    base = (home or Path.home()).expanduser()
    detected: list[str] = []
    for config in AGENT_CONFIGS:
        default = str(config.default_config)
        if not default.startswith("~/"):
            continue
        path = base / default[2:]
        probes = [path]
        if path.parent != base:
            probes.append(path.parent)
        if config.name == "claude-code":
            probes.append(base / ".claude")
        if any(probe.exists() for probe in probes):
            detected.append(config.name)
    return detected


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
    for key, value in config.extra_entry_keys:
        server[key] = value
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


# ── JSON with comments ──────────────────────────────────────────────────
# VS Code and Zed settings are JSONC: // and /* */ comments, trailing commas.
# json.loads rejected them, so `connect --write` failed on exactly the files
# people most often have. Rewriting them as plain JSON would delete every
# comment in someone's editor settings, so the edit is a splice: the file is
# parsed with comments stripped to decide what to do, then only the `link`
# entry is inserted or replaced in the original text, and the result is
# re-parsed to prove it says what was intended before it is written.


def _jsonc_mask(text: str) -> str:
    """Same length as text, with comments blanked out (strings untouched)."""
    out = list(text)
    i, n = 0, len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif text.startswith("//", i):
            end = text.find("\n", i)
            end = n if end < 0 else end
            for j in range(i, end):
                out[j] = " "
            i = end
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            for j in range(i, end):
                if out[j] != "\n":
                    out[j] = " "
            i = end
            continue
        i += 1
    return "".join(out)


_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _jsonc_loads(text: str) -> object:
    masked = _jsonc_mask(text)
    # Trailing commas: remove only those outside strings. The mask keeps
    # strings, so re-scan the masked text and drop commas before } or ].
    cleaned = _strip_trailing_commas(masked)
    return json.loads(cleaned)


def _strip_trailing_commas(masked: str) -> str:
    out = []
    in_string = False
    i, n = 0, len(masked)
    while i < n:
        ch = masked[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(masked[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
            out.append(ch)
        elif ch == ",":
            j = i + 1
            while j < n and masked[j].isspace():
                j += 1
            if j < n and masked[j] in "}]":
                i += 1
                continue
            out.append(ch)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _structural_positions(masked: str) -> list[tuple[int, str, int]]:
    """(index, char, depth-before) for every structural char outside strings."""
    positions: list[tuple[int, str, int]] = []
    depth = 0
    in_string = False
    i, n = 0, len(masked)
    while i < n:
        ch = masked[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_string = False
                positions.append((i, '"end', depth))
        elif ch == '"':
            in_string = True
            positions.append((i, '"start', depth))
        elif ch in "{[":
            positions.append((i, ch, depth))
            depth += 1
        elif ch in "}]":
            depth -= 1
            positions.append((i, ch, depth))
        elif ch in ",:":
            positions.append((i, ch, depth))
        i += 1
    return positions


def _find_key_value(masked: str, key: str, container_open: int) -> tuple[int, int] | None:
    """Span [start, end) of the value of `key` directly inside the object at container_open."""
    positions = _structural_positions(masked)
    start_depth = next(d for idx, ch, d in positions if idx == container_open) + 1
    after = [item for item in positions if item[0] > container_open]
    for index, (idx, ch, depth) in enumerate(after):
        if ch == "}" and depth == start_depth - 1:
            return None
        if ch == '"start' and depth == start_depth:
            end_quote = after[index + 1][0]
            name = json.loads(masked[idx:end_quote + 1])
            colon = after[index + 2]
            if colon[1] != ":":
                continue
            if name != key:
                continue
            value_start = colon[0] + 1
            while masked[value_start].isspace():
                value_start += 1
            if masked[value_start] not in "{[":
                end = value_start
                while masked[end] not in ",}":
                    end += 1
                return value_start, end
            level = 0
            for jdx, jch, _ in positions:
                if jdx < value_start:
                    continue
                if jch in "{[":
                    level += 1
                elif jch in "}]":
                    level -= 1
                    if level == 0:
                        return value_start, jdx + 1
    return None


def _find_member_start(masked: str, key: str, container_open: int) -> int | None:
    """Index of the opening quote of `key` directly inside the object."""
    positions = _structural_positions(masked)
    start_depth = next(d for idx, ch, d in positions if idx == container_open) + 1
    after = [item for item in positions if item[0] > container_open]
    for index, (idx, ch, depth) in enumerate(after):
        if ch == "}" and depth == start_depth - 1:
            return None
        if ch == '"start' and depth == start_depth and index + 2 < len(after) and after[index + 2][1] == ":":
            if json.loads(masked[idx:after[index + 1][0] + 1]) == key:
                return idx
    return None


def _remove_link_entry(text: str, top_key: str) -> tuple[str, bool]:
    """Remove top_key.link from JSON(C) text, keeping everything else."""
    masked = _jsonc_mask(text)
    first = next((i for i, ch in enumerate(masked) if not ch.isspace()), -1)
    if first < 0 or masked[first] != "{":
        return text, False
    top_span = _find_key_value(masked, top_key, first)
    if top_span is None or masked[top_span[0]] != "{":
        return text, False
    link_span = _find_key_value(masked, "link", top_span[0])
    key_start = _find_member_start(masked, "link", top_span[0])
    if link_span is None or key_start is None:
        return text, False
    start, end = key_start, link_span[1]
    back = start - 1
    while back > top_span[0] and masked[back].isspace():
        back -= 1
    if masked[back] == ",":
        start = back  # drop the comma that separated us from the previous member
    else:
        fwd = end
        while fwd < len(masked) and masked[fwd].isspace():
            fwd += 1
        if fwd < len(masked) and masked[fwd] == ",":
            end = fwd + 1  # first member: drop the comma after us instead
    return text[:start] + text[end:], True


def remove_link_mcp_entry(path: Path, config: "AgentMcpConfig", *, write: bool) -> dict[str, object]:
    """Find (and with write, remove) Link's server entry from an agent config."""
    result: dict[str, object] = {"path": str(path), "found": False, "removed": False}
    if not path.exists():
        return result
    text = path.read_text(encoding="utf-8", errors="replace")
    if config.config_format == "codex-toml":
        pattern = re.compile(r"(?ms)^\[mcp_servers\.link\]\r?\n.*?(?=^\[|\Z)")
        if not pattern.search(text):
            return result
        result["found"] = True
        if write:
            updated = pattern.sub("", text).rstrip() + "\n"
            atomic_write_text(path, updated if updated.strip() else "")
            result["removed"] = True
        return result
    updated, found = _remove_link_entry(text, config.top_key)
    result["found"] = found
    if found and write:
        check = _jsonc_loads(updated)
        if not isinstance(check, dict) or "link" in (check.get(config.top_key) or {}):
            raise ValueError(f"could not edit {path} safely; remove the link entry by hand")
        atomic_write_text(path, updated)
        result["removed"] = True
    return result


def _object_is_empty(masked: str, open_index: int) -> bool:
    j = open_index + 1
    while j < len(masked) and masked[j].isspace():
        j += 1
    return j < len(masked) and masked[j] == "}"


def _indent_block(text: str, indent: str) -> str:
    return text.replace("\n", "\n" + indent)


def _splice_link_entry(text: str, top_key: str, entry: dict[str, object]) -> str:
    """Insert or replace top_key.link in JSON(C) text, keeping everything else."""
    masked = _jsonc_mask(text)
    first = next((i for i, ch in enumerate(masked) if not ch.isspace()), -1)
    if first < 0 or masked[first] != "{":
        raise ValueError("config must contain a JSON object")
    entry_json = json.dumps(entry, indent=2)
    top_span = _find_key_value(masked, top_key, first)
    if top_span is None:
        block = f'\n  {json.dumps(top_key)}: {{\n    "link": {_indent_block(entry_json, "    ")}\n  }}'
        comma = "" if _object_is_empty(masked, first) else ","
        return text[: first + 1] + block + comma + text[first + 1:]
    start, end = top_span
    if masked[start] != "{":
        raise ValueError(f"{top_key} must be a JSON object")
    link_span = _find_key_value(masked, "link", start)
    if link_span is None:
        comma = "" if _object_is_empty(masked, start) else ","
        block = f'\n    "link": {_indent_block(entry_json, "    ")}'
        return text[: start + 1] + block + comma + text[start + 1:]
    link_start, link_end = link_span
    return text[:link_start] + _indent_block(entry_json, "    ") + text[link_end:]


def _write_json_config(path: Path, config: AgentMcpConfig, python_cmd: str, wiki_dir: Path) -> None:
    entry = _server_config(config, python_cmd, wiki_dir)
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    if not text.strip():
        atomic_write_json(path, {config.top_key: {"link": entry}})
        return
    try:
        payload = _jsonc_loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON or JSONC ({exc.msg} at line {exc.lineno}); "
                         "fix it, or add the snippet below by hand") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    updated = _splice_link_entry(text, config.top_key, entry)
    try:
        check = _jsonc_loads(updated)
    except json.JSONDecodeError as exc:
        raise ValueError(f"could not edit {path} safely ({exc.msg}); add the snippet below by hand") from exc
    if not isinstance(check, dict) or check.get(config.top_key, {}).get("link") != entry:
        raise ValueError(f"could not edit {path} safely; add the snippet below by hand")
    atomic_write_text(path, updated)


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
            payload = _jsonc_loads(text)
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


def build_disconnect_payload(
    agent: str,
    *,
    config_path: str | None = None,
    hooks_settings: str | None = None,
    write: bool = False,
) -> dict[str, object]:
    """Preview (or with write, perform) removing Link from one agent.

    Uninstalling used to leave the MCP entry and the session hooks behind;
    after the workspace was deleted, every new Claude Code session printed
    "wiki missing" into the model's context. This removes only Link's
    entries - other servers, other hooks and the file's comments stay.
    """
    from .agent_hooks import _find_hook_agent, _settings_path, remove_link_hooks

    config = _agent_by_name(agent)
    mcp_path = _config_path(config.default_config, config_path)
    mcp = remove_link_mcp_entry(mcp_path, config, write=write)
    hook_config = _find_hook_agent(config.name)
    hooks: dict[str, object] = {"supported": False, "found": [], "removed": False}
    if hook_config is not None:
        hooks = remove_link_hooks(_settings_path(hook_config.default_settings, hooks_settings), config.name, write=write)
    found_anything = bool(mcp.get("found")) or bool(hooks.get("found"))
    return {
        "agent": config.name,
        "display_name": config.display_name,
        "write": write,
        "mcp": mcp,
        "hooks": hooks,
        "found": found_anything,
        "changed": bool(mcp.get("removed")) or bool(hooks.get("removed")),
        "restart_hint": f"Restart {config.display_name} so it stops loading Link.",
    }
