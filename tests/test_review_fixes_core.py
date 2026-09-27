"""Regressions found in the 4.0.0 pre-release review of the memory core."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.memory import (  # noqa: E402
    has_negation,
    memory_brief,
    memory_conflict_candidates,
    memory_records,
    recall_memories,
    update_memory_page,
    write_memory_page,
)


def _rec(name, text, memory_type="fact", date="2026-01-01T00:00:00Z", **extra):
    record = {
        "name": name, "title": text, "tldr": text, "snippet": text, "memory_type": memory_type,
        "scope": "user", "status": "active", "review_status": "reviewed", "tags": [],
        "date_captured": date, "body": f"# {text}\n\n> **TLDR:** {text}\n\n## Memory\n\n{text}\n",
    }
    record.update(extra)
    return record


def _no_embedder(_texts):
    return []


class DefaultProjectScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.wiki = Path(self.temp.name) / "wiki"
        (self.wiki / "memories").mkdir(parents=True)
        (self.wiki / "index.md").write_text("# Index\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, text, **kwargs):
        return write_memory_page(
            self.wiki, text, None, "preference", "user", None, "test", "2026-09-27T00:00:00Z",
            contradiction_scorer=None, **kwargs,
        )

    def test_a_default_project_keeps_a_user_memory_user_wide(self):
        # Every CLI and MCP write passes the workspace's default project.
        self._write("I prefer concise answers with no emoji.", project="link")
        (record,) = memory_records(self.wiki)
        self.assertEqual(record["scope"], "user")
        self.assertEqual(recall_memories([record], "concise answers emoji", project="picochat")[0]["name"],
                         record["name"])

    def test_a_named_project_makes_it_a_project_memory(self):
        result = self._write("Use ruff for linting in this service.", project="api", project_explicit=True)
        (record,) = memory_records(self.wiki)
        self.assertEqual(record["scope"], "project")
        self.assertTrue(result["scope_inferred_from_project"])


class FalseConflictTests(unittest.TestCase):
    def _conflicts(self, stored, new, memory_type="fact"):
        hits = memory_conflict_candidates([_rec("stored", stored, memory_type)], new, None, memory_type, "user",
                                          embedder=_no_embedder)
        return [reason for hit in hits for reason in hit["conflict_reasons"]]

    def test_different_subjects_with_different_values_do_not_conflict(self):
        self.assertEqual(self._conflicts("Node 20 runs the api.", "Node 18 runs the worker."), [])

    def test_moving_data_from_a_to_b_is_not_a_revision(self):
        self.assertEqual(
            self._conflicts("Staging database uses Postgres 15.",
                            "Copy the database from staging to prod before each release."),
            [],
        )

    def test_real_value_changes_still_conflict(self):
        self.assertIn("changed_value", self._conflicts("We deploy with Python 3.11.", "We deploy with Python 3.12."))
        self.assertIn("changed_value",
                      self._conflicts("The API listens on port 8080.", "The API listens on port 9090."))
        self.assertIn("replaces_stated_value",
                      self._conflicts("The staging server listens on port 8080.",
                                      "Staging moved from port 8080 to 8443 when we turned on TLS."))

    def test_the_right_subject_is_not_demoted(self):
        api = _rec("api", "Node 20 runs the api.")
        worker = _rec("worker", "Node 18 runs the worker.", date="2026-03-01T00:00:00Z")
        (top,) = recall_memories([api, worker], "which node version runs the api", limit=1)
        self.assertEqual(top["name"], "api")
        self.assertNotIn("contradicted_by", top)


class AdditiveUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.wiki = Path(self.temp.name) / "wiki"
        (self.wiki / "memories").mkdir(parents=True)
        (self.wiki / "index.md").write_text("# Index\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, text):
        write_memory_page(self.wiki, text, None, "decision", "user", None, "test", "2026-09-01T00:00:00Z",
                          records=[], contradiction_scorer=None)
        return memory_records(self.wiki)[0]["name"]

    def test_an_addition_keeps_the_claim_agents_read(self):
        name = self._write("We deploy with Python 3.11 on the api service.")
        update_memory_page(self.wiki, name, "Also pin pip to 24.0 in the Dockerfile.", "test",
                           "2026-09-20T00:00:00Z", records=memory_records(self.wiki))
        record = memory_records(self.wiki)[0]
        self.assertIn("Python 3.11", record["title"])
        self.assertIn("Python 3.11", record["tldr"])
        self.assertIn("pin pip to 24.0", (self.wiki / "memories" / f"{name}.md").read_text(encoding="utf-8"))

    def test_a_heading_inside_an_update_is_not_renamed(self):
        name = self._write("We deploy with Python 3.11 on the api service.")
        page = self.wiki / "memories" / f"{name}.md"
        text = page.read_text(encoding="utf-8")
        page.write_text(text.replace(f"# {memory_records(self.wiki)[0]['title']}\n", "", 1), encoding="utf-8")
        update_memory_page(self.wiki, name, "We deploy with Python 3.12 on the api service.\n\n# Migration notes",
                           "test", "2026-09-20T00:00:00Z", records=memory_records(self.wiki))
        self.assertIn("# Migration notes", page.read_text(encoding="utf-8"))


class SmallFixesTests(unittest.TestCase):
    def test_everyday_words_are_not_negations(self):
        for text in ("发布前特别要运行测试", "区别在于缓存", "個別に確認する", "危ないコマンド", "不具合を直す"):
            with self.subTest(text=text):
                self.assertFalse(has_negation(text))
        for text in ("不要在周五发布", "金曜日にはデプロイしない", "别在周五发布"):
            with self.subTest(text=text):
                self.assertTrue(has_negation(text))

    def test_same_meaning_in_chinese_is_not_a_conflict(self):
        hits = memory_conflict_candidates([_rec("zh", "发布前运行测试", "preference")], "发布前特别要运行测试", None,
                                          "preference", "user", embedder=_no_embedder)
        self.assertFalse(any("opposite_negation" in hit["conflict_reasons"] for hit in hits))

    def test_brief_respects_its_limit(self):
        records = [
            _rec(f"p{i}", f"Answer in short bullet points, variant {i}.", "preference") for i in range(4)
        ]
        brief = memory_brief(records, query="", limit=1)
        self.assertLessEqual(len(brief.get("relevant_memories", [])), 1)

    def test_korean_and_single_kanji_queries_find_their_memory(self):
        ko = _rec("ko", "배포는 금요일에 하지 않는다", "decision")
        ja = _rec("ja", "鍵はVaultに保存する", "decision")
        self.assertEqual([hit["name"] for hit in recall_memories([ko, ja], "배포")], ["ko"])
        self.assertEqual([hit["name"] for hit in recall_memories([ko, ja], "鍵")], ["ja"])
        self.assertGreaterEqual(recall_memories([ja], "Vault")[0]["score"], 30)


if __name__ == "__main__":
    unittest.main()
