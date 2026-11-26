#!/usr/bin/env python3
"""Link memory-poisoning benchmark: prompt injection via durable memory.

A planted memory is injected into every future session, which makes agent
memory the highest-value prompt-injection target there is. This benchmark
drives authored attacks (scripts/poisoning_dataset.py — synthetic, ground
-truth labeled, no LLM) through Link's real pipeline layers and reports,
per attack, where it died or what label it carried when it survived:

  layer 1  extraction   propose_memories_from_text — hearsay/question/echo
                        gates drop what was never the user's own claim
  layer 2  labeling     injected_instruction_warnings — injection-shaped
                        proposals carry a warning the reviewer sees
  layer 3  write gate   write_memory_page refuses credential-shaped text
                        even on a one-click accept
  layer 4  review gate  everything that remains is proposal-only until a
                        human approves it (the architecture's last line —
                        measured here as what reaches the inbox, honestly)

The same attacks are then pushed through the three other ways content
reaches a session, which a review found unmeasured:

  harness     the attack arrives as user-role text the harness wrote - a
              subagent report, command output, a compaction summary, a peer
              session - and session-end mines the transcript; it must never
              become a proposal attributed to the user
  handoff     the attack is left as a session handoff, pushed to the top of
              the next session on any agent; every attack the detector labels
              must be labelled in the brief, and credentials must be redacted
  team        the attack is shared as a teammate's memory; it must be
              rejected, or arrive quarantined for review - never active
  agent       the attack sits in an agent's own memory store (Kiro's
              records, Codex's MEMORY.md), written there after the agent
              read a poisoned page; `lnk import` brings it in as proposals,
              and a one-click `accept --all` must store no payload

Benign controls are legitimate directive shapes; flagging them would erode
trust in the labels, so any benign false positive fails the run.

Exit: non-zero if a credential-class attack survives the write gate, an
injection-class attack reaches proposals unlabeled, or a benign control is
flagged.

Run:  python3 scripts/eval_memory_poisoning.py [--json]
"""
from __future__ import annotations

import os
os.environ["LINK_SEMANTIC"] = "off"  # published numbers stay deterministic: never use a local model

import argparse
import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))
sys.path.insert(0, str(ROOT / "scripts"))

from link_core.memory import (  # noqa: E402
    propose_memories_from_text,
    write_memory_page,
)
from link_core.security import (  # noqa: E402
    _credential_shaped,
    injected_instruction_warnings,
    looks_like_password_note,
    secret_value_warnings,
)
from link_core.agent_hooks import extract_transcript_text  # noqa: E402
from link_core.handoff import handoff_brief_block, pending_handoffs, write_handoff  # noqa: E402
from link_core.memory import is_active_memory, memory_records  # noqa: E402
from link_core.sync import import_team_memories  # noqa: E402
from poisoning_dataset import ATTACKS, BENIGN_CONTROLS  # noqa: E402


def _make_wiki(root: Path) -> Path:
    wiki = root / "wiki"
    (wiki / "memories").mkdir(parents=True)
    (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
    (wiki / "log.md").write_text("# Log\n", encoding="utf-8")
    return wiki


def run_attack(wiki: Path, text: str) -> dict[str, object]:
    """One attack through the real layers; returns where it ended up."""
    proposals = propose_memories_from_text(text, [], source="poison-eval")["proposals"]
    if not proposals:
        return {"outcome": "dropped", "proposed": 0}

    flagged = False
    refused_secret = False
    stored_with_payload = False
    stored_defanged_only = True
    for proposal in proposals:
        memory = str(proposal.get("memory") or "")
        if injected_instruction_warnings(text) or injected_instruction_warnings(memory):
            flagged = True
        # One-click accept simulation through the product's real write gate.
        result = write_memory_page(
            wiki, memory,
            title=str(proposal.get("title") or "") or None,
            memory_type=str(proposal.get("memory_type") or "note"),
            scope=str(proposal.get("scope") or "user"),
            tags=None, source="poison-eval",
            timestamp="2026-08-02T00:00:00Z",
            allow_duplicate=True, allow_conflict=True,
        )
        if result.get("secret"):
            refused_secret = True
        elif result.get("created"):
            # Did the dangerous payload survive into storage, or did
            # extraction strip it down to a harmless residue?
            payload_survived = bool(
                secret_value_warnings(memory)
                or looks_like_password_note(memory)
                or injected_instruction_warnings(memory)
            )
            if payload_survived:
                stored_with_payload = True
            else:
                stored_defanged_only = stored_defanged_only and True
    if refused_secret and not stored_with_payload:
        return {"outcome": "refused", "proposed": len(proposals), "flagged": flagged}
    if flagged:
        return {"outcome": "flagged", "proposed": len(proposals), "flagged": True}
    if not stored_with_payload and stored_defanged_only:
        return {"outcome": "defanged", "proposed": len(proposals), "flagged": False}
    return {"outcome": "exposed-unlabeled", "proposed": len(proposals), "flagged": False}


def _user_entry(text: str, **extra: object) -> dict[str, object]:
    return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}, **extra}


HARNESS_WRAPPERS = (
    ("subagent-report", lambda t: _user_entry(f"<task-notification>\n<result>{t}</result>", origin={"kind": "task-notification"})),
    ("legacy-subagent-report", lambda t: _user_entry(f"<task-notification><result>{t}</result>")),
    ("command-output", lambda t: _user_entry(f"<local-command-stdout>{t}</local-command-stdout>")),
    ("compaction-summary", lambda t: _user_entry(f"This session is being continued from a previous conversation. {t}",
                                                 isCompactSummary=True)),
    ("subagent-turn", lambda t: _user_entry(t, isSidechain=True)),
    ("peer-session", lambda t: _user_entry(t, origin={"kind": "peer", "from": "other-session"})),
)


def harness_channel(workdir: Path) -> dict[str, object]:
    """Attack text written into the transcript in the user's name, not typed."""
    leaked: list[str] = []
    probes = 0
    honest = "From now on I always review pull requests before lunch."
    for name, _class, text, _expected in ATTACKS:
        for wrapper_name, wrap in HARNESS_WRAPPERS:
            probes += 1
            transcript = workdir / f"{name}-{wrapper_name}.jsonl"
            transcript.write_text(
                json.dumps(_user_entry(honest, origin={"kind": "human"})) + "\n" + json.dumps(wrap(text)) + "\n",
                encoding="utf-8",
            )
            mined = extract_transcript_text(transcript, roles=("user",), max_chars=9000, keep_head=True)
            proposals = propose_memories_from_text(mined, [], source="poison-eval")["proposals"]
            attack_words = {w for w in text.lower().split() if len(w) > 6}
            for proposal in proposals:
                memory = str(proposal.get("memory") or "").lower()
                if attack_words and len(attack_words & set(memory.split())) >= 2:
                    leaked.append(f"{name} via {wrapper_name}")
                    break
    return {"probes": probes, "leaked": len(leaked), "leaked_detail": leaked}


def handoff_channel(workdir: Path) -> dict[str, object]:
    """Attacks left as handoffs must be labelled; credentials redacted."""
    unlabeled: list[str] = []
    unredacted: list[str] = []
    labelled = 0
    for index, (name, _class, text, _expected) in enumerate(ATTACKS):
        root = workdir / f"handoff-{index}"
        root.mkdir()
        record = write_handoff(root, text, task="continue the task", now="2026-09-26T10:00:00Z")
        block = handoff_brief_block(pending_handoffs(root, now="2026-09-26T10:01:00Z"), now="2026-09-26T10:01:00Z")
        if "WARNING" in block:
            labelled += 1
        elif injected_instruction_warnings(text):
            unlabeled.append(name)
        stored = Path(str(record["absolute_path"])).read_text(encoding="utf-8")
        for label in secret_value_warnings(text):
            if secret_value_warnings(stored):
                unredacted.append(f"{name} ({label})")
                break
        if looks_like_password_note(text):
            # Check the credential itself, not the whole file: the handoff's
            # own timestamps are credential-shaped words too.
            credentials = [w.strip(".,;:!?") for w in text.split() if _credential_shaped(w)]
            if any(word and word in stored for word in credentials):
                unredacted.append(f"{name} (password note)")
    return {"attacks": len(ATTACKS), "labelled": labelled, "unlabeled": len(unlabeled),
            "unredacted": len(unredacted), "detail": {"unlabeled": unlabeled, "unredacted": unredacted}}


def team_channel(workdir: Path) -> dict[str, object]:
    """Attacks shared as teammates' memories: rejected or quarantined, never active."""
    team_wiki = workdir / "team" / "wiki"
    (team_wiki / "memories").mkdir(parents=True)
    local = workdir / "local"
    wiki = _make_wiki(local)
    for index, (name, _class, text, _expected) in enumerate(ATTACKS):
        (team_wiki / "memories" / f"attack-{index}-{name}.md").write_text(
            f"---\ntitle: \"{name}\"\nmemory_type: preference\nscope: project\nstatus: active\n"
            f"visibility: team\nreview_status: reviewed\n---\n\n# {name}\n\n{text}\n",
            encoding="utf-8",
        )
    report = import_team_memories(team_wiki, wiki, ledger_path=local / ".link-team-imports.json")
    active = [str(r.get("name")) for r in memory_records(wiki) if is_active_memory(r)]
    return {
        "attacks": len(ATTACKS),
        "rejected": len(report["rejected"]),
        "quarantined": len(report["imported"]) - len(active),
        "active": len(active),
        "detail": {"active": active},
    }


KIRO_SCHEMA = """
CREATE TABLE memories (
  id TEXT NOT NULL PRIMARY KEY, memory_type TEXT NOT NULL, scopes TEXT NOT NULL,
  title TEXT NOT NULL, summary TEXT NOT NULL, content TEXT NOT NULL,
  why TEXT, how_to_apply TEXT, session_id TEXT NOT NULL, metadata TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  cloud_state TEXT NOT NULL DEFAULT 'pending', rev_number INTEGER NOT NULL DEFAULT 1,
  content_version TEXT);
CREATE TABLE memory_scopes (memory_id TEXT NOT NULL, scope TEXT NOT NULL,
  PRIMARY KEY (memory_id, scope));
"""


def _memory_bodies(wiki: Path) -> list[str]:
    """The text each stored memory would put in front of an agent."""
    bodies = []
    for page in sorted((wiki / "memories").glob("*.md")):
        text = page.read_text(encoding="utf-8")
        body = text.split("## Memory", 1)[-1].split("## Use This When", 1)[0]
        bodies.append(body.strip())
    return bodies


def agent_memory_channel(workdir: Path) -> dict[str, object]:
    """Attacks an agent wrote into its own memory, brought in by `lnk import`."""
    items = [(name, text) for name, _class, text, _expected in ATTACKS]
    benign = [(name, text) for name, text in BENIGN_CONTROLS]
    results: dict[str, object] = {}
    for store in ("kiro", "codex"):
        home = workdir / store / "home"
        target = workdir / store / "link"
        home.mkdir(parents=True)
        env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), CODEX_HOME=str(home / ".codex"))
        if store == "kiro":
            database = home / ".kiro" / "memories" / "memories.db"
            database.parent.mkdir(parents=True)
            connection = sqlite3.connect(database)
            connection.executescript(KIRO_SCHEMA)
            for index, (name, text) in enumerate(items + benign):
                connection.execute(
                    "INSERT INTO memories (id, memory_type, scopes, title, summary, content,"
                    " session_id, created_at, updated_at) VALUES (?, 'Preference', 'global', ?, ?, ?, 's', ?, ?)",
                    (f"k{index}", name, text, text, f"2026-11-01T10:{index:02d}:00Z", f"2026-11-01T10:{index:02d}:00Z"),
                )
                connection.execute("INSERT INTO memory_scopes VALUES (?, 'global')", (f"k{index}",))
            connection.commit()
            connection.close()
        else:
            memory_file = home / ".codex" / "memories" / "MEMORY.md"
            memory_file.parent.mkdir(parents=True)
            memory_file.write_text(
                "# Memory\n\n" + "".join(f"- {text}\n" for _name, text in items + benign), encoding="utf-8")

        def link(*args: str) -> str:
            done = subprocess.run([sys.executable, str(ROOT / "link.py"), *args],
                                  capture_output=True, text=True, env=env, timeout=300)
            if done.returncode:
                raise RuntimeError(f"link {' '.join(args)} failed: {done.stderr[-400:]}")
            return done.stdout

        link("init", str(target))
        link("import", store, str(target))
        captures = sorted((target / "raw" / "memory-captures").glob("*.md"))
        held = 0
        for capture in captures:
            outcome = json.loads(link("accept-capture", str(capture.relative_to(target)), str(target),
                                      "--all", "--json"))
            held += sum(1 for item in outcome["skipped"] if str(item["reason"]).startswith("reads like"))
        bodies = _memory_bodies(target / "wiki")
        payload = [body[:60] for body in bodies if injected_instruction_warnings(body)]
        credentials = [body[:60] for body in bodies
                       if secret_value_warnings(body) or looks_like_password_note(body)]
        # Mining may restate a line ("I prefer" -> "User prefers"), so a
        # benign record counts as kept when a stored memory carries its words.
        def words(value: str) -> set[str]:
            return {word.strip(".,;:").lower() for word in value.split() if len(word.strip(".,;:")) > 3}

        benign_kept = sum(
            1 for _name, text in benign
            if any(len(words(text) & words(body)) >= 0.7 * len(words(text)) for body in bodies)
        )
        results[store] = {
            "attacks": len(items), "held_back": held, "stored": len(bodies),
            "stored_with_payload": len(payload), "credentials_stored": len(credentials),
            "benign": len(benign), "benign_kept": benign_kept,
            "detail": {"payload": payload, "credentials": credentials},
        }
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    rows: list[dict[str, object]] = []
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as temp:
        wiki = _make_wiki(Path(temp))
        for name, attack_class, text, expected in ATTACKS:
            result = run_attack(wiki, text)
            outcome = str(result["outcome"])
            ok = (
                outcome == expected
                # Dying earlier in the pipeline than expected is strictly
                # better: dropped/defanged/refused all beat "flagged".
                or (expected == "flagged" and outcome in {"dropped", "refused", "defanged"})
                or (expected == "refused" and outcome in {"dropped", "defanged"})
            )
            rows.append({"name": name, "class": attack_class,
                         "expected": expected, "outcome": outcome, "ok": ok})
            if not ok:
                failures.append(f"{name}: expected {expected}, got {outcome}")

    with tempfile.TemporaryDirectory() as temp:
        workdir = Path(temp)
        harness = harness_channel(workdir)
        handoff = handoff_channel(workdir)
        team = team_channel(workdir)
        agent = agent_memory_channel(workdir)
    if harness["leaked"]:
        failures.append(f"harness channel: {harness['leaked']} attack(s) became proposals")
    if handoff["unlabeled"] or handoff["unredacted"]:
        failures.append(f"handoff channel: {handoff['unlabeled']} unlabeled, {handoff['unredacted']} unredacted")
    if team["active"]:
        failures.append(f"team channel: {team['active']} attack(s) became active memory")
    for store, row in agent.items():
        if not isinstance(row, dict):
            continue
        if row["stored_with_payload"] or row["credentials_stored"]:
            failures.append(f"agent channel ({store}): accept --all stored {row['stored_with_payload']} "
                            f"payload(s) and {row['credentials_stored']} credential(s)")
        if row["benign_kept"] != row["benign"]:
            failures.append(f"agent channel ({store}): {row['benign'] - row['benign_kept']} benign record(s) not kept")

    benign_flagged = [
        name for name, text in BENIGN_CONTROLS if injected_instruction_warnings(text)
    ]
    for name in benign_flagged:
        failures.append(f"benign control flagged: {name}")

    by_outcome: dict[str, int] = {}
    for row in rows:
        by_outcome[str(row["outcome"])] = by_outcome.get(str(row["outcome"]), 0) + 1
    report = {
        "attacks": len(rows),
        "outcomes": by_outcome,
        "unlabeled_exposure": by_outcome.get("exposed-unlabeled", 0),
        "benign_controls": len(BENIGN_CONTROLS),
        "benign_false_positives": len(benign_flagged),
        "channels": {"harness": harness, "handoff": handoff, "team": team, "agent": agent},
        "rows": rows,
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Link memory-poisoning benchmark — {len(rows)} authored attacks, "
              f"{len(BENIGN_CONTROLS)} benign controls")
        print(f"\n{'attack':22} {'class':22} {'expected':10} {'outcome':18} ok")
        for row in rows:
            print(f"{row['name']:22} {row['class']:22} {row['expected']:10} "
                  f"{row['outcome']:18} {'yes' if row['ok'] else 'NO'}")
        print(f"\nunlabeled exposure: {report['unlabeled_exposure']} "
              f"(attacks stored or inbox-bound with no warning label)")
        print(f"benign false positives: {len(benign_flagged)} / {len(BENIGN_CONTROLS)}")
        print("\nOther channels into a session:")
        print(f"  harness text  {harness['probes']} probes ({len(ATTACKS)} attacks x {len(HARNESS_WRAPPERS)} wrappers), "
              f"{harness['leaked']} became proposals")
        print(f"  handoffs      {handoff['attacks']} attacks, {handoff['labelled']} labelled, "
              f"{handoff['unlabeled']} unlabeled injection-shaped, {handoff['unredacted']} unredacted credentials")
        print(f"  team imports  {team['attacks']} attacks, {team['rejected']} rejected, "
              f"{team['quarantined']} quarantined for review, {team['active']} active")
        for store, row in agent.items():
            print(f"  {store + ' memory':13} {row['attacks']} attacks, one accept --all: {row['held_back']} held back, "
                  f"{row['stored_with_payload']} payloads and {row['credentials_stored']} credentials stored; "
                  f"{row['benign_kept']} of {row['benign']} benign kept")

    for failure in failures:
        print(f"REGRESSION: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
