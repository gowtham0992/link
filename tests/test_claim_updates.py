"""The claim-updates slice is a CI floor: superseded values never come back first."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ClaimUpdatesTests(unittest.TestCase):
    def test_slice_holds_its_floors(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "eval_claim_updates.py"), "--json"],
                                capture_output=True, text=True, timeout=300, check=False)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        report = json.loads(result.stdout)
        self.assertEqual(report["lineage"]["direct"]["stale@1"], 0)


if __name__ == "__main__":
    unittest.main()
