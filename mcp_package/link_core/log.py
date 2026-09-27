"""Shared Link log helpers."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .files import (
    append_text_unlocked,
    atomic_write_text,
    atomic_write_text_unlocked,
    file_lock,
    rotate_file_unlocked,
)

DEFAULT_LOG_TEXT = "# Link Wiki Log\n\n*Append-only record of wiki operations.*\n"
DEFAULT_LOG_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_LOG_BACKUPS = 5
LOG_HEADING_RE = re.compile(r"^## \[(?P<timestamp>[^\]]+)\] (?P<operation>[^|]+)\| (?P<description>.*)$")
LOG_HASH_RE = re.compile(r"^- log_entry_hash: (?P<hash>[0-9a-f]{64})$")
LOG_PREVIOUS_HASH_RE = re.compile(r"^- log_previous_hash: (?P<hash>[0-9a-f]{64})$")
LOG_GENESIS_HASH = "0" * 64
# Machine-local record of the newest entry this machine wrote or accepted.
# A log whose newest entries were cut off still verifies entry by entry;
# the anchor is what notices the cut.
LOG_ANCHOR_RELATIVE = Path(".link-cache") / "log-anchor.json"
_LINE_BREAK_RE = re.compile(r"[\r\n]+")


def _one_line(value: object) -> str:
    """Log headings and details are single lines by format.

    A newline inside a title or reason split one entry across lines; the
    parser then dropped the continuation and an honest entry failed its
    own hash check.
    """
    return _LINE_BREAK_RE.sub(" ", str(value)).strip()


def log_anchor_path(wiki_dir: Path) -> Path:
    return wiki_dir.parent / LOG_ANCHOR_RELATIVE


def _write_anchor(wiki_dir: Path, head: str) -> None:
    try:
        atomic_write_text(
            log_anchor_path(wiki_dir),
            json.dumps({"head": head, "updated_at": utc_timestamp()}) + "\n",
        )
    except OSError:
        # The anchor is a second line of defence; failing to write it must
        # never fail the operation being logged.
        pass


def _read_anchor(wiki_dir: Path) -> str:
    try:
        payload = json.loads(log_anchor_path(wiki_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    head = payload.get("head") if isinstance(payload, dict) else ""
    return head if isinstance(head, str) and LOG_HASH_RE.match(f"- log_entry_hash: {head}") else ""


def refresh_log_anchor(wiki_dir: Path) -> None:
    """Accept the current log head as trusted (after sync or restore)."""
    _write_anchor(wiki_dir, _last_log_hash(wiki_dir / "log.md"))


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
    heading = f"## [{_one_line(timestamp)}] {_one_line(operation).replace('|', '/')} | {_one_line(description)}"
    detail_lines = [f"- {_one_line(line)}" for line in lines]
    # Read the previous hash and append under one lock. Two separate locks
    # let concurrent hooks and MCP writes both chain onto the same parent,
    # forking the chain so verification then failed on honest entries.
    with file_lock(log_path):
        previous_hash = _last_log_hash(log_path)
        entry_hash = _hash_log_entry(previous_hash, heading, detail_lines)
        entry = [heading, ""]
        entry.extend(detail_lines)
        entry.append(f"- log_previous_hash: {previous_hash}")
        entry.append(f"- log_entry_hash: {entry_hash}")
        entry.extend(["", "---", ""])
        text = "\n".join(entry)
        current_size = log_path.stat().st_size if log_path.exists() else 0
        if max_bytes > 0 and current_size > 0 and current_size + len(text.encode("utf-8")) > max_bytes:
            # Rotation happens after the parent hash is read, so the first
            # entry of the new file continues the chain of the rotated one.
            rotate_file_unlocked(log_path, backups)
        append_text_unlocked(log_path, text, initial_text=DEFAULT_LOG_TEXT)
    _write_anchor(wiki_dir, entry_hash)


def _log_family(log_path: Path) -> list[Path]:
    """log.md and its rotated files, oldest first."""
    rotated = []
    index = 1
    while True:
        candidate = log_path.with_name(f"{log_path.name}.{index}")
        if not candidate.exists():
            break
        rotated.append(candidate)
        index += 1
    return list(reversed(rotated)) + ([log_path] if log_path.exists() else [])


def _first_previous_hash(text: str) -> str:
    for line in text.splitlines():
        match = LOG_PREVIOUS_HASH_RE.match(line.strip())
        if match:
            return match.group("hash")
    return LOG_GENESIS_HASH


def redact_log_references(
    wiki_dir: Path,
    needles: list[str],
    timestamp: str,
    reason: str,
) -> dict[str, object]:
    """Replace needle text in past log entries and re-anchor the hash chain.

    Forgetting a memory must also forget the log lines that quote its title,
    in rotated log files too (they used to keep the title forever). The log
    is tamper-evident, so this is never silent: the chain is rebuilt across
    every file, oldest first, and a final entry declares the redaction and
    the re-anchor. Each file is replaced atomically under the log's lock,
    so a hook appending at the same moment can neither be lost nor
    interleave. Needles shorter than 6 characters are ignored to avoid
    mangling unrelated text.
    """
    log_path = wiki_dir / "log.md"
    safe_needles = [_one_line(n) for n in needles if isinstance(n, str) and len(n.strip()) >= 6]
    if not log_path.exists() or not safe_needles:
        return {"redacted_entries": 0, "rechained": False}
    touched = 0
    with file_lock(log_path):
        family = _log_family(log_path)
        texts = {path: path.read_text(encoding="utf-8", errors="replace") for path in family}
        for path, text in texts.items():
            for needle in safe_needles:
                if needle in text:
                    touched += text.count(needle)
                    text = text.replace(needle, "[forgotten memory]")
            texts[path] = text
        if touched:
            previous_hash = _first_previous_hash(texts[family[0]]) if family else LOG_GENESIS_HASH
            for path in family:
                preamble, entries = _parse_log_text(texts[path])
                rendered, previous_hash = _render_chain_from(preamble, entries, previous_hash)
                atomic_write_text_unlocked(path, rendered)
    if not touched:
        return {"redacted_entries": 0, "rechained": False}
    append_log(
        wiki_dir,
        timestamp,
        "redact-log",
        reason,
        [
            f"Replaced {touched} reference(s) with [forgotten memory].",
            "Hash chain re-anchored by this entry.",
        ],
    )
    return {"redacted_entries": touched, "rechained": True}


def _parse_log_text(text: str) -> tuple[list[str], list[tuple[str, tuple[str, ...]]]]:
    """Split a log into (preamble lines, [(heading, detail lines)]).

    Hash lines and separators are dropped — they are recomputed whenever a
    chain is rebuilt.
    """
    preamble: list[str] = []
    entries: list[tuple[str, tuple[str, ...]]] = []
    heading: str | None = None
    details: list[str] = []
    preamble_done = False
    for line in text.splitlines():
        if line.startswith("## ["):
            if heading is not None:
                entries.append((heading, tuple(details)))
            preamble_done = True
            heading = line
            details = []
            continue
        if not preamble_done:
            preamble.append(line)
            continue
        if LOG_HASH_RE.match(line) or LOG_PREVIOUS_HASH_RE.match(line):
            continue
        if line.strip() == "---" or (heading is not None and not line.strip() and not details):
            continue
        if heading is not None and line.startswith("- "):
            details.append(line)
    if heading is not None:
        entries.append((heading, tuple(details)))
    return preamble, entries


def _render_chain_from(
    preamble: list[str],
    entries: list[tuple[str, tuple[str, ...]]],
    previous_hash: str,
) -> tuple[str, str]:
    """Render entries chained onto `previous_hash`; return (text, last hash)."""
    out = list(preamble)
    for heading, details in entries:
        entry_hash = _hash_log_entry(previous_hash, heading, list(details))
        out.append(heading)
        out.append("")
        out.extend(details)
        out.append(f"- log_previous_hash: {previous_hash}")
        out.append(f"- log_entry_hash: {entry_hash}")
        out.extend(["", "---", ""])
        previous_hash = entry_hash
    return "\n".join(out).rstrip() + "\n", previous_hash


def _render_chained_log(preamble: list[str], entries: list[tuple[str, tuple[str, ...]]]) -> str:
    out = list(preamble)
    previous_hash = LOG_GENESIS_HASH
    for heading, details in entries:
        entry_hash = _hash_log_entry(previous_hash, heading, list(details))
        out.append(heading)
        out.append("")
        out.extend(details)
        out.append(f"- log_previous_hash: {previous_hash}")
        out.append(f"- log_entry_hash: {entry_hash}")
        out.extend(["", "---", ""])
        previous_hash = entry_hash
    return "\n".join(out).rstrip() + "\n"


def merge_log_texts(ours: str, theirs: str) -> str:
    """Union two machines' logs into one freshly chained log.

    Sync brings together two append-only logs that diverged from a common
    ancestor. Entries are identified by (heading, details) — identical
    entries dedupe, distinct ones interleave by their timestamp heading —
    and the whole chain is rebuilt from genesis. The caller must declare
    the re-anchor by appending a sync-merge entry, mirroring how log
    redaction declares its re-chain.
    """
    preamble, our_entries = _parse_log_text(ours)
    _, their_entries = _parse_log_text(theirs)
    seen = set(our_entries)
    merged = list(our_entries)
    for entry in their_entries:
        if entry not in seen:
            merged.append(entry)
            seen.add(entry)
    merged.sort(key=lambda entry: entry[0][: len("## [2026-01-01T00:00:00Z]") + 2])
    return _render_chained_log(preamble, merged)


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
    seen_hashes: set[str] = set()
    for index, block in enumerate(_log_entry_blocks(log_path), start=1):
        entry_hash = str(block.get("entry_hash") or "")
        previous_hash = str(block.get("previous_hash") or "")
        if not entry_hash:
            legacy_entries += 1
            continue
        hashed_entries += 1
        seen_hashes.add(entry_hash)
        if expected_previous is None:
            # The first entry either starts the chain or continues the newest
            # rotated file. Anything else means earlier entries were cut:
            # before this check, deleting the head of the log verified clean.
            rotated = log_path.with_name(f"{log_path.name}.1")
            if previous_hash and previous_hash != LOG_GENESIS_HASH:
                if rotated.exists():
                    if _last_log_hash(rotated) != previous_hash:
                        findings.append("log does not continue the rotated log.md.1 (entries between them are missing)")
                else:
                    findings.append("log starts mid-chain: earlier entries are missing")
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
    anchor = _read_anchor(wiki_dir)
    anchor_state = "missing"
    if anchor:
        if anchor in seen_hashes or not seen_hashes and anchor == LOG_GENESIS_HASH:
            anchor_state = "ok"
        else:
            anchor_state = "mismatch"
            # The newest entry this machine wrote is gone: the tail was cut
            # or the file replaced. Entry-by-entry checks cannot see that.
            findings.append("latest logged entries are missing (log truncated or replaced since this machine last wrote it)")
    return {
        "checked": True,
        "passed": not findings,
        "anchor": anchor_state,
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
