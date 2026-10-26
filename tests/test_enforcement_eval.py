"""The enforcement benchmark's floor: every forbidden call stopped, no ordinary call stopped."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from eval_enforcement import run  # noqa: E402


class EnforcementFloorTests(unittest.TestCase):
    def test_forbidden_calls_are_caught_and_ordinary_ones_pass(self):
        report = run()
        self.assertEqual(report["missed"], [])
        self.assertEqual(report["false_blocks"], 0, report["false_block_calls"])


if __name__ == "__main__":
    unittest.main()
