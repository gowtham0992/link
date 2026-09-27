"""The word rules' published contradiction figures stay true (no model needed)."""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# The claim-update script turns semantic recall off for its own process when
# imported; keep that from leaking into the rest of the suite.
_saved = os.environ.get("LINK_SEMANTIC")
from eval_contradiction_flags import measure, revision_pairs, unrelated_pairs  # noqa: E402

if _saved is None:
    os.environ.pop("LINK_SEMANTIC", None)
else:
    os.environ["LINK_SEMANTIC"] = _saved


class WordRuleFloorTests(unittest.TestCase):
    def test_revisions_are_caught(self):
        report = measure(revision_pairs(), None)
        self.assertEqual(report["pairs"], 20)
        self.assertGreaterEqual(report["word_rules"], 17)

    def test_distinct_memories_are_not_flagged(self):
        report = measure(unrelated_pairs(), None)
        self.assertEqual(report["word_rules"], 0, report["word_rule_hits"])


if __name__ == "__main__":
    unittest.main()
