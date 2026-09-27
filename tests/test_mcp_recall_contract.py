"""The slim MCP surface: what agents can ask, and what they are told to do."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))
sys.path.insert(0, str(ROOT / "tests"))

from mcp_harness import mcp_server  # noqa: E402


def _cli(*args: str) -> None:
    subprocess.run([sys.executable, str(ROOT / "link.py"), *args], check=True, capture_output=True)


class SlimRecallContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "ws"
        _cli("demo", str(self.root), "--force")
        _cli("remember", "Deploys happen on Tuesdays after standup", str(self.root),
             "--title", "Deploy day", "--type", "decision")
        _cli("remember", "The staging database listens on port 5433", str(self.root),
             "--title", "Staging database port", "--type", "fact")

    def tearDown(self):
        self.temp.cleanup()

    def test_memory_type_filter_routes_to_memory_recall(self):
        with mcp_server(self.root) as server:
            payload = json.loads(server.recall(query="staging database port deploy", memory_type="fact"))
        self.assertEqual(payload["mode"], "memory")
        self.assertTrue(payload["memories"])
        self.assertTrue(all(item.get("memory_type") == "fact" for item in payload["memories"]))

    def test_as_of_is_accepted_and_reported(self):
        with mcp_server(self.root) as server:
            payload = json.loads(server.recall(query="deploy day", as_of="2020-01-01"))
        self.assertEqual(payload["mode"], "memory")
        self.assertEqual(payload["as_of"], "2020-01-01")
        # Nothing in this store existed in 2020.
        self.assertEqual(payload["memories"], [])

    def test_bad_as_of_is_an_error_not_a_crash(self):
        with mcp_server(self.root) as server:
            payload = json.loads(server.recall(query="deploy day", as_of="2026-99-99"))
        self.assertIn("error", payload)

    def test_follow_up_calls_are_accepted_by_admin(self):
        with mcp_server(self.root) as server:
            packet = json.loads(server.recall(query="agent memory local markdown", budget="micro"))
            admin_calls = [item for item in packet.get("follow_up", []) if item.get("tool") == "admin"]
            self.assertTrue(admin_calls)
            for call in admin_calls:
                result = json.loads(server.admin(**call["arguments"]))
                self.assertNotIn("error", result, call)

    def test_first_response_reports_the_real_review_queue(self):
        with mcp_server(self.root) as server:
            brief = json.loads(server.recall(query="", mode="brief"))["brief"]
            compact = server._compact_session_brief(brief)
        pending = brief["review"]["count"]
        self.assertGreater(pending, 0, "CLI remember leaves memories pending review")
        # The first-response digest read a key that never existed and said 0.
        self.assertEqual(compact["needs_review"], pending)


if __name__ == "__main__":
    unittest.main()
