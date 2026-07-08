import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.memory import (  # noqa: E402
    memory_applicability,
    memory_brief,
    memory_records,
    parse_applies_when,
    recall_memories,
    write_memory_page,
)


def _memory(name: str, body: str, **extra) -> dict[str, object]:
    record = {
        "name": name,
        "title": name.replace("-", " ").title(),
        "tldr": body,
        "tags": [],
        "body": body,
        "status": "active",
        "scope": "user",
        "memory_type": "preference",
        "review_status": "reviewed",
    }
    record.update(extra)
    return record


class ApplicabilityTests(unittest.TestCase):
    def test_parse_rejects_unknown_kinds_and_empty_arguments(self):
        self.assertEqual(
            parse_applies_when("project:link, task:cutting a release"),
            [("project", "link"), ("task", "cutting a release")],
        )
        with self.assertRaises(ValueError):
            parse_applies_when("branch:main")
        with self.assertRaises(ValueError):
            parse_applies_when("task:")

    def test_applicability_states(self):
        record = _memory("squash-merges", "Use squash merges.", applies_when="project:acme")
        self.assertEqual(memory_applicability(record, project="acme"), "matched")
        self.assertEqual(memory_applicability(record, project="other"), "out_of_context")
        self.assertEqual(memory_applicability(_memory("plain", "x")), "unconditional")

        task_record = _memory("release-notes", "Short release notes.", applies_when="task:release notes")
        self.assertEqual(memory_applicability(task_record, query="drafting the release notes"), "matched")
        self.assertEqual(memory_applicability(task_record, query="fixing a login bug"), "out_of_context")

        path_record = _memory("frontend-style", "Use Prettier.", applies_when="path:*webapp*")
        self.assertEqual(
            memory_applicability(path_record, context_path="/Users/dev/webapp/src"), "matched"
        )
        self.assertEqual(
            memory_applicability(path_record, context_path="/Users/dev/backend"), "out_of_context"
        )
        # A path condition with no known path cannot match, never raises.
        self.assertEqual(memory_applicability(path_record), "out_of_context")

    def test_recall_demotes_and_labels_out_of_context(self):
        conditioned = _memory(
            "acme-deploy", "Deploy releases from the acme pipeline only.",
            applies_when="project:acme",
        )
        unconditioned = _memory("general-deploy", "Deploy releases only after CI passes.")

        results = recall_memories([conditioned, unconditioned], "how do we deploy releases", project="other")
        names = [str(item["name"]) for item in results]
        self.assertEqual(names[0], "general-deploy")
        demoted = next(item for item in results if item["name"] == "acme-deploy")
        self.assertEqual(demoted["applicability"], "out_of_context")

        results = recall_memories([conditioned, unconditioned], "how do we deploy releases", project="acme")
        boosted = next(item for item in results if item["name"] == "acme-deploy")
        self.assertEqual(boosted["applicability"], "matched")
        self.assertEqual([str(item["name"]) for item in results][0], "acme-deploy")

    def test_brief_excludes_out_of_context_conditional_memories(self):
        conditioned = _memory(
            "acme-only", "Acme conventions apply.",
            applies_when="project:acme", memory_type="preference", date_captured="2026-07-01",
        )
        general = _memory(
            "always-on", "Always write tests.",
            memory_type="preference", date_captured="2026-07-01",
        )

        brief = memory_brief([conditioned, general], query="", project="other")
        names = [str(item["name"]) for item in brief["relevant_memories"]]
        self.assertIn("always-on", names)
        self.assertNotIn("acme-only", names)

        brief = memory_brief([conditioned, general], query="", project="acme")
        names = [str(item["name"]) for item in brief["relevant_memories"]]
        self.assertIn("acme-only", names)

    def test_write_page_stores_and_validates_applies_when(self):
        with tempfile.TemporaryDirectory() as temp:
            wiki = Path(temp) / "wiki"
            (wiki / "memories").mkdir(parents=True)
            (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
            (wiki / "log.md").write_text("# Log\n", encoding="utf-8")

            result = write_memory_page(
                wiki, "Use squash merges in the acme repo.", title="Acme squash merges",
                memory_type="preference", scope="user", tags=None, source="test",
                timestamp="2026-07-08T00:00:00Z", applies_when="project:acme, task:merging",
            )
            self.assertTrue(result.get("created"), result)
            page = (wiki / "memories" / "acme-squash-merges.md").read_text(encoding="utf-8")
            self.assertIn('applies_when: "project:acme, task:merging"', page)
            record = memory_records(wiki)[0]
            self.assertEqual(record["applies_when"], "project:acme, task:merging")

            with self.assertRaises(ValueError):
                write_memory_page(
                    wiki, "Bad condition.", title="Bad", memory_type="note", scope="user",
                    tags=None, source="test", timestamp="2026-07-08T00:00:00Z",
                    applies_when="branch:main",
                )


if __name__ == "__main__":
    unittest.main()
