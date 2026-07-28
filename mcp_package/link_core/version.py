"""Shared Link release version."""
from __future__ import annotations

import re
from pathlib import Path

LINK_VERSION = "2.0.0"


def workspace_runtime_version(root: Path) -> str | None:
    """Version of the runtime copy inside a workspace, or None.

    Workspaces carry their own runtime (link.py + link_core) so hooks run
    without depending on the installed package — which also means an
    upgraded install leaves workspace copies behind. Read, never import.
    """
    version_file = root / "link_core" / "version.py"
    if not (root / "link.py").exists() or not version_file.exists():
        return None
    try:
        text = version_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r'LINK_VERSION\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else None


def _version_key(version: str) -> tuple[int, ...]:
    parts = []
    for chunk in version.split("."):
        digits = re.match(r"\d+", chunk)
        parts.append(int(digits.group(0)) if digits else 0)
    return tuple(parts)


def workspace_runtime_is_older(root: Path, installed: str = LINK_VERSION) -> str | None:
    """Return the workspace runtime version when it is older than `installed`.

    Newer workspace copies (a source checkout being dogfooded) are left
    alone — only genuine post-upgrade staleness is reported.
    """
    workspace = workspace_runtime_version(root)
    if workspace and installed and _version_key(workspace) < _version_key(installed):
        return workspace
    return None
