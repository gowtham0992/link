"""The memory receipt: what reached agents, session by session."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))
sys.path.insert(0, str(ROOT / "tests"))

from link_core.usage import load_usage, memory_receipts, record_retrieval  # noqa: E402


def _event(at, kind, names, **extra):
    return {"at": at, "kind": kind, "memories": names, "count": len(names), "project": "", **extra}


class ReceiptBuilderTests(unittest.TestCase):
    def test_sessions_split_on_a_quiet_gap_and_newest_comes_first(self):
        events = [
            _event("2026-09-01T09:00:00Z", "brief", ["a", "b"], surface="hook", tokens=300),
            _event("2026-09-01T09:10:00Z", "query", ["a"], surface="mcp", tokens=1700, truncated=True),
            _event("2026-09-01T13:00:00Z", "brief", ["c"], surface="mcp", tokens=120),
        ]
        receipts = memory_receipts(events, sessions=3)
        self.assertEqual(len(receipts), 2)
        self.assertEqual(receipts[0]["started"], "2026-09-01T13:00:00Z")
        morning = receipts[1]
        self.assertEqual(morning["briefs"], [{"memories": 2, "tokens": 300, "truncated": False}])
        self.assertEqual(morning["recalls"], 1)
        self.assertEqual(morning["estimated_tokens"], 2000)
        self.assertTrue(morning["anything_truncated"])
        self.assertEqual(morning["memories_used"][0], {"name": "a", "times": 2})
        self.assertEqual(morning["surfaces"], ["hook", "mcp"])

    def test_older_events_without_sizes_still_work(self):
        receipts = memory_receipts([_event("2026-09-01T09:00:00Z", "recall", ["a"])])
        self.assertEqual(receipts[0]["estimated_tokens"], 0)


class ReceiptSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "ws"
        subprocess.run([sys.executable, str(ROOT / "link.py"), "demo", str(self.root), "--force"],
                       check=True, capture_output=True, stdin=subprocess.DEVNULL)
        os.environ.pop("LINK_USAGE", None)

    def tearDown(self):
        self.temp.cleanup()

    def test_slim_recall_is_recorded_and_the_receipt_shows_it(self):
        from mcp_harness import mcp_server

        with mcp_server(self.root) as server:
            json.loads(server.recall(query="agent memory local markdown", mode="memory"))
            json.loads(server.recall(query="agent memory local markdown", budget="micro"))
            receipt = json.loads(server.review(action="receipt"))
        kinds = [event["kind"] for event in load_usage(self.root)]
        self.assertIn("recall", kinds)
        self.assertIn("query", kinds)
        session = receipt["sessions"][0]
        self.assertGreater(session["estimated_tokens"], 0)
        self.assertTrue(any(used["title"] for used in session["memories_used"]))

    def test_cli_receipt_prints_memories_with_titles(self):
        record_retrieval(self.root, "brief", ["keep-agent-memory-in-local-markdown"], surface="hook", tokens=250)
        result = subprocess.run(
            [sys.executable, str(ROOT / "link.py"), "receipt", str(self.root)],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Keep agent memory in local Markdown", result.stdout)
        self.assertIn("~250 tokens", result.stdout)


    def test_session_start_hook_records_its_brief(self):
        subprocess.run([sys.executable, str(ROOT / "link.py"), "remember", "We deploy on Tuesdays",
                        str(self.root), "--type", "decision"], check=True, capture_output=True, stdin=subprocess.DEVNULL)
        subprocess.run(
            [sys.executable, str(ROOT / "link.py"), "hook", "session-start", str(self.root)],
            input='{"session_id":"t","source":"startup"}', capture_output=True, text=True, check=True,
        )
        hook_events = [event for event in load_usage(self.root) if event.get("surface") == "hook"]
        self.assertTrue(hook_events, "the hook-delivered brief was not recorded")
        self.assertEqual(hook_events[-1]["kind"], "brief")
        self.assertGreater(hook_events[-1]["tokens"], 0)

    def test_cli_agent_commands_are_recorded_under_cli(self):
        # The shape a CLI-only agent follows from AGENTS.md: brief, recall, query.
        link = [sys.executable, str(ROOT / "link.py")]
        for args in (["brief", "session start"], ["recall", "agent memory"], ["recall", "local markdown"],
                     ["query", "agent memory local markdown", "--budget", "micro"]):
            subprocess.run([*link, args[0], args[1], str(self.root), *args[2:]],
                           check=True, capture_output=True, stdin=subprocess.DEVNULL)
        events = load_usage(self.root)
        self.assertEqual([event["kind"] for event in events], ["brief", "recall", "recall", "query"])
        self.assertEqual({event.get("surface") for event in events}, {"cli"})
        (session,) = memory_receipts(events, sessions=1)
        self.assertEqual(session["surfaces"], ["cli"])
        self.assertEqual(session["recalls"], 3)
        self.assertGreater(session["estimated_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
