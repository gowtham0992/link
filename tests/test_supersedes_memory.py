import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.memory import (  # noqa: E402
    memory_explanation,
    memory_records,
    recall_memories,
    write_memory_page,
)


class SupersedesTests(unittest.TestCase):
    def _wiki(self, temp: str) -> Path:
        wiki = Path(temp) / "wiki"
        (wiki / "memories").mkdir(parents=True)
        (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
        (wiki / "log.md").write_text("# Log\n", encoding="utf-8")
        return wiki

    def _write(self, wiki: Path, text: str, title: str, timestamp: str, **kwargs):
        return write_memory_page(
            wiki, text, title=title, memory_type="decision", scope="user",
            tags=None, source="test", timestamp=timestamp, **kwargs,
        )

    def test_supersede_archives_predecessor_with_lineage_both_ways(self):
        with tempfile.TemporaryDirectory() as temp:
            wiki = self._wiki(temp)
            self._write(wiki, "Releases ship weekly on Thursdays.", "Weekly releases", "2026-01-01T00:00:00Z")
            result = self._write(
                wiki, "Releases ship daily from main after CI.", "Daily releases",
                "2026-06-01T00:00:00Z", supersedes="weekly-releases",
            )

            self.assertTrue(result.get("created"), result)
            self.assertEqual(result["supersedes"], "weekly-releases")
            new_page = (wiki / "memories" / "daily-releases.md").read_text(encoding="utf-8")
            old_page = (wiki / "memories" / "weekly-releases.md").read_text(encoding="utf-8")

        self.assertIn('supersedes: "weekly-releases"', new_page)
        self.assertIn("status: archived", old_page)
        self.assertIn('superseded_by: "daily-releases"', old_page)
        self.assertIn("superseded by daily-releases", old_page)

    def test_superseding_a_conflicting_memory_needs_no_override(self):
        with tempfile.TemporaryDirectory() as temp:
            wiki = self._wiki(temp)
            self._write(wiki, "Releases ship weekly on Thursdays.", "Weekly releases", "2026-01-01T00:00:00Z")

            # Without supersedes, the contradicting write is refused.
            refused = self._write(
                wiki, "Releases never ship weekly; releases ship daily on Thursdays now.",
                "Daily releases", "2026-06-01T00:00:00Z",
            )
            self.assertFalse(refused.get("created"))
            self.assertIn("supersedes", str(refused.get("message", "")))

            # With supersedes pointing at the conflicting memory, it succeeds.
            accepted = self._write(
                wiki, "Releases never ship weekly; releases ship daily on Thursdays now.",
                "Daily releases", "2026-06-01T00:00:00Z", supersedes="weekly-releases",
            )
            self.assertTrue(accepted.get("created"), accepted)

    def test_supersedes_requires_existing_active_target(self):
        with tempfile.TemporaryDirectory() as temp:
            wiki = self._wiki(temp)
            with self.assertRaises(ValueError):
                self._write(
                    wiki, "New rule.", "New rule", "2026-06-01T00:00:00Z",
                    supersedes="does-not-exist",
                )

    def test_temporal_recall_reconstructs_history(self):
        with tempfile.TemporaryDirectory() as temp:
            wiki = self._wiki(temp)
            self._write(wiki, "Releases ship weekly on Thursdays.", "Weekly releases", "2026-01-01T00:00:00Z")
            self._write(
                wiki, "Releases ship daily from main after CI passes.", "Daily releases",
                "2026-06-01T00:00:00Z", supersedes="weekly-releases",
            )
            records = memory_records(wiki)

            today = recall_memories(records, "how often do releases ship")
            self.assertEqual([r["name"] for r in today], ["daily-releases"])

            march = recall_memories(records, "how often do releases ship", as_of="2026-03-01")
            self.assertEqual([r["name"] for r in march], ["weekly-releases"])

            july = recall_memories(records, "how often do releases ship", as_of="2026-07-01")
            self.assertEqual([r["name"] for r in july], ["daily-releases"])

            with self.assertRaises(ValueError):
                recall_memories(records, "releases", as_of="not-a-date")

    def test_explanation_shows_full_lineage_chain(self):
        with tempfile.TemporaryDirectory() as temp:
            wiki = self._wiki(temp)
            self._write(wiki, "Releases ship monthly.", "Monthly releases", "2025-06-01T00:00:00Z")
            self._write(
                wiki, "Releases ship weekly on Thursdays.", "Weekly releases",
                "2026-01-01T00:00:00Z", supersedes="monthly-releases",
            )
            self._write(
                wiki, "Releases ship daily from main after CI passes.", "Daily releases",
                "2026-06-01T00:00:00Z", supersedes="weekly-releases",
            )

            explanation = memory_explanation(wiki, "weekly-releases")

        lineage = explanation["lineage"]
        self.assertEqual(
            [(item["name"], item["relation"]) for item in lineage],
            [
                ("monthly-releases", "superseded"),
                ("weekly-releases", "superseded"),
                ("daily-releases", "successor"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
