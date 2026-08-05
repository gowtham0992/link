"""Retrieval observability: the ledger that answers 'did the agent use it?'"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.usage import (  # noqa: E402
    load_usage,
    record_retrieval,
    usage_path,
    usage_summary,
)


class UsageLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="link-usage-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_records_retrievals_with_names_but_never_the_query(self):
        self.assertTrue(record_retrieval(self.root, "recall", ["a", "b"], project="demo"))
        events = load_usage(self.root)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "recall")
        self.assertEqual(events[0]["memories"], ["a", "b"])
        self.assertEqual(events[0]["count"], 2)
        # The whole ledger must never contain question text.
        raw = usage_path(self.root).read_text(encoding="utf-8")
        self.assertNotIn("query", raw)

    def test_unknown_kinds_are_ignored(self):
        self.assertFalse(record_retrieval(self.root, "remember", ["a"]))
        self.assertEqual(load_usage(self.root), [])

    def test_opt_out_writes_nothing(self):
        import os
        os.environ["LINK_USAGE"] = "off"
        try:
            self.assertFalse(record_retrieval(self.root, "recall", ["a"]))
            self.assertFalse(usage_path(self.root).exists())
            summary = usage_summary(self.root)
            self.assertFalse(summary["tracking"])
        finally:
            del os.environ["LINK_USAGE"]

    def test_ledger_is_bounded(self):
        from link_core.usage import MAX_EVENTS
        for index in range(MAX_EVENTS + 25):
            record_retrieval(self.root, "recall", [f"m{index}"])
        self.assertEqual(len(load_usage(self.root)), MAX_EVENTS)

    def test_corrupt_ledger_degrades_quietly(self):
        usage_path(self.root).write_text("{not json", encoding="utf-8")
        self.assertEqual(load_usage(self.root), [])
        self.assertTrue(record_retrieval(self.root, "recall", ["a"]))

    def test_summary_counts_and_finds_never_retrieved(self):
        record_retrieval(self.root, "brief", ["used-one"])
        record_retrieval(self.root, "recall", ["used-one", "used-two"])
        records = [{"name": "used-one"}, {"name": "used-two"}, {"name": "dead-weight"}]
        summary = usage_summary(self.root, days=30, records=records)
        self.assertTrue(summary["has_data"])
        self.assertEqual(summary["retrievals"], 2)
        self.assertEqual(summary["briefs"], 1)
        self.assertEqual(summary["memories_surfaced"], 2)
        self.assertEqual(summary["never_retrieved"], ["dead-weight"])
        self.assertEqual(str(summary["top_memories"][0]["memory"]), "used-one")

    def test_summary_without_data_is_honest(self):
        summary = usage_summary(self.root)
        self.assertTrue(summary["tracking"])
        self.assertFalse(summary["has_data"])
        self.assertEqual(summary["retrievals"], 0)


class WinsHonestyTests(unittest.TestCase):
    def test_note_reflects_what_is_actually_known(self):
        from link_core.memory_wins import _honest_note
        self.assertIn("unknown", _honest_note({"tracking": False}))
        self.assertIn("not recorded a read yet", _honest_note({"tracking": True, "has_data": False}))
        note = _honest_note({
            "tracking": True, "has_data": True, "window_days": 7,
            "retrievals": 5, "briefs": 2, "memories_surfaced": 3,
        })
        self.assertIn("5 time(s)", note)
        self.assertIn("2 session brief(s)", note)


if __name__ == "__main__":
    unittest.main()
