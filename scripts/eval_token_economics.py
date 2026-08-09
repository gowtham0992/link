#!/usr/bin/env python3
"""Link token-economics benchmark: what a recall actually costs.

The 2026 literature names token economics as one of memory's persistent
production problems — "sending 100k tokens of history for a 50-token
response is financially unsustainable" — and published footprints differ by
orders of magnitude between systems (one hosted system's own comparison
reports ~600k tokens per conversation against another's ~1.8k).

Link's answer is structural: retrieval returns a *bounded packet*, not a
context dump. Budgets cap memories, search results, context pages, and the
characters inside each, so packet size is a function of the budget — not of
how much you have remembered. This benchmark measures that claim two ways:

1. **Cost per recall** at each budget, over the bundled corpus.
2. **Growth**: the same query against stores of increasing size. A store
   that grows 10x must not grow the packet 10x — that is the whole point.

Method: packets are built through the real query path, serialized as the
agent receives them (JSON), and counted with the same 4-chars-per-token
approximation Link uses for its own budget reporting. Approximate by
design and stated as such: exact counts vary by tokenizer, and the
comparison that matters here is order-of-magnitude and growth curve.

Run:  python3 scripts/eval_token_economics.py [--json]
Exit: non-zero if any budget's worst packet exceeds its ceiling, or if the
      packet fails to plateau as the store grows (the bounded-packet
      guarantee: cost tracks the budget you ask for, not what you remember).
"""
from __future__ import annotations

import os
os.environ["LINK_SEMANTIC"] = "off"  # deterministic: published numbers use no model

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))
sys.path.insert(0, str(ROOT / "scripts"))

from link_core.memory import memory_records, write_memory_page  # noqa: E402
from link_core.query import query_link  # noqa: E402
from link_core.wiki import build_wiki_cache, close_wiki_cache  # noqa: E402
from recall_dataset import INTENTS  # noqa: E402

# Ceilings: the worst packet at each budget must stay under these. Set at
# ~1.4x the measured maximum on a 400-memory store, so the gate catches a
# structural regression (an unbounded field leaking into packets) without
# freezing today's exact byte counts.
BUDGET_CEILINGS = {"micro": 2900, "small": 5900, "medium": 10200, "large": 16800}
# The bounded-packet guarantee, stated as the shape it actually has: packet
# size climbs while the budget's slots fill, then stops. Measured at
# 25/100/400/1600 memories the curve is +36%, +12%, +0% — so the last
# quadrupling of the store must move the packet almost not at all.
PLATEAU_TOLERANCE = 1.05
GROWTH_SIZES = (25, 100, 400, 1600)
# CI runs --quick: building 1,600 memories dominates the runtime, so the
# gate checks the same structural property on a smaller curve — each
# step of store growth must move the packet *less* than the one before.
# Deceleration is what a bounded packet looks like before it flattens.
QUICK_GROWTH_SIZES = (25, 100, 400)


def _make_wiki(root: Path) -> Path:
    wiki = root / "wiki"
    (wiki / "memories").mkdir(parents=True)
    (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
    (wiki / "log.md").write_text("# Log\n", encoding="utf-8")
    return wiki


def _populate(wiki: Path, count: int) -> None:
    """Fill a workspace with `count` memories drawn from the recall dataset."""
    intents = list(INTENTS)
    for index in range(count):
        name, _domain, title, _tldr, body, _queries = intents[index % len(intents)]
        suffix = "" if index < len(intents) else f" (variant {index // len(intents)})"
        write_memory_page(
            wiki,
            f"{body}{suffix}",
            title=f"{title}{suffix}",
            memory_type="preference",
            scope="user",
            tags=None,
            source="token-benchmark",
            timestamp="2026-08-01T00:00:00Z",
            allow_duplicate=True,
            allow_conflict=True,
        )


def _packet_tokens(wiki: Path, query: str, budget: str, cache: object, records: object) -> int:
    """One recall packet as the query path produces it.

    This is the per-recall cost. The MCP surface adds one more thing on the
    *first* response of a session - the session brief - which is measured
    separately by `measure_session_brief` rather than folded in here, because
    it is a once-per-session cost, not a per-recall one.

    The cache and records are built once per workspace and reused, which is
    both how a real session works and what keeps this benchmark from
    re-reading the whole wiki for every measured query.
    """
    payload = query_link(wiki, query, cache, records, budget=budget)
    chars = len(json.dumps(payload, ensure_ascii=False))
    return max(1, (chars + 3) // 4)


def measure_session_brief(wiki: Path) -> dict[str, object]:
    """What the MCP surface actually sends, first call vs steady state.

    Link's first MCP tool response of a session carries a memory brief, so
    the first recall costs materially more than every one after it. That is
    a deliberate trade (memory reaches agents that have no session hooks),
    but it must be measured and published, not hidden behind a per-recall
    average.
    """
    import importlib
    import sys

    saved_argv = list(sys.argv)
    sys.argv = ["link_mcp", "--wiki", str(wiki), "--surface", "slim"]
    try:
        import link_mcp.server as server
        importlib.reload(server)
        first = server.recall(query="how do we deploy", budget="micro")
        second = server.recall(query="how do we deploy", budget="micro")
    except Exception as exc:  # pragma: no cover - environment without the MCP SDK
        return {"available": False, "reason": str(exc)[:200]}
    finally:
        sys.argv = saved_argv

    def tokens(text: str) -> int:
        return max(1, (len(text) + 3) // 4)

    return {
        "available": True,
        "first_call_tokens": tokens(first),
        "steady_state_tokens": tokens(second),
        "brief_overhead_tokens": max(0, tokens(first) - tokens(second)),
    }


def measure_handoff_block(root: Path) -> dict[str, object]:
    """What a delivered handoff costs the receiving session.

    Honest scope: this measures Link's side of the trade - the tokens a
    handoff block adds to the next session's opening context. The other
    side (how many re-establishment tokens it saves) depends on agent
    behavior and is community-reported at 20-40% of a session; measuring
    that properly needs real-agent studies, not a synthetic proxy, so it
    is deliberately NOT claimed here.
    """
    from link_core.handoff import handoff_brief_block, pending_handoffs, write_handoff

    write_handoff(
        root,
        "Refactoring the auth middleware. Token validation moved to "
        "middleware/token.py; the refresh-path test still fails. Decided "
        "against JWT rotation for this release.",
        task="Auth middleware refactor",
        next_steps=["Fix the refresh-token test", "Run the linter before committing"],
        source="benchmark",
    )
    block = handoff_brief_block(pending_handoffs(root))
    return {"delivered_tokens": max(1, (len(block) + 3) // 4)}


def measure_budgets(wiki: Path, queries: list[str]) -> dict[str, dict[str, float]]:
    report: dict[str, dict[str, float]] = {}
    cache = build_wiki_cache(wiki)
    records = memory_records(wiki)
    try:
        for budget in ("micro", "small", "medium", "large"):
            counts = [_packet_tokens(wiki, query, budget, cache, records) for query in queries]
            report[budget] = {
                "mean_tokens": round(sum(counts) / len(counts)),
                "max_tokens": max(counts),
                "ceiling": BUDGET_CEILINGS[budget],
            }
    finally:
        close_wiki_cache(cache)
    return report


def measure_growth(queries: list[str], sizes: tuple[int, ...]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for size in sizes:
        with tempfile.TemporaryDirectory() as temp:
            wiki = _make_wiki(Path(temp))
            _populate(wiki, size)
            cache = build_wiki_cache(wiki)
            records = memory_records(wiki)
            try:
                counts = [_packet_tokens(wiki, query, "medium", cache, records) for query in queries]
            finally:
                close_wiki_cache(cache)
            rows.append({
                "memories": size,
                "mean_tokens": round(sum(counts) / len(counts)),
                "max_tokens": max(counts),
            })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quick", action="store_true",
                        help="smaller growth curve for CI (checks deceleration, not the full plateau)")
    args = parser.parse_args()

    queries = [intent_queries[0] for _n, _d, _t, _tl, _b, intent_queries in INTENTS][:20]

    with tempfile.TemporaryDirectory() as temp:
        wiki = _make_wiki(Path(temp))
        _populate(wiki, len(INTENTS))
        budgets = measure_budgets(wiki, queries)

    sizes = QUICK_GROWTH_SIZES if args.quick else GROWTH_SIZES
    growth = measure_growth(queries, sizes)
    first_store, last_store = growth[0], growth[-1]
    growth_ratio = (
        float(last_store["mean_tokens"]) / float(first_store["mean_tokens"])
        if float(first_store["mean_tokens"]) else 0.0
    )
    # The claim is the plateau, not the total: the final quadrupling.
    plateau_ratio = (
        float(growth[-1]["mean_tokens"]) / float(growth[-2]["mean_tokens"])
        if len(growth) > 1 and float(growth[-2]["mean_tokens"]) else 0.0
    )

    with tempfile.TemporaryDirectory() as temp:
        brief_wiki = _make_wiki(Path(temp))
        _populate(brief_wiki, len(INTENTS))
        session_brief = measure_session_brief(brief_wiki)
        handoff_cost = measure_handoff_block(brief_wiki.parent)

    report = {
        "budgets": budgets,
        "growth": growth,
        "mcp_session_brief": session_brief,
        "handoff_block": handoff_cost,
        "store_growth_factor": round(float(last_store["memories"]) / float(first_store["memories"]), 1),
        "packet_growth_factor": round(growth_ratio, 3),
        "plateau_ratio": round(plateau_ratio, 3),
        "queries_measured": len(queries),
    }

    failures: list[str] = []
    for budget, row in budgets.items():
        if row["max_tokens"] > row["ceiling"]:
            failures.append(f"{budget}: {row['max_tokens']} tokens > ceiling {row['ceiling']}")
    if args.quick:
        steps = [
            float(growth[i + 1]["mean_tokens"]) / float(growth[i]["mean_tokens"])
            for i in range(len(growth) - 1)
            if float(growth[i]["mean_tokens"])
        ]
        if len(steps) >= 2 and steps[-1] > steps[0]:
            failures.append(
                f"packet growth accelerated ({steps[0]:.2f}x then {steps[-1]:.2f}x); "
                "bounded packets decelerate toward a plateau"
            )
    elif plateau_ratio > PLATEAU_TOLERANCE:
        failures.append(
            f"packet grew {plateau_ratio:.2f}x on the last {sizes[-1] // sizes[-2]}x "
            "of store growth; bounded packets must plateau"
        )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Link token-economics benchmark — {len(queries)} queries, "
              f"{len(INTENTS)}-memory corpus\n")
        print(f"{'budget':10} {'mean tokens':>12} {'max':>8} {'ceiling':>9}")
        for budget, row in budgets.items():
            print(f"{budget:10} {row['mean_tokens']:>12} {row['max_tokens']:>8} {row['ceiling']:>9}")
        print(f"\n{'store size':12} {'mean tokens (medium budget)':>30}")
        for row in growth:
            print(f"{row['memories']:<12} {row['mean_tokens']:>30}")
        print(f"\nHandoff delivery cost: {handoff_cost['delivered_tokens']} tokens added to the "
              "receiving session's opening context (savings side needs real-agent studies; not claimed)")
        if session_brief.get("available"):
            print(f"\nMCP surface: first recall of a session {session_brief['first_call_tokens']} tokens "
                  f"(carries the session brief), steady state {session_brief['steady_state_tokens']} tokens")
        print(f"\nStore grew {report['store_growth_factor']}x; packet grew "
              f"{report['packet_growth_factor']}x, and the last quadrupling moved it "
              f"{report['plateau_ratio']}x — bounded packets plateau.")

    for failure in failures:
        print(f"REGRESSION: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
