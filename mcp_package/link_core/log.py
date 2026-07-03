"""Shared Link log helpers."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .files import append_text_with_rotation, atomic_write_text

DEFAULT_LOG_TEXT = "# Link Wiki Log\n\n*Append-only record of wiki operations.*\n"
DEFAULT_LOG_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_LOG_BACKUPS = 5
LOG_HEADING_RE = re.compile(r"^## \[(?P<timestamp>[^\]]+)\] (?P<operation>[^|]+)\| (?P<description>.*)$")
LOG_HASH_RE = re.compile(r"^- log_entry_hash: (?P<hash>[0-9a-f]{64})$")
LOG_PREVIOUS_HASH_RE = re.compile(r"^- log_previous_hash: (?P<hash>[0-9a-f]{64})$")
LOG_GENESIS_HASH = "0" * 64


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_default_log(path: Path) -> None:
    atomic_write_text(path, DEFAULT_LOG_TEXT)


def _last_log_hash(log_path: Path) -> str:
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return LOG_GENESIS_HASH
    for line in reversed(lines):
        match = LOG_HASH_RE.match(line.strip())
        if match:
            return match.group("hash")
    return LOG_GENESIS_HASH


def _hash_log_entry(previous_hash: str, heading: str, detail_lines: list[str]) -> str:
    canonical = "\n".join([previous_hash, heading, *detail_lines])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
    heading = f"## [{timestamp}] {operation} | {description}"
    detail_lines = [f"- {line}" for line in lines]
    previous_hash = _last_log_hash(log_path)
    entry_hash = _hash_log_entry(previous_hash, heading, detail_lines)
    entry = [heading, ""]
    entry.extend(detail_lines)
    entry.append(f"- log_previous_hash: {previous_hash}")
    entry.append(f"- log_entry_hash: {entry_hash}")
    entry.extend(["", "---", ""])
    append_text_with_rotation(
        log_path,
        "\n".join(entry),
        initial_text=DEFAULT_LOG_TEXT,
        max_bytes=max_bytes,
        backups=backups,
    )


def _log_entry_blocks(log_path: Path) -> list[dict[str, Any]]:
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in lines:
        stripped = line.strip()
        match = LOG_HEADING_RE.match(stripped)
        if match:
            if current:
                blocks.append(current)
            current = {"heading": stripped, "detail_lines": [], "previous_hash": "", "entry_hash": ""}
            continue
        if current is None:
            continue
        if stripped == "---":
            blocks.append(current)
            current = None
            continue
        previous_match = LOG_PREVIOUS_HASH_RE.match(stripped)
        if previous_match:
            current["previous_hash"] = previous_match.group("hash")
            continue
        hash_match = LOG_HASH_RE.match(stripped)
        if hash_match:
            current["entry_hash"] = hash_match.group("hash")
            continue
        if stripped.startswith("- "):
            current["detail_lines"].append(stripped)
    if current:
        blocks.append(current)
    return blocks


def verify_log_integrity(wiki_dir: Path) -> dict[str, object]:
    """Verify the append-only hash chain in ``wiki/log.md`` when present."""
    log_path = wiki_dir / "log.md"
    if not log_path.exists():
        return {
            "checked": False,
            "passed": True,
            "hashed_entries": 0,
            "legacy_entries": 0,
            "findings": ["wiki/log.md is missing"],
        }
    findings: list[str] = []
    hashed_entries = 0
    legacy_entries = 0
    expected_previous: str | None = None
    for index, block in enumerate(_log_entry_blocks(log_path), start=1):
        entry_hash = str(block.get("entry_hash") or "")
        previous_hash = str(block.get("previous_hash") or "")
        if not entry_hash:
            legacy_entries += 1
            continue
        hashed_entries += 1
        if expected_previous is None:
            # The first visible hashed entry may continue from a rotated log file.
            expected_previous = previous_hash or LOG_GENESIS_HASH
        if previous_hash != expected_previous:
            findings.append(f"entry {index} previous hash mismatch")
        expected_hash = _hash_log_entry(
            previous_hash,
            str(block.get("heading") or ""),
            list(block.get("detail_lines") or []),
        )
        if entry_hash != expected_hash:
            findings.append(f"entry {index} hash mismatch")
        expected_previous = entry_hash
    return {
        "checked": True,
        "passed": not findings,
        "hashed_entries": hashed_entries,
        "legacy_entries": legacy_entries,
        "findings": findings,
    }


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
        previous_match = LOG_PREVIOUS_HASH_RE.match(stripped)
        if previous_match:
            current["previous_hash"] = previous_match.group("hash")
            continue
        hash_match = LOG_HASH_RE.match(stripped)
        if hash_match:
            current["entry_hash"] = hash_match.group("hash")
            continue
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
