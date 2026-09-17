#!/usr/bin/env python3
"""Staleness detection: does it stay quiet when it should?

A staleness flag is only worth having if people believe it. One false flag on
a memory that was fine teaches them to skim past the next one, so the number
that matters here is not how many stale references are caught - it is how many
correct memories are left alone.

Two tracks, both over a real repository:

1. **False flags.** Every repository-looking path in the project's own current
   documentation. These references are correct by construction: the docs
   describe the code as it is. Any flag is a false positive.
2. **True flags.** Synthetic memories naming paths this repository genuinely
   deleted, taken from git history rather than invented, plus prose paths the
   repository never had.

Run:  python3 scripts/eval_staleness.py [--repo PATH] [--json]
Exit: non-zero if any false flag appears, or if a known deletion is missed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.staleness import repo_path_references, stale_findings  # noqa: E402

DOCS = ("README.md", "CHANGELOG.md", "ARCHITECTURE.md", "CONTRIBUTING.md", "SECURITY.md")
# Paths that were never in the repository: prose, not stale references.
PROSE = (
    "put the token in config/settings.py before running",
    "their setup uses src/app/main.ts and lib/util.go",
    "we shipped 2.3.0 on Tuesday, see e.g. the notes",
)


def deleted_paths(repo: Path, limit: int = 6) -> list[str]:
    """Paths this repository actually removed, read from git."""
    try:
        out = subprocess.run(
            ["git", "log", "--all", "--diff-filter=D", "--name-only", "--format=", "-n", "400"],
            cwd=str(repo), capture_output=True, text=True, timeout=30, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found: list[str] = []
    for line in out.splitlines():
        name = line.strip()
        if not name or (repo / name).exists() or name in found:
            continue
        # Probe only what the detector claims to cover. Scope lives in the
        # extractor, so this cannot be quietly widened to flatter the score:
        # if a path is out of scope there, it is out of scope here too.
        if name.startswith(("wiki/", "raw/")) or not repo_path_references(name):
            continue
        found.append(name)
        if len(found) >= limit:
            break
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure staleness-flag precision.")
    parser.add_argument("--repo", default=str(ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo = Path(args.repo).expanduser().resolve()

    references = 0
    false_flags: list[str] = []
    for name in DOCS:
        document = repo / name
        if not document.is_file():
            continue
        text = document.read_text(encoding="utf-8", errors="replace")
        references += len(repo_path_references(text))
        for finding in stale_findings(text, repo, limit=80):
            false_flags.append(f"{name}: {finding['path']}")

    removed = deleted_paths(repo)
    missed = [
        path for path in removed
        if not stale_findings(f"the implementation lives in {path}", repo)
    ]
    prose_flags = [text for text in PROSE if stale_findings(text, repo)]

    report = {
        "repository": str(repo),
        "documentation_references": references,
        "false_flags": len(false_flags),
        "false_flag_rate": round(len(false_flags) / references, 4) if references else 0.0,
        "known_deletions_probed": len(removed),
        "known_deletions_missed": len(missed),
        "prose_paths_probed": len(PROSE),
        "prose_false_flags": len(prose_flags),
        "detail": {"false_flags": false_flags, "missed": missed, "prose": prose_flags},
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"repository: {repo}")
        print(f"documentation references: {references}")
        print(f"false flags: {len(false_flags)} ({report['false_flag_rate']:.2%})")
        print(f"known deletions: {len(removed)} probed, {len(missed)} missed")
        print(f"prose paths: {len(PROSE)} probed, {len(prose_flags)} flagged")
        for line in false_flags:
            print(f"  FALSE FLAG {line}")
        for path in missed:
            print(f"  MISSED {path}")
    if false_flags or prose_flags:
        return 1
    if removed and missed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
