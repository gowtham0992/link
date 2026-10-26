#!/usr/bin/env python3
"""Contradiction flags at write time: word rules versus the optional NLI tier.

When a memory is written, Link checks it against stored memories for a
contradiction. The word rules always run; the NLI tier (`lnk semantic
--setup --nli`) adds a local natural-language-inference model. This script
measures both on two fixed sets, with no network and no LLM:

- revisions: every consecutive pair of versions in the claim-update
  subjects (scripts/eval_claim_updates.py), stored claim first, revision
  second. A flag here is a catch.
- unrelated pairs: every pair of memories in the recall benchmark corpus
  (scripts/recall_dataset.py) that shares at least one subject word. They
  are distinct rules, so a flag here is a false alarm.

Three detectors are compared: the word rules (memory_conflict_candidates),
the model alone at its threshold, and the model as shipped (only on
neighbours whose subject words overlap by NLI_MIN_SUBJECT_OVERLAP). The
shipped flag is a review note, never a refusal; this measures how often it
would be raised, and whether it would be raised for the right reasons.

    python3 scripts/eval_contradiction_flags.py          # needs the NLI model
    python3 scripts/eval_contradiction_flags.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))
sys.path.insert(0, str(ROOT / "scripts"))

from eval_claim_updates import SUBJECTS  # noqa: E402
from link_core.memory import (  # noqa: E402
    _CONFLICT_CUE_TOKENS,
    cached_stems,
    memory_conflict_candidates,
    nli_contradiction_flags,
    significant_memory_tokens,
)
from link_core.nli import CONTRADICTION_THRESHOLD, load_contradiction_scorer  # noqa: E402
from recall_dataset import build_corpus  # noqa: E402


def _record(name: str, text: str, memory_type: str, title: str | None = None) -> dict[str, object]:
    title = title or text
    return {
        "name": name, "title": title, "tldr": text, "snippet": text, "memory_type": memory_type,
        "scope": "user", "status": "active", "review_status": "reviewed", "tags": [],
        "date_captured": "2026-01-01T00:00:00Z",
        "body": f"# {title}\n\n> **TLDR:** {text}\n\n## Memory\n\n{text}\n",
    }


def revision_pairs() -> list[tuple[dict[str, object], str, str, str]]:
    pairs = []
    for subject in SUBJECTS:
        for index in range(1, len(subject.versions)):
            stored = _record(f"{subject.name}-{index - 1}", subject.versions[index - 1][1], subject.memory_type)
            pairs.append((stored, subject.versions[index][1], subject.memory_type, subject.name))
    return pairs


def _subject_words(text: str) -> frozenset[str]:
    return cached_stems(frozenset(significant_memory_tokens(text))) - _CONFLICT_CUE_TOKENS


def unrelated_pairs() -> list[tuple[dict[str, object], str, str, str]]:
    corpus = build_corpus()
    pairs = []
    for i, first in enumerate(corpus):
        for second in corpus[i + 1:]:
            head_a = f"{first['title']} {first['tldr']}"
            head_b = f"{second['title']} {second['tldr']}"
            if not (_subject_words(head_a) & _subject_words(head_b)):
                continue
            stored = _record(str(first["name"]), str(first["tldr"]), str(first["memory_type"]), str(first["title"]))
            pairs.append((stored, str(second["tldr"]), str(second["memory_type"]),
                          f"{first['name']} / {second['name']}"))
    return pairs


def measure(pairs, scorer) -> dict[str, object]:
    words = model = shipped = 0
    shipped_labels: list[str] = []
    rule_labels: list[str] = []
    probabilities = scorer([(str(stored["tldr"]), text) for stored, text, _type, _label in pairs]) if scorer else []
    for index, (stored, text, memory_type, label) in enumerate(pairs):
        if memory_conflict_candidates([stored], text, None, memory_type, "user", embedder=lambda _texts: []):
            words += 1
            rule_labels.append(label)
        if scorer is None:
            continue
        if probabilities[index] >= CONTRADICTION_THRESHOLD:
            model += 1
        if nli_contradiction_flags([stored], text, None, memory_type, "user", None, scorer):
            shipped += 1
            shipped_labels.append(label)
    return {
        "pairs": len(pairs),
        "word_rules": words,
        "model_alone": model if scorer else None,
        "model_as_shipped": shipped if scorer else None,
        "word_rule_hits": rule_labels,
        "shipped_hits": shipped_labels,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    scorer = load_contradiction_scorer(allow_download=False)
    if scorer is None:
        print("NLI model unavailable offline; word rules only. Set it up with "
              "`lnk semantic <dir> --setup --nli`.", file=sys.stderr)
    revisions = measure(revision_pairs(), scorer)
    unrelated = measure(unrelated_pairs(), scorer)
    report = {"threshold": CONTRADICTION_THRESHOLD, "revisions": revisions, "unrelated": unrelated}
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    missed_by_rules = sorted(set(revisions["shipped_hits"]) - set(revisions["word_rule_hits"]))
    print(f"Contradiction flags - {revisions['pairs']} revisions (should flag), "
          f"{unrelated['pairs']} unrelated pairs sharing a subject word (should not)")
    print(f"{'detector':22s} {'revisions caught':>18s} {'false alarms':>14s}")
    print(f"{'word rules':22s} {revisions['word_rules']:>18d} {unrelated['word_rules']:>14d}")
    if scorer is not None:
        print(f"{'model alone':22s} {revisions['model_alone']:>18d} {unrelated['model_alone']:>14d}")
        print(f"{'model as shipped':22s} {revisions['model_as_shipped']:>18d} {unrelated['model_as_shipped']:>14d}")
        print(f"revisions the model adds over the word rules: {', '.join(missed_by_rules) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
