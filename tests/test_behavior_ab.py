"""The behavioral A/B harness is a CI gate in dry mode."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BehaviorAbTests(unittest.TestCase):
    def test_dry_run_passes_and_link_beats_no_memory(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "eval_behavior_ab.py"), "--json"],
            capture_output=True, text=True, timeout=300, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        report = json.loads(result.stdout)
        self.assertGreater(report["with_link_correct"], report["without_link_correct"])
        self.assertGreaterEqual(report["memory_in_packet"], report["scenarios"] - len(report["known_gaps"]))

    def test_live_mode_refuses_to_spend_without_yes(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "eval_behavior_ab.py"), "--mode", "live",
             "--agent-command", "some-model-cli"],
            capture_output=True, text=True, timeout=60, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--yes", result.stderr)


if __name__ == "__main__":
    unittest.main()
