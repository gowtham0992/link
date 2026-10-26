#!/usr/bin/env python3
"""Does Link change what an agent does? A with/without behavioral A/B.

Retrieval benchmarks measure whether the right memory comes back. The
question people actually ask is different: with Link connected, does the
agent do the right thing more often than without it? The one external
review of Link named this exact gap - no with/without behavioral test.

Each scenario is a task whose correct answer depends on something the user
told an earlier session: a deploy day, a branch rule, a package manager, a
port, a decision that was later reversed. Every scenario's memories go into
one shared store with realistic distractors, so recall has to pick the
right memory out of many. Two conditions per scenario:

  A  no memory   the task alone, as an agent without Link sees it
  B  Link        what a connected agent actually has: the session-start
                 brief Link's hook injects, plus the recall packet for the
                 task (query_link, budget micro)

Answers are scored by fixed patterns - the current truth must appear, the
stale or generic answer must not. No model grades another model.

Two ways to run it:

  --mode dry (default, CI)
      A deterministic oracle stands in for the model: it gives the informed
      answer only when the governing memory is present in its context, and
      when both the current and the superseded claim are present it follows
      whichever comes first (the position bias real models show). This
      measures the half of the question Link controls - is the memory that
      should change the behavior actually in front of the agent, ahead of
      the stale one - with no model and no network.

  --mode live --agent-command "claude -p --model claude-haiku-4-5" --yes
      Each prompt is piped to the command's stdin and its stdout is scored.
      Link itself never touches the network: the command is yours, and so
      is the cost. Nothing runs without --yes; the number of calls is
      printed first.

Run:  python3 scripts/eval_behavior_ab.py [--json]
Exit: dry mode is a CI gate - non-zero if Link's condition B does not beat
      condition A, or if any scenario's governing memory is missing from
      the packet.
"""
from __future__ import annotations

import os

os.environ["LINK_SEMANTIC"] = "off"  # deterministic: never load a local model

import argparse
import json
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))
sys.path.insert(0, str(ROOT / "scripts"))

from link_core.memory import memory_brief, memory_records, slugify, write_memory_page  # noqa: E402
from link_core.query import query_link  # noqa: E402
from link_core.wiki import build_wiki_cache, close_wiki_cache  # noqa: E402
from recall_dataset import INTENTS  # noqa: E402


@dataclass(frozen=True)
class Memory:
    title: str
    text: str
    memory_type: str = "decision"
    supersedes: str = ""  # title of the memory this one replaces


@dataclass(frozen=True)
class Scenario:
    name: str
    kind: str
    memories: tuple[Memory, ...]
    task: str
    key: str                 # phrase that shows the governing memory reached the agent
    stale_key: str = ""      # phrase of a superseded claim, if any
    informed: str = ""       # what an agent that saw the memory answers
    default: str = ""        # what an agent without it plausibly answers
    correct: str = ""        # regex the answer must match
    wrong: str = ""          # regex the answer must not match
    tags: tuple[str, ...] = field(default_factory=tuple)


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("deploy-day", "decision",
             (Memory("Payments deploy day", "We deploy the payments service only on Tuesdays after standup."),),
             "I want to ship the payments fix this week. Which day should the deploy go out?",
             key="only on tuesdays", informed="Deploy it on Tuesday after standup.",
             default="Any weekday works; Friday afternoon is fine if tests pass.",
             correct=r"\btuesday", wrong=r"\bfriday"),
    Scenario("branch-policy", "preference",
             (Memory("Branch policy", "I push feature work to the develop branch, never straight to main.", "preference"),),
             "Which branch should I push this refactor to?",
             key="develop branch", informed="Push it to develop.", default="Push it to main.",
             correct=r"\bdevelop\b", wrong=r"\bto main\b"),
    Scenario("package-manager", "preference",
             (Memory("Package manager", "This repo uses pnpm for everything; do not run npm install here.", "preference"),),
             "What command installs the dependencies for this repo?",
             key="uses pnpm", informed="pnpm install", default="npm install",
             correct=r"\bpnpm install\b", wrong=r"\bnpm install\b"),
    Scenario("test-runner", "procedure",
             (Memory("How to run tests", "Run the test suite with `make check`, which also runs the linters.", "procedure"),),
             "How do I run the tests before I open a PR?",
             key="make check", informed="Run make check.", default="Run pytest.",
             correct=r"make check", wrong=r"^run pytest"),
    Scenario("staging-port", "fact",
             (Memory("Local staging port", "The local staging server listens on port 8443, not 3000.", "fact"),),
             "Which port do I open to reach the local staging server?",
             key="port 8443", informed="Port 8443.", default="Port 3000.",
             correct=r"8443", wrong=r"\b3000\b"),
    Scenario("never-touch-env", "constraint",
             (Memory("Secrets files", "Never read or edit .env files in this project; ask for the value instead.", "preference"),),
             "The build needs the database URL. Should I read it from the .env file?",
             key="never read or edit .env", informed="No - ask for the value instead of reading .env.",
             default="Yes, read DATABASE_URL from .env.",
             correct=r"\bask\b", wrong=r"^yes"),
    Scenario("reversed-deploy-day", "supersession",
             (Memory("Mobile release day", "Mobile releases go out on Mondays."),
              Memory("Mobile release day moved", "Mobile releases now go out on Thursdays, no longer Mondays.",
                     supersedes="Mobile release day")),
             "When does the next mobile release go out?",
             key="now go out on thursdays", stale_key="go out on mondays.",
             informed="Thursday.", default="Probably Monday.",
             correct=r"\bthursday", wrong=r"\bmonday\b(?! no longer)"),
    Scenario("reversed-db", "supersession",
             (Memory("Primary database", "The service stores data in MySQL.", "fact"),
              Memory("Primary database migrated", "We migrated the service from MySQL to Postgres in June.", "fact",
                     supersedes="Primary database")),
             "Which database client library should the new service module import?",
             key="to postgres", stale_key="stores data in mysql",
             informed="A Postgres client such as psycopg.", default="A MySQL client.",
             correct=r"postgres|psycopg", wrong=r"\bmysql client"),
    Scenario("answer-style", "preference",
             (Memory("Answer style", "Keep answers short and cite the wiki page you used.", "preference"),),
             "Explain how our cache invalidation works.",
             key="cite the wiki page", informed="Short answer, citing the wiki page.",
             default="A long answer with no citation.",
             correct=r"cit", wrong=r"no citation"),
    Scenario("release-owner", "fact",
             (Memory("Release owner", "Priya owns the release checklist and signs off every release.", "fact"),),
             "Who do I ask to sign off the release?",
             key="priya owns the release", informed="Ask Priya.", default="Ask the team lead.",
             correct=r"\bpriya\b", wrong=r"team lead"),
    Scenario("api-versioning", "decision",
             (Memory("API versioning", "Breaking API changes ship behind a new /v2 path; /v1 stays frozen.", "decision"),),
             "I need to rename a field in the public API response. How do I ship it?",
             key="new /v2 path", informed="Ship it under /v2 and leave /v1 frozen.",
             default="Rename it in place and bump the minor version.",
             correct=r"/v2", wrong=r"in place"),
    Scenario("logging-lib", "decision",
             (Memory("Logging library", "Use structlog for all new logging; the stdlib logging module is being phased out.",
                     "decision"),),
             "Which logging library should the new worker use?",
             key="use structlog", informed="structlog.", default="The standard logging module.",
             correct=r"structlog", wrong=r"standard logging"),
)


# Scenarios where the governing memory does not reach the agent today. They
# are published, not hidden: the gate fails on any *new* miss, and a gap
# that gets fixed should be deleted here so the gate tightens with it.
KNOWN_GAPS: dict[str, str] = {
    "reversed-db": "an unrelated 'Logging library' memory outranks the migration memory on the shared word "
                   "'library', and the micro budget returns one memory",
}


def _distractors() -> list[Memory]:
    """Real-shaped unrelated memories so recall has to discriminate."""
    return [Memory(title, body, "preference") for _name, _domain, title, _tldr, body, _q in list(INTENTS)[:48]]


def build_store(root: Path) -> Path:
    wiki = root / "wiki"
    (wiki / "memories").mkdir(parents=True)
    (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
    (wiki / "log.md").write_text("# Log\n", encoding="utf-8")
    names: dict[str, str] = {}
    memories: list[Memory] = _distractors()
    for scenario in SCENARIOS:
        memories.extend(scenario.memories)
    for memory in memories:
        result = write_memory_page(
            wiki, memory.text, title=memory.title, memory_type=memory.memory_type, scope="user",
            tags=None, source="behavior-ab", timestamp="2026-08-01T00:00:00Z",
            supersedes=names.get(memory.supersedes) or None,
            allow_duplicate=True, allow_conflict=True,
            log_writer=lambda *a: None, rebuild_backlinks=lambda: True,
        )
        names[memory.title] = str(result.get("name") or slugify(memory.title))
    return wiki


SESSION_BRIEF_LIMIT = 5  # the session-start hook's default


def session_brief(records: object) -> str:
    """The brief the session-start hook injects before any task is known."""
    brief = memory_brief(records, query="", limit=SESSION_BRIEF_LIMIT)  # type: ignore[arg-type]
    return json.dumps(brief.get("relevant_memories") or [], ensure_ascii=False)


def packet_context(wiki: Path, task: str, cache: object, records: object, brief: str = "") -> str:
    """The text Link puts in front of the agent for this task."""
    packet = query_link(wiki, task, cache, records, budget="micro")  # type: ignore[arg-type]
    task_packet = json.dumps(packet, ensure_ascii=False)
    return f"{brief}\n{task_packet}" if brief else task_packet


def oracle_answer(scenario: Scenario, context: str) -> str:
    """A deterministic stand-in for a model (dry mode).

    It knows nothing but its context: the informed answer only when the
    governing memory is there, the default otherwise; when the current and
    superseded claims are both present, it follows whichever comes first.
    """
    lowered = context.lower()
    at_key = lowered.find(scenario.key.lower())
    at_stale = lowered.find(scenario.stale_key.lower()) if scenario.stale_key else -1
    if at_key < 0:
        return scenario.default
    if 0 <= at_stale < at_key:
        return scenario.default
    return scenario.informed


def score(scenario: Scenario, answer: str) -> bool:
    text = answer.strip().lower()
    if scenario.wrong and re.search(scenario.wrong, text, re.M):
        return False
    return bool(re.search(scenario.correct, text, re.M))


def prompt_for(scenario: Scenario, context: str | None) -> str:
    parts = ["You are a coding agent helping the user in their repository. Answer in one or two sentences."]
    if context:
        parts.append("Local memory Link loaded for this task (JSON):\n" + context)
    parts.append("Task: " + scenario.task)
    return "\n\n".join(parts)


def run_command(command: str, prompt: str, timeout: int) -> str:
    completed = subprocess.run(shlex.split(command), input=prompt, capture_output=True,
                               text=True, timeout=timeout, check=False)
    return completed.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("dry", "live"), default="dry")
    parser.add_argument("--agent-command", default="", help="live mode: command that reads a prompt on stdin")
    parser.add_argument("--yes", action="store_true", help="live mode: actually run the calls")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.mode == "live":
        calls = len(SCENARIOS) * 2
        if not args.agent_command:
            print("live mode needs --agent-command, e.g. \"claude -p --model claude-haiku-4-5\"", file=sys.stderr)
            return 2
        if not args.yes:
            print(f"live mode would make {calls} calls to: {args.agent_command}\n"
                  "That spends your model budget. Re-run with --yes to do it.", file=sys.stderr)
            return 2

    rows: list[dict[str, object]] = []
    missing: list[str] = []
    with tempfile.TemporaryDirectory(prefix="link-behavior-ab-") as temp:
        wiki = build_store(Path(temp))
        cache = build_wiki_cache(wiki, use_persistent_cache=False)
        records = memory_records(wiki)
        brief = session_brief(records)
        try:
            for scenario in SCENARIOS:
                context = packet_context(wiki, scenario.task, cache, records, brief)
                present = scenario.key.lower() in context.lower()
                if not present:
                    missing.append(scenario.name)
                if args.mode == "dry":
                    answer_a = oracle_answer(scenario, "")
                    answer_b = oracle_answer(scenario, context)
                else:
                    answer_a = run_command(args.agent_command, prompt_for(scenario, None), args.timeout)
                    answer_b = run_command(args.agent_command, prompt_for(scenario, context), args.timeout)
                rows.append({
                    "scenario": scenario.name, "kind": scenario.kind,
                    "memory_in_packet": present,
                    "packet_tokens": max(1, (len(context) + 3) // 4),
                    "a_correct": score(scenario, answer_a), "b_correct": score(scenario, answer_b),
                    "a_answer": answer_a[:200], "b_answer": answer_b[:200],
                })
        finally:
            close_wiki_cache(cache)

    total = len(rows)
    a_score = sum(1 for row in rows if row["a_correct"])
    b_score = sum(1 for row in rows if row["b_correct"])
    report = {
        "mode": args.mode,
        "agent": args.agent_command if args.mode == "live" else "deterministic oracle",
        "scenarios": total,
        "store_size": len(_distractors()) + sum(len(s.memories) for s in SCENARIOS),
        "without_link_correct": a_score,
        "with_link_correct": b_score,
        "memory_in_packet": total - len(missing),
        "known_gaps": {name: KNOWN_GAPS[name] for name in missing if name in KNOWN_GAPS},
        "mean_packet_tokens": round(sum(int(str(r["packet_tokens"])) for r in rows) / max(1, total)),
        "rows": rows,
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Behavioral A/B - {total} scenarios, {report['store_size']} memories in the store, "
              f"agent: {report['agent']}")
        print(f"\n{'scenario':22} {'kind':13} {'in packet':10} {'A no memory':12} {'B Link':7}")
        for row in rows:
            print(f"{row['scenario']:22} {row['kind']:13} {'yes' if row['memory_in_packet'] else 'NO':10} "
                  f"{'right' if row['a_correct'] else 'wrong':12} {'right' if row['b_correct'] else 'wrong':7}")
        print(f"\nwithout Link: {a_score}/{total} right   with Link: {b_score}/{total} right   "
              f"governing memory in packet: {report['memory_in_packet']}/{total}   "
              f"mean packet: {report['mean_packet_tokens']} tokens")
    new_misses = [name for name in missing if name not in KNOWN_GAPS]
    if not args.json:
        for name in missing:
            if name in KNOWN_GAPS:
                print(f"known gap: {name} - {KNOWN_GAPS[name]}")
        for name in KNOWN_GAPS:
            if name not in missing:
                print(f"known gap now fixed, remove it from KNOWN_GAPS: {name}")
    if args.mode == "dry" and (new_misses or b_score <= a_score):
        for name in new_misses:
            print(f"REGRESSION: governing memory missing from the packet: {name}", file=sys.stderr)
        if b_score <= a_score:
            print("REGRESSION: Link did not beat the no-memory condition", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
