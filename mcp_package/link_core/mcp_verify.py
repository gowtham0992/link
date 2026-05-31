"""Shared MCP verification helpers for Link."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Callable, Mapping


PREFERRED_LINK_COMMAND = "lnk"
LEGACY_LINK_COMMAND = "link"


def normalize_command_parts(parts: list[str]) -> list[str]:
    """Use Link's non-conflicting CLI command name in generated user commands."""
    if parts and parts[0] == LEGACY_LINK_COMMAND:
        return [PREFERRED_LINK_COMMAND, *parts[1:]]
    return list(parts)


def display_command(parts: list[str]) -> str:
    """Return a shell-safe command for the current platform."""
    parts = normalize_command_parts(parts)
    if os.name == "nt":
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)


def mcp_verify_action(tool: str, label: str, command: list[str]) -> dict[str, object]:
    command = normalize_command_parts(command)
    return {
        "tool": tool,
        "label": label,
        "command": command,
        "command_text": display_command(command),
    }


def check_link_mcp_import(python_cmd: str) -> dict[str, object]:
    """Check whether link-mcp and its MCP SDK dependency import in a Python runtime."""
    code = (
        "import json\n"
        "status = {'installed': False, 'version': None, 'mcp_sdk': False, 'error': None}\n"
        "try:\n"
        "    import link_mcp\n"
        "    status['installed'] = True\n"
        "    status['version'] = getattr(link_mcp, '__version__', 'unknown')\n"
        "    from mcp.server.fastmcp import FastMCP\n"
        "    status['mcp_sdk'] = True\n"
        "except Exception as exc:\n"
        "    status['error'] = str(exc)\n"
        "print(json.dumps(status))\n"
    )
    try:
        result = subprocess.run(
            [python_cmd, "-c", code],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        return {"installed": False, "version": None, "error": str(exc)}
    if result.returncode != 0:
        error = (result.stderr or result.stdout).strip()
        return {"installed": False, "version": None, "error": error}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"installed": False, "version": None, "error": "could not parse link_mcp import output"}
    return {
        "installed": bool(data.get("installed")),
        "version": data.get("version") or "unknown",
        "mcp_sdk": bool(data.get("mcp_sdk")),
        "error": data.get("error"),
    }


def mcp_config(python_cmd: str, wiki_dir: Path) -> dict[str, object]:
    return {
        "mcpServers": {
            "link": {
                "command": python_cmd,
                "args": ["-m", "link_mcp", "--wiki", str(wiki_dir)],
            }
        }
    }


def expand_command_prefix(command: str) -> str:
    """Expand a leading home shortcut without normalizing command path syntax."""
    if command == "~" or command.startswith("~/") or command.startswith("~\\"):
        return str(Path(command).expanduser())
    return command


def resolve_mcp_python(target: Path, wiki_dir: Path, python_cmd: str | None, *, default_python: str) -> str:
    if python_cmd:
        return expand_command_prefix(python_cmd)

    root = wiki_dir.parent if wiki_dir.name == "wiki" else target
    marker = root / ".link-mcp-python"
    if marker.exists():
        configured = marker.read_text(encoding="utf-8", errors="replace").strip()
        if configured:
            return expand_command_prefix(configured)

    return default_python


def build_mcp_verify_status(
    *,
    target: Path,
    wiki_dir: Path,
    expected_version: str,
    init_command: list[str],
    python_cmd: str | None = None,
    default_python: str,
    import_check: Callable[[str], dict[str, object]] = check_link_mcp_import,
) -> dict[str, object]:
    resolved_python = resolve_mcp_python(target, wiki_dir, python_cmd, default_python=default_python)
    import_status = import_check(resolved_python)
    wiki_exists = wiki_dir.exists() and wiki_dir.is_dir()
    installed_version = str(import_status.get("version") or "")
    mcp_sdk_ready = bool(import_status.get("mcp_sdk", import_status.get("installed")))
    version_matches = bool(import_status.get("installed")) and installed_version == expected_version
    ready = bool(import_status.get("installed")) and mcp_sdk_ready and wiki_exists and version_matches
    normalized_import_status = dict(import_status)
    normalized_import_status.setdefault("mcp_sdk", mcp_sdk_ready)
    normalized_import_status.setdefault("error", None)
    issues, next_actions = mcp_verify_guidance(
        target=target,
        init_command=init_command,
        expected_version=expected_version,
        python_cmd=resolved_python,
        import_status=normalized_import_status,
        mcp_sdk_ready=mcp_sdk_ready,
        version_matches=version_matches,
        wiki_exists=wiki_exists,
    )
    return {
        "ready": ready,
        "target": str(target),
        "python": resolved_python,
        "expected_version": expected_version,
        "version_matches": version_matches,
        "link_mcp": normalized_import_status,
        "wiki": {
            "path": str(wiki_dir),
            "exists": wiki_exists,
        },
        "config": mcp_config(resolved_python, wiki_dir),
        "issues": issues,
        "next_actions": next_actions,
    }


def mcp_verify_guidance(
    *,
    target: Path,
    init_command: list[str],
    expected_version: str,
    python_cmd: str,
    import_status: Mapping[str, object],
    mcp_sdk_ready: bool,
    version_matches: bool,
    wiki_exists: bool,
) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    """Build structured MCP setup issues and repair actions."""
    installed = bool(import_status.get("installed"))
    issues: list[dict[str, str]] = []
    next_actions: list[dict[str, object]] = []

    if not installed:
        issues.append({
            "code": "link_mcp_missing",
            "message": "link-mcp is not importable from the configured Python.",
        })
        next_actions.append(
            mcp_verify_action(
                "install_link_mcp",
                "Install link-mcp in the configured Python environment",
                [python_cmd, "-m", "pip", "install", "--upgrade", "link-mcp"],
            )
        )
    else:
        if not mcp_sdk_ready:
            issues.append({
                "code": "mcp_sdk_missing",
                "message": "link-mcp is installed, but the MCP SDK dependency is missing.",
            })
            next_actions.append(
                mcp_verify_action(
                    "reinstall_link_mcp",
                    f"Reinstall link-mcp dependencies for Link {expected_version}",
                    [python_cmd, "-m", "pip", "install", "--upgrade", f"link-mcp=={expected_version}"],
                )
            )
        if not version_matches:
            issues.append({"code": "version_mismatch", "message": f"link-mcp must match Link {expected_version}."})
            next_actions.append(
                mcp_verify_action(
                    "upgrade_link_mcp",
                    f"Upgrade link-mcp to Link {expected_version}",
                    [python_cmd, "-m", "pip", "install", "--upgrade", f"link-mcp=={expected_version}"],
                )
            )
    if not wiki_exists:
        issues.append({
            "code": "wiki_missing",
            "message": "The configured Link wiki directory does not exist.",
        })
        next_actions.append(
            mcp_verify_action(
                "init_wiki",
                "Create or repair the local Link wiki",
                init_command,
            )
        )

    return issues, next_actions


def _action_by_tool(status: Mapping[str, object], tool: str) -> Mapping[str, object]:
    actions = status.get("next_actions") if isinstance(status.get("next_actions"), list) else []
    for action in actions:
        if isinstance(action, Mapping) and action.get("tool") == tool:
            return action
    return {}


def render_mcp_verify_text(status: Mapping[str, object]) -> tuple[int, str]:
    """Render human-readable MCP verification output and return exit code."""
    import_status = status.get("link_mcp") if isinstance(status.get("link_mcp"), Mapping) else {}
    wiki = status.get("wiki") if isinstance(status.get("wiki"), Mapping) else {}
    config = status.get("config") if isinstance(status.get("config"), Mapping) else {}
    ready = bool(status.get("ready"))
    expected_version = str(status.get("expected_version") or "")
    python_cmd = str(status.get("python") or "")
    wiki_path = str(wiki.get("path") or "")
    wiki_exists = bool(wiki.get("exists"))
    installed = bool(import_status.get("installed"))
    mcp_sdk_ready = bool(import_status.get("mcp_sdk", installed))
    version_matches = bool(status.get("version_matches"))

    lines = [
        f"Link MCP verification: {status.get('target', '')}",
        "",
        f"Python: {python_cmd}",
    ]
    if installed:
        lines.append(f"link-mcp: installed ({import_status.get('version')})")
        if not mcp_sdk_ready:
            lines.append("MCP SDK: missing")
            error = import_status.get("error")
            if error:
                lines.append(f"Import error: {error}")
        if not version_matches:
            lines.append(f"Expected version: {expected_version}")
    else:
        lines.append("link-mcp: missing")
        error = import_status.get("error")
        if error:
            lines.append(f"Import error: {error}")
    lines.append(f"Wiki: {'found' if wiki_exists else 'missing'} ({wiki_path})")
    lines.extend(["", "MCP config:", json.dumps(config, indent=2)])

    if ready:
        lines.extend(["", "Result: ready"])
        return 0, "\n".join(lines)

    lines.extend(["", "Next:"])
    if not installed:
        action = _action_by_tool(status, "install_link_mcp")
        lines.append(f"  Install: {action.get('command_text') or display_command([python_cmd, '-m', 'pip', 'install', '--upgrade', 'link-mcp'])}")
        lines.append("  macOS/Homebrew fallback:")
        lines.append("    python3 -m venv ~/.link-mcp-venv")
        lines.append("    ~/.link-mcp-venv/bin/python -m pip install --upgrade pip link-mcp")
        lines.append("    Then rerun with: python3 link.py verify-mcp . --python ~/.link-mcp-venv/bin/python")
    elif not mcp_sdk_ready:
        action = _action_by_tool(status, "reinstall_link_mcp")
        lines.append(f"  Reinstall link-mcp dependencies for Link {expected_version}:")
        lines.append(f"    {action.get('command_text')}")
    elif not version_matches:
        action = _action_by_tool(status, "upgrade_link_mcp")
        lines.append(f"  Upgrade link-mcp to match Link {expected_version}:")
        lines.append(f"    {action.get('command_text')}")
    if not wiki_exists:
        lines.append("  Create a wiki with an installer, or try: python3 link.py init")
    lines.extend(["", "Result: needs attention"])
    return 1, "\n".join(lines)
