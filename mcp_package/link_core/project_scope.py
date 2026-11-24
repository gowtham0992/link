"""Project names, filename slugs and applies_when fences.

The small, dependency-free part of the memory model that every tool call
needs: which project a directory belongs to, how a project name is
normalised, whether a memory is visible in a project, and how an
`applies_when` fence parses. It lives apart from memory.py so the pre-tool
hook, which runs before every shell command and file access, can decide
without loading the whole memory module.
"""
from __future__ import annotations

import functools
import re
import unicodedata
from collections.abc import Mapping
from pathlib import Path


# Letters carrying no Unicode decomposition that still need a Latin
# equivalent, so "Größe" and "grosse" reach the same token.
_TOKEN_FOLD_PAIRS = {
    "ß": "ss", "æ": "ae", "œ": "oe", "ø": "o",
    "đ": "d", "ł": "l", "ð": "d", "þ": "th", "ı": "i",
}
_TOKEN_MARKS = {"Mn", "Mc"}

def _compose(value: str) -> str:
    """Recompose a token after NFKD.

    NFKD splits Hangul syllables into conjoining jamo, so a Korean word would
    be stored decomposed. Retrieval would still match, since queries decompose
    the same way, but the tokens belong in the form a person would recognise.
    """
    return unicodedata.normalize("NFC", value)

def _slug_fold(value: str) -> str:
    """Fold a title for use as a filename, keeping every script readable.

    Same rules as the tokenizer: lowercase, Latin accents removed so "Zürich"
    files as zurich, combining marks in Indic and other scripts kept because
    they are vowels, everything that is not a letter, digit, or mark becomes a
    separator. Han, kana, Hangul, Cyrillic, Arabic and the rest survive as
    themselves; a Japanese title becomes a Japanese filename.
    """
    lowered = value.lower()
    for source, replacement in _TOKEN_FOLD_PAIRS.items():
        if source in lowered:
            lowered = lowered.replace(source, replacement)
    out: list[str] = []
    base_is_latin = False
    for character in unicodedata.normalize("NFKD", lowered):
        if unicodedata.category(character) in _TOKEN_MARKS:
            if not base_is_latin:
                out.append(character)
            continue
        if character.isalnum():
            base_is_latin = character.isascii()
            out.append(character)
            continue
        base_is_latin = False
        out.append("-")
    return _compose("".join(out))

def slugify(value: str, fallback: str = "memory", max_len: int = 80) -> str:
    """Filename-safe name for a memory page.

    ASCII titles keep their exact historical slugs. Titles in other scripts
    used to slug to nothing and land on the bare fallback, so every non-Latin
    memory was called memory.md and the second one was refused as a duplicate
    of the first. They now keep their own script (accents folded for Latin).
    """
    if value.isascii():
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    else:
        slug = re.sub(r"-+", "-", _slug_fold(value)).strip("-")
    if len(slug.encode("utf-8")) > max_len:
        # Cap in bytes for filesystem limits (255-byte filenames; a CJK
        # character is three bytes); cut at a word boundary so truncated
        # slugs stay readable.
        head = slug.encode("utf-8")[:max_len].decode("utf-8", "ignore")
        slug = head.rsplit("-", 1)[0] if "-" in head else head
    return slug.strip("-") or fallback

def normalize_project(value: str | None) -> str:
    return _normalize_project_cached(value or "")


@functools.lru_cache(maxsize=4096)
def _normalize_project_cached(value: str) -> str:
    return slugify(value, fallback="")

def default_project_for_target(target: Path) -> str:
    resolved = target.expanduser().resolve()
    if resolved.name == "wiki" and (resolved / "index.md").exists():
        resolved = resolved.parent
    if (resolved / ".git").exists():
        return normalize_project(_main_checkout_name(resolved))
    return ""

def _main_checkout_name(checkout: Path) -> str:
    """The project a git worktree belongs to: the main checkout's folder name, not the worktree's.

    A linked worktree (`git worktree add ../app-hotfix`, Claude Code's
    `.claude/worktrees/<name>`) has a `.git` file pointing at
    `<main>/.git/worktrees/<id>`; named by its own folder, the project's
    rules and memories would stop applying in it. A submodule's `.git` file
    points at `.git/modules/...` and keeps its own name. Read from the files:
    no git process.
    """
    marker = checkout / ".git"
    if not marker.is_file():
        return checkout.name
    try:
        line = marker.read_text(encoding="utf-8", errors="replace").strip().splitlines()[0]
    except (OSError, IndexError):
        return checkout.name
    if not line.startswith("gitdir:"):
        return checkout.name
    gitdir = Path(line[len("gitdir:"):].strip())
    if not gitdir.is_absolute():
        gitdir = checkout / gitdir
    try:
        common = gitdir / (gitdir / "commondir").read_text(encoding="utf-8").strip()
    except OSError:
        # Linked worktrees always live in <common dir>/worktrees/<id>.
        if gitdir.parent.name != "worktrees":
            return checkout.name
        common = gitdir.parent.parent
    try:
        common = common.resolve()
    except (OSError, ValueError):
        return checkout.name
    if common.name == ".git":
        return common.parent.name
    # A bare repository (`app.git`) with its worktrees beside it.
    return common.name[:-4] if common.name.endswith(".git") and len(common.name) > 4 else common.name

def memory_visible_for_project(record: Mapping[str, object], project: str | None = None) -> bool:
    project_name = normalize_project(project)
    if not project_name:
        return True
    if str(record.get("scope") or "").lower() != "project":
        return True
    record_project = normalize_project(str(record.get("project") or ""))
    return not record_project or record_project == project_name

APPLICABILITY_CONDITION_KINDS = ("project", "path", "task")


def parse_applies_when(value: object) -> list[tuple[str, str]]:
    """Parse an applies_when string into (kind, argument) conditions.

    Format: comma-separated `kind:argument` conditions with OR semantics,
    e.g. "project:link, task:cutting a release, path:*picochat*".
    Raises ValueError for unknown kinds or empty arguments.
    """
    text = str(value or "").strip()
    if not text:
        return []
    conditions: list[tuple[str, str]] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        kind, _, argument = part.partition(":")
        kind = kind.strip().lower()
        argument = argument.strip()
        if kind not in APPLICABILITY_CONDITION_KINDS or not argument:
            raise ValueError(
                "applies_when conditions must look like project:<slug>, path:<glob>, or task:<phrase>"
            )
        if kind == "project":
            # Store the slug recall actually compares against, so the
            # condition matches what it displays — and reject a value that
            # slugifies to nothing (e.g. "project:!!!"), which would be a
            # silently-dead scope.
            normalized = normalize_project(argument)
            if not normalized:
                raise ValueError(
                    f"applies_when project condition has no usable slug: {argument!r}"
                )
            argument = normalized
        conditions.append((kind, argument))
    return conditions
