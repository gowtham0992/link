"""Shared Link log helpers."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from .files import append_text_with_rotation, atomic_write_text

DEFAULT_LOG_TEXT = "# Link Wiki Log\n\n*Append-only record of wiki operations.*\n"
DEFAULT_LOG_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_LOG_BACKUPS = 5
LOG_HEADING_RE = re.compile(r"^## \[(?P<timestamp>[^\]]+)\] (?P<operation>[^|]+)\| (?P<description>.*)$")


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_default_log(path: Path) -> None:
    atomic_write_text(path, DEFAULT_LOG_TEXT)


def append_log(
    wiki_dir: Path,
    timestamp: str,
    operation: str,
    description: str,
    lines: list[str],
    *,
    max_bytes: int = DEFAULT_LOG_MAX_BYTES,
    backups: int = DEFAULT_LOG_BACKUPS,
) -> None:
    log_path = wiki_dir / "log.md"
    entry = [f"## [{timestamp}] {operation} | {description}", ""]
    entry.extend(f"- {line}" for line in lines)
    entry.extend(["", "---", ""])
    append_text_with_rotation(
        log_path,
        "\n".join(entry),
        initial_text=DEFAULT_LOG_TEXT,
        max_bytes=max_bytes,
        backups=backups,
    )


def read_log_entries(wiki_dir: Path, *, limit: int = 100) -> list[dict[str, object]]:
    """Return recent structured entries from ``wiki/log.md``."""
    try:
        parsed_limit = int(limit)
    except (TypeError, ValueError):
        parsed_limit = 100
    limit = max(1, min(parsed_limit, 1000))
    log_path = wiki_dir / "log.md"
    if not log_path.exists():
        return []
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line in lines:
        match = LOG_HEADING_RE.match(line.strip())
        if match:
            if current:
                entries.append(current)
            current = {
                "timestamp": match.group("timestamp").strip(),
                "operation": match.group("operation").strip(),
                "description": match.group("description").strip(),
                "details": [],
            }
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped == "---":
            entries.append(current)
            current = None
        elif stripped.startswith("- "):
            details = current.setdefault("details", [])
            if isinstance(details, list):
                details.append(stripped[2:])
    if current:
        entries.append(current)
    return entries[-limit:]
