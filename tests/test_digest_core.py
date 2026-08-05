"""The weekly digest: bounded, deterministic reflection over memory health."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.consolidate import build_digest, render_digest_text  # noqa: E402


def _memory(name, title, captured, review_after="", reviewed_at="", status="active"):
    return {
        "name": name, "title": title, "memory_type": "preference", "scope": "user",
        "status": status, "date_captured": captured, "review_after": review_after,
        "reviewed_at": reviewed_at, "tldr": title,
    }


class DigestTests(unittest.TestCase):
    TODAY = "2026-08-03"

    def _digest(self, records, merges=None, captures=0, review=None, days=7):
        return build_digest(
            records=records, merge_candidates=merges or [], capture_count=captures,
            review_items=review or [], days=days, today=self.TODAY, command_target=".",
        )

    def test_counts_what_changed_in_the_window(self):
        payload = self._digest([
            _memory("a", "New this week", "2026-08-01T00:00:00Z"),
            _memory("b", "Older", "2026-05-01T00:00:00Z"),
            _memory("c", "Reviewed recently", "2026-01-01T00:00:00Z",
                    reviewed_at="2026-08-02T00:00:00Z"),
        ])
        self.assertEqual(payload["learned_count"], 1)
        self.assertEqual(payload["reviewed_count"], 1)
        self.assertEqual(payload["active_memories"], 3)

    def test_separates_overdue_from_due_soon(self):
        payload = self._digest([
            _memory("a", "Overdue", "2026-01-01T00:00:00Z", review_after="2026-07-01"),
            _memory("b", "Due soon", "2026-01-01T00:00:00Z", review_after="2026-08-06"),
            _memory("c", "Far off", "2026-01-01T00:00:00Z", review_after="2027-01-01"),
        ])
        self.assertEqual(payload["overdue_count"], 1)
        self.assertEqual(payload["due_soon_count"], 1)
        self.assertEqual(str(payload["overdue"][0]["title"]), "Overdue")

    def test_archived_memories_are_out_of_scope(self):
        payload = self._digest([
            _memory("a", "Archived", "2026-08-01T00:00:00Z", status="archived"),
        ])
        self.assertEqual(payload["active_memories"], 0)
        self.assertEqual(payload["learned_count"], 0)

    def test_quiet_week_says_so(self):
        text = render_digest_text(self._digest([]))
        self.assertIn("Nothing needs you", text)

    def test_busy_week_reports_each_section(self):
        payload = self._digest(
            [_memory("a", "New this week", "2026-08-01T00:00:00Z"),
             _memory("b", "Stale", "2026-01-01T00:00:00Z", review_after="2026-07-01")],
            merges=[{"survivor_title": "Keep this", "absorbed_title": "Duplicate"}],
            captures=3,
        )
        text = render_digest_text(payload)
        self.assertIn("What you taught Link", text)
        self.assertIn("Aging out of its trust window", text)
        self.assertIn("Saying the same thing twice", text)
        self.assertIn("3 session capture(s)", text)

    def test_window_is_configurable(self):
        records = [_memory("a", "Three weeks old", "2026-07-14T00:00:00Z")]
        self.assertEqual(self._digest(records, days=7)["learned_count"], 0)
        self.assertEqual(self._digest(records, days=30)["learned_count"], 1)


if __name__ == "__main__":
    unittest.main()
