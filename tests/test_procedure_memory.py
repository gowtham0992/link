import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.capture import capture_accept_memory_args  # noqa: E402
from link_core.memory import (  # noqa: E402
    extract_procedure_candidates,
    memory_records,
    procedure_steps_excerpt,
    propose_memories_from_text,
    recall_memories,
    write_memory_page,
)

STEPS = (
    "1. Bump the version in pyproject and server.json\n"
    "2. Run make test and the large-wiki smoke\n"
    "3. Update CHANGELOG with the release section\n"
    "4. Tag release/x.y.z and push"
)


def _write_procedure(wiki: Path) -> dict[str, object]:
    return write_memory_page(
        wiki,
        STEPS,
        title="Cutting a release",
        memory_type="procedure",
        scope="user",
        tags=None,
        source="test",
        timestamp="2026-07-08T00:00:00Z",
        trigger="cutting or preparing a new release",
    )


class ProcedureMemoryTests(unittest.TestCase):
    def _wiki(self, temp: str) -> Path:
        wiki = Path(temp) / "wiki"
        (wiki / "memories").mkdir(parents=True)
        (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
        (wiki / "log.md").write_text("# Log\n", encoding="utf-8")
        return wiki

    def test_procedure_page_carries_trigger_frontmatter(self):
        with tempfile.TemporaryDirectory() as temp:
            wiki = self._wiki(temp)
            result = _write_procedure(wiki)
            self.assertTrue(result.get("created"), result)
            page = (wiki / "memories" / "cutting-a-release.md").read_text(encoding="utf-8")

        self.assertIn('trigger: "cutting or preparing a new release"', page)
        self.assertIn("memory_type: procedure", page)
        self.assertIn("- cutting or preparing a new release", page)

    def test_trigger_phrase_recalls_procedure_with_steps(self):
        with tempfile.TemporaryDirectory() as temp:
            wiki = self._wiki(temp)
            _write_procedure(wiki)
            records = memory_records(wiki)
            results = recall_memories(records, "preparing a new release", limit=3)

        self.assertTrue(results)
        recalled = results[0]
        self.assertEqual(recalled["memory_type"], "procedure")
        self.assertIn("Bump the version", str(recalled["steps"]))
        self.assertIn(recalled["confidence"], {"strong", "moderate"})

    def test_invalid_trigger_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            wiki = self._wiki(temp)
            with self.assertRaises(ValueError):
                write_memory_page(
                    wiki, STEPS, title=None, memory_type="procedure", scope="user",
                    tags=None, source="test", timestamp="2026-07-08T00:00:00Z",
                    trigger="x" * 250,
                )

    def test_extract_candidates_need_three_numbered_steps(self):
        text = "To hotfix production:\n1. Cut a branch\n2. Cherry-pick the fix\n3. Deploy from the tag"
        candidates = extract_procedure_candidates(text)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["trigger"], "To hotfix production")

        short = "Notes:\n1. one\n2. two"
        self.assertEqual(extract_procedure_candidates(short), [])

        bullets = "Notes:\n- one\n- two\n- three\n- four"
        self.assertEqual(extract_procedure_candidates(bullets), [])

    def test_proposals_include_procedure_with_trigger(self):
        text = (
            "User: write down how we hotfix production.\n"
            "Here is how we hotfix production:\n"
            "1. Cut a branch from the last release tag\n"
            "2. Cherry-pick the fix and run make test\n"
            "3. Deploy to staging and verify\n"
            "4. Tag hotfix and redeploy production"
        )
        result = propose_memories_from_text(text, records=[], source="test")
        procedures = [p for p in result["proposals"] if p["memory_type"] == "procedure"]
        self.assertEqual(len(procedures), 1)
        proposal = procedures[0]
        self.assertEqual(proposal["trigger"], "Here is how we hotfix production")
        self.assertIn("1. Cut a branch", proposal["memory"])

        args = capture_accept_memory_args({"proposal": proposal, "project": "", "capture": "raw/x.md"})
        self.assertEqual(args["trigger"], "Here is how we hotfix production")
        self.assertEqual(args["memory_type"], "procedure")

    def test_steps_excerpt_extracts_memory_section(self):
        body = "# T\n\n> **TLDR:** t\n\n## Memory\n\n1. a\n2. b\n\n## Source\n\nx"
        self.assertEqual(procedure_steps_excerpt(body), "1. a\n2. b")


if __name__ == "__main__":
    unittest.main()
