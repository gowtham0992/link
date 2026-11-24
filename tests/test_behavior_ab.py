"""The behavioral A/B harness is a CI gate in dry mode."""
import json
import shlex
import subprocess
import sys
import tempfile
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

    def test_an_outage_partway_through_stops_the_run_instead_of_scoring_wrong_answers(self):
        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp) / "outage_agent.py"
            # Answers the canary, then reports an outage with exit code 0 as agent CLIs do.
            fake.write_text("import sys\nprompt = sys.stdin.read()\n"
                            "print('READY' if 'exactly the word READY' in prompt else "
                            "'Credit balance is too low to access the Anthropic API.')\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "eval_behavior_ab.py"), "--mode", "live", "--yes", "--json",
                 "--agent-command", shlex.join([sys.executable, str(fake)])],
                capture_output=True, text=True, timeout=300, check=False,
            )
        self.assertEqual(result.returncode, 2, result.stdout[-500:])
        self.assertEqual(result.stdout, "", "no report, so no numbers to publish")
        self.assertIn("Credit balance is too low", result.stderr)
        self.assertIn("nothing was scored", result.stderr)


if __name__ == "__main__":
    unittest.main()
