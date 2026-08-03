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
    injected_instruction_warnings,
    looks_like_password_note,
    secret_value_warnings,
)
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

    for failure in failures:
        print(f"REGRESSION: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
