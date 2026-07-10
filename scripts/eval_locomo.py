#!/usr/bin/env python3
"""Third-party retrieval track: LoCoMo evidence retrieval with Link recall.

LoCoMo (Maharana et al., ACL 2024, Snap Research) is the long-term
conversational memory benchmark the hosted-memory industry quotes. This track
uses only its third-party ground truth — no LLM, no judging, no generation:

- every dialog turn of a conversation becomes one Link memory record;
- every evidence-annotated question becomes a recall query;
- we measure whether Link's ranking returns the annotated evidence turns
  (any-evidence hit@k and evidence recall@k), lexical vs hybrid.

This is NOT the LoCoMo QA task (no answers are generated or scored), so the
numbers are not comparable to end-to-end LLM QA scores quoted elsewhere; it
isolates the retrieval stage with third-party queries and third-party gold
labels over third-party conversations.

Dataset: locomo10.json, CC BY-NC 4.0, (c) Snap Inc. Not redistributed here —
download it yourself first (this script contains no network code):

    curl -L -o /tmp/locomo10.json \
        https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json

Run:
    python3 scripts/eval_locomo.py /tmp/locomo10.json --mode off    # lexical
    python3 scripts/eval_locomo.py /tmp/locomo10.json --mode real   # hybrid
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

from link_core.memory import recall_memories  # noqa: E402
from link_core.semantic import load_embedder, semantic_memory_scores  # noqa: E402

ADVERSARIAL_CATEGORY = 5


def _turn_records(sample: dict) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    conversation = sample["conversation"]
    session = 1
    while f"session_{session}" in conversation:
        date = str(conversation.get(f"session_{session}_date_time") or "")
        turns: list[tuple[str, str, str]] = []
        for turn in conversation[f"session_{session}"] or []:
            text = str(turn.get("text") or "").strip() or str(turn.get("blip_caption") or "").strip()
            if not text:
                continue
            turns.append((str(turn.get("dia_id")), str(turn.get("speaker") or ""), text))
        for index, (dia_id, speaker, text) in enumerate(turns):
            # The turn is the memory's claim; its +/-1 dialogue neighbors go
            # into the record's retrieval `context` field. A turn like "the
            # stories were so inspiring" is only findable by what it was
            # about, and the conversation gives that context away for free.
            # Measured: hit@10 0.685 -> 0.749 over context-free turn records.
            neighbor_text = " ".join(
                f"{spk}: {txt}"
                for j in (index - 1, index + 1)
                if 0 <= j < len(turns)
                for _, spk, txt in (turns[j],)
            )
            records.append({
                "name": dia_id,
                "title": f"{speaker} (session {session})",
                "tldr": date,
                "tags": [],
                "body": text,
                "context": neighbor_text,
                "status": "active",
                "scope": "user",
                "memory_type": "fact",
                "review_status": "reviewed",
            })
        session += 1
    return records


def _queries(sample: dict) -> list[dict[str, object]]:
    queries = []
    for qa in sample.get("qa", []):
        if int(qa.get("category") or 0) == ADVERSARIAL_CATEGORY:
            continue
        evidence = qa.get("evidence") or []
        if not isinstance(evidence, list) or not evidence:
            continue
        queries.append({"question": str(qa.get("question") or ""), "evidence": [str(e) for e in evidence]})
    return queries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", help="path to locomo10.json (see module docstring for the download command)")
    parser.add_argument("--mode", choices=["off", "real"], default="off")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    dataset_path = Path(args.dataset).expanduser()
    if not dataset_path.exists():
        print(f"Dataset not found: {dataset_path}", file=sys.stderr)
        print("Download it first (CC BY-NC 4.0, (c) Snap Inc.):", file=sys.stderr)
        print(
            "  curl -L -o /tmp/locomo10.json "
            "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json",
            file=sys.stderr,
        )
        return 2

    embedder = None
    if args.mode == "real":
        embedder = load_embedder(allow_download=False)
        if embedder is None:
            print(
                "Semantic model unavailable offline. Install a provider and run "
                "`lnk semantic --setup` (or `python3 -m link_mcp --semantic-setup`) first.",
                file=sys.stderr,
            )
            return 2

    samples = json.loads(dataset_path.read_text(encoding="utf-8"))
    k = max(1, args.k)
    total_queries = 0
    total_turns = 0
    any_hits = {1: 0, 5: 0, k: 0}
    evidence_recall: list[float] = []
    latencies: list[float] = []

    with tempfile.TemporaryDirectory() as temp:
        for index, sample in enumerate(samples):
            records = _turn_records(sample)
            queries = _queries(sample)
            total_turns += len(records)
            root = Path(temp) / f"conv-{index}"
            for query in queries:
                started = time.perf_counter()
                scores = (
                    semantic_memory_scores(root, query["question"], records, embedder=embedder)
                    if embedder is not None
                    else None
                )
                results = recall_memories(records, query["question"], limit=k, semantic_scores=scores)
                latencies.append((time.perf_counter() - started) * 1000)
                names = [str(item["name"]) for item in results]
                gold = set(query["evidence"])
                for cutoff in any_hits:
                    if gold & set(names[:cutoff]):
                        any_hits[cutoff] += 1
                evidence_recall.append(len(gold & set(names[:k])) / len(gold))
                total_queries += 1

    report = {
        "dataset": "LoCoMo locomo10.json (CC BY-NC 4.0, Snap Inc.) — retrieval stage only",
        "mode": args.mode,
        "conversations": len(samples),
        "turn_memories": total_turns,
        "queries": total_queries,
        "any_evidence_hit@1": round(any_hits[1] / total_queries, 4),
        "any_evidence_hit@5": round(any_hits[5] / total_queries, 4),
        f"any_evidence_hit@{k}": round(any_hits[k] / total_queries, 4),
        f"evidence_recall@{k}": round(statistics.fmean(evidence_recall), 4),
        "latency_ms_p50": round(statistics.median(latencies), 2),
        "latency_ms_mean": round(statistics.fmean(latencies), 2),
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
