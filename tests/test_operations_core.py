import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.operations import (  # noqa: E402
    begin_operation,
    operation_journal,
    operation_report,
    pending_operations,
    render_operations_text,
)


class OperationsCoreTests(unittest.TestCase):
    def test_operation_journal_clears_marker_on_success(self):
        wiki = Path(tempfile.mkdtemp(prefix="link-operations-core-")) / "wiki"
        wiki.mkdir(parents=True)

        with operation_journal(wiki, "remember", "Saved memory", timestamp="2026-05-17T00:00:00Z"):
            pass

        self.assertEqual(pending_operations(wiki), [])

    def test_operation_journal_leaves_failed_marker(self):
        wiki = Path(tempfile.mkdtemp(prefix="link-operations-core-")) / "wiki"
        wiki.mkdir(parents=True)

        with self.assertRaisesRegex(RuntimeError, "boom"):
            with operation_journal(wiki, "remember", "Saved memory", timestamp="2026-05-17T00:00:00Z"):
                raise RuntimeError("boom")

        operations = pending_operations(wiki)
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0]["operation"], "remember")
        self.assertEqual(operations[0]["status"], "failed")
        self.assertTrue(operations[0]["stale"])
        self.assertIn("boom", operations[0]["error"])

    def test_pending_operations_marks_old_marker_stale(self):
        wiki = Path(tempfile.mkdtemp(prefix="link-operations-core-")) / "wiki"
        wiki.mkdir(parents=True)
        begin_operation(wiki, "update-memory", "Update memory", timestamp="2026-05-17T00:00:00Z")

        operations = pending_operations(wiki, now=2_000_000_000, stale_after_seconds=60)

        self.assertEqual(len(operations), 1)
        self.assertTrue(operations[0]["stale"])
        self.assertEqual(operations[0]["operation"], "update-memory")

    def test_operation_report_renders_clear_state(self):
        wiki = Path(tempfile.mkdtemp(prefix="link-operations-core-")) / "wiki"
        wiki.mkdir(parents=True)

        payload = operation_report(wiki)
        code, text = render_operations_text(payload)

        self.assertEqual(code, 0)
        self.assertEqual(payload["operation_count"], 0)
        self.assertIn("No pending, failed, or interrupted Link operations.", text)
        self.assertIn(str(wiki.parent.resolve()), text)
        self.assertIn("Result: clear", text)

    def test_operation_report_renders_stale_marker_guidance(self):
        wiki = Path(tempfile.mkdtemp(prefix="link-operations-core-")) / "wiki"
        wiki.mkdir(parents=True)
        begin_operation(
            wiki,
            "remember",
            "Save memory",
            timestamp="2026-05-17T00:00:00Z",
            paths=["wiki/memories/prefer-local.md", "wiki/log.md"],
        )

        payload = operation_report(wiki, now=2_000_000_000, stale_after_seconds=60)
        code, text = render_operations_text(payload)

        self.assertEqual(code, 1)
        self.assertEqual(payload["stale_count"], 1)
        self.assertIn("remember | pending | stale", text)
        self.assertIn("Description: Save memory", text)
        self.assertIn("Touched: wiki/memories/prefer-local.md, wiki/log.md", text)
        self.assertIn("lnk validate", text)
        self.assertIn(str(wiki.parent.resolve()), text)
        self.assertIn("Result: needs attention", text)


if __name__ == "__main__":
    unittest.main()
