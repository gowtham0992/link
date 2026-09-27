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

An anchor also records which repository it belongs to - the root commit,
`path:line symbol @<root>` - because memories live in one store and are
recalled from many checkouts. An anchor is only ever checked inside the
repository it was written in; anywhere else it is simply not checked, so
`app.py` in one project never looks "deleted" from another. Paths are
repository-relative and cannot reach outside the checkout.
"""
from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

from .frontmatter import parse_frontmatter, update_frontmatter_fields
from .staleness import repo_identity, repo_path_references, safe_relative_path

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
            cwd=str(start or Path.cwd()), stdin=subprocess.DEVNULL, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=5, check=False,
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


_TOO_LARGE: list[str] = []  # sentinel: the file exists but is not read


def _read_lines(path: Path) -> list[str] | None:
    """The file's lines; `_TOO_LARGE` when it is too big to read; None when missing."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return _TOO_LARGE
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None


def _inside(repo_root: Path, rel: str) -> Path | None:
    """The file for a repository-relative path, or None if it would leave the checkout."""
    if not safe_relative_path(rel):
        return None
    root = repo_root.resolve()
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None  # a symlink pointing out of the repository
    return target


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


def find_anchors(text: str, repo_root: Path, identity: str | None = None) -> list[str]:
    """`path:line symbol @root` for every named file that contains a named symbol.

    No anchors without a repository identity (a fresh `git init` with no
    commits has none): an anchor that cannot say where it belongs could only
    ever be checked against the wrong repository.
    """
    symbols = symbol_candidates(text)
    if not symbols:
        return []
    if identity is None:
        roots = sorted(repo_identity(repo_root))
        identity = roots[0] if roots else ""
    if not identity:
        return []
    anchors: list[str] = []
    for rel in repo_path_references(text):
        path = _inside(repo_root, rel)
        if path is None or not path.is_file():
            continue
        lines = _read_lines(path)
        if not lines:
            continue
        for symbol in symbols:
            line = locate(lines, symbol)
            if line is not None:
                anchor = f"{rel}:{line} {symbol} @{identity}"
                if anchor not in anchors:
                    anchors.append(anchor)
            if len(anchors) >= MAX_ANCHORS:
                return anchors
    return anchors


_ANCHOR_RE = re.compile(
    r"^(?P<path>[^\s:]+):(?P<line>\d+)\s+(?P<symbol>[A-Za-z_][\w]*)(?:\s+@(?P<repo>[0-9a-f]{7,40}))?$"
)


def parse_anchor(anchor: str) -> tuple[str, int, str, str] | None:
    """(path, line, symbol, repository root commit or "") for one anchor string."""
    match = _ANCHOR_RE.match(str(anchor or "").strip())
    if not match or not safe_relative_path(match.group("path")):
        return None
    return match.group("path"), int(match.group("line")), match.group("symbol"), match.group("repo") or ""


def verify_anchors(
    anchors: Iterable[str],
    repo_root: Path,
    *,
    identity: set[str] | None = None,
    was_known: Callable[[str], bool] | None = None,
) -> list[dict[str, object]]:
    """Re-read each anchored file: holds, moved (with the new line), gone, or skipped.

    `skipped` is not a verdict: the anchor belongs to another repository (or
    predates repository identities), its path would leave the checkout, or
    the file is too large to read. `gone` for a missing file also needs git
    to confirm the file was ever tracked here, when `was_known` is given.
    """
    results: list[dict[str, object]] = []
    cache: dict[str, list[str] | None] = {}
    roots = identity if identity is not None else repo_identity(repo_root)
    for anchor in anchors:
        parsed = parse_anchor(anchor)
        if parsed is None:
            continue
        rel, line, symbol, repo = parsed

        def skipped(reason: str) -> dict[str, object]:
            return {"anchor": anchor, "path": rel, "symbol": symbol, "state": "skipped", "reason": reason}

        if not repo or not any(root.startswith(repo) or repo.startswith(root) for root in roots):
            results.append(skipped("other repository"))
            continue
        path = _inside(repo_root, rel)
        if path is None:
            results.append(skipped("outside the repository"))
            continue
        if rel not in cache:
            cache[rel] = _read_lines(path) if path.is_file() else None
        lines = cache[rel]
        if lines is _TOO_LARGE:
            results.append(skipped("file too large to read"))
            continue
        if lines is None:
            if was_known is not None and not was_known(rel):
                results.append(skipped("never tracked here"))
                continue
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
