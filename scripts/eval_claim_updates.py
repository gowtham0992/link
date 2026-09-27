#!/usr/bin/env python3
"""Claim-shaped recall: does Link return the current value of a fact that changed?

LoCoMo is chat logs with a lenient judge and an answer key that is partly
wrong; the published agent-memory results that matter most for a store of
durable claims come from fact-update benchmarks (MemoryAgentBench's
FactConsolidation, HorizonBench's evolving preferences). The finding there
is consistent: systems retrieve an outdated value more often than they miss
entirely, and deterministic recency beats model-mediated resolution.

This slice asks that question of Link directly. Subjects - a rate limit, a
port, a database, a deploy day, an indentation preference - change value
two or three times, a month apart, phrased the way people actually write
updates ("we switched from X to Y", "Z replaced Y"). Each subject is
queried twice: once in the words of the claim, once as a paraphrase that
shares little vocabulary with it. Every subject lives in one store with
the others as distractors.

Two stores, because both happen in real use:

  lineage     each update was saved with `supersedes`, as review or
              lnk remember --supersedes records it
  no lineage  each update was saved as a new memory with nothing linking
              it to the old one

Reported per store: current@1 (the top memory states the current value),
stale@1 (it states an older value), miss@1 (neither), and point-in-time
accuracy (recall as of a date between two versions returns the value that
was true then). Values are matched as exact tokens, never judged by a model.

This slice was authored after the ranking changes it measures and was not
used to tune them. The gate is a floor set from the first measurement, not
a target: it fails only if a change makes recall return stale values more
often than it does today.

Run:  python3 scripts/eval_claim_updates.py [--json]
"""
from __future__ import annotations

import os

os.environ["LINK_SEMANTIC"] = "off"  # deterministic lexical recall

import argparse
import json
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.memory import memory_records, recall_memories, write_memory_page  # noqa: E402


@dataclass(frozen=True)
class Subject:
    name: str
    memory_type: str
    versions: tuple[tuple[str, str], ...]   # (value token, sentence)
    direct: str                              # query in the claim's own words
    paraphrase: str                          # query sharing little vocabulary


SUBJECTS: tuple[Subject, ...] = (
    Subject("rate-limit", "fact", (
        ("100/min", "The public API rate limit is 100/min per client."),
        ("500/min", "We raised the public API rate limit from 100/min to 500/min."),
        ("1000/min", "The API rate limit is now 1000/min per client after the capacity upgrade."),
    ), "what is the public API rate limit", "how many requests can one client send each minute"),
    Subject("staging-port", "fact", (
        ("8080", "The staging server listens on port 8080."),
        ("8443", "Staging moved from port 8080 to 8443 when we turned on TLS."),
    ), "which port does the staging server listen on", "where do I point my browser to reach staging locally"),
    Subject("primary-db", "decision", (
        ("mysql", "The orders service stores its data in MySQL."),
        ("postgres", "We migrated the orders service from MySQL to Postgres."),
    ), "which database does the orders service use", "what engine sits behind order persistence"),
    Subject("deploy-day", "decision", (
        ("tuesday", "Payments deploys go out every Tuesday."),
        ("thursday", "Payments deploys moved from Tuesday to Thursday."),
        ("wednesday", "Payments deploys now go out on Wednesday, not Thursday."),
    ), "which day do payments deploys go out", "when in the week can the billing change ship"),
    Subject("package-manager", "preference", (
        ("npm", "The web app uses npm for dependencies."),
        ("pnpm", "The web app switched from npm to pnpm."),
    ), "which package manager does the web app use", "what installs the frontend dependencies"),
    Subject("ci-provider", "decision", (
        ("jenkins", "Our CI runs on Jenkins."),
        ("buildkite", "Buildkite replaced Jenkins for CI."),
        ("github-actions", "CI moved from Buildkite to github-actions."),
    ), "which CI system do we run", "where do the pull request checks execute"),
    Subject("node-version", "fact", (
        ("18", "The backend runs on Node 18."),
        ("20", "We upgraded the backend from Node 18 to Node 20."),
        ("22", "The backend is on Node 22 now."),
    ), "which Node version does the backend run", "what JavaScript runtime release powers the server"),
    Subject("region", "decision", (
        ("us-east-1", "Production lives in the us-east-1 region."),
        ("eu-west-1", "We moved production from us-east-1 to eu-west-1 for data residency."),
    ), "which region is production in", "where are the live servers hosted geographically"),
    Subject("indentation", "preference", (
        ("tabs", "I prefer tabs for indentation."),
        ("spaces", "I switched from tabs to spaces for indentation."),
    ), "tabs or spaces for indentation", "how should new code be indented"),
    Subject("oncall-owner", "fact", (
        ("priya", "Priya owns the on-call rotation."),
        ("marcus", "Marcus took over the on-call rotation from Priya."),
    ), "who owns the on-call rotation", "who do I page when production breaks at night"),
    Subject("retry-count", "fact", (
        ("3", "Webhook delivery retries 3 times before giving up."),
        ("5", "Webhook delivery now retries 5 times instead of 3."),
    ), "how many times does webhook delivery retry", "how persistent is the callback sender after a failure"),
    Subject("logger", "decision", (
        ("logging", "Services log with the standard logging module."),
        ("structlog", "We moved all services from logging to structlog."),
    ), "which logging library do services use", "what should a new worker emit its log lines with"),
    Subject("standup-time", "fact", (
        ("9:30", "Standup is at 9:30 every morning."),
        ("10:00", "Standup moved from 9:30 to 10:00."),
    ), "what time is standup", "when does the daily team sync start"),
    Subject("answer-length", "preference", (
        ("detailed", "I like detailed answers with background."),
        ("short", "I now prefer short answers; skip the background."),
    ), "how long should answers be", "how much should the assistant write in a reply"),
    Subject("python-version", "fact", (
        ("3.10", "The data pipeline runs on Python 3.10."),
        ("3.12", "The data pipeline moved from Python 3.10 to 3.12."),
    ), "which Python version does the data pipeline use", "what interpreter release do the ETL jobs need"),
    Subject("search-backend", "decision", (
        ("elasticsearch", "Site search is backed by Elasticsearch."),
        ("typesense", "Typesense replaced Elasticsearch for site search."),
    ), "what backs site search", "which engine answers queries in the search box"),
)

MONTHS = ("2026-01-15", "2026-03-15", "2026-05-15", "2026-07-15")


def _value_in(text: str, value: str) -> bool:
    # Token boundaries, except that a sentence-ending period may follow.
    return re.search(rf"(?<![\w.:/-]){re.escape(value.lower())}(?![\w:/-])(?!\.\w)", text.lower()) is not None


def _memory_text(record: dict[str, object]) -> str:
    return " ".join(str(record.get(key) or "") for key in ("title", "tldr", "snippet", "body"))


def build_store(root: Path, *, lineage: bool) -> Path:
    wiki = root / "wiki"
    (wiki / "memories").mkdir(parents=True)
    (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
    (wiki / "log.md").write_text("# Log\n", encoding="utf-8")
    for subject in SUBJECTS:
        previous: str | None = None
        for index, (_value, sentence) in enumerate(subject.versions):
            result = write_memory_page(
                wiki, sentence, title=None, memory_type=subject.memory_type, scope="user", tags=None,
                source="claim-updates", timestamp=f"{MONTHS[index]}T09:00:00Z",
                supersedes=previous if lineage else None,
                records=memory_records(wiki),
                allow_duplicate=True, allow_conflict=True,
                log_writer=lambda *a: None, rebuild_backlinks=lambda: True,
            )
            previous = str(result.get("name") or "") or previous
    return wiki


def classify(record: dict[str, object] | None, subject: Subject, current_index: int) -> str:
    if record is None:
        return "miss"
    text = _memory_text(record)
    current_value = subject.versions[current_index][0]
    older = [value for value, _ in subject.versions[:current_index]]
    newer = [value for value, _ in subject.versions[current_index + 1:]]
    states_current = _value_in(text, current_value)
    # An update sentence names the old value too ("from 100/min to 500/min"):
    # it counts as current when it states the current value and no newer one.
    if states_current and not any(_value_in(text, value) for value in newer):
        return "current"
    if any(_value_in(text, value) for value in older + newer):
        return "stale"
    return "miss"


def measure(wiki: Path) -> dict[str, object]:
    records = memory_records(wiki)
    counts = {"direct": {"current": 0, "stale": 0, "miss": 0}, "paraphrase": {"current": 0, "stale": 0, "miss": 0}}
    as_of_hits = 0
    as_of_total = 0
    failures: list[str] = []
    for subject in SUBJECTS:
        latest = len(subject.versions) - 1
        for kind, query in (("direct", subject.direct), ("paraphrase", subject.paraphrase)):
            hits = recall_memories(records, query, limit=3)
            outcome = classify(hits[0] if hits else None, subject, latest)
            counts[kind][outcome] += 1
            if outcome != "current":
                failures.append(f"{kind}:{subject.name}:{outcome}")
        # Point in time: a date between the first two versions must return v1.
        as_of_total += 1
        hits = recall_memories(records, subject.direct, limit=3, as_of="2026-02-15")
        if classify(hits[0] if hits else None, subject, 0) == "current":
            as_of_hits += 1
        else:
            failures.append(f"as_of:{subject.name}")
    total = len(SUBJECTS)

    def rates(bucket: dict[str, int]) -> dict[str, float]:
        return {f"{key}@1": round(value / total, 4) for key, value in bucket.items()}

    return {
        "direct": rates(counts["direct"]),
        "paraphrase": rates(counts["paraphrase"]),
        "as_of_accuracy": round(as_of_hits / as_of_total, 4),
        "failures": failures,
    }


# Floors from the first measurement (see the docstring): the gate catches a
# regression toward stale values; it is not a target to tune against.
# First measurement (lexical, 2026-09-26): lineage direct current 0.875,
# as-of 0.94; no-lineage direct current 0.56 with 0.38 stale. Paraphrase
# queries are left ungated: they are what the semantic tier is for.
FLOORS = {
    ("lineage", "direct", "current@1"): 0.8,
    ("lineage", "direct", "stale@1"): None,     # must stay at 0: lineage never returns a superseded value
    ("lineage", "as_of_accuracy"): 0.85,
    ("no_lineage", "direct", "current@1"): 0.45,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report: dict[str, object] = {"subjects": len(SUBJECTS),
                                 "versions": sum(len(s.versions) for s in SUBJECTS)}
    for label, lineage in (("lineage", True), ("no_lineage", False)):
        with tempfile.TemporaryDirectory(prefix="link-claim-updates-") as temp:
            report[label] = measure(build_store(Path(temp), lineage=lineage))
    problems: list[str] = []
    for key, floor in FLOORS.items():
        value: object = report
        for part in key:
            value = value[part] if isinstance(value, dict) else None  # type: ignore[index]
        if floor is None:
            if value != 0:
                problems.append(f"{'.'.join(key)} = {value}; a superseded value came back first")
        elif not isinstance(value, (int, float)) or value < floor:
            problems.append(f"{'.'.join(key)} = {value} is below the floor {floor}")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Claim updates - {report['subjects']} subjects, {report['versions']} versions, "
              "each queried in its own words and as a paraphrase")
        for label in ("lineage", "no_lineage"):
            part = report[label]
            assert isinstance(part, dict)
            print(f"\n{label.replace('_', ' ')}:")
            for kind in ("direct", "paraphrase"):
                r = part[kind]
                print(f"  {kind:10}  current {r['current@1']:.2f}   stale {r['stale@1']:.2f}   miss {r['miss@1']:.2f}")
            print(f"  as of a past date: {part['as_of_accuracy']:.2f}")
    for problem in problems:
        print(f"REGRESSION: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
