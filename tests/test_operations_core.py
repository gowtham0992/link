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
        (wiki / "index.md").write_text("# Index\n", encoding="utf-8")

        with operation_journal(
            wiki,
            "remember",
            "Saved memory",
            timestamp="2026-05-17T00:00:00Z",
            paths=["wiki/index.md"],
        ):
            pass

        self.assertEqual(pending_operations(wiki), [])
        self.assertEqual(list((wiki / ".link-operations").glob("remember-*")), [])

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

    def test_operation_journal_rolls_back_touched_files_on_failure(self):
        wiki = Path(tempfile.mkdtemp(prefix="link-operations-core-")) / "wiki"
        (wiki / "memories").mkdir(parents=True)
        index_path = wiki / "index.md"
        new_page = wiki / "memories" / "new-memory.md"
        index_path.write_text("# Index\n\nold\n", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "boom"):
            with operation_journal(
                wiki,
                "remember",
                "Saved memory",
                timestamp="2026-05-17T00:00:00Z",
                paths=["wiki/index.md", "wiki/memories/new-memory.md"],
            ):
                index_path.write_text("# Index\n\nnew\n", encoding="utf-8")
                new_page.write_text("# New memory\n", encoding="utf-8")
                raise RuntimeError("boom")

        self.assertEqual(index_path.read_text(encoding="utf-8"), "# Index\n\nold\n")
        self.assertFalse(new_page.exists())
        operations = pending_operations(wiki)
        self.assertEqual(len(operations), 1)
        rollback = operations[0]["rollback"]
        self.assertEqual(rollback["restored"], ["wiki/index.md"])
        self.assertEqual(rollback["removed"], ["wiki/memories/new-memory.md"])
        payload = operation_report(wiki)
        _, text = render_operations_text(payload)
        self.assertIn("Rollback: restored wiki/index.md; removed wiki/memories/new-memory.md", text)

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
