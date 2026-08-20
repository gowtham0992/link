"""Notice when a memory has outlived the code it describes.

The most common complaint about agent memory is that nobody can tell when a
memory stopped being true. A note says a thing lives in `a/b.py`, the file is
renamed, and the memory keeps being retrieved and believed. Hosted memory
services cannot fix this: they never see the repository. A local tool sitting
beside the checkout can.

The signal used here is deliberately narrow. A memory is only questioned when
it names a repository path that

1. does not exist now, and
2. did exist at some point in git history.

Both halves matter. Without (2) an unresolvable path is just prose - "put it
in config/settings.py" written before that file was ever created - and
flagging it would be noise. With (2) the path was real and is gone, which is
about as close to proof of staleness as a heuristic gets.

Nothing here rewrites or deletes a memory. Findings are routed to the same
review gate every other change goes through, because a flag that acts on its
own is a flag people learn to fear, and a flag that fires loosely is one they
learn to ignore. Silence is the normal output.
"""
from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

# Scope is source, config, and documentation. Binary assets are left out on
# purpose: documentation names image files constantly, so they are mostly
# false-flag surface, and a moved logo rarely makes a memory wrong.
#
# Two shapes are recognised: anything with a directory separator, and bare
# filenames carrying a source-code extension. Extraction can afford to be
# generous because it is not the precision gate - git history is. A word that
# merely looks like a filename was never tracked, so it is never flagged.
_CODE_SUFFIXES = (
    "py|js|mjs|cjs|ts|tsx|jsx|go|rs|rb|java|kt|swift|c|h|cc|cpp|hpp|cs|php|"
    "sh|bash|zsh|ps1|sql|toml|yml|yaml|json|ini|cfg|md|rst|txt|lock|gradle"
)
_PATH_REFERENCE = re.compile(
    r"(?<![\w./-])("
    r"(?:[\w.-]+/)+[\w-]+\.[A-Za-z0-9]{1,8}"          # has a directory part
    r"|[\w-]+\.(?:" + _CODE_SUFFIXES + r")"              # bare source filename
    r")(?![\w/])"
)

# Paths inside the memory store itself are not code and move for their own
# reasons; questioning a memory because a wiki page was renamed is noise.
_IGNORED_PREFIXES = ("wiki/", "raw/", ".link-cache/", ".git/")

MAX_PATH_LOOKUPS = 12


def repo_path_references(text: str) -> list[str]:
    """Repository-looking paths named by a memory, in first-seen order."""
    seen: list[str] = []
    for match in _PATH_REFERENCE.finditer(text or ""):
        candidate = match.group(1)
        if candidate.startswith(_IGNORED_PREFIXES) or candidate in seen:
            continue
        seen.append(candidate)
    return seen


def _git(repo_root: Path, arguments: list[str], runner: Callable[..., object] | None = None) -> str:
    """Run one read-only git command, returning "" when git cannot answer."""
    if runner is not None:
        return str(runner(repo_root, arguments) or "")
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout


def path_was_known(repo_root: Path, path: str, runner: Callable[..., object] | None = None) -> bool:
    """True when git has ever tracked this path."""
    output = _git(repo_root, ["log", "--all", "--oneline", "-1", "--", path], runner)
    return bool(output.strip())


# Renames are read in one pass rather than one call per path. Asking git for
# a rename by the *old* path returns nothing - history simplification hides
# the commit - so the rename records are listed once and matched in memory.
RENAME_SCAN_COMMITS = 400


def rename_map(repo_root: Path, runner: Callable[..., object] | None = None) -> dict[str, str]:
    """Old path -> new path, for renames git recorded recently."""
    output = _git(
        repo_root,
        ["log", "--all", "--diff-filter=R", "--name-status", "--format=", "-n", str(RENAME_SCAN_COMMITS)],
        runner,
    )
    moves: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].startswith("R"):
            moves.setdefault(parts[1], parts[2])
    return moves


def stale_findings(
    text: str,
    repo_root: Path,
    *,
    runner: Callable[..., object] | None = None,
    limit: int = MAX_PATH_LOOKUPS,
) -> list[dict[str, str]]:
    """Paths this memory names that git once tracked and that are now gone.

    An empty list is the expected result. A finding says only that the memory
    refers to something that moved; a person decides what the memory should
    say now.
    """
    root = Path(repo_root).expanduser()
    findings: list[dict[str, str]] = []
    moves: dict[str, str] | None = None   # built lazily; only a finding needs it
    for candidate in repo_path_references(text)[:limit]:
        if (root / candidate).exists():
            continue
        if not path_was_known(root, candidate, runner):
            continue  # never in the repository: prose, not a stale reference
        if moves is None:
            moves = rename_map(root, runner)
        successor = moves.get(candidate, "")
        findings.append(
            {
                "path": candidate,
                "reason": "renamed" if successor else "removed",
                "successor": successor,
            }
        )
    return findings


def describe_findings(findings: Iterable[dict[str, str]]) -> list[str]:
    """One reviewable line per finding."""
    lines: list[str] = []
    for finding in findings:
        if finding.get("successor"):
            lines.append(f"{finding['path']} was renamed to {finding['successor']}")
        else:
            lines.append(f"{finding['path']} is no longer in the repository")
    return lines
