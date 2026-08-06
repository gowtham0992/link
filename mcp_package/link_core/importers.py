"""Bring scattered memory home: parse other tools' memory surfaces.

Link's pitch is memory that is not locked inside one vendor profile — so
day one should not start empty while the user's actual memory sits in
ChatGPT's export, `~/.claude/CLAUDE.md`, Cursor rules, or a hand-tended
`AGENTS.md`. Importers read those surfaces and return their text; the
curated miner turns each deliberate line into a proposal, and everything
lands in the capture inbox for review. Nothing is ever auto-accepted:
import is a faster way to fill the review queue, not a way around it.

Link's own instruction sections are excluded (importing them would echo
Link back into Link), and every unit passes the same secret scanning and
injection labeling as any other capture.
"""
from __future__ import annotations

from pathlib import Path

from .agent_instructions import INSTRUCTION_MARKERS, _SECTION_PATTERN

IMPORT_SOURCES = ("claude-code", "cursor", "codex", "file")


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
    """The user's AGENTS.md, minus the Link section Link itself wrote."""
    agents = home / "AGENTS.md"
    text = _strip_link_sections(_read(agents))
    if not text:
        return []
    return [{"origin": str(agents), "label": "Codex · AGENTS.md", "text": text}]


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
) -> list[dict[str, str]]:
    """Units of importable text for a source; empty when nothing is found."""
    base = (home or Path.home()).expanduser()
    if source == "claude-code":
        return claude_code_units(base)
    if source == "cursor":
        return cursor_units(base)
    if source == "codex":
        return codex_units(base)
    if source == "file":
        if file_path is None:
            raise ImportError_("import from a file needs the file path")
        return file_units(file_path)
    raise ImportError_(
        f"unknown import source '{source}' (expected one of: {', '.join(IMPORT_SOURCES)})"
    )
