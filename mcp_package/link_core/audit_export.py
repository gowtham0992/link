"""Compliance-style audit exports for Link."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .files import atomic_write_json
from .log import read_log_entries, utc_timestamp
from .memory import memory_inbox, memory_profile, memory_records, slim_memory
from .operations import pending_operations
from .status import link_status


def log_entries(wiki_dir: Path, *, limit: int = 100) -> list[dict[str, object]]:
    """Return recent structured entries from ``wiki/log.md`` without raw content."""
    return read_log_entries(wiki_dir, limit=max(1, min(limit, 500)))


def build_compliance_export(
    wiki_dir: Path,
    *,
    version: str = "",
    project: str | None = None,
    limit: int = 100,
) -> dict[str, object]:
    """Build a read-only audit packet for security reviews and team handoffs."""
    wiki = wiki_dir.expanduser().resolve()
    records = memory_records(wiki, include_body=False) if wiki.exists() else []
    profile = memory_profile(records, limit=min(limit, 50), project=project)
    inbox = memory_inbox(records, limit=min(limit, 50), include_archived=True, project=project)
    status = link_status(wiki, version=version, records=records, include_validation=True)
    operations = pending_operations(wiki, limit=min(limit, 100)) if wiki.exists() else []
    return {
        "schema": "link-compliance-export-v1",
        "generated_at": utc_timestamp(),
        "version": version,
        "wiki": str(wiki),
        "project": str(profile.get("project") or ""),
        "status": status,
        "memory_profile": profile,
        "memory_inbox": inbox,
        "memories": [slim_memory(record) for record in records[:max(1, min(limit, 500))]],
        "operations": operations,
        "log_entries": log_entries(wiki, limit=limit),
        "privacy_note": "Raw source contents and memory bodies are not included in this export.",
    }


def write_compliance_export(path: Path, payload: Mapping[str, object]) -> None:
    """Write an audit export JSON file atomically."""
    atomic_write_json(path.expanduser(), dict(payload))


def render_compliance_export_text(payload: Mapping[str, object], *, output: str = "") -> tuple[int, str]:
    """Render a short CLI summary after writing or printing an audit export."""
    status = payload.get("status")
    ready = ""
    if isinstance(status, Mapping):
        ready = "yes" if status.get("ready") else "no"
    lines = [
        "Link compliance export",
        f"Wiki: {payload.get('wiki')}",
        f"Ready: {ready or 'unknown'}",
        f"Memories exported: {len(payload.get('memories') or [])}",
        f"Log entries exported: {len(payload.get('log_entries') or [])}",
        "Raw source contents and memory bodies were not included.",
    ]
    if output:
        lines.insert(1, f"Wrote: {output}")
    return 0, "\n".join(lines)
