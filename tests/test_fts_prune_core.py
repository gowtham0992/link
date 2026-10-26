"""An upgrade does not leave the old full-text index behind."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.wiki import _persistent_fts_path, build_wiki_cache, close_wiki_cache  # noqa: E402


class FtsPruneTests(unittest.TestCase):
    def test_old_index_versions_are_removed_and_others_untouched(self):
        with tempfile.TemporaryDirectory() as t:
            wiki = Path(t) / "wiki"
            (wiki / "concepts").mkdir(parents=True)
            (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
            (wiki / "concepts" / "a.md").write_text("---\ntype: concept\ntitle: A\n---\n\n# A\n\nText.\n", encoding="utf-8")
            cache_dir = wiki.parent / ".link-cache"
            cache_dir.mkdir()
            for name in ("page-fts-v1.sqlite", "page-fts-v2.sqlite", "page-fts-v2.sqlite-wal", "notes.sqlite"):
                (cache_dir / name).write_bytes(b"old")
            cache = build_wiki_cache(wiki)
            try:
                remaining = sorted(path.name for path in cache_dir.iterdir())
            finally:
                close_wiki_cache(cache)
            self.assertIn(_persistent_fts_path(wiki).name, remaining)
            self.assertIn("notes.sqlite", remaining)
            self.assertFalse(any(name.startswith(("page-fts-v1", "page-fts-v2")) for name in remaining))


class FtsThreadingTests(unittest.TestCase):
    """The viewer builds the index on one request thread and uses it on others."""

    def test_search_and_close_work_from_another_thread(self):
        import threading

        from link_core.search import build_fts_index
        pages = [{"name": "alpha", "title": "Alpha", "aliases": [], "tags": [], "tldr": ""}]
        index = build_fts_index(pages, {"alpha": "retrieval augmented generation"})
        self.assertIsNotNone(index)
        seen: dict[str, object] = {}

        def other_request() -> None:
            try:
                seen["search"] = index.search("retrieval", 5)
                index.close()
                seen["closed"] = True
            except Exception as exc:  # the viewer turned this into an empty response
                seen["error"] = repr(exc)

        worker = threading.Thread(target=other_request)
        worker.start()
        worker.join()
        self.assertEqual(seen, {"search": ["alpha"], "closed": True})


if __name__ == "__main__":
    unittest.main()
