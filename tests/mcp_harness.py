"""Drive the MCP server against a temp workspace, and always close it.

A recall builds the persistent FTS index under `.link-cache/`, which
holds an open SQLite handle. POSIX happily unlinks open files, so a test
that leaves the cache open still cleans up locally - on Windows the same
test fails at `TemporaryDirectory` teardown with

    PermissionError: [WinError 32] The process cannot access the file
    because it is being used by another process: ...page-fts-v1.sqlite

which is a platform-only failure invisible to everyone developing on
macOS or Linux. Using this context manager makes the close automatic, so
the next MCP test cannot reintroduce it by forgetting.
"""
from __future__ import annotations

import contextlib
import importlib
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any


@contextlib.contextmanager
def mcp_server(workspace: Path, surface: str = "slim") -> Iterator[Any]:
    """Reload link_mcp.server bound to `workspace/wiki`; close on exit."""
    saved_argv = list(sys.argv)
    sys.argv = ["link_mcp", "--wiki", str(Path(workspace) / "wiki"), "--surface", surface]
    import link_mcp.server as server

    importlib.reload(server)
    try:
        yield server
    finally:
        sys.argv = saved_argv
        try:
            server._clear_cache()
        except Exception:
            pass
