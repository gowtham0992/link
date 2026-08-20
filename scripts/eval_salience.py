#!/usr/bin/env python3
"""Usage-aware ranking: does it help without burying the cold memories?

Ranking by how often something is read is the oldest trick in retrieval and
it has an equally old failure: the thing you reach for constantly crowds out
the thing you need rarely and urgently. A memory system where the rarely-used
memory becomes unreachable is worse than one that never learned usage at all,
because the frequent memories were the ones you would have remembered anyway.

So the question is not "does salience raise the average". It is whether the
cold half survives. This split measures both:

- **hot queries** - the answer is a memory with retrieval history
- **cold queries** - the answer is a memory that has never been read

Salience passes only if hot improves and cold does not regress.

Three formulations were measured, none adopted:

- **additive** - the boost is added to every score. Helps the hot half and
  costs the cold half at every ceiling from 1 to 4; at ceiling 1 the hot half
  gains nothing and cold still falls. Anything that adds points to a subset
  can demote a better match for the complement.
- **tiebreak** - the boost only separates equal scores, so it cannot demote a
  better match. Provably safe and completely inert here: ties occur among
  low-scoring memories, not at the decision boundary.
- **recency** - the Generative Agents decay itself, measured across the
  recommended 7-to-30 day half-life range. The worst of the three: at a 30 day
  half-life the fresh half gains 0.0204 while the old half loses 0.0510, and
  at a 7 day half-life with a small ceiling the fresh half gains nothing and
  the old half still falls. A constraint read six months ago is still true.
- **diversity (MMR)** - the literature's other suggestion, penalising
  near-duplicates in the top-K rather than boosting anything. Measured on
  LoCoMo, Link's top-10 has a near-duplicate pair rate of 0.0000, so there is
  nothing for it to fix.

The underlying reason is a category difference. The Generative Agents
formulation that production retrieval policies descend from
(alpha*recency + beta*importance + gamma*similarity) was built for episodic
observation streams, where an old observation genuinely matters less. Link
stores durable constraints. "We deploy on Tuesdays" does not become less true
because it went unread for a month - that is exactly when it most needs
surfacing.

Run:  python3 scripts/eval_salience.py [--json]
Exit: non-zero if cold-query accuracy drops at all.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))
sys.path.insert(0, str(ROOT / "scripts"))

from link_core.memory import memory_rank_score, recall_memories, score_memory  # noqa: E402
from link_core.usage import usage_salience  # noqa: E402
from recall_dataset import INTENTS  # noqa: E402

HOT_SHARE = 0.3          # a realistic ledger is skewed: a few memories, many reads
READS_FOR_HOT = 12


def build() -> tuple[list[dict], set[str], list[tuple[str, str]]]:
    records: list[dict] = []
    queries: list[tuple[str, str]] = []
    for name, _domain, title, tldr, body, intent_queries in INTENTS:
        records.append({
            "name": name, "title": title, "tldr": tldr, "body": body,
            "memory_type": "preference", "scope": "user", "status": "active",
            "review_status": "reviewed", "date_captured": "2026-05-01T00:00:00Z",
            "context": "", "project": "",
        })
        for question in intent_queries:
            queries.append((question, name))
    hot_count = max(1, int(len(records) * HOT_SHARE))
    hot = {str(record["name"]) for record in records[:hot_count]}
    return records, hot, queries


def accuracy(records: list[dict], queries: list[tuple[str, str]],
             salience: dict[str, int] | None, wanted_hot: bool, hot: set[str],
             mode: str = "additive") -> float:
    hits = total = 0
    for question, gold in queries:
        if (gold in hot) != wanted_hot:
            continue
        total += 1
        if mode == "tiebreak" and salience:
            # Rank on the base score, using salience only to order equals.
            ranked = sorted(
                records,
                key=lambda record: (
                    memory_rank_score(record, score_memory(record, question)),
                    salience.get(str(record.get("name")), 0),
                ),
                reverse=True,
            )
            top = str(ranked[0].get("name")) if ranked else ""
        else:
            results = recall_memories(records, question, limit=1, salience=salience)
            top = str(results[0].get("name")) if results else ""
        if top == gold:
            hits += 1
    return hits / total if total else 0.0



# Recency track. The Generative Agents formulation decays by time since last
# read, so it is measured on its own terms: a plausible access pattern where a
# third of the corpus was read this week, a third this month, and a third not
# for half a year. Every one of them is still true, which is the whole point.
RECENCY_BUCKET_HOURS = (24 * 3, 24 * 30, 24 * 180)


def access_ages(records: list[dict]) -> dict[str, int]:
    return {
        str(record["name"]): RECENCY_BUCKET_HOURS[index % len(RECENCY_BUCKET_HOURS)]
        for index, record in enumerate(records)
    }


def recency_boost(hours: int | None, half_life_days: float, ceiling: int) -> int:
    if hours is None or ceiling <= 0:
        return 0
    return int(round((0.5 ** (hours / (half_life_days * 24))) * ceiling))


def recency_accuracy(records: list[dict], queries: list[tuple[str, str]],
                     ages: dict[str, int], subset: set[str],
                     half_life_days: float, ceiling: int) -> float:
    hits = total = 0
    for question, gold in queries:
        if gold not in subset:
            continue
        total += 1
        best_name, best_key = "", None
        for record in records:
            name = str(record["name"])
            key = memory_rank_score(record, score_memory(record, question))
            key += recency_boost(ages.get(name), half_life_days, ceiling)
            if best_key is None or key > best_key:
                best_key, best_name = key, name
        if best_name == gold:
            hits += 1
    return hits / total if total else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure usage-aware ranking.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    records, hot, queries = build()
    events = [{"memories": [name]} for name in hot for _ in range(READS_FOR_HOT)]
    salience = usage_salience(events)

    report = {
        "memories": len(records), "queries": len(queries),
        "hot_memories": len(hot), "salience_entries": len(salience),
        "hot_hit@1_off": round(accuracy(records, queries, None, True, hot), 4),
        "hot_hit@1_on": round(accuracy(records, queries, salience, True, hot), 4),
        "cold_hit@1_off": round(accuracy(records, queries, None, False, hot), 4),
        "cold_hit@1_on": round(accuracy(records, queries, salience, False, hot), 4),
        "hot_hit@1_tiebreak": round(accuracy(records, queries, salience, True, hot, "tiebreak"), 4),
        "cold_hit@1_tiebreak": round(accuracy(records, queries, salience, False, hot, "tiebreak"), 4),
    }
    report["hot_delta"] = round(report["hot_hit@1_on"] - report["hot_hit@1_off"], 4)
    report["cold_delta"] = round(report["cold_hit@1_on"] - report["cold_hit@1_off"], 4)

    ages = access_ages(records)
    fresh = {name for name, hours in ages.items() if hours <= 24 * 7}
    old = {name for name, hours in ages.items() if hours >= 24 * 180}
    report["recency_fresh_off"] = round(recency_accuracy(records, queries, ages, fresh, 30, 0), 4)
    report["recency_old_off"] = round(recency_accuracy(records, queries, ages, old, 30, 0), 4)
    report["recency_fresh_on"] = round(recency_accuracy(records, queries, ages, fresh, 30, 4), 4)
    report["recency_old_on"] = round(recency_accuracy(records, queries, ages, old, 30, 4), 4)
    report["recency_old_delta"] = round(report["recency_old_on"] - report["recency_old_off"], 4)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"memories {report['memories']}, queries {report['queries']}, "
              f"hot {report['hot_memories']}, salience entries {report['salience_entries']}")
        print(f"hot  hit@1: {report['hot_hit@1_off']} -> {report['hot_hit@1_on']}  ({report['hot_delta']:+})")
        print(f"cold hit@1: {report['cold_hit@1_off']} -> {report['cold_hit@1_on']}  ({report['cold_delta']:+})")
        print(f"tiebreak-only  hot {report['hot_hit@1_tiebreak']}  cold {report['cold_hit@1_tiebreak']}"
              "   (safe by construction, and inert)")
        print(f"recency (30d half-life): fresh {report['recency_fresh_off']} -> "
              f"{report['recency_fresh_on']}, old {report['recency_old_off']} -> "
              f"{report['recency_old_on']}  ({report['recency_old_delta']:+})")
        regressed = report["cold_delta"] < 0 or report["recency_old_delta"] < 0
        print(f"verdict: {'usage-aware ranking regressed' if regressed else 'held'}")
    return 1 if (report["cold_delta"] < 0 or report["recency_old_delta"] < 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
