"""Local backup helpers for Link wiki data."""
from __future__ import annotations

import re
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .validation import validate_wiki


BACKUP_DIR_NAME = ".link-backups"
DEFAULT_BACKUP_LIMIT = 20


class BackupError(RuntimeError):
    """Raised when a backup archive cannot be completed safely."""


class RestoreError(RuntimeError):
    """Raised when a backup archive cannot be restored safely."""


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _filename_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_label(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(label).lower()).strip("-")
    return slug or "manual"


def _iter_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )


def _unique_backup_path(backup_dir: Path, label: str) -> Path:
    stem = f"{_filename_timestamp()}-{_safe_label(label)}"
    candidate = backup_dir / f"{stem}.tar.gz"
    suffix = 2
    while candidate.exists():
        candidate = backup_dir / f"{stem}-{suffix}.tar.gz"
        suffix += 1
    return candidate


def _prune_backups(backup_dir: Path, limit: int) -> list[str]:
    if limit <= 0:
        return []
    backups = sorted(
        backup_dir.glob("*.tar.gz"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    pruned: list[str] = []
    for path in backups[limit:]:
        try:
            path.unlink()
            pruned.append(path.name)
        except OSError:
            continue
    return pruned


def create_backup(
    link_root: Path,
    *,
    label: str = "manual",
    include_raw: bool = False,
    max_backups: int = DEFAULT_BACKUP_LIMIT,
) -> dict[str, Any]:
    """Create a timestamped local backup archive for a Link root.

    The default archive includes only ``wiki/`` because ``raw/`` can contain
    pasted source files or session captures with sensitive material. Callers
    must opt in with ``include_raw=True`` when they intentionally want raw
    sources copied into the local backup.
    """
    root = link_root.expanduser().resolve()
    wiki_dir = root / "wiki"
    if not wiki_dir.exists() or not wiki_dir.is_dir():
        raise FileNotFoundError(f"Link wiki not found at {wiki_dir}")

    backup_dir = root / BACKUP_DIR_NAME
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = _unique_backup_path(backup_dir, label)

    included_roots: list[tuple[str, Path]] = [("wiki", wiki_dir)]
    raw_dir = root / "raw"
    if include_raw and raw_dir.exists() and raw_dir.is_dir():
        included_roots.append(("raw", raw_dir))

    file_count = 0
    current_arcname = ""
    try:
        with tarfile.open(backup_path, "w:gz") as tar:
            for prefix, source_root in included_roots:
                for path in _iter_files(source_root):
                    rel = path.relative_to(source_root)
                    current_arcname = (Path(prefix) / rel).as_posix()
                    tar.add(path, arcname=current_arcname, recursive=False)
                    file_count += 1
    except (OSError, tarfile.TarError) as exc:
        try:
            backup_path.unlink(missing_ok=True)
        except OSError:
            pass
        detail = f" while adding {current_arcname}" if current_arcname else ""
        raise BackupError(f"backup failed{detail}: {exc}") from exc

    pruned = _prune_backups(backup_dir, int(max_backups))
    return {
        "created": True,
        "path": str(backup_path),
        "name": backup_path.name,
        "created_at": _utc_timestamp(),
        "included": [name for name, _ in included_roots],
        "include_raw": include_raw,
        "file_count": file_count,
        "bytes": backup_path.stat().st_size,
        "retention_limit": int(max_backups),
        "pruned": pruned,
        "privacy_note": "raw/ is excluded by default because it may contain sensitive source material",
    }


def list_backups(link_root: Path, *, limit: int = 20) -> dict[str, Any]:
    """Return recent local backups for a Link root."""
    root = link_root.expanduser().resolve()
    backup_dir = root / BACKUP_DIR_NAME
    backups: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    if backup_dir.exists():
        archive_stats: list[tuple[Path, Any]] = []
        for path in backup_dir.glob("*.tar.gz"):
            try:
                archive_stats.append((path, path.stat()))
            except OSError as exc:
                warnings.append({"backup": path.name, "error": str(exc) or exc.__class__.__name__})
        for path, stat in sorted(
            archive_stats,
            key=lambda item: (item[1].st_mtime, item[0].name),
            reverse=True,
        )[: max(int(limit), 0)]:
            created_at = (
                datetime.fromtimestamp(stat.st_mtime, timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
            backups.append({
                "name": path.name,
                "path": str(path),
                "bytes": stat.st_size,
                "created_at": created_at,
            })
    return {
        "backup_dir": str(backup_dir),
        "count": len(backups),
        "warning_count": len(warnings),
        "warnings": warnings,
        "backups": backups,
    }


def _resolve_backup_path(root: Path, backup: str | Path) -> Path:
    value = Path(str(backup)).expanduser()
    candidates = [value]
    if not value.is_absolute():
        candidates.append(root / BACKUP_DIR_NAME / value)
    for candidate in candidates:
        path = candidate.resolve()
        if path.exists() and path.is_file():
            return path
    return candidates[-1].resolve()


def _safe_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise RestoreError(f"backup contains unsafe path: {name}")
    if not path.parts or path.parts[0] not in {"wiki", "raw"}:
        raise RestoreError(f"backup contains unsupported path: {name}")
    return path


def inspect_backup(
    link_root: Path,
    backup: str | Path,
    *,
    include_raw: bool = False,
) -> dict[str, Any]:
    """Inspect a backup archive and return the safe restore plan."""
    root = link_root.expanduser().resolve()
    backup_path = _resolve_backup_path(root, backup)
    if not backup_path.exists() or not backup_path.is_file():
        raise FileNotFoundError(f"backup archive not found: {backup_path}")

    restore_roots: set[str] = set()
    skipped_roots: set[str] = set()
    file_count = 0
    skipped_count = 0
    with tarfile.open(backup_path, "r:gz") as tar:
        for member in tar.getmembers():
            safe_path = _safe_member_path(member.name)
            root_name = safe_path.parts[0]
            if not (member.isfile() or member.isdir()):
                raise RestoreError(f"backup contains unsupported member type: {member.name}")
            if root_name == "raw" and not include_raw:
                skipped_roots.add("raw")
                if member.isfile():
                    skipped_count += 1
                continue
            restore_roots.add(root_name)
            if member.isfile():
                file_count += 1
    return {
        "backup": str(backup_path),
        "name": backup_path.name,
        "include_raw": include_raw,
        "restore_roots": sorted(restore_roots),
        "skipped_roots": sorted(skipped_roots),
        "file_count": file_count,
        "skipped_file_count": skipped_count,
    }


def restore_backup(
    link_root: Path,
    backup: str | Path,
    *,
    include_raw: bool = False,
    confirm: bool = False,
    safety_backup: bool = True,
) -> dict[str, Any]:
    """Restore wiki/ and optionally raw/ from a local Link backup archive."""
    root = link_root.expanduser().resolve()
    plan = inspect_backup(root, backup, include_raw=include_raw)
    if not confirm:
        return {
            "restored": False,
            "confirmation_required": True,
            **plan,
            "message": "Restore preview only. Pass --confirm to replace local files.",
        }
    if not plan["restore_roots"]:
        raise RestoreError("backup has no restorable files")

    backup_path = Path(str(plan["backup"]))
    safety: dict[str, Any] | None = None
    if safety_backup and (root / "wiki").exists():
        safety = create_backup(
            root,
            label="pre-restore",
            include_raw=include_raw and (root / "raw").exists(),
        )

    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".link-restore-", dir=root) as tmp_name:
        staging = Path(tmp_name)
        with tarfile.open(backup_path, "r:gz") as tar:
            for member in tar.getmembers():
                safe_path = _safe_member_path(member.name)
                root_name = safe_path.parts[0]
                if root_name == "raw" and not include_raw:
                    continue
                if member.isdir():
                    (staging / safe_path).mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise RestoreError(f"backup contains unsupported member type: {member.name}")
                target_path = staging / safe_path
                target_path.parent.mkdir(parents=True, exist_ok=True)
                source = tar.extractfile(member)
                if source is None:
                    raise RestoreError(f"backup member could not be read: {member.name}")
                with source, target_path.open("wb") as output:
                    shutil.copyfileobj(source, output)

        for root_name in plan["restore_roots"]:
            restored_root = staging / root_name
            destination = root / root_name
            if not restored_root.exists():
                continue
            if destination.exists():
                if destination.is_dir():
                    shutil.rmtree(destination)
                else:
                    destination.unlink()
            shutil.move(str(restored_root), str(destination))

    integrity: dict[str, Any] = {
        "checked": False,
        "passed": False,
        "error_count": 0,
        "warning_count": 0,
        "finding_count": 0,
    }
    if "wiki" in plan["restore_roots"]:
        validation = validate_wiki(root / "wiki")
        integrity = {
            "checked": True,
            "passed": bool(validation.get("passed")),
            "error_count": int(validation.get("error_count") or 0),
            "warning_count": int(validation.get("warning_count") or 0),
            "finding_count": int(validation.get("finding_count") or 0),
        }

    return {
        "restored": True,
        "confirmation_required": False,
        **plan,
        "safety_backup": safety,
        "integrity": integrity,
    }
