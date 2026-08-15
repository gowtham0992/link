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


class FirstResponseBriefTests(unittest.TestCase):
    """Push memory to agents that have no session hooks, via MCP itself."""

    def _server(self, wiki_root: Path):
        """The MCP server bound to this workspace, as a context manager.

        Entering and exiting inside the caller's `with tempfile...` block
        is deliberate: the server's FTS handle must close *before* the
        temp directory is removed, or Windows fails cleanup with
        WinError 32. See tests/mcp_harness.py.
        """
        from mcp_harness import mcp_server
        return mcp_server(wiki_root)

    def _workspace(self, temp: Path) -> Path:
        from link_core.memory import write_memory_page
        wiki = temp / "wiki"
        (wiki / "memories").mkdir(parents=True)
        (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
        (wiki / "log.md").write_text("# Log\n", encoding="utf-8")
        write_memory_page(
            wiki, "I only deploy on Tuesdays.", title="Deploy day",
            memory_type="preference", scope="user", tags=None,
            source="test", timestamp="2026-08-01T00:00:00Z",
        )
        return temp

    def test_first_response_carries_the_brief_and_only_the_first(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._workspace(Path(temp))
            with self._server(root) as server:
                first = json.loads(server.status())
                self.assertIn("link_session_brief", first)
                attached = first["link_session_brief"]
            self.assertIn("memory", str(attached["note"]).lower())
            memories = attached.get("memories")
            self.assertTrue(memories, "digest must carry the memory claims")
            self.assertIn("claim", memories[0])
            # The public promise: the first response costs a note, not a
            # novel. Hard budget, asserted here so it cannot regress.
            self.assertLessEqual(
                len(json.dumps(attached)), server.SESSION_BRIEF_MAX_CHARS,
                "session brief digest exceeded its hard budget",
            )
            second = json.loads(server.status())
            self.assertNotIn("link_session_brief", second)

    def test_the_push_is_recorded_as_a_retrieval(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._workspace(Path(temp))
            with self._server(root) as server:
                server.status()
            events = load_usage(root)
            self.assertTrue(any(event["kind"] == "brief" for event in events), events)

    def test_opt_out_leaves_responses_untouched(self):
        import os
        with tempfile.TemporaryDirectory() as temp:
            root = self._workspace(Path(temp))
            os.environ["LINK_MCP_AUTOBRIEF"] = "off"
            try:
                with self._server(root) as server:
                    self.assertNotIn("link_session_brief", json.loads(server.status()))
            finally:
                del os.environ["LINK_MCP_AUTOBRIEF"]

    def test_empty_memory_does_not_pad_responses(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wiki = root / "wiki"
            (wiki / "memories").mkdir(parents=True)
            (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
            (wiki / "log.md").write_text("# Log\n", encoding="utf-8")
            with self._server(root) as server:
                self.assertNotIn("link_session_brief", json.loads(server.status()))


class ColdWalkRegressionTests(unittest.TestCase):
    """Frictions found by the fresh-user walk must stay fixed."""

    def test_day_one_memory_is_not_dead_weight(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record_retrieval(root, "recall", [])
            records = [
                {"name": "saved-today", "date_captured": "2026-08-05T10:00:00Z"},
                {"name": "old-and-unused", "date_captured": "2026-01-01T00:00:00Z"},
            ]
            summary = usage_summary(root, days=7, records=records, today="2026-08-05")
            self.assertNotIn("saved-today", summary["never_retrieved"])
            self.assertIn("old-and-unused", summary["never_retrieved"])

    def test_wins_note_never_claims_reads_that_did_not_happen(self):
        from link_core.memory_wins import _honest_note
        note = _honest_note({
            "tracking": True, "has_data": True, "window_days": 7,
            "retrievals": 3, "briefs": 0, "memories_surfaced": 0,
        })
        self.assertIn("reached for memory", note)
        self.assertIn("no memories matched yet", note)
        self.assertNotIn("read memory back", note)

    def test_recall_miss_hint_matches_store_state(self):
        from link_core.cli_memory import render_recall_text
        _code, empty_store = render_recall_text(
            query="anything", results=[], target=".", store_count=0)
        self.assertIn("Add one", empty_store)
        _code, full_store = render_recall_text(
            query="anything", results=[], target=".", store_count=5)
        self.assertNotIn("Add one", full_store)
        self.assertIn("Try different words", full_store)
        self.assertIn("match by meaning", full_store)

    def test_offline_guard_also_silences_progress_bars(self):
        import os
        from link_core.semantic import _set_offline_guard
        _set_offline_guard(False)
        try:
            self.assertEqual(os.environ.get("HF_HUB_OFFLINE"), "1")
            self.assertEqual(os.environ.get("HF_HUB_DISABLE_PROGRESS_BARS"), "1")
        finally:
            _set_offline_guard(True)
