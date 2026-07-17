"""Project seeding helpers for day-one Link context."""
from __future__ import annotations

import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .files import atomic_write_json, atomic_write_text
from .frontmatter import frontmatter_string, yaml_list
from .security import clean_text_input, secret_value_warnings
from .wiki import build_backlinks_from_cache, build_wiki_cache, close_wiki_cache, rebuild_index


DEFAULT_MAX_FILE_BYTES = 128 * 1024
DEFAULT_FILE_LIMIT = 12
DEFAULT_GIT_LOG_LIMIT = 20
SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".link-backups",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "venv",
    "__pycache__",
    "build",
    "dist",
    "link-demo",
    "link-proof",
    "node_modules",
    "raw",
    "wiki",
}

DIRECT_PROJECT_FILES = (
    "README.md",
    "README.markdown",
    "README.txt",
    "README.rst",
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".cursorrules",
    ".windsurfrules",
    ".clinerules",
    ".github/copilot-instructions.md",
)

PROJECT_GLOBS = (
    ".cursor/rules/*.md",
    ".cursor/rules/*.mdc",
    ".github/instructions/*.instructions.md",
    ".kiro/steering/*.md",
    "docs/adr/*.md",
    "docs/adrs/*.md",
    "docs/decisions/*.md",
    "adr/*.md",
)

ADR_PATH_HINTS = ("adr", "adrs", "decisions")


def _slugify(value: str, fallback: str = "project") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or fallback


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _limited(items: list[dict[str, object]], limit: int = 20) -> list[dict[str, object]]:
    return items[:max(0, limit)]


def _project_title(project_root: Path, project_name: str | None) -> str:
    return clean_text_input(project_name, max_len=80) if project_name else clean_text_input(project_root.name, max_len=80)


def _candidate_files(project_root: Path, limit: int) -> list[Path]:
    root = project_root.expanduser().resolve()
    seen: set[Path] = set()
    candidates: list[Path] = []

    def add(path: Path) -> None:
        if len(candidates) >= limit:
            return
        try:
            resolved = path.resolve()
        except OSError:
            return
        if resolved in seen:
            return
        if not _is_relative_to(resolved, root):
            return
        try:
            rel = resolved.relative_to(root)
        except ValueError:
            return
        if any(part in SKIP_DIR_NAMES for part in rel.parts[:-1]):
            return
        if not resolved.is_file():
            return
        seen.add(resolved)
        candidates.append(resolved)

    for relative in DIRECT_PROJECT_FILES:
        add(root / relative)
    for pattern in PROJECT_GLOBS:
        for path in sorted(root.glob(pattern)):
            add(path)
            if len(candidates) >= limit:
                break
    return candidates


def discover_project_seed_files(project_root: Path, *, limit: int = DEFAULT_FILE_LIMIT) -> list[dict[str, object]]:
    """Return project files Link can safely consider for a day-one seed."""
    root = project_root.expanduser().resolve()
    safe_limit = max(0, min(int(limit), 50))
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
        }
        for path in _candidate_files(root, safe_limit)
    ]


def _read_project_files(
    project_root: Path,
    *,
    limit: int,
    max_file_bytes: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    root = project_root.expanduser().resolve()
    included: list[dict[str, object]] = []
    skipped_large: list[dict[str, object]] = []
    blocked_secret: list[dict[str, object]] = []
    read_errors: list[dict[str, object]] = []
    for path in _candidate_files(root, max(0, min(limit, 50))):
        rel = path.relative_to(root).as_posix()
        try:
            data = path.read_bytes()
        except OSError as exc:
            read_errors.append({"path": rel, "error": str(exc)})
            continue
        if len(data) > max_file_bytes:
            skipped_large.append({"path": rel, "size_bytes": len(data), "max_file_bytes": max_file_bytes})
            continue
        text = data.decode("utf-8", errors="replace")
        labels = secret_value_warnings(text)
        if labels:
            blocked_secret.append({"path": rel, "labels": labels})
            continue
        included.append({"path": rel, "size_bytes": len(data), "text": text})
    return included, skipped_large, blocked_secret, read_errors


def _adr_decision_candidates(included: list[dict[str, object]], limit: int = 5) -> list[dict[str, str]]:
    """Mine ADR/decision files for decision-shaped memory candidates.

    Deterministic and proposal-only: takes each ADR's title plus the text of
    its Decision section and suggests one reviewable `decision` memory. Link
    never writes these — the user approves each with the printed command.
    """
    candidates: list[dict[str, str]] = []
    for item in included:
        rel = str(item.get("path") or "")
        parts = {part.lower() for part in Path(rel).parts}
        if not (parts & set(ADR_PATH_HINTS)):
            continue
        text = str(item.get("text") or "")
        title = ""
        for line in text.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        match = re.search(
            r"^#{1,3}\s*Decision\b[^\n]*\n+(.*?)(?=\n#{1,3}\s|\Z)",
            text,
            re.IGNORECASE | re.DOTALL | re.MULTILINE,
        )
        decision_text = " ".join(match.group(1).split()) if match else ""
        if not decision_text or len(decision_text) < 20:
            continue
        if len(decision_text) > 400:
            decision_text = decision_text[:400].rstrip() + " …"
        memory = f"{title}: {decision_text}" if title else decision_text
        candidates.append({"path": rel, "title": title or rel, "memory": memory})
        if len(candidates) >= limit:
            break
    return candidates


def _git_history(project_root: Path, limit: int) -> dict[str, object]:
    safe_limit = max(0, min(int(limit), 100))
    if safe_limit == 0 or not (project_root / ".git").exists():
        return {"included": False, "lines": [], "error": ""}
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--decorate=no", "-n", str(safe_limit)],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"included": False, "lines": [], "error": str(exc)}
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "git log failed").strip()
        return {"included": False, "lines": [], "error": clean_text_input(error, max_len=240)}
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return {"included": bool(lines), "lines": lines, "error": ""}


def _format_raw_seed(
    *,
    project_title: str,
    project_slug: str,
    project_root: Path,
    included: list[dict[str, object]],
    git_history: dict[str, object],
) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    parts = [
        "---",
        f'title: "Project seed: {frontmatter_string(project_title)}"',
        "source_type: project_seed",
        f"date_captured: {today}",
        f"project: {project_slug}",
        "---",
        "",
        f"# Project seed: {project_title}",
        "",
        "This source was generated by `lnk seed` from allowlisted project context files.",
        "It is meant to give agents useful day-one context without inventing durable memories.",
        "",
        "## Project",
        "",
        f"- Name: {project_title}",
        f"- Slug: `{project_slug}`",
        f"- Local path: `{project_root}`",
        "",
        "## Included Files",
        "",
    ]
    for item in included:
        parts.extend([
            f"### `{item['path']}`",
            "",
            "```text",
            str(item["text"]).rstrip(),
            "```",
            "",
        ])
    if git_history.get("included"):
        parts.extend([
            "## Recent Git History",
            "",
            "```text",
            "\n".join(str(line) for line in git_history.get("lines", [])),
            "```",
            "",
        ])
    return "\n".join(parts).rstrip() + "\n"


def _summary_from_files(included: list[dict[str, object]]) -> str:
    names = ", ".join(str(item["path"]) for item in included[:5])
    if len(included) > 5:
        names += f", and {len(included) - 5} more"
    return f"Seeded project context from {names}."


def _format_source_page(
    *,
    project_title: str,
    project_slug: str,
    raw_rel: str,
    included: list[dict[str, object]],
    git_history: dict[str, object],
) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    aliases = [project_title, f"{project_title} project context", f"{project_slug} project seed"]
    summary = _summary_from_files(included)
    # Recall packets return excerpts of this page, so the page must carry the
    # actual (secret-scanned) context, not just a list of file names.
    excerpt_limit = 1200
    file_lines: list[str] = []
    for item in included:
        text = str(item.get("text") or "").strip()
        truncated = len(text) > excerpt_limit
        excerpt = text[:excerpt_limit].rstrip()
        file_lines.extend([
            f"### `{item['path']}` ({item['size_bytes']} bytes)",
            "",
            "```text",
            excerpt + ("\n[... truncated for recall budget]" if truncated else ""),
            "```",
            "",
        ])
    git_lines = [str(line) for line in git_history.get("lines", [])]
    if git_history.get("included") and git_lines:
        file_lines.extend([
            f"### Recent git history ({len(git_lines)} commits)",
            "",
            *[f"- {line}" for line in git_lines[:10]],
            "",
        ])
    if file_lines and file_lines[-1] == "":
        file_lines.pop()
    git_note = " Recent git history was included." if git_history.get("included") else ""
    return "\n".join([
        "---",
        "type: source",
        f'title: "Project seed: {frontmatter_string(project_title)}"',
        "source_type: project_seed",
        f"date_ingested: {today}",
        "tags: [project-seed, onboarding, project-context]",
        "confidence: high",
        f"project: {project_slug}",
        f"raw_path: {raw_rel}",
        f"aliases: {yaml_list(aliases)}",
        "---",
        "",
        f"# Project seed: {project_title}",
        "",
        f"> **TLDR:** {summary}",
        "",
        "## Summary",
        "",
        f"{summary}{git_note} This page exists so the first Link recall can return useful project context immediately.",
        "",
        "## Key Context",
        "",
        *file_lines,
        "",
        "## Raw Source",
        "",
        f"`{raw_rel}`",
        "",
    ])


def _rebuild_graph_indexes(wiki_dir: Path) -> None:
    rebuild_index(wiki_dir)
    cache = build_wiki_cache(wiki_dir, use_persistent_cache=False)
    try:
        backlinks = build_backlinks_from_cache(cache, body_only=False)
    finally:
        close_wiki_cache(cache)
    atomic_write_json(wiki_dir / "_backlinks.json", backlinks)


def _ensure_wiki_structure(root: Path) -> None:
    wiki_dir = root / "wiki"
    for dirname in ("sources", "concepts", "entities", "memories", "comparisons", "explorations"):
        (wiki_dir / dirname).mkdir(parents=True, exist_ok=True)
    log_path = wiki_dir / "log.md"
    if not log_path.exists():
        atomic_write_text(log_path, "# Link Wiki Log\n\n")


def seed_project_context(
    target: Path,
    project_root: Path,
    *,
    project_name: str | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
    limit: int = DEFAULT_FILE_LIMIT,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    include_git_log: bool = True,
    git_log_limit: int = DEFAULT_GIT_LOG_LIMIT,
    rebuild: bool = True,
) -> dict[str, object]:
    """Seed Link with source-backed context from common project files."""
    root = target.expanduser().resolve()
    project = project_root.expanduser().resolve()
    if not project.exists() or not project.is_dir():
        raise ValueError(f"project directory not found: {project}")
    safe_limit = max(0, min(int(limit), 50))
    title = _project_title(project, project_name) or "Project"
    slug = _slugify(title)
    raw_rel = f"raw/project-seeds/{slug}/project-context.md"
    source_rel = f"wiki/sources/project-seed-{slug}.md"
    raw_path = root / raw_rel
    source_path = root / source_rel

    included, skipped_large, blocked_secret, read_errors = _read_project_files(
        project,
        limit=safe_limit,
        max_file_bytes=max_file_bytes,
    )
    git_history = _git_history(project, git_log_limit) if include_git_log else {"included": False, "lines": [], "error": ""}
    decision_candidates = _adr_decision_candidates(included)

    status = "ok"
    if blocked_secret or read_errors:
        status = "needs_attention"
    elif not included:
        status = "empty"
    elif skipped_large or git_history.get("error"):
        status = "partial"

    would_write = bool(included) and not blocked_secret and not read_errors
    existing = [rel for rel, path in ((raw_rel, raw_path), (source_rel, source_path)) if path.exists()]
    if would_write and existing and not overwrite:
        status = "already_seeded"
        would_write = False

    wrote = False
    if would_write and not dry_run:
        _ensure_wiki_structure(root)
        raw_text = _format_raw_seed(
            project_title=title,
            project_slug=slug,
            project_root=project,
            included=included,
            git_history=git_history,
        )
        source_text = _format_source_page(
            project_title=title,
            project_slug=slug,
            raw_rel=raw_rel,
            included=included,
            git_history=git_history,
        )
        atomic_write_text(raw_path, raw_text)
        atomic_write_text(source_path, source_text)
        if rebuild:
            _rebuild_graph_indexes(root / "wiki")
        wrote = True

    next_commands = [
        f"lnk query \"what is this project about?\" {root}",
        f"lnk brief \"working on {title}\" {root}",
        f"lnk health {root}",
    ]
    if status == "already_seeded":
        next_commands.insert(0, f"lnk seed {project} {root} --overwrite")
    if status == "needs_attention":
        next_commands = [f"redact blocked project files, then rerun: lnk seed {project} {root}"]
    elif status == "empty":
        next_commands = ["add README.md, AGENTS.md, CLAUDE.md, .cursorrules, or agent rule files, then rerun seed"]
    return {
        "status": status,
        "target": str(root),
        "project_root": str(project),
        "project": slug,
        "project_title": title,
        "dry_run": dry_run,
        "overwrite": overwrite,
        "limit": safe_limit,
        "included_count": len(included),
        "skipped_large_count": len(skipped_large),
        "blocked_secret_count": len(blocked_secret),
        "read_error_count": len(read_errors),
        "git_log_included": bool(git_history.get("included")),
        "decision_candidates": decision_candidates,
        "git_log_error": git_history.get("error", ""),
        "existing": existing,
        "wrote": wrote,
        "raw_path": raw_rel,
        "source_page": source_rel,
        "included": _limited([{key: value for key, value in item.items() if key != "text"} for item in included]),
        "skipped_large": _limited(skipped_large),
        "blocked_secret": _limited(blocked_secret),
        "read_errors": _limited(read_errors),
        "next_prompt": f"query Link for {title} project context",
        "next_commands": next_commands,
    }


def render_seed_project_text(payload: dict[str, object]) -> tuple[int, str]:
    """Render a concise CLI report for project seeding."""
    lines = [
        f"Link project seed: {payload['project_root']}",
        f"Target: {payload['target']}",
        "",
        f"Status: {payload['status']}",
        f"Included files: {payload['included_count']}",
        f"Skipped large: {payload['skipped_large_count']}",
        f"Blocked for secrets: {payload['blocked_secret_count']}",
        f"Read errors: {payload['read_error_count']}",
    ]
    if payload.get("git_log_included"):
        lines.append("Recent git history: included")
    elif payload.get("git_log_error"):
        lines.append(f"Recent git history: skipped ({payload['git_log_error']})")
    candidates = payload.get("decision_candidates") if isinstance(payload.get("decision_candidates"), list) else []
    if candidates:
        lines.extend(["", f"Decision candidates found in ADRs ({len(candidates)}) — review with the user, nothing was saved:"])
        for candidate in candidates:
            lines.append(f"- {candidate.get('title')} ({candidate.get('path')})")
            # The command must be paste-safe: the full candidate text, shell
            # quoted. A display-truncated command would save a cut-off memory.
            memory_text = str(candidate.get("memory") or "")
            save_command = shlex.join([
                "lnk", "remember", memory_text,
                "--type", "decision",
                "--source", str(candidate.get("path") or ""),
            ])
            lines.append(f"  Save if approved: {save_command}")
    if payload.get("dry_run"):
        lines.append("Dry run: no files were written.")
    if payload.get("wrote"):
        lines.extend([
            "",
            "Created source-backed context:",
            f"- {payload['raw_path']}",
            f"- {payload['source_page']}",
        ])
    if payload.get("existing"):
        lines.append("")
        lines.append("Existing seed files:")
        for rel in payload.get("existing", []):  # type: ignore[assignment]
            lines.append(f"- {rel}")
    if payload.get("included"):
        lines.append("")
        lines.append("Included:")
        for item in payload.get("included", []):  # type: ignore[assignment]
            lines.append(f"- {item['path']}")
    if payload.get("blocked_secret"):
        lines.append("")
        lines.append("Blocked files:")
        for item in payload.get("blocked_secret", []):  # type: ignore[assignment]
            labels = ", ".join(str(label) for label in item.get("labels", []))
            lines.append(f"- {item['path']} ({labels})")
    if payload.get("skipped_large"):
        lines.append("")
        lines.append("Skipped large files:")
        for item in payload.get("skipped_large", []):  # type: ignore[assignment]
            lines.append(f"- {item['path']} ({item['size_bytes']} bytes)")
    lines.extend([
        "",
        "Next:",
        f"  Ask your agent: {payload['next_prompt']}",
        *[f"  Run: {command}" for command in payload.get("next_commands", [])],
    ])
    code = 0 if payload.get("status") in {"ok", "partial", "already_seeded"} else 1
    return code, "\n".join(lines)
