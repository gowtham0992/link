"""An update must change what recall shows, not only the page body."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.memory import (  # noqa: E402
    memory_records,
    recall_memories,
    update_memory_page,
    write_memory_page,
)

COMMON = dict(scope="user", tags=None, source="test", log_writer=lambda *a: None, rebuild_backlinks=lambda: True)


class UpdateMovesHeadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.wiki = Path(self.temp.name) / "wiki"
        (self.wiki / "memories").mkdir(parents=True)
        (self.wiki / "index.md").write_text("# Index\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_claim_shaped_title_and_tldr_follow_the_update(self):
        write_memory_page(self.wiki, "We deploy with Python 3.11", None, "decision",
                          timestamp="2026-09-01T00:00:00Z", records=[], **COMMON)
        name = memory_records(self.wiki)[0]["name"]
        update_memory_page(self.wiki, name, "We now deploy with Python 3.12", "test",
                           "2026-09-20T00:00:00Z", records=memory_records(self.wiki))
        record = memory_records(self.wiki)[0]
        self.assertEqual(record["tldr"], "We now deploy with Python 3.12")
        self.assertEqual(record["title"], "We now deploy with Python 3.12")
        self.assertEqual(record["name"], name, "the filename, and so every link to it, stays put")
        hit = recall_memories(memory_records(self.wiki), "python 3.12 deploy")[0]
        self.assertIn("3.12", hit["tldr"])
        body = (self.wiki / "memories" / f"{name}.md").read_text(encoding="utf-8")
        self.assertIn("We deploy with Python 3.11", body, "history stays in the Memory section")

    def test_label_title_is_kept(self):
        write_memory_page(self.wiki, "Deploys go out on Tuesdays after standup", "Deploy day", "decision",
                          timestamp="2026-09-01T00:00:00Z", records=[], **COMMON)
        name = memory_records(self.wiki)[0]["name"]
        update_memory_page(self.wiki, name, "Deploys go out on Wednesdays after standup", "test",
                           "2026-09-20T00:00:00Z", records=memory_records(self.wiki), allow_conflict=True)
        record = memory_records(self.wiki)[0]
        self.assertEqual(record["title"], "Deploy day")
        self.assertEqual(record["tldr"], "Deploys go out on Wednesdays after standup")


if __name__ == "__main__":
    unittest.main()
