import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HygieneBenchmarkTests(unittest.TestCase):
    def test_gated_pipeline_beats_ungated_on_every_hygiene_metric(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts/eval_memory_hygiene.py"), "--json"],
            capture_output=True, text=True, timeout=600,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        gated, ungated = report["gated"], report["ungated"]

        # The architectural guarantees, as numbers:
        self.assertEqual(gated["junk_stored"], 0)              # echo guard: zero by construction
        self.assertGreater(ungated["junk_rate"], 0.15)         # ungated re-ingests its own voice
        self.assertLess(
            gated["contradiction_exposure@3"], ungated["contradiction_exposure@3"]
        )                                                      # supersession beats coexistence
        self.assertLess(gated["active_memories"], ungated["active_memories"])
        self.assertGreaterEqual(gated["as_of_accuracy"], 0.9)  # temporal recall reconstructs history


if __name__ == "__main__":
    unittest.main()
