#!/usr/bin/env python3
"""Benchmark Link memory recall quality: lexical vs hybrid (semantic) recall.

Dataset: scripts/recall_dataset.py — fully authored, deterministic, auditable
(no LLM, no network, no randomness). Queries are classified by *measured*
token overlap with their target memory, not by how they were authored:

- token-overlap: the query shares at least one significant stemmed token
  with its target memory (lexical recall has a fighting chance)
- zero-overlap: the query provably shares no significant stemmed token with
  its target (pure paraphrase; token matching cannot find it directly)

Metrics per group and mode: hit@1, hit@3, hit@5, MRR@5, plus recall latency.

Modes:
- --mode off   lexical-only baseline
- --mode fake  deterministic synonym-axis embedder (CI-safe, no model)
- --mode real  the actual local model (pip install "link-mcp[semantic]";
               pass --allow-download to fetch it here explicitly)

Exit code is non-zero if hybrid recall scores below lexical recall on any
group metric (hybrid must never regress lexical behavior).

Reproduce the published numbers:
    python3 -m venv /tmp/linkbench && /tmp/linkbench/bin/pip install model2vec
    /tmp/linkbench/bin/python scripts/eval_recall_quality.py \
        --suite full --mode real --allow-download
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from link_core.memory import (  # noqa: E402
    memory_tokens,
    recall_memories,
    significant_memory_tokens,
    stemmed_memory_tokens,
)
from link_core.semantic import load_embedder, semantic_memory_scores  # noqa: E402
from recall_dataset import build_cases, build_corpus  # noqa: E402
from test_semantic_core import fake_embedder  # noqa: E402

RANK_LIMIT = 5


def _target_tokens(memory: dict[str, object]) -> set[str]:
    text = " ".join([
        str(memory.get("title") or ""),
        str(memory.get("tldr") or ""),
        " ".join(str(tag) for tag in memory.get("tags", [])),
        str(memory.get("body") or ""),
    ])
    return stemmed_memory_tokens(memory_tokens(text))


def classify_cases(cases: list[dict[str, str]], corpus: list[dict[str, object]]) -> None:
    """Annotate each case with its measured overlap group."""
    tokens_by_name = {str(memory["name"]): _target_tokens(memory) for memory in corpus}
    for case in cases:
        query_tokens = stemmed_memory_tokens(significant_memory_tokens(case["query"]))
        overlap = query_tokens & tokens_by_name[case["target"]]
        case["group"] = "token-overlap" if overlap else "zero-overlap"


def _blank_stats() -> dict[str, float]:
    return {"hit@1": 0.0, "hit@3": 0.0, "hit@5": 0.0, "mrr@5": 0.0, "cases": 0}


def run_suite(
    cases: list[dict[str, str]],
    corpus: list[dict[str, object]],
    embedder,
    root: Path,
) -> dict[str, object]:
    groups: dict[str, dict[str, float]] = {}
    domains: dict[str, dict[str, float]] = {}
    latencies: list[float] = []
    for case in cases:
        started = time.perf_counter()
        scores = (
            semantic_memory_scores(root, case["query"], corpus, embedder=embedder)
            if embedder is not None
            else None
        )
        results = recall_memories(corpus, case["query"], limit=RANK_LIMIT, semantic_scores=scores)
        latencies.append((time.perf_counter() - started) * 1000)
        names = [str(item["name"]) for item in results]
        rank = names.index(case["target"]) + 1 if case["target"] in names else 0
        for bucket in (groups.setdefault(case["group"], _blank_stats()),
                       domains.setdefault(case["domain"], _blank_stats())):
            bucket["cases"] += 1
            if rank == 1:
                bucket["hit@1"] += 1
            if 1 <= rank <= 3:
                bucket["hit@3"] += 1
            if 1 <= rank <= 5:
                bucket["hit@5"] += 1
            if rank:
                bucket["mrr@5"] += 1.0 / rank
    for bucket_map in (groups, domains):
        for stats in bucket_map.values():
            count = stats["cases"] or 1
            for metric in ("hit@1", "hit@3", "hit@5", "mrr@5"):
                stats[metric] = round(stats[metric] / count, 4)
    return {
        "groups": groups,
        "domains": domains,
        "latency_ms": {
            "p50": round(statistics.median(latencies), 2),
            "p95": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 2),
            "mean": round(statistics.fmean(latencies), 2),
        },
    }


def _print_block(label: str, block: dict[str, object], show_domains: bool) -> None:
    print(f"\n{label}:")
    for group in sorted(block["groups"]):
        stats = block["groups"][group]
        print(
            f"  {group:14s} hit@1 {stats['hit@1']:.3f}  hit@3 {stats['hit@3']:.3f}"
            f"  hit@5 {stats['hit@5']:.3f}  mrr@5 {stats['mrr@5']:.3f}  ({int(stats['cases'])} cases)"
        )
    latency = block["latency_ms"]
    print(f"  latency/query  p50 {latency['p50']}ms  p95 {latency['p95']}ms  mean {latency['mean']}ms")
    if show_domains:
        for domain in sorted(block["domains"]):
            stats = block["domains"][domain]
            print(
                f"    {domain:12s} hit@1 {stats['hit@1']:.3f}  hit@3 {stats['hit@3']:.3f}"
                f"  ({int(stats['cases'])} cases)"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["off", "fake", "real"], default="fake")
    parser.add_argument("--suite", choices=["small", "full"], default="small",
                        help="small: authored queries only; full: plus deterministic phrasing variants")
    parser.add_argument("--allow-download", action="store_true", help="allow the real model to be fetched once")
    parser.add_argument("--domains", action="store_true", help="show per-domain breakdown")
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

    corpus = build_corpus()
    cases = build_cases(expand=(args.suite == "full"))
    classify_cases(cases, corpus)
    authored = sum(1 for case in cases if case["authored"] == "yes")

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        report: dict[str, object] = {
            "suite": args.suite,
            "mode": args.mode,
            "corpus_memories": len(corpus),
            "total_cases": len(cases),
            "authored_cases": authored,
            "wrapped_variant_cases": len(cases) - authored,
            "lexical_baseline": run_suite(cases, corpus, None, root),
            "hybrid": run_suite(cases, corpus, embedder, root) if embedder is not None else None,
        }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"Link recall benchmark — suite: {args.suite}, mode: {args.mode}, "
            f"corpus: {report['corpus_memories']} memories, cases: {report['total_cases']} "
            f"({authored} authored + {report['wrapped_variant_cases']} phrasing variants)"
        )
        _print_block("lexical-only", report["lexical_baseline"], args.domains)
        if report["hybrid"] is not None:
            _print_block("hybrid", report["hybrid"], args.domains)

    if report["hybrid"] is not None:
        baseline_groups = report["lexical_baseline"]["groups"]
        hybrid_groups = report["hybrid"]["groups"]
        for group, baseline in baseline_groups.items():
            for metric in ("hit@1", "hit@3", "hit@5", "mrr@5"):
                if hybrid_groups[group][metric] < baseline[metric]:
                    print(f"REGRESSION: hybrid {group} {metric} below lexical baseline", file=sys.stderr)
                    return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
