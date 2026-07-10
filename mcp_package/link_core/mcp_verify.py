"""Shared MCP verification helpers for Link."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Callable, Mapping


PREFERRED_LINK_COMMAND = "lnk"
LEGACY_LINK_COMMAND = "link"
_link_command_override: list[str] | None = None


def set_link_command_override(parts: list[str] | tuple[str, ...] | None) -> None:
    """Override generated Link CLI commands for the current runtime."""
    global _link_command_override
    if parts is None:
        _link_command_override = None
        return
    cleaned = [str(part) for part in parts if str(part)]
    _link_command_override = cleaned or None


def _configured_link_command() -> list[str]:
    if _link_command_override:
        return list(_link_command_override)
    env_command = os.environ.get("LINK_CLI_COMMAND", "").strip()
    if env_command:
        return [env_command]
    return [PREFERRED_LINK_COMMAND]


def normalize_command_parts(parts: list[str]) -> list[str]:
    """Use Link's non-conflicting CLI command name in generated user commands."""
    if parts and parts[0] == LEGACY_LINK_COMMAND:
        return [*_configured_link_command(), *parts[1:]]
    if parts and parts[0] == PREFERRED_LINK_COMMAND and _link_command_override:
        return [*_configured_link_command(), *parts[1:]]
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


def python_is_externally_managed(python_cmd: str | None = None) -> bool:
    """PEP 668: True when the interpreter refuses direct pip installs.

    Homebrew and Debian pythons ship an EXTERNALLY-MANAGED marker; any
    guidance telling those users to `pip install` directly is dead on
    arrival — point them at Link's managed venv instead.
    """
    if python_cmd is None or python_cmd == sys.executable:
        return (Path(sysconfig.get_path("stdlib")) / "EXTERNALLY-MANAGED").exists()
    code = (
        "import sysconfig, pathlib; "
        "print((pathlib.Path(sysconfig.get_path('stdlib')) / 'EXTERNALLY-MANAGED').exists())"
    )
    try:
        result = subprocess.run(
            [python_cmd, "-c", code],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
    except OSError:
        return False
    return result.returncode == 0 and result.stdout.strip() == "True"


LINK_EXTRAS = ("semantic", "semantic-quality", "rerank")


def provision_link_extras(
    python_cmd: str,
    expected_version: str,
    *,
    extras: tuple[str, ...] = LINK_EXTRAS,
    venv_dir: Path | None = None,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, object]:
    """Install link-mcp with the given extras into Link's managed venv.

    Used when the runtime python cannot host the optional tiers itself
    (PEP 668). Returns {"ready", "python", "notes"}.
    """
    notes: list[str] = []
    venv_root = venv_dir or (Path.home() / ".link-mcp-venv")
    venv_python = default_mcp_venv_python(venv_dir)
    spec = f"link-mcp[{','.join(extras)}]=={expected_version}"
    steps: list[list[str]] = []
    if not Path(venv_python).exists():
        steps.append([python_cmd, "-m", "venv", str(venv_root)])
    steps.append([venv_python, "-m", "pip", "install", "--upgrade", "pip", spec])
    for step in steps:
        try:
            result = run(step, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except OSError as exc:
            notes.append(f"failed: {display_command(list(step))}: {exc}")
            return {"ready": False, "python": venv_python, "notes": notes}
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            notes.append(f"failed: {display_command(list(step))}: {detail[-1] if detail else 'unknown error'}")
            return {"ready": False, "python": venv_python, "notes": notes}
    notes.append(f"installed {spec} into {venv_root}")
    return {"ready": True, "python": venv_python, "notes": notes}


def default_mcp_venv_python(venv_dir: Path | None = None) -> str:
    """Path to the python inside Link's standard MCP venv (~/.link-mcp-venv)."""
    venv = venv_dir or (Path.home() / ".link-mcp-venv")
    if os.name == "nt":
        return str(venv / "Scripts" / "python.exe")
    return str(venv / "bin" / "python")


def _runtime_ready(status: Mapping[str, object], expected_version: str) -> bool:
    return (
        bool(status.get("installed"))
        and bool(status.get("mcp_sdk", status.get("installed")))
        and str(status.get("version") or "") == expected_version
    )


def ensure_link_mcp_runtime(
    python_cmd: str,
    expected_version: str,
    *,
    provision: bool = False,
    venv_dir: Path | None = None,
    import_check: Callable[[str], dict[str, object]] = check_link_mcp_import,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, object]:
    """Find or create a Python runtime whose link-mcp matches Link's version.

    Order: the configured python, then an existing ~/.link-mcp-venv, then —
    only when `provision` is set — create that venv and install the pinned
    link-mcp from PyPI. Returns {"ready", "python", "status", "provisioned",
    "notes"}; callers must not write an MCP config when ready is False.
    """
    notes: list[str] = []
    status = import_check(python_cmd)
    if _runtime_ready(status, expected_version):
        return {"ready": True, "python": python_cmd, "status": status, "provisioned": False, "notes": notes}
    notes.append(
        f"{python_cmd}: link-mcp "
        + (f"{status.get('version')} (need {expected_version})" if status.get("installed") else "not importable")
    )

    venv_python = default_mcp_venv_python(venv_dir)
    if venv_python != python_cmd and Path(venv_python).exists():
        venv_status = import_check(venv_python)
        if _runtime_ready(venv_status, expected_version):
            notes.append(f"using existing MCP venv: {venv_python}")
            return {"ready": True, "python": venv_python, "status": venv_status, "provisioned": False, "notes": notes}
        notes.append(
            f"{venv_python}: link-mcp "
            + (f"{venv_status.get('version')} (need {expected_version})" if venv_status.get("installed") else "not importable")
        )

    if not provision:
        return {"ready": False, "python": python_cmd, "status": status, "provisioned": False, "notes": notes}

    venv_root = venv_dir or (Path.home() / ".link-mcp-venv")
    steps = (
        [python_cmd, "-m", "venv", str(venv_root)],
        [venv_python, "-m", "pip", "install", "--upgrade", "pip", f"link-mcp=={expected_version}"],
    )
    for step in steps:
        try:
            result = run(step, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except OSError as exc:
            notes.append(f"provisioning failed: {display_command(list(step))}: {exc}")
            return {"ready": False, "python": python_cmd, "status": status, "provisioned": False, "notes": notes}
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            notes.append(f"provisioning failed: {display_command(list(step))}: {detail[-1] if detail else 'unknown error'}")
            return {"ready": False, "python": python_cmd, "status": status, "provisioned": False, "notes": notes}

    final_status = import_check(venv_python)
    if _runtime_ready(final_status, expected_version):
        notes.append(f"provisioned {venv_root} with link-mcp {expected_version}")
        return {"ready": True, "python": venv_python, "status": final_status, "provisioned": True, "notes": notes}
    notes.append(f"provisioned venv still not ready: {final_status.get('error') or final_status.get('version')}")
    return {"ready": False, "python": python_cmd, "status": final_status, "provisioned": True, "notes": notes}


def mcp_config(python_cmd: str, wiki_dir: Path) -> dict[str, object]:
    return {
        "mcpServers": {
            "link": {
                "command": python_cmd,
                "args": ["-m", "link_mcp", "--wiki", str(wiki_dir), "--surface", "slim"],
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
    if not import_status.get("installed"):
        normalized_import_status["externally_managed"] = python_is_externally_managed(resolved_python)
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
        if import_status.get("externally_managed"):
            # PEP 668: a direct pip install into this python would be refused.
            lines.append("  This Python refuses direct pip installs (PEP 668). Use Link's managed venv:")
            lines.append("    " + display_command(["lnk", "connect", "<agent>", ".", "--write"]) + "  # provisions ~/.link-mcp-venv automatically")
            lines.append("  Or by hand:")
            lines.append("    python3 -m venv ~/.link-mcp-venv")
            lines.append("    ~/.link-mcp-venv/bin/python -m pip install --upgrade pip link-mcp")
            lines.append("    Then rerun with: " + display_command(["lnk", "verify-mcp", ".", "--python", "~/.link-mcp-venv/bin/python"]))
        else:
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
