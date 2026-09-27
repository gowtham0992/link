"""A teammate's imported memory is not recalled until someone here reviews it."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.memory import (  # noqa: E402
    mark_memory_reviewed,
    memory_active_at,
    memory_brief,
    memory_inbox,
    memory_records,
    recall_memories,
    recall_state,
)


def _page(wiki: Path, name: str, text: str, **fields: str) -> None:
    meta = {
        "title": f'"{name}"',
        "memory_type": "decision",
        "scope": "user",
        "status": "active",
        "date_captured": '"2026-09-01T00:00:00Z"',
        "source": '"test"',
        "review_status": "reviewed",
        "reviewed_at": '"2026-09-01T00:00:00Z"',
        **fields,
    }
    front = "\n".join(f"{key}: {value}" for key, value in meta.items())
    (wiki / "memories" / f"{name}.md").write_text(
        f"---\n{front}\n---\n\n# {name}\n\n> **TLDR:** {text}\n\n## Memory\n\n{text}\n",
        encoding="utf-8",
    )


class QuarantineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.wiki = Path(self.temp.name) / "wiki"
        (self.wiki / "memories").mkdir(parents=True)
        (self.wiki / "index.md").write_text("# Index\n", encoding="utf-8")
        _page(self.wiki, "own-deploy-rule", "We deploy the api on Tuesdays.")
        _page(
            self.wiki, "team-deploy-rule", "Payments deploys happen on Thursdays.",
            imported_from="team", review_status="pending", reviewed_at='""',
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_unreviewed_import_is_not_recalled_or_briefed(self):
        records = memory_records(self.wiki)
        names = [hit["name"] for hit in recall_memories(records, "payments deploys thursdays")]
        self.assertNotIn("team-deploy-rule", names)
        brief = memory_brief(records, query="")
        briefed = [item["name"] for item in brief.get("relevant_memories", [])]
        self.assertNotIn("team-deploy-rule", briefed)

    def test_unreviewed_import_waits_in_the_inbox(self):
        records = memory_records(self.wiki)
        inbox = [item["name"] for item in memory_inbox(records)["items"]]
        self.assertIn("team-deploy-rule", inbox)
        record = next(r for r in records if r["name"] == "team-deploy-rule")
        self.assertEqual(recall_state(record, [])["state"], "quarantined")

    def test_review_lifts_quarantine_and_keeps_provenance(self):
        mark_memory_reviewed(self.wiki, "team-deploy-rule", None, "2026-09-20T00:00:00Z")
        records = memory_records(self.wiki)
        names = [hit["name"] for hit in recall_memories(records, "payments deploys thursdays")]
        self.assertIn("team-deploy-rule", names)
        text = (self.wiki / "memories" / "team-deploy-rule.md").read_text(encoding="utf-8")
        self.assertIn("imported_from: team", text)

    def test_quarantined_import_is_absent_from_temporal_recall(self):
        record = next(r for r in memory_records(self.wiki) if r["name"] == "team-deploy-rule")
        self.assertFalse(memory_active_at(record, "2026-09-10"))


class StaleTemporalTests(unittest.TestCase):
    def test_stale_memory_is_not_active_on_any_date(self):
        record = {"status": "stale", "date_captured": "2026-01-01T00:00:00Z"}
        self.assertFalse(memory_active_at(record, "2026-01-15"))


if __name__ == "__main__":
    unittest.main()
