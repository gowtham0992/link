#!/usr/bin/env python3
"""Measure Link memory recall quality: lexical vs hybrid (semantic) recall.

Runs a fixed set of queries against a synthetic personal-memory corpus and
reports hit@1 / hit@3 for two query groups:

- lexical: queries sharing tokens with the target memory (must stay perfect)
- paraphrase: queries phrased differently from the memory (where token
  matching struggles and local embeddings should help)

Modes:
- --mode off   lexical-only baseline
- --mode fake  deterministic synonym-axis embedder (CI-safe, no model)
- --mode real  the actual local model (requires `pip install "link-mcp[semantic]"`
               and a cached model via `lnk semantic --setup`; pass
               --allow-download to fetch it here explicitly)

Exit code is non-zero if hybrid recall ever scores below lexical recall on
the same cases (hybrid must be a strict superset in quality).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))
sys.path.insert(0, str(ROOT / "tests"))

from link_core.memory import recall_memories  # noqa: E402
from link_core.semantic import load_embedder, semantic_memory_scores  # noqa: E402
from test_semantic_core import fake_embedder  # noqa: E402


def _memory(name: str, title: str, tldr: str, body: str, memory_type: str = "preference") -> dict[str, object]:
    return {
        "name": name,
        "title": title,
        "tldr": tldr,
        "tags": [],
        "body": body,
        "status": "active",
        "scope": "user",
        "memory_type": memory_type,
        "review_status": "reviewed",
    }


MEMORIES = [
    _memory(
        "commit-style", "Commit style",
        "Small commits, PR summary first.",
        "The user prefers small commits and pull requests structured with a one-paragraph summary first, then bullet points.",
    ),
    _memory(
        "deploy-from-main", "Deploy from main",
        "Releases ship only from main.",
        "Releases ship only from the main branch after CI passes; never deploy from feature branches.",
        "decision",
    ),
    _memory(
        "sqlite-storage", "SQLite for local storage",
        "Local data lives in SQLite.",
        "The project stores local data in SQLite with FTS enabled; no external database services.",
        "decision",
    ),
    _memory(
        "short-answers", "Short answers with sources",
        "Keep answers short, cite sources.",
        "The user prefers short, direct answers that cite the wiki pages they came from.",
    ),
    _memory(
        "python-versions", "Supported Python versions",
        "Support Python 3.10 through 3.14.",
        "The project supports Python 3.10 through 3.14 and tests all of them in CI.",
        "fact",
    ),
    _memory(
        "no-cloud-sync", "No cloud sync",
        "Memory stays on the machine.",
        "The project decided agent memory stays in local Markdown files with no cloud synchronization.",
        "decision",
    ),
    _memory(
        "review-before-merge", "Review before merge",
        "Every change needs a review pass.",
        "Every pull request needs at least one review pass before merging to the default branch.",
        "decision",
    ),
    _memory(
        "meeting-notes-obsidian", "Meeting notes live in Obsidian",
        "Meeting notes are kept in the Obsidian vault.",
        "The user keeps meeting notes in an Obsidian vault and imports the relevant ones into Link.",
        "fact",
    ),
]

# (query, expected memory name)
LEXICAL_CASES = [
    ("commit style", "commit-style"),
    ("deploy from main", "deploy-from-main"),
    ("sqlite storage", "sqlite-storage"),
    ("short answers with sources", "short-answers"),
    ("supported python versions", "python-versions"),
    ("cloud sync", "no-cloud-sync"),
    ("review before merge", "review-before-merge"),
    ("meeting notes obsidian", "meeting-notes-obsidian"),
]

PARAPHRASE_CASES = [
    ("how should I structure my pull requests", "commit-style"),
    ("which branch do we ship production builds from", "deploy-from-main"),
    ("what do we use to persist data on disk", "sqlite-storage"),
    ("how verbose should my replies be", "short-answers"),
    ("which interpreter releases must keep working", "python-versions"),
    ("does anything leave this machine", "no-cloud-sync"),
    ("can I land this change without another set of eyes", "review-before-merge"),
    ("where are the writeups from our sync calls", "meeting-notes-obsidian"),
]


def run_cases(cases, embedder, root: Path) -> dict[str, float]:
    hit1 = hit3 = 0
    for query, expected in cases:
        scores = (
            semantic_memory_scores(root, query, MEMORIES, embedder=embedder)
            if embedder is not None
            else None
        )
        results = recall_memories(MEMORIES, query, limit=3, semantic_scores=scores)
        names = [str(item["name"]) for item in results]
        if names[:1] == [expected]:
            hit1 += 1
        if expected in names:
            hit3 += 1
    total = len(cases)
    return {"hit@1": hit1 / total, "hit@3": hit3 / total, "cases": total}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["off", "fake", "real"], default="fake")
    parser.add_argument("--allow-download", action="store_true", help="allow the real model to be fetched once")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    embedder = None
    if args.mode == "fake":
        embedder = fake_embedder
    elif args.mode == "real":
        embedder = load_embedder(allow_download=args.allow_download)
        if embedder is None:
            print(
                "Real model unavailable. Install with: pip install \"link-mcp[semantic]\" "
                "and cache the model via `lnk semantic --setup` (or pass --allow-download).",
                file=sys.stderr,
            )
            return 2

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        report = {
            "mode": args.mode,
            "lexical_baseline": {
                "lexical_queries": run_cases(LEXICAL_CASES, None, root),
                "paraphrase_queries": run_cases(PARAPHRASE_CASES, None, root),
            },
            "hybrid": {
                "lexical_queries": run_cases(LEXICAL_CASES, embedder, root),
                "paraphrase_queries": run_cases(PARAPHRASE_CASES, embedder, root),
            } if embedder is not None else None,
        }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Link recall quality eval (mode: {args.mode})")
        for label, block in (("lexical-only", report["lexical_baseline"]), ("hybrid", report["hybrid"])):
            if block is None:
                continue
            print(f"\n{label}:")
            for group, stats in block.items():
                print(
                    f"  {group:20s} hit@1 {stats['hit@1']:.2f}  hit@3 {stats['hit@3']:.2f}"
                    f"  ({stats['cases']} cases)"
                )

    if report["hybrid"] is not None:
        for group in ("lexical_queries", "paraphrase_queries"):
            for metric in ("hit@1", "hit@3"):
                if report["hybrid"][group][metric] < report["lexical_baseline"][group][metric]:
                    print(f"REGRESSION: hybrid {group} {metric} below lexical baseline", file=sys.stderr)
                    return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
