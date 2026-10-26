#!/usr/bin/env python3
"""Staleness detection: does it stay quiet when it should?

A staleness flag is only worth having if people believe it. One false flag on
a memory that was fine teaches them to skim past the next one, so the number
that matters here is not how many stale references are caught - it is how many
correct memories are left alone.

Three tracks:

1. **False flags.** Every checkable reference in the project's own current
   documentation - paths, package scripts, make targets, dependencies,
   environment variables, URLs, runtime versions, package managers. These
   references are correct by construction: the docs describe the code as it
   is. Any flag is a false positive.
2. **True flags (paths).** Synthetic memories naming paths this repository
   genuinely deleted, taken from git history rather than invented, plus prose
   paths the repository never had.
3. **True flags (v2).** A scratch repository that removes one of each v2
   kind between two commits; every removal must be caught, and a memory that
   names only things still present must stay silent.

Run:  python3 scripts/eval_staleness.py [--repo PATH] [--json]
Exit: non-zero if any false flag appears, or if a known deletion is missed.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.staleness import (  # noqa: E402
    StalenessChecker,
    checkable_references,
    repo_path_references,
    stale_findings,
)

DOCS = ("README.md", "CHANGELOG.md", "ARCHITECTURE.md", "CONTRIBUTING.md", "SECURITY.md", "LINK.md")
HTML_DOCS = "docs/*.html"
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


def _doc_texts(repo: Path) -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = []
    for name in DOCS:
        document = repo / name
        if document.is_file():
            texts.append((name, document.read_text(encoding="utf-8", errors="replace")))
    for document in sorted(repo.glob(HTML_DOCS)):
        raw = document.read_text(encoding="utf-8", errors="replace")
        if len(raw) > 400_000:
            continue  # bundled single-file pages carry fonts and scripts, not prose
        body = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)
        texts.append((str(document.relative_to(repo)), html.unescape(re.sub(r"<[^>]+>", " ", body))))
    return texts


def _git(repo: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=str(repo), capture_output=True, check=True,
                   env={"GIT_AUTHOR_NAME": "eval", "GIT_AUTHOR_EMAIL": "eval@example.com",
                        "GIT_COMMITTER_NAME": "eval", "GIT_COMMITTER_EMAIL": "eval@example.com",
                        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})


V2_REMOVALS = {
    "script": "Deploy staging with npm run deploy:staging.",
    "make_target": "Cut a release with make release.",
    "dependency": "We pad strings with `left-pad`.",
    "env_var": "Export LEGACY_API_TOKEN before running.",
    "url": "Staging is at https://staging.acme.internal:8443/api.",
    "version": "We target Python 3.10.",
    "package_manager": "Always use npm install for dependencies.",
}
V2_STILL_TRUE = "Build with npm run build, make clean, `express`, API_TOKEN, https://api.acme.dev, Python 3.12, use pnpm."


def v2_track() -> dict[str, object]:
    """Remove one of each v2 kind between two commits; each must be caught."""
    with tempfile.TemporaryDirectory(prefix="link-stale-eval-") as temp:
        repo = Path(temp)
        _git(repo, "init", "-q", "--initial-branch", "main")
        (repo / "package.json").write_text(json.dumps({
            "scripts": {"build": "tsc", "deploy:staging": "node d.js"},
            "dependencies": {"left-pad": "1", "express": "4"}}), encoding="utf-8")
        (repo / "Makefile").write_text("release:\n\ttrue\nclean:\n\ttrue\n", encoding="utf-8")
        (repo / "app.py").write_text("T = 'LEGACY_API_TOKEN'\nU = 'https://staging.acme.internal:8443/api'\n", encoding="utf-8")
        (repo / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.10"\n', encoding="utf-8")
        (repo / "package-lock.json").write_text("{}", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "before")
        (repo / "package.json").write_text(json.dumps({
            "scripts": {"build": "tsc"}, "dependencies": {"express": "4"}}), encoding="utf-8")
        (repo / "Makefile").write_text("clean:\n\ttrue\n", encoding="utf-8")
        (repo / "app.py").write_text("T = 'API_TOKEN'\nU = 'https://api.acme.dev'\n", encoding="utf-8")
        (repo / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.12"\n', encoding="utf-8")
        (repo / "package-lock.json").unlink()
        (repo / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "after")
        checker = StalenessChecker(repo)
        missed = [kind for kind, text in V2_REMOVALS.items()
                  if kind not in {f.get("kind") for f in checker.findings(text)}]
        silent_violations = [f"{f.get('kind')}: {f.get('reference')}" for f in checker.findings(V2_STILL_TRUE)]
    return {"probed": len(V2_REMOVALS), "missed": missed, "false_flags": silent_violations}


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure staleness-flag precision.")
    parser.add_argument("--repo", default=str(ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo = Path(args.repo).expanduser().resolve()

    references = 0
    false_flags: list[str] = []
    for name, text in _doc_texts(repo):
        references += checkable_references(text)
        for finding in stale_findings(text, repo, limit=200):
            false_flags.append(f"{name}: {finding.get('kind', 'path')} {finding['path']}")

    removed = deleted_paths(repo)
    missed = [
        path for path in removed
        if not stale_findings(f"the implementation lives in {path}", repo)
    ]
    prose_flags = [text for text in PROSE if stale_findings(text, repo)]
    v2 = v2_track()

    report = {
        "repository": str(repo),
        "documentation_references": references,
        "false_flags": len(false_flags),
        "false_flag_rate": round(len(false_flags) / references, 4) if references else 0.0,
        "known_deletions_probed": len(removed),
        "known_deletions_missed": len(missed),
        "prose_paths_probed": len(PROSE),
        "prose_false_flags": len(prose_flags),
        "v2_removals_probed": v2["probed"],
        "v2_removals_missed": len(v2["missed"]),  # type: ignore[arg-type]
        "v2_still_true_false_flags": len(v2["false_flags"]),  # type: ignore[arg-type]
        "detail": {"false_flags": false_flags, "missed": missed, "prose": prose_flags, "v2": v2},
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"repository: {repo}")
        print(f"documentation references: {references}")
        print(f"false flags: {len(false_flags)} ({report['false_flag_rate']:.2%})")
        print(f"known deletions: {len(removed)} probed, {len(missed)} missed")
        print(f"prose paths: {len(PROSE)} probed, {len(prose_flags)} flagged")
        print(f"v2 removals: {v2['probed']} probed, {len(v2['missed'])} missed"  # type: ignore[arg-type]
              f"; still-true memory flagged {len(v2['false_flags'])} time(s)")  # type: ignore[arg-type]
        for line in false_flags:
            print(f"  FALSE FLAG {line}")
        for path in missed:
            print(f"  MISSED {path}")
    if false_flags or prose_flags or v2["missed"] or v2["false_flags"]:
        return 1
    if removed and missed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
