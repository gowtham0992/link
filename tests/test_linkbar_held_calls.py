"""LinkBar shows only the held calls `lnk approve` would accept, and approves none from a banner.

LinkBar reads `.link-cache/approvals.json` itself (Models.swift, HeldCall.load).
Each case here is written by hand, read by approvals.py and by a small build
of Models.swift, and the two must list the same requests.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core import approvals  # noqa: E402

SOURCES = ROOT / "apps" / "LinkBar" / "Sources" / "LinkBar"
HARNESS = """import Foundation
let calls = HeldCall.load(from: CommandLine.arguments[1])
print(calls.map(\\.id).joined(separator: ","))
"""


def _stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class LinkBarHeldCallSourceTests(unittest.TestCase):
    def test_a_notification_never_approves_a_call(self):
        """macOS cuts a banner's text short and the agent wrote it: approving happens in the popover."""
        callers = sorted(path.name for path in SOURCES.glob("*.swift")
                         if "approveHeldCall(" in path.read_text(encoding="utf-8"))
        self.assertEqual(callers, ["LinkStore.swift", "PopoverView.swift"])
        notifications = (SOURCES / "Notifications.swift").read_text(encoding="utf-8")
        self.assertNotIn("Approve once", notifications)
        self.assertIn("showHeldCall(id:", notifications)


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("swiftc"), "LinkBar builds on macOS")
class LinkBarHeldCallParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        main = Path(cls.build.name) / "main.swift"
        main.write_text(HARNESS, encoding="utf-8")
        cls.binary = Path(cls.build.name) / "held"
        subprocess.run(["swiftc", "-o", str(cls.binary), str(SOURCES / "Models.swift"), str(main)], check=True,
                       capture_output=True, timeout=300)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = approvals.approvals_path(self.root)
        self.path.parent.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, requests):
        self.path.write_text(json.dumps({"requests": requests, "grants": {}}), encoding="utf-8")

    def _linkbar(self):
        out = subprocess.run([str(self.binary), str(self.root)], capture_output=True, text=True, check=True).stdout
        return [item for item in out.strip().split(",") if item]

    def _cli(self):
        return [row["id"] for row in approvals.pending(self.root)]

    def test_linkbar_lists_exactly_what_the_cli_would_approve(self):
        now = datetime.now(timezone.utc)
        entry = {"key": "k", "display": "command: git push --force", "title": "t", "rule": "r", "agent": "codex"}
        self._write({
            "aaaaaa": {**entry, "at": _stamp(now)},
            "bbbbbb": {**entry, "at": _stamp(now - timedelta(hours=1))},
            "cccccc": {k: v for k, v in entry.items() if k != "key"} | {"at": _stamp(now)},  # no call key
            "dddddd": {**entry, "at": _stamp(now + timedelta(hours=2))},  # dated in the future
            "eeeeee": {**entry, "at": _stamp(now - timedelta(hours=25))},  # expired
            "ffffff": {**entry, "at": now.isoformat()},  # not Link's own stamp
            "abcdef": {**entry, "at": _stamp(now), "used": "yesterday"},
        })
        self.assertEqual(self._cli(), ["aaaaaa", "bbbbbb"])
        self.assertEqual(self._linkbar(), self._cli())

    @unittest.skipIf(os.name == "nt", "hard links")
    def test_a_file_with_a_second_name_reads_as_empty(self):
        self._write({"aaaaaa": {"key": "k", "display": "command: npm publish", "at": _stamp(datetime.now(timezone.utc))}})
        self.assertEqual(self._linkbar(), ["aaaaaa"])
        os.link(self.path, self.root / "other-name.json")
        self.assertEqual(self._cli(), [])
        self.assertEqual(self._linkbar(), [], "another name for the file could have written the request")


if __name__ == "__main__":
    unittest.main()
