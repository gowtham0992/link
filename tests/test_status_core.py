import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core import status as status_core  # noqa: E402
from link_core.operations import begin_operation  # noqa: E402
from link_core.status import link_status  # noqa: E402
from link_core.schema import write_schema  # noqa: E402
from link_core.wiki import build_backlinks, build_wiki_cache  # noqa: E402


def write_page(wiki: Path, rel: str, text: str) -> None:
    path = wiki / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class StatusCoreTests(unittest.TestCase):
    def make_wiki(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="link-status-core-"))
        wiki = root / "wiki"
        for dirname in ("sources", "concepts", "entities", "memories", "comparisons", "explorations"):
            (wiki / dirname).mkdir(parents=True, exist_ok=True)
        write_page(wiki, "index.md", "# Index\n")
        write_page(wiki, "log.md", "# Log\n")
        write_page(
            wiki,
            "memories/prefer-local-memory.md",
            "---\n"
            "type: memory\n"
            "title: Prefer local memory\n"
            "memory_type: preference\n"
            "scope: user\n"
            "status: active\n"
            "date_captured: \"2026-05-05T00:00:00Z\"\n"
            "source: unit-test\n"
            "review_status: reviewed\n"
            "---\n\n"
            "# Prefer local memory\n\n"
            "> **TLDR:** User prefers local memory.\n\n"
            "## Memory\n\nUser prefers local memory.\n\n"
            "## Source\n\nunit-test\n",
        )
        (wiki / "_backlinks.json").write_text(json.dumps(build_backlinks(wiki, body_only=False)), encoding="utf-8")
        write_schema(wiki)
        return wiki

    def test_link_status_reports_ready_wiki(self):
        wiki = self.make_wiki()

        payload = link_status(wiki, version="9.9.9", cache=build_wiki_cache(wiki), include_validation=True)

        self.assertTrue(payload["ready"])
        self.assertEqual(payload["version"], "9.9.9")
        self.assertEqual(payload["page_count"], 3)
        self.assertEqual(payload["content_page_count"], 1)
        self.assertEqual(payload["memory_count"], 1)
        self.assertEqual(payload["active_memory_count"], 1)
        self.assertIn(payload["search_backend"], {"sqlite-fts", "token-index"})
        self.assertTrue(payload["persistent_cache"]["enabled"])
        self.assertEqual(payload["persistent_cache"]["total_records"], 3)
        self.assertEqual(payload["schema"]["status"], "current")
        self.assertTrue(payload["validation"]["passed"])
        self.assertEqual(payload["next_actions"][0]["tool"], "recall")
        self.assertEqual(payload["next_actions"][0]["arguments"], {"query": "<user task>", "budget": "micro"})

    def test_link_status_reports_missing_structure(self):
        wiki = Path(tempfile.mkdtemp(prefix="link-status-core-")) / "wiki"

        payload = link_status(wiki, include_validation=True)

        self.assertFalse(payload["ready"])
        self.assertIn("wiki", payload["missing"])
        self.assertEqual(payload["schema"]["status"], "missing")
        self.assertEqual(payload["page_count"], 0)
        self.assertEqual(payload["search_backend"], "unavailable")
        self.assertEqual(payload["next_actions"][0]["tool"], "doctor")

    def test_link_status_guides_empty_initialized_wiki_to_ingest(self):
        root = Path(tempfile.mkdtemp(prefix="link-status-core-"))
        wiki = root / "wiki"
        for dirname in ("sources", "concepts", "entities", "memories", "comparisons", "explorations"):
            (wiki / dirname).mkdir(parents=True, exist_ok=True)
        write_page(wiki, "index.md", "# Index\n")
        write_page(wiki, "log.md", "# Log\n")
        (wiki / "_backlinks.json").write_text(json.dumps(build_backlinks(wiki, body_only=False)), encoding="utf-8")
        write_schema(wiki)

        payload = link_status(wiki)

        self.assertTrue(payload["ready"])
        self.assertEqual(payload["page_count"], 2)
        self.assertEqual(payload["content_page_count"], 0)
        self.assertEqual(payload["next_actions"][0]["tool"], "ingest")
        self.assertEqual(payload["next_actions"][0]["arguments"], {"action": "status"})
        self.assertEqual(payload["next_actions"][1]["tool"], "admin")
        self.assertEqual(payload["next_actions"][1]["arguments"], {"action": "prompts"})

    def test_link_status_surfaces_cache_and_memory_warnings(self):
        wiki = self.make_wiki()

        with (
            patch.object(status_core, "build_wiki_cache", side_effect=RuntimeError("cache failed")),
            patch.object(status_core, "memory_records", side_effect=RuntimeError("memory failed")),
        ):
            payload = link_status(wiki)

        self.assertFalse(payload["ready"])
        self.assertEqual(payload["page_count"], 0)
        self.assertEqual(payload["memory_count"], 0)
        self.assertEqual(
            [warning["code"] for warning in payload["warnings"]],
            ["cache_unavailable", "memory_records_unavailable"],
        )
        self.assertEqual(payload["warnings"][0]["detail"], "cache failed")
        self.assertEqual(payload["warnings"][1]["detail"], "memory failed")

    def test_link_status_surfaces_cache_read_warnings(self):
        wiki = self.make_wiki()
        cache = build_wiki_cache(wiki)
        cache["read_warning_count"] = 1
        cache["read_warnings"] = [{"page": "wiki/concepts/locked.md", "error": "permission denied"}]

        payload = link_status(wiki, cache=cache)

        self.assertFalse(payload["ready"])
        self.assertEqual(payload["warnings"][0]["code"], "cache_read_warnings")

    def test_link_status_warns_when_search_uses_token_fallback(self):
        wiki = self.make_wiki()
        cache = build_wiki_cache(wiki)
        cache["search_backend"] = "token-index"
        cache["fts_index_info"] = {
            "available": False,
            "persistent": False,
            "reused": False,
            "path": "",
        }

        payload = link_status(wiki, cache=cache)

        self.assertTrue(payload["ready"])
        self.assertIn("search_backend_fallback", [warning["code"] for warning in payload["warnings"]])

    def test_link_status_blocks_ready_on_stale_operation_marker(self):
        wiki = self.make_wiki()
        begin_operation(wiki, "remember", "Saved memory", timestamp="2000-01-01T00:00:00Z")

        payload = link_status(wiki)

        self.assertFalse(payload["ready"])
        self.assertIn("stale_operations", [warning["code"] for warning in payload["warnings"]])
        self.assertEqual(payload["next_actions"][0]["tool"], "doctor")
        self.assertEqual(payload["next_actions"][1]["tool"], "ingest")
        self.assertEqual(payload["next_actions"][1]["arguments"], {"action": "validate"})

    def test_link_status_points_validation_shape_errors_to_doctor_fix(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "sources/bad-source.md",
            "---\ntype: source\ntitle: Bad Source\n---\n\n"
            "# Bad Source\n\n"
            "Captured from raw/bad-source.md.\n",
        )
        (wiki / "_backlinks.json").write_text(json.dumps(build_backlinks(wiki, body_only=False)), encoding="utf-8")

        payload = link_status(wiki, include_validation=True)

        self.assertFalse(payload["ready"])
        self.assertIn("missing_required_section", payload["validation"]["error_codes"])
        self.assertEqual(payload["next_actions"][0]["tool"], "doctor")
        self.assertEqual(payload["next_actions"][0]["arguments"], {"fix": True})
        self.assertEqual(payload["next_actions"][1]["tool"], "ingest")
        self.assertEqual(payload["next_actions"][1]["arguments"], {"action": "validate"})
        self.assertNotIn({"tool": "ingest", "arguments": {"action": "rebuild"}}, payload["next_actions"])

    def test_link_status_points_stale_backlinks_to_rebuild(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/linking.md",
            "---\ntype: concept\ntitle: Linking\n---\n\n"
            "# Linking\n\n"
            "> **TLDR:** Valid linked concept.\n\n"
            "## Overview\n\nLinks to [[prefer-local-memory]].\n\n"
            "## Sources\n\n- [[prefer-local-memory]]\n",
        )
        (wiki / "_backlinks.json").write_text(json.dumps({"backlinks": {}, "forward": {}}), encoding="utf-8")

        payload = link_status(wiki, include_validation=True)

        self.assertFalse(payload["ready"])
        self.assertIn("stale_backlinks", payload["validation"]["error_codes"])
        self.assertEqual(payload["next_actions"][0]["tool"], "ingest")
        self.assertEqual(payload["next_actions"][0]["arguments"], {"action": "rebuild"})
        self.assertEqual(payload["next_actions"][1]["tool"], "ingest")
        self.assertEqual(payload["next_actions"][1]["arguments"], {"action": "validate"})


if __name__ == "__main__":
    unittest.main()
