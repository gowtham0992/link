"""Ranking behaviours added in 4.0: whole words, temporal fairness, contradictions."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.memory import (  # noqa: E402
    memory_conflict_candidates,
    memory_recall_confidence,
    negated_claim_tokens,
    recall_memories,
    score_memory,
    stem_memory_token,
)


def _rec(name, title, tldr=None, memory_type="decision", **extra):
    tldr = tldr or title
    record = {
        "name": name, "title": title, "memory_type": memory_type, "scope": "user",
        "status": "active", "review_status": "reviewed", "tags": [],
        "date_captured": "2026-01-01T00:00:00Z",
        "body": f"# {title}\n\n> **TLDR:** {tldr}\n\n## Memory\n\n{tldr}\n",
        "tldr": tldr, "snippet": tldr,
    }
    record.update(extra)
    return record


class WholeWordTests(unittest.TestCase):
    def test_a_word_inside_another_word_does_not_match(self):
        noise = _rec("allowlist", "Maintain the domain allowlist")
        self.assertEqual(score_memory(noise, "main"), 0)

    def test_plural_and_inflected_forms_still_match(self):
        self.assertGreater(score_memory(_rec("uv", "uv manages Python packages"), "package manager"), 0)
        self.assertGreater(score_memory(_rec("mit", "MIT licensed"), "project license"), 0)

    def test_question_words_do_not_carry_the_match(self):
        policy = _rec("branch", "Branch policy", "Commit features to develop, never straight to main")
        self.assertEqual(memory_recall_confidence(policy, "what is the branch policy"), "strong")

    def test_one_shared_word_is_never_strong(self):
        deploy = _rec("deploy", "I only deploy the payments service on Tuesdays")
        self.assertNotEqual(memory_recall_confidence(deploy, "can you deploy it"), "strong")


class StemmerTests(unittest.TestCase):
    def test_forms_of_a_word_meet(self):
        for a, b in (("commit", "committing"), ("run", "running"), ("stop", "stopped"),
                     ("package", "packages"), ("license", "licensed"), ("policy", "policies")):
            with self.subTest(pair=(a, b)):
                self.assertEqual(stem_memory_token(a), stem_memory_token(b))

    def test_non_latin_tokens_are_left_alone(self):
        self.assertEqual(stem_memory_token("デプロイ"), "デプロイ")


class TemporalRankingTests(unittest.TestCase):
    def test_archived_memory_is_not_penalised_on_a_date_it_was_active(self):
        old = _rec("old-notes", "Release notes kept to a few bullets",
                   status="archived", archived_at="2026-05-25T12:00:00Z",
                   date_captured="2026-03-01T00:00:00Z", memory_type="preference")
        other = _rec("answers", "Short direct answers that cite the wiki",
                     date_captured="2026-02-01T00:00:00Z", memory_type="preference")
        hits = recall_memories([old, other], "short release notes", limit=2, as_of="2026-03-28")
        self.assertEqual(hits[0]["name"], "old-notes")


class ContradictionRankingTests(unittest.TestCase):
    def test_newer_contradicting_memory_is_read_first(self):
        old = _rec("small-commits", "The user prefers small focused commits",
                   memory_type="preference", date_captured="2026-01-01T00:00:00Z")
        new = _rec("stacked-diffs", "The user does not prefer small standalone commits anymore; stacked diffs now",
                   memory_type="preference", date_captured="2026-06-01T00:00:00Z")
        hits = recall_memories([old, new], "small commits", limit=2)
        self.assertEqual([hit["name"] for hit in hits], ["stacked-diffs", "small-commits"])
        self.assertEqual(hits[1].get("contradicted_by"), "stacked-diffs")


class NegatedObjectTests(unittest.TestCase):
    def test_negated_phrase_is_extracted(self):
        tokens = negated_claim_tokens("The user does not prefer small standalone commits anymore; stacked diffs now.")
        self.assertTrue({stem_memory_token("small"), stem_memory_token("commits")} <= tokens)

    def test_revision_of_a_long_claim_is_a_conflict(self):
        original = _rec(
            "commits", "The user prefers small, focused commits and pull requests whose description opens with a summary",
            memory_type="preference",
        )
        hits = memory_conflict_candidates(
            [original], "The user does not prefer small standalone commits anymore; we settled on stacked diffs.",
            None, "preference", "user", embedder=lambda _texts: [],
        )
        self.assertIn("negates_existing_claim", hits[0]["conflict_reasons"])

    def test_restating_a_revision_is_not_a_conflict(self):
        revision = _rec("no-morning", "The user does not prefer morning meetings anymore", memory_type="preference")
        hits = memory_conflict_candidates(
            [revision], "Just confirming: the user does not prefer morning meetings anymore.",
            None, "preference", "user", embedder=lambda _texts: [],
        )
        self.assertFalse(any("negates_existing_claim" in hit["conflict_reasons"] for hit in hits))


class OptionGroupContextTests(unittest.TestCase):
    def test_release_notes_are_not_a_branch_policy(self):
        squash = _rec("squash", "Pull requests are squash-merged; main history stays linear")
        hits = memory_conflict_candidates(
            [squash], "The user prefers release notes kept to a few bullets", None, "decision", "user",
            embedder=lambda _texts: [],
        )
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
