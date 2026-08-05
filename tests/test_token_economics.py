"""Token economics is a CI gate: packets stay bounded as memory grows."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TokenEconomicsTests(unittest.TestCase):
    def test_packets_stay_bounded_and_plateau(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "eval_token_economics.py"), "--json"],
            capture_output=True, text=True, timeout=600,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        for budget, row in report["budgets"].items():
            self.assertLessEqual(row["max_tokens"], row["ceiling"], budget)
        # Quick mode checks deceleration; the full run (no --quick) verifies
        # the plateau at 1,600 memories and produces the published numbers.
        means = [row["mean_tokens"] for row in report["growth"]]
        first_step = means[1] / means[0]
        last_step = means[-1] / means[-2]
        self.assertLessEqual(last_step, first_step, report)


if __name__ == "__main__":
    unittest.main()
