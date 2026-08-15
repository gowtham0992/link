"""Session handoff: the packet that follows you across agents."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.handoff import (  # noqa: E402
    clear_handoff,
    handoff_brief_block,
    pending_handoffs,
    write_handoff,
)


class HandoffCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="link-handoff-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_write_and_surface_round_trip(self):
        write_handoff(
            self.root, "Refactoring auth. Tests failing on refresh path.",
            task="Auth refactor", next_steps=["Fix refresh test"],
            source="claude-code", now="2026-08-06T10:00:00Z",
        )
        pending = pending_handoffs(self.root, now="2026-08-06T11:00:00Z")
        self.assertEqual(len(pending), 1)
        block = handoff_brief_block(pending, now="2026-08-06T11:00:00Z")
        self.assertIn("HANDOFF WAITING", block)
        self.assertIn("1h ago", block)
        self.assertIn("from claude-code", block)
        self.assertIn("Fix refresh test", block)
        # Boilerplate never reaches the brief.
        self.assertNotIn("Standalone by design", block)

    def test_expiry_is_automatic(self):
        write_handoff(self.root, "note", now="2026-08-06T10:00:00Z", ttl_hours=48)
        self.assertEqual(len(pending_handoffs(self.root, now="2026-08-08T09:59:00Z")), 1)
        self.assertEqual(len(pending_handoffs(self.root, now="2026-08-08T10:01:00Z")), 0)

    def test_secrets_are_redacted_at_write(self):
        token = "ghp_" + "aB3dE5fG7hI9jK1lM3nO5pQ7rS9tU1vX3yZ5aB"
        record = write_handoff(self.root, f"deploy key is {token}", now="2026-08-06T10:00:00Z")
        text = (self.root / str(record["path"])).read_text(encoding="utf-8")
        self.assertNotIn(token, text)

    def test_chain_breadcrumb_links_to_previous(self):
        write_handoff(self.root, "first", now="2026-08-06T10:00:00Z")
        second = write_handoff(self.root, "second", now="2026-08-06T11:00:00Z")
        text = (self.root / str(second["path"])).read_text(encoding="utf-8")
        self.assertIn("previous:", text)

    def test_clear_removes_and_empty_note_rejected(self):
        record = write_handoff(self.root, "note", now="2026-08-06T10:00:00Z")
        clear_handoff(self.root, str(record["path"]))
        self.assertEqual(pending_handoffs(self.root, now="2026-08-06T10:30:00Z"), [])
        with self.assertRaises(ValueError):
            write_handoff(self.root, "   ")

    def test_brief_block_truncates_verbose_handoffs(self):
        write_handoff(self.root, "x" * 5000, task="Big", now="2026-08-06T10:00:00Z")
        block = handoff_brief_block(pending_handoffs(self.root, now="2026-08-06T10:05:00Z"))
        self.assertLess(len(block), 2200)


class HandoffDeliveryTests(unittest.TestCase):
    """Push, never pull: both surfaces must carry a waiting handoff."""

    def _workspace(self, temp: Path) -> Path:
        wiki = temp / "wiki"
        (wiki / "memories").mkdir(parents=True)
        (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
        (wiki / "log.md").write_text("# Log\n", encoding="utf-8")
        return temp

    def test_mcp_first_response_carries_handoff_even_with_zero_memories(self):
        from mcp_harness import mcp_server
        with tempfile.TemporaryDirectory() as temp:
            root = self._workspace(Path(temp))
            write_handoff(root, "resume the migration", task="DB migration", source="codex")
            with mcp_server(root) as server:
                first = json.loads(server.status())
                self.assertIn("link_session_brief", first)
                self.assertIn("HANDOFF WAITING", first["link_session_brief"].get("handoff_waiting", ""))

    def test_session_start_hook_opens_with_handoff(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._workspace(Path(temp))
            write_handoff(root, "resume the migration", task="DB migration", source="codex")
            completed = subprocess.run(
                [sys.executable, str(ROOT / "link.py"), "hook", "session-start", str(root)],
                input=json.dumps({"cwd": str(root)}),
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(
                completed.stdout.lstrip().startswith("HANDOFF WAITING"),
                completed.stdout[:200],
            )


class BulkDeleteTargetingTests(unittest.TestCase):
    """`delete-capture <dir> --all` must target <dir> - the misparse that
    once pointed a destructive bulk delete at the default workspace."""

    def test_positional_is_target_when_all(self):
        from link_core.cli_parser import build_cli_parser, dispatch_cli_command
        seen = {}

        def fake_delete(target, capture, confirm=False, delete_all=False, json_output=False):
            seen.update(target=str(target), capture=capture, delete_all=delete_all)
            return 0

        parser = build_cli_parser()
        args = parser.parse_args(["delete-capture", "somews", "--all"])
        dispatch_cli_command(args, {"delete-capture": fake_delete})
        self.assertEqual(seen["target"], "somews")
        self.assertIsNone(seen["capture"])
        self.assertTrue(seen["delete_all"])


if __name__ == "__main__":
    unittest.main()
