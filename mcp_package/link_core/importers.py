"""Bring scattered memory home: parse other tools' memory surfaces.

Link's pitch is memory that is not locked inside one vendor profile — so
day one should not start empty while the user's actual memory sits in
ChatGPT's export, `~/.claude/CLAUDE.md`, Cursor rules, or a hand-tended
`AGENTS.md`. Importers read those surfaces and return their text; the
curated miner turns each deliberate line into a proposal, and everything
lands in the capture inbox for review. Nothing is ever auto-accepted:
import is a faster way to fill the review queue, not a way around it.

Agents now keep memory of their own, each in a store no other agent reads.
Kiro's is a database of whole records (a title, a summary, why it matters,
how to apply it), so its unit carries those records as they are instead of
text to mine: each record becomes one proposal, never split into lines.
The database is opened read-only and never written.

Link's own instruction sections are excluded (importing them would echo
Link back into Link), and every unit passes the same secret scanning and
injection labeling as any other capture.
"""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path

from .agent_instructions import _SECTION_PATTERN

IMPORT_SOURCES = ("claude-code", "cursor", "codex", "kiro", "file")

# Kiro's memory types, mapped onto Link's. "Other" and anything newer is a note.
KIRO_TYPES = {"preference": "preference", "fact": "fact", "decision": "decision",
              "procedure": "procedure", "project": "project"}
KIRO_FIELDS = ("id", "memory_type", "scopes", "title", "summary", "content",
               "why", "how_to_apply", "rev_number", "updated_at")


class ImportError_(ValueError):
    """An import source could not be read."""


def _strip_link_sections(text: str) -> str:
    """Remove Link's own instruction section — never import ourselves."""
    return _SECTION_PATTERN.sub("", text).strip()


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            return text[end + 4:].lstrip("\n")
    return text


def claude_code_units(home: Path) -> list[dict[str, str]]:
    """Claude Code's memory surfaces: global CLAUDE.md + auto-memory files."""
    units: list[dict[str, str]] = []
    claude_md = home / ".claude" / "CLAUDE.md"
    text = _strip_link_sections(_read(claude_md))
    if text:
        units.append({"origin": str(claude_md), "label": "Claude Code · CLAUDE.md", "text": text})
    projects = home / ".claude" / "projects"
    if projects.is_dir():
        for memory_dir in sorted(projects.glob("*/memory")):
            parts: list[str] = []
            for page in sorted(memory_dir.glob("*.md")):
                if page.name == "MEMORY.md":
                    continue  # index file: pointers, not memory content
                body = _strip_frontmatter(_read(page)).strip()
                if body:
                    parts.append(body)
            if parts:
                units.append({
                    "origin": str(memory_dir),
                    "label": f"Claude Code · auto-memory ({memory_dir.parent.name})",
                    "text": "\n\n".join(parts),
                })
    return units


def cursor_units(home: Path) -> list[dict[str, str]]:
    """Cursor rules files, excluding Link's own rule."""
    units: list[dict[str, str]] = []
    rules = home / ".cursor" / "rules"
    if rules.is_dir():
        for rule in sorted(rules.iterdir()):
            if rule.suffix not in {".mdc", ".md"} or rule.name == "link.mdc":
                continue
            text = _strip_link_sections(_strip_frontmatter(_read(rule))).strip()
            if text:
                units.append({"origin": str(rule), "label": f"Cursor · {rule.name}", "text": text})
    return units


def codex_units(home: Path) -> list[dict[str, str]]:
    """The user's AGENTS.md, minus the Link section Link itself wrote, and
    the memory Codex consolidated for itself (`MEMORY.md` in its memories
    folder; the other files there are its working state)."""
    units: list[dict[str, str]] = []
    agents = home / "AGENTS.md"
    text = _strip_link_sections(_read(agents))
    if text:
        units.append({"origin": str(agents), "label": "Codex · AGENTS.md", "text": text})
    codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex").expanduser()
    for folder in ("memories_v2", "memories"):
        memory = codex_home / folder / "MEMORY.md"
        text = _strip_frontmatter(_read(memory)).strip()
        if text:
            units.append({"origin": str(memory), "label": f"Codex · {folder}/MEMORY.md", "text": text})
    return units


def _kiro_connect(database: Path) -> sqlite3.Connection:
    """Open Kiro's memory database without ever writing to it.

    With no write-ahead log beside it (Kiro is not running), the file on
    disk is the whole store, and reading it as immutable creates nothing in
    Kiro's folder. While Kiro runs, its newest writes sit in the log, so
    Link reads as one more read-only reader, the way SQLite shares a store;
    if that cannot open, it falls back to the file alone.
    """
    uri = database.resolve().as_uri()
    if not database.with_name(database.name + "-wal").exists():
        return sqlite3.connect(f"{uri}?immutable=1", uri=True)
    try:
        connection = sqlite3.connect(f"{uri}?mode=ro", uri=True)
        connection.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        return connection
    except sqlite3.Error:
        return sqlite3.connect(f"{uri}?immutable=1", uri=True)


def kiro_memory_records(home: Path) -> list[dict[str, str]]:
    """Kiro's own memories, as plain records, oldest first.

    Kiro does not document this database, so Link reads only the columns it
    knows by name and skips a store whose shape it does not recognise rather
    than guessing at it.
    """
    database = home / ".kiro" / "memories" / "memories.db"
    if not database.is_file():
        return []
    try:
        connection = _kiro_connect(database)
    except sqlite3.Error as exc:
        raise ImportError_(f"could not open Kiro's memory database: {exc}") from exc
    try:
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(memories)")}
        if not {"id", "title", "content"} <= columns:
            raise ImportError_(
                "Kiro's memory database has a layout Link does not recognise; nothing was read"
            )
        wanted = [field for field in KIRO_FIELDS if field in columns]
        order = "created_at, id" if "created_at" in columns else "id"
        rows = connection.execute(
            f"SELECT {', '.join(wanted)} FROM memories ORDER BY {order}"  # noqa: S608 - fixed names
        ).fetchall()
        scopes: dict[str, list[str]] = {}
        tables = {str(row[0]) for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "memory_scopes" in tables:
            for memory_id, scope in connection.execute("SELECT memory_id, scope FROM memory_scopes"):
                scopes.setdefault(str(memory_id), []).append(str(scope))
    except sqlite3.Error as exc:
        raise ImportError_(f"could not read Kiro's memory database: {exc}") from exc
    finally:
        connection.close()
    records: list[dict[str, str]] = []
    for row in rows:
        record = {field: "" if value is None else str(value) for field, value in zip(wanted, row)}
        listed = scopes.get(record["id"]) or [part.strip() for part in record.get("scopes", "").split(",")]
        record["scopes"] = ",".join(part for part in listed if part)
        records.append(record)
    return records


def kiro_project(scopes: str) -> str:
    """The repository a Kiro memory is fenced to, or "" when it is global.

    Kiro names a repository scope by its path or remote; Link names projects
    by the repository's folder name, which is the last part of either.
    """
    for scope in scopes.split(","):
        value = scope.strip().rstrip("/")
        if not value or value.lower() in {"global", "user", "all"}:
            continue
        value = value.split(":", 1)[1] if value.lower().startswith(("repo:", "repository:", "workspace:")) else value
        name = value.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        name = name[:-4] if name.endswith(".git") else name
        if name:
            return name
    return ""


def kiro_import_item(record: dict[str, str]) -> dict[str, str]:
    """One Kiro record as the proposal it becomes: nothing mined, nothing split.

    The summary leads (it is the claim recall shows), the content follows
    when it says more, and why / how to apply stay with it in Kiro's words.
    """
    def clean(value: str) -> str:
        return " ".join(str(value or "").split())

    summary, content = clean(record.get("summary", "")), clean(record.get("content", ""))
    lead = summary or content
    parts = [lead]
    if content and content != lead:
        parts.append(content)
    if clean(record.get("why", "")):
        parts.append(f"Why: {clean(record['why'])}")
    if clean(record.get("how_to_apply", "")):
        parts.append(f"How to apply: {clean(record['how_to_apply'])}")
    kind = clean(record.get("memory_type", "")).lower()
    project = kiro_project(record.get("scopes", ""))
    return {
        "origin": f"kiro:{record.get('id', '')}",
        "revision": clean(record.get("rev_number", "")),
        "updated_at": clean(record.get("updated_at", "")),
        "title": clean(record.get("title", "")),
        "memory": "\n\n".join(part for part in parts if part),
        "memory_type": KIRO_TYPES.get(kind, "note"),
        "scope": "project" if project else "user",
        "project": project,
    }


def kiro_units(home: Path) -> list[dict[str, object]]:
    """Kiro's memory store as one unit of whole records."""
    items = [item for item in (kiro_import_item(record) for record in kiro_memory_records(home))
             if item["memory"]]
    if not items:
        return []
    database = home / ".kiro" / "memories" / "memories.db"
    text = "\n\n".join(f"{item['title'] or 'Memory'}: {item['memory']}" for item in items)
    return [{"origin": str(database), "label": f"Kiro · memories ({len(items)})",
             "text": text, "records": items}]


def file_units(path: Path) -> list[dict[str, str]]:
    """Any plain text/markdown file — the ChatGPT copy-paste path.

    ChatGPT's saved memories have no stable export format across vendors
    and eras, but they all paste as one-statement-per-line text, which is
    exactly what the curated miner reads.
    """
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ImportError_(f"file not found: {resolved}")
    text = _read(resolved).strip()
    if not text:
        raise ImportError_(f"file is empty: {resolved}")
    return [{"origin": str(resolved), "label": f"file · {resolved.name}", "text": text}]


def collect_import_units(
    source: str,
    *,
    home: Path | None = None,
    file_path: Path | None = None,
) -> Sequence[Mapping[str, object]]:
    """Units of importable text for a source; empty when nothing is found."""
    base = (home or Path.home()).expanduser()
    if source == "claude-code":
        return claude_code_units(base)
    if source == "cursor":
        return cursor_units(base)
    if source == "codex":
        return codex_units(base)
    if source == "kiro":
        return kiro_units(base)
    if source == "file":
        if file_path is None:
            raise ImportError_("import from a file needs the file path")
        return file_units(file_path)
    raise ImportError_(
        f"unknown import source '{source}' (expected one of: {', '.join(IMPORT_SOURCES)})"
    )


def _origin_line(text: str) -> str:
    return " ".join(str(text or "").split()).rstrip(".").lower()


def origin_findings(
    records: Sequence[Mapping[str, object]],
    home: Path,
) -> dict[str, object]:
    """Has the place an imported memory came from changed since it was accepted?

    An accepted import records its origin: another agent's record and the
    revision read, or a file and the line taken from it. The agent keeps
    writing its own memory and people keep editing their files, so the
    origin can move on while Link's copy stays as it was. This reports, per
    memory, a record the agent revised or removed and a line that is no
    longer in its file. It reads; it never rewrites a memory, and never
    writes the agent's store.

    A memory whose origin cannot be read here (the agent is not installed,
    its store has a layout Link does not recognise) is counted as
    unchecked, not as fine.
    """
    from .memory import curated_candidate_lines

    kiro: dict[str, dict[str, str]] | None = None
    kiro_error = ""
    file_lines: dict[str, set[str] | None] = {}
    text: str | None
    findings: list[dict[str, str]] = []
    checked = unchecked = 0
    for record in records:
        origin = str(record.get("origin") or "").strip()
        if not origin:
            continue
        entry = {"name": str(record.get("name") or ""), "title": str(record.get("title") or ""),
                 "path": str(record.get("path") or ""), "origin": origin}
        if origin.startswith("kiro:"):
            if kiro is None and not kiro_error:
                try:
                    rows = kiro_memory_records(home)
                except (ImportError_, sqlite3.Error, OSError) as exc:
                    rows, kiro_error = [], str(exc) or exc.__class__.__name__
                if not rows and not kiro_error and not (home / ".kiro" / "memories" / "memories.db").is_file():
                    kiro_error = "Kiro's memory store is not on this machine"
                kiro = {f"kiro:{row.get('id', '')}": row for row in rows}
            if kiro_error:
                unchecked += 1
                continue
            checked += 1
            row = (kiro or {}).get(origin)
            if row is None:
                findings.append({**entry, "kind": "origin_removed",
                                 "evidence": "Kiro no longer has this record."})
                continue
            saved, current = str(record.get("origin_revision") or "").strip(), str(row.get("rev_number") or "").strip()
            if saved.isdigit() and current.isdigit() and int(current) > int(saved):
                now = str(kiro_import_item(row).get("memory") or "").splitlines()[0][:200]
                findings.append({**entry, "kind": "origin_revised",
                                 "evidence": f"Kiro revised this record (revision {saved} to {current}). It now says: {now}"})
        elif origin.startswith("file:"):
            name = origin[len("file:"):]
            path = Path(name).expanduser() if not name.startswith("~/") else home / name[2:]
            key = str(path)
            if key not in file_lines:
                if path.is_dir():
                    # Claude Code's auto memory: one file per memory, read
                    # the way the importer read it.
                    text = "\n\n".join(
                        _strip_frontmatter(_read(page)).strip()
                        for page in sorted(path.glob("*.md")) if page.name != "MEMORY.md")
                elif path.is_file():
                    text = _strip_link_sections(_strip_frontmatter(_read(path)))
                else:
                    text = None
                file_lines[key] = None if text is None else {
                    _origin_line(line) for line in curated_candidate_lines(text)}
            lines = file_lines[key]
            checked += 1
            if lines is None:
                findings.append({**entry, "kind": "origin_missing", "evidence": f"{name} is no longer there."})
                continue
            wanted = _origin_line(str(record.get("evidence") or record.get("tldr") or ""))
            if wanted and wanted not in lines:
                findings.append({**entry, "kind": "origin_line_gone",
                                 "evidence": f"The line it was taken from is no longer in {name}."})
        else:
            unchecked += 1
    return {"checked": checked, "unchecked": unchecked, "unchecked_reason": kiro_error, "findings": findings}
