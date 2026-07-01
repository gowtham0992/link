"""Lightweight operation journal for Link's local multi-file writes."""
from __future__ import annotations

import re
import shutil
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .files import atomic_write_json
from .mcp_verify import display_command

OPERATION_DIR_NAME = ".link-operations"
DEFAULT_STALE_AFTER_SECONDS = 10 * 60


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slug(value: str, fallback: str = "operation") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80] or fallback


def operation_dir(wiki_dir: Path) -> Path:
    return wiki_dir / OPERATION_DIR_NAME


def begin_operation(
    wiki_dir: Path,
    operation: str,
    description: str,
    *,
    timestamp: str = "",
    paths: Iterable[str] | None = None,
) -> Path:
    """Write a pending operation marker before a multi-file mutation begins."""
    marker_dir = operation_dir(wiki_dir)
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker = marker_dir / f"{_slug(operation)}-{uuid.uuid4().hex}.json"
    now = timestamp or _utc_timestamp()
    atomic_write_json(marker, {
        "status": "pending",
        "operation": operation,
        "description": description,
        "started_at": now,
        "monotonic_started_at": time.monotonic(),
        "paths": list(paths or []),
    })
    return marker


def _snapshot_dir(marker: Path) -> Path:
    return marker.with_suffix("")


def _resolve_touched_path(wiki_dir: Path, value: str) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute():
        return None
    root = wiki_dir.parent.resolve()
    if candidate.parts and candidate.parts[0] == "wiki":
        target = root / candidate
    else:
        target = wiki_dir / candidate
    try:
        resolved = target.expanduser().resolve()
    except OSError:
        resolved = target.expanduser().absolute()
    if resolved == root or root not in resolved.parents:
        return None
    return resolved


def _snapshot_paths(marker: Path, wiki_dir: Path, paths: Iterable[str] | None) -> None:
    items = list(paths or [])
    if not items:
        return
    snapshot_dir = _snapshot_dir(marker)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []
    for index, raw_path in enumerate(items):
        target = _resolve_touched_path(wiki_dir, raw_path)
        if target is None:
            manifest.append({"path": raw_path, "valid": False, "existed": False})
            continue
        entry: dict[str, object] = {
            "path": raw_path,
            "target": str(target),
            "valid": True,
            "existed": target.exists(),
            "snapshot": "",
            "kind": "missing",
        }
        if target.is_file():
            snapshot_name = f"{index:04d}.snapshot"
            shutil.copy2(target, snapshot_dir / snapshot_name)
            entry.update({"snapshot": snapshot_name, "kind": "file"})
        elif target.exists():
            entry["kind"] = "unsupported"
        manifest.append(entry)
    atomic_write_json(snapshot_dir / "manifest.json", {"paths": manifest})


def _rollback_snapshots(marker: Path) -> dict[str, object]:
    snapshot_dir = _snapshot_dir(marker)
    manifest_path = snapshot_dir / "manifest.json"
    if not manifest_path.exists():
        return {"attempted": False, "restored": [], "removed": [], "errors": []}
    import json

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"attempted": True, "restored": [], "removed": [], "errors": [f"could not read snapshot manifest: {exc}"]}
    restored: list[str] = []
    removed: list[str] = []
    errors: list[str] = []
    for item in manifest.get("paths", []):
        if not isinstance(item, dict) or not item.get("valid"):
            continue
        target = Path(str(item.get("target") or ""))
        raw_path = str(item.get("path") or target)
        try:
            if item.get("kind") == "file" and item.get("snapshot"):
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(snapshot_dir / str(item["snapshot"]), target)
                restored.append(raw_path)
            elif not item.get("existed") and target.exists() and target.is_file():
                target.unlink()
                removed.append(raw_path)
        except OSError as exc:
            errors.append(f"{raw_path}: {exc}")
    return {"attempted": True, "restored": restored, "removed": removed, "errors": errors}


def finish_operation(marker: Path) -> None:
    """Clear a pending marker after a mutation fully completes."""
    try:
        shutil.rmtree(_snapshot_dir(marker))
    except FileNotFoundError:
        pass
    except OSError:
        pass
    try:
        marker.unlink()
    except FileNotFoundError:
        pass


def fail_operation(marker: Path, exc: BaseException, rollback: Mapping[str, object] | None = None) -> None:
    """Leave a failed marker with a small error summary for doctor/status."""
    try:
        payload = _read_marker(marker)
        payload["status"] = "failed"
        payload["failed_at"] = _utc_timestamp()
        payload["error"] = str(exc)[:300] or exc.__class__.__name__
        if rollback is not None:
            payload["rollback"] = dict(rollback)
        atomic_write_json(marker, payload)
    except OSError:
        pass


@contextmanager
def operation_journal(
    wiki_dir: Path,
    operation: str,
    description: str,
    *,
    timestamp: str = "",
    paths: Iterable[str] | None = None,
):
    marker = begin_operation(wiki_dir, operation, description, timestamp=timestamp, paths=paths)
    _snapshot_paths(marker, wiki_dir, paths)
    try:
        yield marker
    except BaseException as exc:
        rollback = _rollback_snapshots(marker)
        fail_operation(marker, exc, rollback=rollback)
        raise
    else:
        finish_operation(marker)


def _parse_timestamp(value: object) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _read_marker(path: Path) -> dict[str, Any]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def pending_operations(
    wiki_dir: Path,
    *,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
    now: float | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return pending or failed operation markers, newest first."""
    marker_dir = operation_dir(wiki_dir)
    if not marker_dir.exists():
        return []
    current = time.time() if now is None else now
    operations: list[dict[str, Any]] = []
    for marker in sorted(marker_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
        try:
            payload = _read_marker(marker)
        except (OSError, ValueError):
            payload = {"status": "invalid", "operation": "unknown", "description": "Unreadable operation marker"}
        started_epoch = _parse_timestamp(payload.get("started_at"))
        age_seconds = max(0, current - started_epoch) if started_epoch is not None else None
        payload["marker"] = marker.name
        payload["path"] = str(marker)
        payload["age_seconds"] = age_seconds
        payload["stale"] = age_seconds is None or age_seconds >= stale_after_seconds or payload.get("status") == "failed"
        operations.append(payload)
    return operations


def _format_age(age_seconds: object) -> str:
    if not isinstance(age_seconds, (int, float)):
        return "unknown age"
    seconds = max(0, int(age_seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h"
    return f"{hours // 24}d"


def operation_report(
    wiki_dir: Path,
    *,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
    now: float | None = None,
    limit: int = 20,
) -> dict[str, object]:
    """Return a user-facing summary of interrupted or active Link write operations."""
    wiki_dir = wiki_dir.expanduser().resolve()
    operations = pending_operations(
        wiki_dir,
        stale_after_seconds=stale_after_seconds,
        now=now,
        limit=limit,
    )
    stale_count = sum(1 for item in operations if item.get("stale"))
    failed_count = sum(1 for item in operations if str(item.get("status") or "") == "failed")
    active_count = len(operations) - stale_count
    command_target = str(wiki_dir.parent if wiki_dir.name == "wiki" else wiki_dir)
    next_actions: list[dict[str, object]] = []
    if stale_count:
        next_actions.extend([
            {
                "label": "inspect operation marker files before deleting them",
                "command": display_command(["link", "operations", command_target]),
            },
            {
                "label": "validate wiki structure after reviewing interrupted writes",
                "command": display_command(["link", "validate", command_target]),
            },
            {
                "label": "repair generated indexes if validation reports stale graph data",
                "command": display_command(["link", "doctor", "--fix", command_target]),
            },
        ])
    elif active_count:
        next_actions.append({
            "label": "wait for the active Link write to finish, then rerun this command",
            "command": display_command(["link", "operations", command_target]),
        })
    else:
        next_actions.append({
            "label": "continue using Link normally",
            "command": display_command(["link", "status", "--validate", command_target]),
        })
    return {
        "wiki": str(wiki_dir),
        "operation_count": len(operations),
        "stale_count": stale_count,
        "failed_count": failed_count,
        "active_count": active_count,
        "limit": limit,
        "operations": operations,
        "next_actions": next_actions,
    }


def render_operations_text(payload: dict[str, object]) -> tuple[int, str]:
    """Render operation markers for the CLI."""
    operations = [
        item for item in payload.get("operations", [])
        if isinstance(item, dict)
    ]
    stale_count = int(payload.get("stale_count") or 0)
    lines = [f"Link operations: {payload.get('wiki')}", ""]
    if not operations:
        lines.append("No pending, failed, or interrupted Link operations.")
    else:
        count = len(operations)
        lines.append(f"{count} operation marker{'s' if count != 1 else ''}:")
        for item in operations:
            operation = str(item.get("operation") or "unknown")
            status = str(item.get("status") or "unknown")
            marker = str(item.get("marker") or "unknown")
            age = _format_age(item.get("age_seconds"))
            state = "stale" if item.get("stale") else "active"
            lines.append(f"- {operation} | {status} | {state} | {marker} | age {age}")
            description = str(item.get("description") or "").strip()
            if description:
                lines.append(f"  Description: {description}")
            started_at = str(item.get("started_at") or "").strip()
            if started_at:
                lines.append(f"  Started: {started_at}")
            error = str(item.get("error") or "").strip()
            if error:
                lines.append(f"  Error: {error}")
            rollback = item.get("rollback") if isinstance(item.get("rollback"), Mapping) else {}
            if rollback:
                restored = [
                    str(path)
                    for path in rollback.get("restored", [])
                    if isinstance(path, str) and path.strip()
                ]
                removed = [
                    str(path)
                    for path in rollback.get("removed", [])
                    if isinstance(path, str) and path.strip()
                ]
                rollback_errors = [
                    str(path)
                    for path in rollback.get("errors", [])
                    if isinstance(path, str) and path.strip()
                ]
                if restored or removed or rollback_errors:
                    parts: list[str] = []
                    if restored:
                        parts.append(f"restored {', '.join(restored[:4])}")
                    if removed:
                        parts.append(f"removed {', '.join(removed[:4])}")
                    if rollback_errors:
                        parts.append(f"errors {', '.join(rollback_errors[:2])}")
                    lines.append("  Rollback: " + "; ".join(parts))
            paths = [
                str(path)
                for path in item.get("paths", [])
                if isinstance(path, str) and path.strip()
            ]
            if paths:
                lines.append(f"  Touched: {', '.join(paths[:8])}")
            path = str(item.get("path") or "").strip()
            if path:
                lines.append(f"  Marker: {path}")
    actions = [
        item for item in payload.get("next_actions", [])
        if isinstance(item, dict)
    ]
    if actions:
        lines.append("")
        lines.append("Next:")
        for action in actions:
            label = str(action.get("label") or "").strip()
            command = str(action.get("command") or "").strip()
            if label and command:
                lines.append(f"- {label}: {command}")
            elif label:
                lines.append(f"- {label}")
            elif command:
                lines.append(f"- {command}")
    lines.append("")
    lines.append("Result: needs attention" if stale_count else "Result: clear")
    return (1 if stale_count else 0), "\n".join(lines)
