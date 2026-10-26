"""Contradictions the lexical rules could not see before 4.0."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.memory import claim_values, memory_conflict_candidates  # noqa: E402


def _rec(name, text, memory_type="decision"):
    return {
        "name": name, "title": text, "memory_type": memory_type, "scope": "user",
        "status": "active", "review_status": "reviewed", "tags": [],
        "body": f"# {text}\n\n> **TLDR:** {text}\n\n## Memory\n\n{text}\n",
        "tldr": text, "snippet": text,
    }


def _conflicts(existing, text, memory_type="decision"):
    return memory_conflict_candidates(
        [existing], text, None, memory_type, "user", embedder=lambda _texts: []
    )


class ChangedValueTests(unittest.TestCase):
    def test_values_are_extracted_without_the_tokenizer_floor(self):
        self.assertEqual(claim_values("Python 3.11 on port 8080, v2 api"), {"3.11", "8080", "2"})

    def test_version_change_is_a_conflict_not_a_duplicate(self):
        hits = _conflicts(_rec("py", "We deploy with Python 3.11"), "We deploy with Python 3.12")
        self.assertEqual([h["name"] for h in hits], ["py"])
        self.assertIn("changed_value", hits[0]["conflict_reasons"])

    def test_facts_can_conflict(self):
        hits = _conflicts(_rec("port", "The API listens on port 8080 locally", "fact"),
                          "The API listens on port 9090 locally", "fact")
        self.assertTrue(hits)

    def test_different_subjects_with_different_numbers_do_not_conflict(self):
        self.assertEqual(_conflicts(_rec("node", "Use Node 20 for the api service"),
                                    "Use Node 18 for the worker queue"), [])


class NegationOverlapTests(unittest.TestCase):
    def test_short_negated_claim_meets_its_opposite(self):
        hits = _conflicts(_rec("ruff", "Use Ruff for linting"), "Never use Ruff")
        self.assertIn("opposite_negation", hits[0]["conflict_reasons"])


class BranchPolicyTests(unittest.TestCase):
    def test_agent_names_are_not_branch_options(self):
        self.assertEqual(_conflicts(_rec("codex", "Codex handles the review step"),
                                    "Feature branches need a review step before merge"), [])


if __name__ == "__main__":
    unittest.main()
