"""TTY-only styling for Link's human CLI output."""
from __future__ import annotations

import os
import re
import sys
from typing import TextIO

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"


def supports_color(stream: TextIO | None = None) -> bool:
    """Return whether human CLI output should include ANSI styling."""
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR") or os.environ.get("LINK_PLAIN"):
        return False
    if os.environ.get("CLICOLOR") == "0":
        return False
    if os.environ.get("TERM", "").lower() == "dumb":
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def _wrap(text: str, *codes: str) -> str:
    return "".join(codes) + text + RESET


def style_cli_text(text: str, *, stream: TextIO | None = None) -> str:
    """Apply light product styling to human-readable CLI output.

    The function is deliberately conservative: it only styles whole lines and
    only when stdout is a TTY. JSON output and captured test output stay plain.
    """
    if not supports_color(stream):
        return text
    styled: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            styled.append(line)
        elif re.match(r"^(Link|No Link)\b", stripped):
            styled.append(_wrap(line, BOLD, CYAN))
        elif stripped in {"Next:", "Warnings:", "Errors:", "Fixes applied:", "Suggested workflow:"}:
            styled.append(_wrap(line, BOLD))
        elif stripped.startswith("OK ") or stripped in {"Result: healthy", "Result: passed", "Result: ready"}:
            styled.append(_wrap(line, GREEN))
        elif stripped.startswith("WARNING") or stripped.startswith("Warning") or stripped.startswith("- search_backend_fallback"):
            styled.append(_wrap(line, YELLOW))
        elif stripped.startswith("ERROR") or stripped.startswith("Error") or "Result: failed" in stripped:
            styled.append(_wrap(line, RED))
        elif stripped.startswith("Ready: yes") or " validation passed" in stripped:
            styled.append(_wrap(line, GREEN))
        elif stripped.startswith("Ready: no") or "needs attention" in stripped:
            styled.append(_wrap(line, YELLOW))
        elif stripped.startswith(("lnk ", "python3 ", "py ", "brew ", "bash ", "http://", "https://")):
            styled.append(_wrap(line, CYAN))
        elif line.startswith("  ") and stripped:
            styled.append(_wrap(line, DIM))
        else:
            styled.append(line)
    return "\n".join(styled)
