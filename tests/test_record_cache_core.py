"""The record cache must never serve a stale or shared record."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.memory import memory_records, recall_memories  # noqa: E402


def _page(wiki: Path, name: str, text: str) -> Path:
    path = wiki / "memories" / f"{name}.md"
    path.write_text(
        f"---\ntitle: \"{name}\"\nmemory_type: decision\nscope: user\nstatus: active\n"
        f"date_captured: \"2026-09-01T00:00:00Z\"\nsource: test\nreview_status: reviewed\n---\n\n"
        f"# {name}\n\n> **TLDR:** {text}\n\n## Memory\n\n{text}\n",
        encoding="utf-8",
    )
    return path


class RecordCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.wiki = Path(self.temp.name) / "wiki"
        (self.wiki / "memories").mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_an_edit_is_seen_on_the_next_read(self):
        path = _page(self.wiki, "deploy-day", "We deploy on Tuesdays.")
        self.assertEqual(memory_records(self.wiki)[0]["tldr"], "We deploy on Tuesdays.")
        # Same length, same second: only the content changes.
        path.write_text(path.read_text(encoding="utf-8").replace("Tuesdays", "Thursday"), encoding="utf-8")
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000))
        self.assertEqual(memory_records(self.wiki)[0]["tldr"], "We deploy on Thursday.")

    def test_added_and_deleted_files_are_seen(self):
        _page(self.wiki, "one", "First claim about caching.")
        self.assertEqual(len(memory_records(self.wiki)), 1)
        second = _page(self.wiki, "two", "Second claim about caching.")
        self.assertEqual(len(memory_records(self.wiki)), 2)
        second.unlink()
        self.assertEqual([r["name"] for r in memory_records(self.wiki)], ["one"])

    def test_callers_cannot_mutate_the_cache(self):
        _page(self.wiki, "one", "First claim about caching.")
        memory_records(self.wiki)[0]["title"] = "changed by a caller"
        self.assertEqual(memory_records(self.wiki)[0]["title"], "one")

    def test_without_body_omits_body_only(self):
        _page(self.wiki, "one", "First claim about caching.")
        record = memory_records(self.wiki, include_body=False)[0]
        self.assertNotIn("body", record)
        self.assertEqual(record["tldr"], "First claim about caching.")

    def test_prefilter_keeps_short_queries_working(self):
        _page(self.wiki, "go", "go")
        # A two-letter query has no indexable words; it must still reach the
        # phrase match rather than being filtered out.
        hits = recall_memories(memory_records(self.wiki), "go")
        self.assertEqual([hit["name"] for hit in hits], ["go"])


if __name__ == "__main__":
    unittest.main()
