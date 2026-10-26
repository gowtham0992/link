#!/usr/bin/env python3
"""Instruction-file checks (`lnk stale --instructions`): quiet when right, loud when not.

Two tracks:

1. **Planted findings.** A scratch repository whose AGENTS.md, CLAUDE.md,
   Cursor rule and Windsurf rule name things the repository then removes,
   exceed each vendor's size limit, and contradict each other and a reviewed
   memory. Every planted finding must be reported. The same repository also
   carries a duplicated rule (AGENTS.md and CLAUDE.md copies), rules that
   still hold, and history phrasing ("we dropped Python 3.9"); none of those
   may be reported.
2. **Real repositories.** Pass `--repo PATH` (repeatable) for checkouts with
   git history. Every finding is listed with its evidence for a person to
   judge; the numbers published in benchmarks/RESULTS.md are those
   judgements, not the tool grading itself.

Run:  python3 scripts/eval_instructions.py [--repo PATH ...] [--json]
Exit: non-zero if a planted finding is missed or a quiet case is flagged.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.instruction_lint import (  # noqa: E402
    claim_lines,
    discover_instruction_files,
    lint_instructions,
    user_owned_lines,
)
from link_core.staleness import checkable_references  # noqa: E402


def _git(repo: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=repo, check=True, capture_output=True, env={
        **os.environ, "GIT_AUTHOR_NAME": "eval", "GIT_AUTHOR_EMAIL": "eval@example.test",
        "GIT_COMMITTER_NAME": "eval", "GIT_COMMITTER_EMAIL": "eval@example.test",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull})


def _write(repo: Path, files: dict[str, str | None]) -> None:
    for rel, text in files.items():
        path = repo / rel
        if text is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


SHARED_RULES = (
    "- One concern per pull request; split unrelated fixes into their own branch.\n"
    "- Run the full test suite before asking for review.\n"
)

# (kind, file, what) for everything that must be reported.
PLANTED = [
    ("stale", "AGENTS.md", "tools/release.sh"),
    ("stale", "AGENTS.md", "deploy:staging"),
    ("stale", "CLAUDE.md", "LEGACY_API_TOKEN"),
    ("stale", "CLAUDE.md", "python 3.10"),
    ("stale", ".cursor/rules/style.mdc", "left-pad"),
    ("budget", "docs/AGENTS.md", "32 KiB"),
    ("budget", ".windsurf/rules/big.md", "12,000"),
    ("contradiction", "AGENTS.md", "CLAUDE.md"),
    ("contradiction", "CLAUDE.md", "memory team-formatting"),
]


def planted_track() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="link-eval-instructions-") as temp:
        repo = Path(temp)
        _git(repo, "init", "-q", "--initial-branch", "main")
        _write(repo, {
            "tools/release.sh": "echo release\n",
            "package.json": json.dumps({"scripts": {"build": "tsc", "deploy:staging": "sh deploy.sh"},
                                        "dependencies": {"left-pad": "1.0.0", "express": "4.0.0"}}),
            "config.py": "import os\nKEY = os.environ['LEGACY_API_TOKEN']\n",
            "pyproject.toml": '[project]\nname = "x"\nrequires-python = ">=3.10"\n',
        })
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "seed")
        _write(repo, {
            "tools/release.sh": None,
            "package.json": json.dumps({"scripts": {"build": "tsc"}, "dependencies": {"express": "4.0.0"}}),
            "config.py": "import os\nKEY = os.environ['API_TOKEN']\n",
            "pyproject.toml": '[project]\nname = "x"\nrequires-python = ">=3.12"\n',
            "AGENTS.md": "# Agents\n\n" + SHARED_RULES
                         + "- Cut releases with tools/release.sh.\n- Deploy with `npm run deploy:staging`.\n"
                         + "- Always use tabs for indentation in Python files.\n"
                         + "- Build with npm run build; the API reads API_TOKEN.\n",
            "CLAUDE.md": "# Claude\n\n" + SHARED_RULES
                         + "- Never use tabs for indentation in Python files.\n"
                         + "- Export LEGACY_API_TOKEN before running the server.\n"
                         + "- The service runs on Python 3.10.\n"
                         + "- We dropped Python 3.9 support last year.\n"
                         + "- Use 2 space indentation in YAML files.\n",
            ".cursor/rules/style.mdc": "---\ndescription: style\nglobs: src/**\nalwaysApply: false\n---\n"
                                       "- Pad strings with `left-pad`.\n- Serve with `express`.\n",
            "docs/AGENTS.md": "# Docs\n\n" + ("- Write short, plain sentences in every page of the docs.\n" * 700),
            ".windsurf/rules/big.md": "---\ntrigger: always_on\n---\n" + ("Keep functions small and named. " * 420),
        })
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "move on")
        memory = {"name": "team-formatting", "title": "YAML indentation", "memory_type": "decision",
                  "tldr": "Use 4 space indentation in YAML files.", "status": "active",
                  "review_status": "reviewed", "scope": "project", "visibility": "project"}
        report = lint_instructions(repo, [memory])
    found = report["findings"]

    def hit(kind: str, rel: str, what: str) -> bool:
        for item in found:
            if item["kind"] != kind or item["file"] != rel:
                continue
            haystack = " ".join(str(item.get(key) or "") for key in ("reason", "reference", "other")).lower()
            if what.lower() in haystack:
                return True
        return False

    missed = [f"{kind} {rel} {what}" for kind, rel, what in PLANTED if not hit(kind, rel, what)]
    expected = {(kind, rel) for kind, rel, _ in PLANTED}
    quiet_violations = []
    for item in found:
        text = f"{item.get('text', '')} {item.get('other_text', '')} {item.get('reason', '')}"
        if "One concern per pull request" in text or "full test suite" in text:
            quiet_violations.append(f"duplicated rule flagged: {item['file']}:{item['line']}")
        if "3.9" in text or "npm run build" in text or "API_TOKEN any more" in text.replace("LEGACY_API_TOKEN", ""):
            quiet_violations.append(f"still-true or history rule flagged: {item['file']}:{item['line']} {item['reason']}")
        if (item["kind"], item["file"]) not in expected and item["kind"] != "contradiction":
            quiet_violations.append(f"unexpected {item['kind']} in {item['file']}: {item['reason']}")
    return {"planted": len(PLANTED), "missed": missed, "quiet_violations": quiet_violations,
            "findings": len(found)}


def repository_track(repo: Path) -> dict[str, object]:
    started = time.monotonic()
    report = lint_instructions(repo)
    files = discover_instruction_files(Path(str(report["repo"])))
    references = claims = 0
    for rel, _kind in files:
        lines = user_owned_lines((Path(str(report["repo"])) / rel).read_text(encoding="utf-8", errors="replace"))
        references += sum(checkable_references(line) for _, line in lines)
        claims += len(claim_lines(lines))
    return {
        "repo": str(report["repo"]),
        "files": len(files),
        "references": references,
        "rule_lines": claims,
        "seconds": round(time.monotonic() - started, 1),
        "findings": report["findings"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure instruction-file check precision and recall.")
    parser.add_argument("--repo", action="append", default=[], help="a git checkout with instruction files")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    planted = planted_track()
    repos = [repository_track(Path(path).expanduser().resolve()) for path in args.repo]
    if args.json:
        print(json.dumps({"planted": planted, "repositories": repos}, indent=2))
    else:
        print(f"planted: {planted['planted']} findings, {len(planted['missed'])} missed, "
              f"{len(planted['quiet_violations'])} quiet cases flagged")
        for line in planted["missed"] + planted["quiet_violations"]:
            print(f"  ! {line}")
        for item in repos:
            print(f"{item['repo']}: {item['files']} files, {item['references']} checkable references, "
                  f"{item['rule_lines']} rule lines, {len(item['findings'])} findings, {item['seconds']}s")
            for finding in item["findings"]:
                print(f"  - {finding['kind']} {finding['file']}:{finding['line'] or ''} {finding['reason']}")
                if finding["kind"] == "contradiction":
                    print(f"      {finding.get('text', '')[:110]}\n      vs {finding.get('other_text', '')[:110]}")
    return 1 if planted["missed"] or planted["quiet_violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
