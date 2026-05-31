"""Obsidian vault import helpers for Link."""
from __future__ import annotations

import re
from pathlib import Path

from .files import atomic_write_bytes
from .security import secret_value_warnings


DEFAULT_MAX_FILE_BYTES = 512 * 1024
SKIP_DIR_NAMES = {".git", ".obsidian", ".trash", "__pycache__", "node_modules"}
OBSIDIAN_SUFFIXES = {".md", ".markdown"}


def _slugify(value: str, fallback: str = "vault") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or fallback


def _is_hidden_or_skipped(path: Path, vault: Path) -> bool:
    try:
        rel = path.relative_to(vault)
    except ValueError:
        return True
    return any(part.startswith(".") or part in SKIP_DIR_NAMES for part in rel.parts[:-1])


def _limited(items: list[dict[str, object]], limit: int = 20) -> list[dict[str, object]]:
    return items[:max(0, limit)]


def iter_obsidian_notes(vault: Path) -> list[Path]:
    """Return supported Markdown notes from an Obsidian vault."""
    root = vault.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Obsidian vault not found: {root}")
    notes: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if _is_hidden_or_skipped(path, root):
            continue
        if path.suffix.lower() in OBSIDIAN_SUFFIXES:
            notes.append(path)
    return sorted(notes)


def import_obsidian_vault(
    target: Path,
    vault: Path,
    *,
    overwrite: bool = False,
    dry_run: bool = False,
    limit: int | None = None,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> dict[str, object]:
    """Copy Obsidian Markdown notes into ``raw/obsidian/<vault>/`` for ingest."""
    root = target.expanduser().resolve()
    vault_root = vault.expanduser().resolve()
    notes = iter_obsidian_notes(vault_root)
    if limit is not None:
        notes = notes[:max(0, limit)]

    vault_slug = _slugify(vault_root.name)
    raw_prefix = root / "raw" / "obsidian" / vault_slug
    imported: list[dict[str, object]] = []
    skipped_existing: list[dict[str, object]] = []
    skipped_large: list[dict[str, object]] = []
    blocked_secret: list[dict[str, object]] = []
    read_errors: list[dict[str, object]] = []

    for note in notes:
        rel = note.relative_to(vault_root)
        rel_posix = rel.as_posix()
        destination = raw_prefix / rel
        raw_rel = destination.relative_to(root).as_posix()
        try:
            data = note.read_bytes()
        except OSError as exc:
            read_errors.append({"path": rel_posix, "error": str(exc)})
            continue
        if len(data) > max_file_bytes:
            skipped_large.append({"path": rel_posix, "size_bytes": len(data)})
            continue
        labels = secret_value_warnings(data.decode("utf-8", errors="replace"))
        if labels:
            blocked_secret.append({"path": rel_posix, "labels": labels})
            continue
        if destination.exists() and not overwrite:
            skipped_existing.append({"path": rel_posix, "raw_path": raw_rel})
            continue
        if not dry_run:
            atomic_write_bytes(destination, data)
        imported.append({"path": rel_posix, "raw_path": raw_rel, "size_bytes": len(data)})

    status = "ok"
    if blocked_secret or read_errors:
        status = "needs_attention"
    elif skipped_large:
        status = "partial"
    has_wiki_dir = (root / "wiki").is_dir()
    next_commands = [f"lnk ingest-status {root}", f"lnk validate {root}", f"lnk health {root}"]
    if not has_wiki_dir:
        next_commands = [f"lnk init {root}", *next_commands]
    return {
        "status": status,
        "target": str(root),
        "vault": str(vault_root),
        "vault_name": vault_root.name,
        "raw_prefix": raw_prefix.relative_to(root).as_posix(),
        "dry_run": dry_run,
        "overwrite": overwrite,
        "note_count": len(notes),
        "imported_count": len(imported),
        "skipped_existing_count": len(skipped_existing),
        "skipped_large_count": len(skipped_large),
        "blocked_secret_count": len(blocked_secret),
        "read_error_count": len(read_errors),
        "imported": _limited(imported),
        "skipped_existing": _limited(skipped_existing),
        "skipped_large": _limited(skipped_large),
        "blocked_secret": _limited(blocked_secret),
        "read_errors": _limited(read_errors),
        "has_wiki_dir": has_wiki_dir,
        "next_prompt": f"ingest raw/obsidian/{vault_slug} into Link",
        "next_commands": next_commands,
    }


def render_import_obsidian_text(payload: dict[str, object]) -> tuple[int, str]:
    """Render a concise CLI report for an Obsidian import."""
    lines = [
        f"Obsidian import: {payload['vault']}",
        f"Raw destination: {payload['raw_prefix']}",
        "",
        f"Notes scanned: {payload['note_count']}",
        f"Imported: {payload['imported_count']}",
        f"Skipped existing: {payload['skipped_existing_count']}",
        f"Skipped large: {payload['skipped_large_count']}",
        f"Blocked for secrets: {payload['blocked_secret_count']}",
        f"Read errors: {payload['read_error_count']}",
    ]
    if payload.get("dry_run"):
        lines.append("Dry run: no files were written.")
    if not payload.get("has_wiki_dir"):
        lines.append("Link wiki is not initialized yet; run the init command below before ingest.")
    if payload.get("imported"):
        lines.append("")
        lines.append("Imported raw files:")
        for item in payload["imported"]:  # type: ignore[index]
            lines.append(f"- {item['raw_path']}")
    if payload.get("blocked_secret"):
        lines.append("")
        lines.append("Blocked files:")
        for item in payload["blocked_secret"]:  # type: ignore[index]
            labels = ", ".join(str(label) for label in item.get("labels", []))
            lines.append(f"- {item['path']} ({labels})")
    lines.extend([
        "",
        "Next:",
        f"  Ask your agent: {payload['next_prompt']}",
        *[f"  Run: {command}" for command in payload.get("next_commands", [])],
    ])
    return (1 if payload.get("blocked_secret_count") or payload.get("read_error_count") else 0), "\n".join(lines)
