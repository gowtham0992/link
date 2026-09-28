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

    def test_a_year_in_the_question_still_reaches_the_wiki(self):
        with mcp_server(self.root) as server:
            plain = json.loads(server.recall(query="how did transformers change retrieval"))
            dated = json.loads(server.recall(query="how did transformers change retrieval in 2017"))
        self.assertEqual(plain["mode"], "query")
        self.assertEqual(dated["mode"], "query", "no memory holds 2017, so the wiki must answer")
        self.assertTrue(dated["found"])
        self.assertTrue(dated["context_packet"], "the dated question gets the same wiki pages")

    def test_unknown_memory_type_is_an_error(self):
        with mcp_server(self.root) as server:
            payload = json.loads(server.recall(query="deploy day", memory_type="preferences"))
        self.assertIn("error", payload)
        self.assertIn("preference", payload["error"])

    def test_remember_can_carry_rules_that_wait_for_review(self):
        with mcp_server(self.root) as server:
            saved = json.loads(server.remember(text="Never run `git push --force` on main.",
                                               enforce="ask command: git push --force*"))
            self.assertEqual(saved["enforce"], ["ask command: git push --force*"])
            # The agent cannot approve its own rule, or clear, archive or rewrite one.
            approved = json.loads(server.review(action="reviewed", identifier=saved["name"]))
            cleared = json.loads(server.admin(action="set_enforce", arguments=json.dumps(
                {"identifier": saved["name"], "clear": True})))
            archived = json.loads(server.review(action="archive", identifier=saved["name"]))
        for refused in (approved, cleared, archived):
            self.assertRegex(str(refused.get("error")), r"Only the person|the person's call")

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
