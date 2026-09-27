"""Claim provenance: anchor memories about code to the lines they describe.

A memory that says "`parse_frontmatter` in link_core/frontmatter.py strips
quotes" is a claim about specific code. Staleness checks can tell when the
file disappears; they cannot tell when the function moved to another file,
or was deleted while the file stayed. An anchor can.

When a memory is written or updated inside a git checkout and it names a
repository file together with a symbol that appears in that file, Link
records where: `path:line symbol`, in the memory's `anchors` frontmatter.
Nothing is inferred by a model - the file is read, the symbol is found, the
line number is written down. Later the same code re-reads the file:

- the symbol is still on that line: the anchor holds;
- the symbol moved within the file: the anchor is `moved`, with the new line;
- the symbol is gone from the file, or the file is gone: the anchor is
  `gone`, and the memory is a question for its owner, not a fact.

Anchors are added only when both halves are present, so an ordinary
preference or decision never grows one. `LINK_ANCHORS=off` disables them.
"""
from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

from .frontmatter import parse_frontmatter, update_frontmatter_fields
from .staleness import repo_path_references

MAX_ANCHORS = 6
MAX_FILE_BYTES = 2_000_000

# Identifier shapes worth anchoring: backticked names, snake_case, camelCase,
# PascalCase with an inner capital, and call-shaped `name()`.
_BACKTICK_RE = re.compile(r"`([A-Za-z_][\w.]*)(?:\(\))?`")
_IDENTIFIER_RE = re.compile(
    r"(?<![\w./-])("
    r"[a-z_][a-z0-9]*(?:_[a-z0-9]+)+"          # snake_case (at least one underscore)
    r"|[a-z]+(?:[A-Z][a-z0-9]+)+"               # camelCase
    r"|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+"       # PascalCase with two humps
    r")(?:\(\))?(?![\w/-])"
)
_DEFINITION_TEMPLATE = (
    r"^\s*(?:export\s+|pub\s+|public\s+|private\s+|static\s+|async\s+)*"
    r"(?:def|class|function|func|fn|const|let|var|struct|interface|type|enum|trait|module)\s+{name}\b"
    r"|^\s*{name}\s*(?::[^=]*)?=(?!=)"
)


def anchors_enabled() -> bool:
    return os.environ.get("LINK_ANCHORS", "").strip().lower() not in {"off", "0", "false", "no"}


def detect_repo_root(start: Path | None = None) -> Path | None:
    """The git checkout the current process is working in, if any."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start or Path.cwd()), capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    return Path(completed.stdout.strip())


def symbol_candidates(text: str) -> list[str]:
    """Code identifiers a memory names, backticked ones first."""
    seen: list[str] = []
    for name in _BACKTICK_RE.findall(text or ""):
        name = name.split(".")[-1]
        if len(name) >= 3 and name not in seen:
            seen.append(name)
    for name in _IDENTIFIER_RE.findall(text or ""):
        if name not in seen:
            seen.append(name)
    return seen


def _read_lines(path: Path) -> list[str] | None:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None


def locate(lines: list[str], symbol: str) -> int | None:
    """1-based line of the symbol's definition, else its first whole-word use."""
    definition = re.compile(_DEFINITION_TEMPLATE.format(name=re.escape(symbol)))
    for index, line in enumerate(lines, start=1):
        if definition.search(line):
            return index
    word = re.compile(rf"(?<![\w]){re.escape(symbol)}(?![\w])")
    for index, line in enumerate(lines, start=1):
        if word.search(line):
            return index
    return None


def find_anchors(text: str, repo_root: Path) -> list[str]:
    """`path:line symbol` for every named file that contains a named symbol."""
    symbols = symbol_candidates(text)
    if not symbols:
        return []
    anchors: list[str] = []
    for rel in repo_path_references(text):
        path = repo_root / rel
        if not path.is_file():
            continue
        lines = _read_lines(path)
        if not lines:
            continue
        for symbol in symbols:
            line = locate(lines, symbol)
            if line is not None:
                anchor = f"{rel}:{line} {symbol}"
                if anchor not in anchors:
                    anchors.append(anchor)
            if len(anchors) >= MAX_ANCHORS:
                return anchors
    return anchors


_ANCHOR_RE = re.compile(r"^(?P<path>[^\s:]+):(?P<line>\d+)\s+(?P<symbol>[A-Za-z_][\w]*)$")


def parse_anchor(anchor: str) -> tuple[str, int, str] | None:
    match = _ANCHOR_RE.match(str(anchor or "").strip())
    if not match:
        return None
    return match.group("path"), int(match.group("line")), match.group("symbol")


def verify_anchors(anchors: Iterable[str], repo_root: Path) -> list[dict[str, object]]:
    """Re-read each anchored file: holds, moved (with the new line), or gone."""
    results: list[dict[str, object]] = []
    cache: dict[str, list[str] | None] = {}
    for anchor in anchors:
        parsed = parse_anchor(anchor)
        if parsed is None:
            continue
        rel, line, symbol = parsed
        if rel not in cache:
            path = repo_root / rel
            cache[rel] = _read_lines(path) if path.is_file() else None
        lines = cache[rel]
        if lines is None:
            results.append({"anchor": anchor, "path": rel, "symbol": symbol, "state": "gone",
                            "evidence": f"{rel} is no longer in the repository (anchored {symbol} at line {line})"})
            continue
        if 0 < line <= len(lines) and re.search(rf"(?<![\w]){re.escape(symbol)}(?![\w])", lines[line - 1]):
            results.append({"anchor": anchor, "path": rel, "symbol": symbol, "state": "holds", "line": line})
            continue
        found = locate(lines, symbol)
        if found is None:
            results.append({"anchor": anchor, "path": rel, "symbol": symbol, "state": "gone",
                            "evidence": f"{symbol} is no longer in {rel} (was at line {line})"})
        else:
            results.append({"anchor": anchor, "path": rel, "symbol": symbol, "state": "moved", "line": found,
                            "evidence": f"{symbol} moved from line {line} to {found} in {rel}"})
    return results


def add_anchors_to_page(page: str, claim_text: str, repo_root: Path | None = None) -> str:
    """Stamp `anchors:` into a memory page's frontmatter when the claim has any.

    Called from the memory write paths. Returns the page unchanged when
    anchors are disabled, there is no git checkout, or the claim names no
    file-and-symbol pair - so ordinary memories are untouched. On update,
    newly found anchors replace the old ones; if the new text names none,
    the existing anchors stay.
    """
    if not anchors_enabled():
        return page
    root = repo_root or detect_repo_root()
    if root is None:
        return page
    anchors = find_anchors(claim_text, root)
    if not anchors:
        return page
    return update_frontmatter_fields(page, {"anchors": anchors})


def page_anchors(page: str) -> list[str]:
    meta, _ = parse_frontmatter(page)
    value = meta.get("anchors")
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.strip("[]").split(",") if part.strip()]
    return []
