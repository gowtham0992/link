#!/usr/bin/env python3
"""Link memory-hygiene benchmark: memory quality over simulated months.

Existing memory benchmarks measure retrieval on a frozen store. This one
measures what matters over time: does the store stay trustworthy as sessions
accumulate — no junk, no self-echo, contradictions resolved instead of
coexisting, history reconstructable?

Two pipelines run over the same deterministic event stream
(scripts/hygiene_dataset.py — authored text, exact ground-truth labels,
no LLM anywhere):

- gated:   Link's real pipeline. Extraction drops Link-injected output,
           echo containment drops restatements, duplicates are refused,
           detected contradictions resolve via supersession (archive with
           lineage). Where Link's conflict detector misses a contradiction,
           the gated pipeline honestly accrues the penalty — this benchmark
           grades the detector too.
- ungated: the same extractor and the same retrieval with governance off:
           every extracted candidate is stored, duplicates and conflicts
           coexist. Architecturally, this is what unsupervised
           LLM-extraction memory systems do on every message.

Metrics: junk rate (echo/brief/noise entries stored), contradiction
exposure (outdated version recalled in top-3 after a revision),
current-truth precision@1, active-store growth vs ground truth, and as-of
temporal accuracy for revised facts.

Run:  python3 scripts/eval_memory_hygiene.py [--json]
Exit: non-zero if the gated pipeline stores any junk, or fails to beat the
      ungated baseline on contradiction exposure or store growth.
"""
from __future__ import annotations

import os
os.environ["LINK_SEMANTIC"] = "off"  # published numbers stay deterministic: never use a local model

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))
sys.path.insert(0, str(ROOT / "scripts"))

from link_core.agent_hooks import LINK_ECHO_MARKERS  # noqa: E402
from link_core.memory import (  # noqa: E402
    is_existing_memory_echo,
    memory_records,
    propose_memories_from_text,
    recall_memories,
    write_memory_page,
)
from hygiene_dataset import INTENTS, build_event_stream, revision_names  # noqa: E402


def _make_wiki(root: Path) -> Path:
    wiki = root / "wiki"
    (wiki / "memories").mkdir(parents=True)
    (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
    (wiki / "log.md").write_text("# Log\n", encoding="utf-8")
    return wiki


def _write(wiki: Path, proposal: dict, date: str, **kwargs) -> dict:
    return write_memory_page(
        wiki,
        str(proposal.get("memory") or ""),
        title=str(proposal.get("title") or "") or None,
        memory_type=str(proposal.get("memory_type") or "note"),
        scope=str(proposal.get("scope") or "user"),
        tags=None,
        source="hygiene-benchmark",
        timestamp=f"{date}T12:00:00Z",
        **kwargs,
    )


def run_pipeline(gated: bool, events: list[dict[str, str]], wiki: Path) -> dict[str, object]:
    """Drive one pipeline over the stream; return the store ledger."""
    ledger: list[dict[str, str]] = []          # every stored entry + its event kind
    latest_for_intent: dict[str, str] = {}     # intent -> current page name
    original_for_intent: dict[str, tuple[str, str]] = {}  # intent -> (name, fact date)

    for event in events:
        text = event["text"]
        # Layer 1 (gated only): drop Link's own injected output.
        if gated and any(marker in text for marker in LINK_ECHO_MARKERS):
            continue
        records = memory_records(wiki)
        proposals = propose_memories_from_text(text, records=records, source="session")["proposals"]
        for proposal in proposals:
            memory_text = str(proposal.get("memory") or "")
            # Layer 2 (gated only): drop restatements of stored memory.
            if gated and is_existing_memory_echo(records, memory_text):
                continue
            if gated:
                result = _write(wiki, proposal, event["date"])
                if result.get("conflict"):
                    # The documented resolution loop: replace, with lineage.
                    candidate = result["conflict_candidates"][0]
                    result = _write(
                        wiki, proposal, event["date"],
                        supersedes=str(candidate.get("name")),
                    )
                if not result.get("created"):
                    continue  # duplicate-refused: the gate did its job
            else:
                result = _write(
                    wiki, proposal, event["date"],
                    allow_duplicate=True, allow_conflict=True,
                )
                if not result.get("created"):
                    continue
            name = str(result.get("name"))
            ledger.append({"name": name, "kind": event["kind"], "intent": event["intent"]})
            if event["intent"]:
                if event["kind"] == "fact" and event["intent"] not in original_for_intent:
                    original_for_intent[event["intent"]] = (name, event["date"])
                latest_for_intent[event["intent"]] = name
    return {
        "ledger": ledger,
        "latest": latest_for_intent,
        "original": original_for_intent,
    }


def measure(wiki: Path, state: dict[str, object]) -> dict[str, float]:
    records = memory_records(wiki)
    ledger = state["ledger"]
    latest = state["latest"]
    original = state["original"]
    revised = revision_names()
    queries = {name: intent_queries[0] for name, _d, _t, _tl, _b, intent_queries in INTENTS}

    active = [r for r in records if str(r.get("status") or "active") == "active"]
    # v2 junk classes: question and pasted_ai came from real dogfooding (quiz
    # questions and pasted third-party AI advice proposed as user memory);
    # repeat measures cross-session re-proposal of the same claim.
    junk_kinds = {"echo", "brief_echo", "noise", "question", "pasted_ai", "repeat"}
    junk = [entry for entry in ledger if entry["kind"] in junk_kinds]
    junk_by_kind = {
        kind: len([entry for entry in junk if entry["kind"] == kind])
        for kind in sorted(junk_kinds)
        if any(entry["kind"] == kind for entry in junk)
    }

    precision_hits = 0
    exposure_hits = 0
    as_of_hits = 0
    measured = 0
    for intent, query in queries.items():
        if intent not in latest:
            continue
        measured += 1
        results = recall_memories(records, query, limit=3)
        names = [str(item["name"]) for item in results]
        if names and names[0] == latest[intent]:
            precision_hits += 1
        if intent in revised:
            outdated_name, fact_date = original[intent]
            if outdated_name != latest[intent] and outdated_name in names:
                exposure_hits += 1
            historical = recall_memories(records, query, limit=1, as_of=fact_date)
            if historical and str(historical[0]["name"]) == outdated_name:
                as_of_hits += 1

    revised_measured = len([i for i in revised if i in latest]) or 1
    return {
        "stored_entries": len(ledger),
        "active_memories": len(active),
        "junk_stored": len(junk),
        "junk_by_kind": junk_by_kind,
        "junk_rate": round(len(junk) / len(ledger), 4) if ledger else 0.0,
        "current_truth_precision@1": round(precision_hits / measured, 4) if measured else 0.0,
        "contradiction_exposure@3": round(exposure_hits / revised_measured, 4),
        "as_of_accuracy": round(as_of_hits / revised_measured, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    events = build_event_stream()
    report: dict[str, object] = {
        "events": len(events),
        "ground_truth_facts": len(INTENTS),
        "ground_truth_revisions": len(revision_names()),
    }
    for label, gated in (("gated", True), ("ungated", False)):
        with tempfile.TemporaryDirectory() as temp:
            wiki = _make_wiki(Path(temp))
            state = run_pipeline(gated, events, wiki)
            report[label] = measure(wiki, state)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        gated, ungated = report["gated"], report["ungated"]
        print(
            f"Link memory-hygiene benchmark — {report['events']} session events, "
            f"{report['ground_truth_facts']} facts, {report['ground_truth_revisions']} revisions"
        )
        width = max(len(k) for k in gated)
        print(f"\n{'metric':{width}}  {'gated (Link)':>14}  {'ungated':>10}")
        for key in gated:
            if isinstance(gated[key], dict):
                gated_kinds = ", ".join(f"{k}:{v}" for k, v in gated[key].items()) or "none"
                ungated_kinds = ", ".join(f"{k}:{v}" for k, v in ungated[key].items()) or "none"
                print(f"{key:{width}}  gated: {gated_kinds} | ungated: {ungated_kinds}")
                continue
            print(f"{key:{width}}  {gated[key]:>14}  {ungated[key]:>10}")

    gated, ungated = report["gated"], report["ungated"]
    failures = []
    if gated["junk_stored"] != 0:
        failures.append("gated pipeline stored junk")
    if gated["contradiction_exposure@3"] >= ungated["contradiction_exposure@3"] and ungated["contradiction_exposure@3"] > 0:
        failures.append("gated contradiction exposure not better than ungated")
    if gated["active_memories"] > ungated["active_memories"]:
        failures.append("gated store grew beyond ungated")
    for failure in failures:
        print(f"REGRESSION: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
