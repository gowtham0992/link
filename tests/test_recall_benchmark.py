import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RecallBenchmarkTests(unittest.TestCase):
    def test_small_fake_suite_passes_regression_gate(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts/eval_recall_quality.py"),
             "--suite", "small", "--mode", "fake", "--json"],
            capture_output=True, text=True, timeout=300,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertGreaterEqual(report["corpus_memories"], 50)
        self.assertGreaterEqual(report["authored_cases"], 250)
        groups = report["lexical_baseline"]["groups"]
        self.assertIn("token-overlap", groups)
        self.assertIn("zero-overlap", groups)
        # The paraphrase group must stay genuinely hard for lexical recall;
        # if this rises, queries have drifted into token overlap.
        self.assertLess(groups["zero-overlap"]["hit@1"], 0.2)
        self.assertGreaterEqual(groups["zero-overlap"]["cases"], 50)

    def test_full_suite_reaches_one_thousand_cases(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        from recall_dataset import build_cases, build_corpus

        self.assertGreaterEqual(len(build_cases(expand=True)), 1000)
        self.assertGreaterEqual(len(build_corpus()), 50)


if __name__ == "__main__":
    unittest.main()
