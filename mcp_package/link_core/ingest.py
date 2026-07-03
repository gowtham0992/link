"""Shared Link ingest status helpers."""
from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from .frontmatter import parse_frontmatter
from .mcp_verify import display_command
from .security import secret_file_scan
from .wiki import build_backlinks, load_backlinks_index


DEFAULT_SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "dist",
    "build",
    ".venv",
    "venv",
    "node_modules",
}

SOURCE_RAW_MATCH_CHUNK_SIZE = 256


def raw_source_files(raw_dir: Path, skip_dirs: set[str] | None = None) -> list[Path]:
    if not raw_dir.exists():
        return []
    skipped = skip_dirs or DEFAULT_SKIP_DIRS
    files: list[Path] = []
    for path in sorted(raw_dir.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        rel_parts = path.relative_to(raw_dir).parts
        if rel_parts and rel_parts[0] == "memory-captures":
            continue
        if any(part in skipped for part in rel_parts):
            continue
        files.append(path)
    return files


def source_page_texts(wiki_dir: Path) -> dict[str, str]:
    return {name: str(record["text"]) for name, record in source_page_index(wiki_dir).items()}


def _heading_title(body: str) -> str:
    match = re.search(r"^#\s+(.+)", body, re.MULTILINE)
    return match.group(1).strip() if match else ""


def source_page_index(
    wiki_dir: Path,
    read_warnings: list[dict[str, str]] | None = None,
) -> dict[str, dict[str, object]]:
    sources_dir = wiki_dir / "sources"
    if not sources_dir.exists():
        return {}
    records: dict[str, dict[str, object]] = {}
    for page in sorted(sources_dir.rglob("*.md")):
        if page.name.startswith("."):
            continue
        try:
            text = page.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            if read_warnings is not None:
                read_warnings.append({
                    "page": f"wiki/{page.relative_to(wiki_dir).as_posix()}",
                    "error": str(exc),
                })
            continue
        meta, body = parse_frontmatter(text)
        try:
            page_mtime = page.stat().st_mtime
        except OSError:
            page_mtime = 0.0
        name = page.stem.lower()
        records[name] = {
            "name": page.stem,
            "path": f"wiki/{page.relative_to(wiki_dir).as_posix()}",
            "title": str(meta.get("title") or _heading_title(body) or page.stem),
            "text": text,
            "mtime": page_mtime,
        }
    return records


def source_matches_by_raw(
    source_records: dict[str, dict[str, object]],
    raw_rels: list[str],
    *,
    chunk_size: int = SOURCE_RAW_MATCH_CHUNK_SIZE,
) -> dict[str, list[str]]:
    """Build raw path -> source page matches without an O(raw * source) scan."""
    matches: dict[str, list[str]] = {raw_rel: [] for raw_rel in raw_rels}
    if not source_records or not raw_rels:
        return matches

    unique_raw_rels = sorted(set(raw_rels), key=lambda value: (-len(value), value))
    safe_chunk_size = max(1, chunk_size)
    patterns = [
        re.compile("|".join(re.escape(raw_rel) for raw_rel in unique_raw_rels[index : index + safe_chunk_size]))
        for index in range(0, len(unique_raw_rels), safe_chunk_size)
    ]
    for source_name, source_record in source_records.items():
        text = str(source_record.get("text") or "")
        if not text:
            continue
        seen_in_source: set[str] = set()
        for pattern in patterns:
            for match in pattern.finditer(text):
                raw_rel = match.group(0)
                if raw_rel in seen_in_source:
                    continue
                seen_in_source.add(raw_rel)
                matches.setdefault(raw_rel, []).append(source_name)
    return matches


def normalize_link_index(data: dict[str, dict[str, list[str]]]) -> dict[str, dict[str, list[str]]]:
    normalized: dict[str, dict[str, list[str]]] = {"backlinks": {}, "forward": {}}
    for section in ("backlinks", "forward"):
        for key, values in data.get(section, {}).items():
            if isinstance(values, list):
                normalized[section][key.lower()] = sorted({str(value).lower() for value in values})
    return normalized


def backlinks_health(wiki_dir: Path) -> tuple[str, str]:
    current, load_error = load_backlinks_index(
        wiki_dir / "_backlinks.json",
        missing_error="missing wiki/_backlinks.json",
    )
    if load_error:
        return "missing" if "missing" in load_error else "invalid", load_error
    try:
        expected = build_backlinks(wiki_dir)
    except OSError as exc:
        return "invalid", f"could not inspect wiki pages for backlinks: {exc}"
    if current is not None and normalize_link_index(current) == normalize_link_index(expected):
        return "current", "wiki/_backlinks.json is current"
    return "stale", "wiki/_backlinks.json is stale"


def _source_page_suggestion(raw_rel: str) -> str:
    stem = Path(raw_rel).stem.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", stem).strip("-") or "source"
    return f"wiki/sources/{slug}.md"


def _target_command(command: str, target: str) -> str:
    if target and target in command:
        return command
    parts = command.split()
    if not parts or parts[0] not in {"link", "lnk"} or not target:
        return command
    if target in parts[1:]:
        return display_command(parts)
    return display_command([*parts, target])


def _target_commands(commands: object, target: str) -> list[str]:
    if not isinstance(commands, list):
        return []
    return [_target_command(str(command), target) for command in commands if str(command).strip()]


def _secret_blocked_items(items: list[dict[str, object]]) -> list[dict[str, object]]:
    return [item for item in items if item.get("secret_warnings")]


def _access_blocked_items(items: list[dict[str, object]]) -> list[dict[str, object]]:
    return [item for item in items if item.get("scan_error")]


def build_ingest_safety(
    pending_raw: list[dict[str, object]],
    represented_raw: list[dict[str, object]],
) -> dict[str, object]:
    """Summarize raw-source secret warning state for agents and UI."""
    secret_blocked = _secret_blocked_items(pending_raw)
    access_blocked = _access_blocked_items(pending_raw)
    blocked = secret_blocked + [item for item in access_blocked if item not in secret_blocked]
    represented_warnings = _secret_blocked_items(represented_raw)
    warning_items = blocked + represented_warnings
    label_set: set[str] = set()
    for item in warning_items:
        labels_for_item = item.get("secret_warnings")
        if isinstance(labels_for_item, list):
            label_set.update(str(label) for label in labels_for_item)
    labels = sorted(label_set)
    warning_count = sum(int(item.get("secret_warning_count") or 0) for item in warning_items)
    if access_blocked:
        status = "blocked"
        summary = f"{len(access_blocked)} pending raw file could not be inspected before ingest."
        if len(access_blocked) != 1:
            summary = f"{len(access_blocked)} pending raw files could not be inspected before ingest."
    elif secret_blocked:
        status = "blocked"
        summary = f"{len(secret_blocked)} pending raw file needs redaction before ingest."
        if len(secret_blocked) != 1:
            summary = f"{len(secret_blocked)} pending raw files need redaction before ingest."
    elif represented_warnings:
        status = "warning"
        summary = "Raw source warnings exist in already represented files."
    else:
        status = "clear"
        summary = "No secret-looking values detected in raw sources."
    return {
        "status": status,
        "summary": summary,
        "blocked_count": len(blocked),
        "access_blocked_count": len(access_blocked),
        "warning_count": warning_count,
        "labels": labels,
        "blocked_raw": [str(item.get("raw") or "") for item in blocked],
    }


def build_ingest_plan(status: dict[str, object], limit: int = 5) -> dict[str, object]:
    """Build a short, actionable ingest workflow for agents and humans."""
    guidance = status.get("guidance") if isinstance(status.get("guidance"), dict) else {}
    state = str(guidance.get("state") or "unknown")
    pending_raw = status.get("pending_raw") if isinstance(status.get("pending_raw"), list) else []
    ordered_pending_raw = sorted(
        pending_raw,
        key=lambda item: (0 if isinstance(item, dict) and item.get("stale") else 1, str(item.get("raw") or "")),
    )
    batch: list[dict[str, object]] = []
    for item in ordered_pending_raw[: max(limit, 1)]:
        raw_rel = str(item.get("raw") or "")
        if not raw_rel:
            continue
        batch_item = {
            "raw": raw_rel,
            "size_bytes": int(item.get("size_bytes") or 0),
            "suggested_source_page": _source_page_suggestion(raw_rel),
        }
        if item.get("stale"):
            source_page_paths = list(item.get("source_page_paths") or [])
            batch_item["stale"] = True
            batch_item["stale_reason"] = str(item.get("stale_reason") or "")
            batch_item["source_page_paths"] = source_page_paths
            if source_page_paths:
                batch_item["target_source_page"] = source_page_paths[0]
        batch.append(batch_item)

    if state == "pending_raw" and batch:
        first = batch[0]
        batch_count = len(batch)
        file_label = "file" if batch_count == 1 else "files"
        return {
            "state": state,
            "title": "Ingest pending raw sources",
            "summary": f"Start with {first['raw']} and process at most {batch_count} {file_label} in this pass.",
            "batch": batch,
            "steps": [
                "Read each raw file completely before writing wiki pages.",
                "Create or update one source page per raw file and include the exact raw path.",
                "Update existing concept/entity/memory pages before creating new thin pages.",
                "Keep durable memories proposal-only until the human approves them.",
                "Rebuild index and backlinks, then validate before reporting ingest complete.",
            ],
            "agent_prompt": guidance.get("agent_prompt"),
            "memory_prompt": f"propose memories from {first['raw']}",
            "post_checks": [
                "lnk rebuild-index",
                "lnk rebuild-backlinks",
                "lnk validate",
                "lnk health",
            ],
        }

    if state == "stale_raw" and batch:
        first = batch[0]
        batch_count = len(batch)
        file_label = "file" if batch_count == 1 else "files"
        return {
            "state": state,
            "title": "Refresh stale source pages",
            "summary": f"Start with {first['raw']} and refresh at most {batch_count} stale raw {file_label} in this pass.",
            "batch": batch,
            "steps": [
                "Read each changed raw file completely before editing wiki pages.",
                "Update the existing source page rather than creating a duplicate page.",
                "Update affected concept/entity pages only where the source materially changed.",
                "Keep durable memories proposal-only until the human approves them.",
                "Rebuild index and backlinks, then validate before reporting ingest complete.",
            ],
            "agent_prompt": guidance.get("agent_prompt"),
            "memory_prompt": f"propose memories from {first['raw']}",
            "post_checks": [
                "lnk rebuild-index",
                "lnk rebuild-backlinks",
                "lnk validate",
                "lnk health",
            ],
        }

    if state == "blocked_secrets":
        blocked = _secret_blocked_items(pending_raw)
        first = blocked[0] if blocked else {"raw": "raw/<file>"}
        return {
            "state": state,
            "title": "Redact raw sources before ingest",
            "summary": f"Start with {first['raw']}; Link will not suggest ingesting secret-looking raw content.",
            "batch": [
                {
                    "raw": str(item.get("raw") or ""),
                    "size_bytes": int(item.get("size_bytes") or 0),
                    "secret_warnings": list(item.get("secret_warnings") or []),
                    "suggested_source_page": _source_page_suggestion(str(item.get("raw") or "")),
                }
                for item in blocked[: max(limit, 1)]
            ],
            "steps": [
                "Open each flagged raw file locally.",
                "Remove or redact the secret-looking values before asking any agent to ingest it.",
                "Refresh ingest status after redaction.",
                "Only then ask the agent to create source-backed wiki pages.",
            ],
            "agent_prompt": None,
            "memory_prompt": None,
            "post_checks": ["lnk ingest-status", "lnk health"],
        }

    if state == "blocked_raw_access":
        blocked = _access_blocked_items(pending_raw)
        first = blocked[0] if blocked else {"raw": "raw/<file>"}
        return {
            "state": state,
            "title": "Inspect raw source access",
            "summary": f"Start with {first['raw']}; Link could not read it to run safety checks.",
            "batch": [
                {
                    "raw": str(item.get("raw") or ""),
                    "size_bytes": int(item.get("size_bytes") or 0),
                    "scan_error": str(item.get("scan_error") or ""),
                    "suggested_source_page": _source_page_suggestion(str(item.get("raw") or "")),
                }
                for item in blocked[: max(limit, 1)]
            ],
            "steps": [
                "Check the file still exists and is readable by the local user.",
                "Fix permissions or move the source to a readable raw/ file.",
                "Refresh ingest status before asking an agent to ingest it.",
                "Only ingest after Link can inspect the raw source for secret-looking values.",
            ],
            "agent_prompt": None,
            "memory_prompt": None,
            "post_checks": ["lnk ingest-status", "lnk health"],
        }

    if state == "blocked_source_access":
        warnings = status.get("source_read_warnings") if isinstance(status.get("source_read_warnings"), list) else []
        first = warnings[0] if warnings and isinstance(warnings[0], dict) else {"page": "wiki/sources/<page>.md"}
        return {
            "state": state,
            "title": "Inspect source page access",
            "summary": f"Start with {first['page']}; Link could not read one or more source pages.",
            "batch": [
                {
                    "page": str(item.get("page") or ""),
                    "error": str(item.get("error") or ""),
                }
                for item in warnings[: max(limit, 1)]
                if isinstance(item, dict)
            ],
            "steps": [
                "Check that the source page still exists and is readable by the local user.",
                "Fix permissions or repair the page before relying on represented/pending raw counts.",
                "Refresh ingest status after the page is readable.",
                "Run validation before reporting ingest complete.",
            ],
            "agent_prompt": None,
            "memory_prompt": None,
            "post_checks": ["lnk ingest-status", "lnk validate", "lnk health"],
        }

    if state == "stale_graph":
        return {
            "state": state,
            "title": "Repair graph index",
            "summary": "Raw sources are represented, but the graph index is stale.",
            "batch": [],
            "steps": [
                "Run the graph repair before relying on search, context, or graph views.",
                "Validate the wiki after rebuilding backlinks.",
            ],
            "agent_prompt": guidance.get("agent_prompt"),
            "post_checks": ["lnk rebuild-backlinks", "lnk validate", "lnk health"],
        }

    if state == "empty":
        return {
            "state": state,
            "title": "Add first sources",
            "summary": "Drop notes, articles, transcripts, screenshots, or project files into raw/.",
            "batch": [],
            "steps": [
                "Add one or more source files to raw/.",
                "Ask your agent to ingest the specific raw file.",
                "Review generated pages before relying on them as memory.",
            ],
            "agent_prompt": None,
            "post_checks": ["lnk ingest-status", "lnk health"],
        }

    if state == "ready":
        return {
            "state": state,
            "title": "Ready for new sources",
            "summary": "All current raw sources are represented and the graph index is current.",
            "batch": [],
            "steps": [
                "Use query or brief for retrieval.",
                "Add new files to raw/ when Link should learn new source-backed context.",
            ],
            "agent_prompt": None,
            "post_checks": ["lnk doctor", "lnk health"],
        }

    return {
        "state": state,
        "title": "Initialize Link",
        "summary": "Link needs its raw/ and wiki/ structure before ingest can start.",
        "batch": [],
        "steps": [
            "Run lnk init or rerun an installer.",
            "Check readiness before adding sources.",
        ],
        "agent_prompt": None,
        "post_checks": ["lnk init", "lnk health"],
    }


def build_ingest_completion(status: dict[str, object], limit: int = 8) -> dict[str, object]:
    """Summarize raw files that are already represented in source pages."""
    represented_raw = status.get("represented_raw") if isinstance(status.get("represented_raw"), list) else []
    pending_count = int(status.get("pending_count") or 0)
    represented_count = int(status.get("represented_count") or 0)
    guidance = status.get("guidance") if isinstance(status.get("guidance"), dict) else {}
    items: list[dict[str, object]] = []
    for item in represented_raw[: max(limit, 1)]:
        raw_rel = str(item.get("raw") or "")
        page_names = item.get("source_pages") if isinstance(item.get("source_pages"), list) else []
        page_paths = item.get("source_page_paths") if isinstance(item.get("source_page_paths"), list) else []
        page_titles = item.get("source_page_titles") if isinstance(item.get("source_page_titles"), list) else []
        pages: list[dict[str, str]] = []
        for index, page_name in enumerate(page_names):
            pages.append({
                "name": str(page_name),
                "path": str(page_paths[index]) if index < len(page_paths) else "",
                "title": str(page_titles[index]) if index < len(page_titles) else str(page_name),
            })
        items.append({
            "raw": raw_rel,
            "size_bytes": int(item.get("size_bytes") or 0),
            "source_pages": pages,
            "memory_prompt": f"propose memories from {raw_rel}" if raw_rel else "",
            "query_prompt": f"query Link for {Path(raw_rel).stem.replace('-', ' ')}" if raw_rel else "",
            "secret_warnings": list(item.get("secret_warnings") or []),
            "scan_error": str(item.get("scan_error") or ""),
        })

    if represented_count and pending_count:
        summary = f"{represented_count} raw source(s) are represented; {pending_count} still need ingest."
        next_prompt = str(guidance.get("agent_prompt") or "")
    elif represented_count:
        summary = f"All {represented_count} raw source(s) are represented in wiki source pages."
        next_prompt = 'start with Link before we continue'
    else:
        summary = "No raw source files are represented yet."
        next_prompt = str(guidance.get("agent_prompt") or "ingest raw/<file> into Link")

    return {
        "title": "Ingest completion",
        "summary": summary,
        "represented_count": represented_count,
        "pending_count": pending_count,
        "shown_count": len(items),
        "has_more": represented_count > len(items),
        "items": items,
        "next_prompt": next_prompt,
    }


def render_ingest_status_text(target: str, status: dict[str, object]) -> str:
    """Render human-readable ingest status output."""
    lines = [f"Link ingest status: {target}", ""]
    if not status["has_raw_dir"]:
        lines.append("Missing raw/ directory")
    if not status["has_wiki_dir"]:
        lines.append("Missing wiki/ directory")
    if not status["has_raw_dir"] or not status["has_wiki_dir"]:
        lines.extend(["", "Next:", f"  Run an installer or initialize this directory: {_target_command('lnk init', target)}"])
        return "\n".join(lines)

    lines.append(f"Raw files: {status['raw_count']}")
    lines.append(f"Source pages: {status['source_page_count']}")
    if int(status.get("source_read_warning_count") or 0):
        lines.append(f"Source page read warnings: {status['source_read_warning_count']}")
    lines.append(f"Represented in wiki/sources: {status['represented_count']}")
    lines.append(f"Pending ingest: {status['pending_count']}")
    if int(status.get("stale_count") or 0):
        lines.append(f"Stale represented raw: {status['stale_count']}")
    lines.append(f"Backlinks: {status['backlinks_status']} ({status['backlinks_message']})")
    safety = status.get("safety") if isinstance(status.get("safety"), dict) else {}
    if safety:
        lines.append(f"Safety: {safety.get('status')} ({safety.get('summary')})")
    guidance = status["guidance"]
    if isinstance(guidance, dict):
        lines.append(f"Guidance: {guidance['summary']}")

    pending_raw = status["pending_raw"]
    if pending_raw:
        lines.extend(["", "Pending raw files:"])
        for item in pending_raw[:20]:
            warnings = item.get("secret_warnings") if isinstance(item.get("secret_warnings"), list) else []
            scan_error = str(item.get("scan_error") or "")
            if scan_error:
                lines.append(f"- {item['raw']} [fix access before ingest: {scan_error}]")
            elif warnings:
                labels = ", ".join(str(label) for label in warnings)
                lines.append(f"- {item['raw']} [redact before ingest: {labels}]")
            elif item.get("stale"):
                reason = str(item.get("stale_reason") or "raw changed after wiki source page")
                lines.append(f"- {item['raw']} [refresh source page: {reason}]")
            else:
                lines.append(f"- {item['raw']}")
        if len(pending_raw) > 20:
            lines.append(f"- ... {len(pending_raw) - 20} more")
    source_warnings = status.get("source_read_warnings") if isinstance(status.get("source_read_warnings"), list) else []
    if source_warnings:
        lines.extend(["", "Source page warnings:"])
        for item in source_warnings[:20]:
            if isinstance(item, dict):
                lines.append(f"- {item.get('page')} [fix access: {item.get('error')}]")

    lines.extend(["", "Next:"])
    if isinstance(guidance, dict):
        agent_prompt = guidance.get("agent_prompt")
        if agent_prompt:
            lines.append(f"  Ask your agent: {agent_prompt}")
        for command in _target_commands(guidance.get("commands", []), target):
            lines.append(f"  Run: {command}")
        notes = guidance.get("notes") or []
        for note in notes[:2]:
            lines.append(f"  Note: {note}")

    plan = status.get("plan") if isinstance(status.get("plan"), dict) else {}
    steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    batch = plan.get("batch") if isinstance(plan.get("batch"), list) else []
    post_checks = plan.get("post_checks") if isinstance(plan.get("post_checks"), list) else []
    if plan:
        lines.extend(["", f"Suggested workflow: {plan.get('title')}"])
        summary = plan.get("summary")
        if summary:
            lines.append(f"  {summary}")
        memory_prompt = plan.get("memory_prompt")
        if memory_prompt:
            lines.append(f"  Memory review: {memory_prompt}")
        for index, step in enumerate(steps[:6], start=1):
            lines.append(f"  {index}. {step}")
        if batch:
            lines.append("  Batch:")
            for item in batch[:5]:
                subject = item.get("raw") or item.get("page") or ""
                target_page = item.get("target_source_page") or item.get("suggested_source_page") or item.get("error") or ""
                lines.append(f"  - {subject} -> {target_page}")
        if post_checks:
            lines.append("  Post-ingest checks:")
            for check in _target_commands(post_checks[:6], target):
                lines.append(f"  - {check}")

    completion = status.get("completion") if isinstance(status.get("completion"), dict) else {}
    completion_items = completion.get("items") if isinstance(completion.get("items"), list) else []
    if completion_items:
        lines.extend(["", f"Ingest completion: {completion.get('summary')}"])
        for item in completion_items[:8]:
            pages = item.get("source_pages") if isinstance(item.get("source_pages"), list) else []
            page_labels = []
            for page in pages:
                if isinstance(page, dict):
                    label = page.get("path") or page.get("name")
                    if label:
                        page_labels.append(str(label))
            target_pages = ", ".join(page_labels) if page_labels else "source page missing"
            lines.append(f"  - {item.get('raw')} -> {target_pages}")
            memory_prompt = item.get("memory_prompt")
            if memory_prompt:
                lines.append(f"    Memory review: {memory_prompt}")
            query_prompt = item.get("query_prompt")
            if query_prompt:
                lines.append(f"    Retrieval check: {query_prompt}")
        if completion.get("has_more"):
            represented_count = int(completion.get("represented_count") or 0)
            shown_count = int(completion.get("shown_count") or 0)
            lines.append(f"  ... {represented_count - shown_count} more represented raw source(s)")
        next_prompt = completion.get("next_prompt")
        if next_prompt:
            lines.append(f"  Next check: {next_prompt}")

    return "\n".join(lines)


def build_ingest_guidance(status: dict[str, object]) -> dict[str, object]:
    has_raw_dir = bool(status.get("has_raw_dir"))
    has_wiki_dir = bool(status.get("has_wiki_dir"))
    pending_raw = status.get("pending_raw")
    pending_items = pending_raw if isinstance(pending_raw, list) else []
    pending_count = int(status.get("pending_count") or 0)
    raw_count = int(status.get("raw_count") or 0)
    backlinks_status = str(status.get("backlinks_status") or "unknown")
    source_read_warning_count = int(status.get("source_read_warning_count") or 0)
    secret_items = _secret_blocked_items(pending_items)
    access_items = _access_blocked_items(pending_items)
    stale_items = [item for item in pending_items if isinstance(item, dict) and item.get("stale")]

    if not has_raw_dir or not has_wiki_dir:
        return {
            "state": "missing_structure",
            "summary": "Link is not initialized here yet.",
            "agent_prompt": None,
            "commands": ["lnk init", "lnk health"],
            "notes": ["Run the installer or initialize this directory before ingesting sources."],
        }

    if source_read_warning_count:
        return {
            "state": "blocked_source_access",
            "summary": f"{source_read_warning_count} source page could not be inspected. Fix source page access before ingest.",
            "agent_prompt": None,
            "commands": ["lnk ingest-status", "lnk validate", "lnk health"],
            "notes": [
                "Represented and pending raw counts may be incomplete while source pages cannot be read.",
                "Fix permissions or repair the page, then refresh ingest status.",
            ],
        }

    if access_items:
        first = str(access_items[0].get("raw", "raw/<file>"))
        count = len(access_items)
        summary = f"{count} pending raw file could not be inspected."
        if count != 1:
            summary = f"{count} pending raw files could not be inspected."
        return {
            "state": "blocked_raw_access",
            "summary": summary + f" Fix access for {first} before ingest.",
            "agent_prompt": None,
            "commands": ["lnk ingest-status", "lnk health"],
            "notes": [
                "Do not ask an agent to ingest raw files that Link cannot read and scan for secret-looking values.",
                "Fix permissions or replace the file, then refresh ingest status.",
            ],
        }

    if secret_items:
        first = str(secret_items[0].get("raw", "raw/<file>"))
        count = len(secret_items)
        summary = f"{count} pending raw file contains secret-looking values."
        if count != 1:
            summary = f"{count} pending raw files contain secret-looking values."
        return {
            "state": "blocked_secrets",
            "summary": summary + f" Redact {first} before ingest.",
            "agent_prompt": None,
            "commands": ["lnk ingest-status", "lnk health"],
            "notes": [
                "Do not ask an agent to ingest flagged raw files until the secret-looking values are removed or redacted.",
                "After redaction, refresh ingest status and continue with the normal ingest prompt.",
            ],
        }

    if stale_items:
        first = str(stale_items[0].get("raw", "raw/<file>"))
        count = len(stale_items)
        summary = f"{count} represented raw file changed after its source page was written."
        if count != 1:
            summary = f"{count} represented raw files changed after their source pages were written."
        return {
            "state": "stale_raw",
            "summary": summary,
            "agent_prompt": f"re-ingest {first} into Link",
            "commands": ["lnk rebuild-index", "lnk rebuild-backlinks", "lnk validate", "lnk health"],
            "notes": [
                "The raw file is represented, but it is newer than the linked source page.",
                "Ask the agent to refresh the existing source page before relying on retrieval.",
            ],
        }

    if pending_items:
        first = str(pending_items[0].get("raw", "raw/<file>"))
        more = pending_count - 1
        summary = f"{pending_count} raw file needs ingest."
        if pending_count != 1:
            summary = f"{pending_count} raw files need ingest."
        if more > 0:
            summary += f" Start with {first}; {more} more remain."
        return {
            "state": "pending_raw",
            "summary": summary,
            "agent_prompt": f"ingest {first} into Link",
            "commands": ["lnk rebuild-index", "lnk rebuild-backlinks", "lnk validate", "lnk health"],
            "notes": [
                "If the source contains user preferences, decisions, or project context, ask for memory proposals before saving durable memories.",
                "After ingest, rebuild index/backlinks if your agent did not already do it.",
            ],
        }

    if backlinks_status != "current":
        return {
            "state": "stale_graph",
            "summary": "Raw files are represented, but the graph index needs repair.",
            "agent_prompt": "rebuild Link backlinks and validate the wiki",
            "commands": ["lnk rebuild-backlinks", "lnk validate", "lnk doctor"],
            "notes": ["Run the graph repair before relying on context or graph views."],
        }

    if raw_count == 0:
        return {
            "state": "empty",
            "summary": "Link is ready, but raw/ has no source files yet.",
            "agent_prompt": None,
            "commands": ["lnk health", "lnk serve"],
            "notes": ["Drop notes, articles, transcripts, or project files into raw/, then ask your agent to ingest them into Link."],
        }

    return {
        "state": "ready",
        "summary": "All raw files are represented in wiki/sources and the graph index is current.",
        "agent_prompt": None,
        "commands": ["lnk doctor", "lnk health"],
        "notes": ["Add new files to raw/ when you want Link to learn new source-backed knowledge."],
    }


def collect_ingest_status(target: Path, skip_dirs: set[str] | None = None) -> dict[str, object]:
    target = target.expanduser().resolve()
    raw_dir = target / "raw"
    wiki_dir = target / "wiki"
    raw_files = raw_source_files(raw_dir, skip_dirs=skip_dirs)
    source_read_warnings: list[dict[str, str]] = []
    source_records = source_page_index(wiki_dir, read_warnings=source_read_warnings)
    raw_rels = [raw_path.relative_to(target).as_posix() for raw_path in raw_files]
    source_matches = source_matches_by_raw(source_records, raw_rels)

    represented_raw: list[dict[str, object]] = []
    pending_raw: list[dict[str, object]] = []
    raw_secret_warning_count = 0
    raw_scan_warnings: list[dict[str, str]] = []
    stale_raw: list[dict[str, object]] = []
    for raw_path, rel in zip(raw_files, raw_rels):
        matches = source_matches.get(rel, [])
        match_records = [source_records[source_name] for source_name in matches]
        scan = secret_file_scan(raw_path)
        warnings = list(scan.get("labels") or [])
        scan_error = str(scan.get("error") or "")
        raw_secret_warning_count += len(warnings)
        raw_mtime = 0.0
        try:
            raw_stat = raw_path.stat()
            size_bytes = raw_stat.st_size
            raw_mtime = raw_stat.st_mtime
        except OSError as exc:
            size_bytes = 0
            if not scan_error:
                scan_error = str(exc)
        source_mtimes = [
            float(record.get("mtime") or 0)
            for record in match_records
            if record.get("mtime") is not None
        ]
        latest_source_mtime = max(source_mtimes) if source_mtimes else 0.0
        is_stale = bool(matches and raw_mtime and latest_source_mtime and raw_mtime > latest_source_mtime + 0.001)
        if scan_error:
            raw_scan_warnings.append({"raw": rel, "error": scan_error})
        item = {
            "raw": rel,
            "size_bytes": size_bytes,
            "source_pages": matches,
            "source_page_paths": [str(record.get("path") or "") for record in match_records],
            "source_page_titles": [str(record.get("title") or record.get("name") or "") for record in match_records],
            "secret_warnings": warnings,
            "secret_warning_count": len(warnings),
            "readable": not bool(scan_error),
            "scan_error": scan_error,
            "stale": is_stale,
            "stale_reason": "raw changed after wiki source page" if is_stale else "",
            "raw_mtime": raw_mtime,
            "latest_source_mtime": latest_source_mtime,
        }
        if is_stale:
            stale_raw.append(item)
            pending_raw.append(item)
        elif matches:
            represented_raw.append(item)
        else:
            pending_raw.append(item)

    backlinks_status, backlinks_message = (
        backlinks_health(wiki_dir)
        if wiki_dir.exists()
        else ("missing", "missing wiki directory")
    )

    payload: dict[str, object] = {
        "target": str(target),
        "raw_count": len(raw_files),
        "source_page_count": len(source_records),
        "source_read_warning_count": len(source_read_warnings),
        "source_read_warnings": source_read_warnings,
        "represented_count": len(represented_raw),
        "pending_count": len(pending_raw),
        "stale_count": len(stale_raw),
        "stale_raw": stale_raw,
        "represented_raw": represented_raw,
        "pending_raw": pending_raw,
        "raw_secret_warning_count": raw_secret_warning_count,
        "raw_scan_warning_count": len(raw_scan_warnings),
        "raw_scan_warnings": raw_scan_warnings,
        "backlinks_status": backlinks_status,
        "backlinks_message": backlinks_message,
        "has_raw_dir": raw_dir.exists(),
        "has_wiki_dir": wiki_dir.exists(),
    }
    payload["safety"] = build_ingest_safety(pending_raw, represented_raw)
    payload["guidance"] = build_ingest_guidance(payload)
    payload["plan"] = build_ingest_plan(payload)
    payload["completion"] = build_ingest_completion(payload)
    guidance = payload.get("guidance") if isinstance(payload.get("guidance"), dict) else {}
    if guidance:
        guidance["commands"] = _target_commands(guidance.get("commands"), str(target))
    plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
    if plan:
        plan["post_checks"] = _target_commands(plan.get("post_checks"), str(target))
    return payload


def raw_ingest_findings(status: Mapping[str, object]) -> dict[str, list[str]]:
    """Classify pending raw files for doctor-style health warnings."""
    pending = status.get("pending_raw") if isinstance(status.get("pending_raw"), list) else []
    findings: dict[str, list[str]] = {
        "new": [],
        "stale": [],
        "blocked": [],
    }
    for item in pending:
        if not isinstance(item, Mapping):
            continue
        raw_rel = str(item.get("raw") or "")
        if not raw_rel:
            continue
        if item.get("scan_error") or item.get("secret_warnings"):
            findings["blocked"].append(raw_rel)
        elif item.get("stale"):
            findings["stale"].append(raw_rel)
        else:
            findings["new"].append(raw_rel)
    return {key: sorted(values) for key, values in findings.items()}
