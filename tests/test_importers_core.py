"""lnk import: scattered memory comes home as proposals, never as facts."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.importers import collect_import_units, ImportError_  # noqa: E402
from link_core.memory import curated_candidate_lines, propose_memories_from_text  # noqa: E402


def _fake_home(base: Path) -> Path:
    (base / ".claude").mkdir(parents=True)
    (base / ".claude" / "CLAUDE.md").write_text(
        "# Mine\n\n- Always run tests before declaring done.\n\n"
        "## Link — Local Agent Memory\n\nnever import this\n",
        encoding="utf-8",
    )
    memory_dir = base / ".claude" / "projects" / "proj-a" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "MEMORY.md").write_text("# index\n- pointer\n", encoding="utf-8")
    (memory_dir / "tabs.md").write_text(
        "---\nname: tabs\n---\n\nThe user prefers tabs in Go files.\n", encoding="utf-8"
    )
    rules = base / ".cursor" / "rules"
    rules.mkdir(parents=True)
    (rules / "style.mdc").write_text(
        "---\ndescription: x\n---\nUse Tailwind for all new UI work.\n", encoding="utf-8"
    )
    (rules / "link.mdc").write_text(
        "## Link — Local Agent Memory\n\nours\n", encoding="utf-8"
    )
    (base / "AGENTS.md").write_text(
        "Run make lint before every commit.\n\n## Link — Local Agent Memory\n\nours\n",
        encoding="utf-8",
    )
    return base


class ImporterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="link-import-")
        self.home = _fake_home(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_link_sections_are_never_imported_back(self):
        for source in ("claude-code", "cursor", "codex"):
            for unit in collect_import_units(source, home=self.home):
                self.assertNotIn("Link — Local Agent Memory", unit["text"], source)
                self.assertNotIn("never import this", unit["text"], source)

    def test_claude_code_finds_global_and_auto_memory(self):
        units = collect_import_units("claude-code", home=self.home)
        labels = [unit["label"] for unit in units]
        self.assertEqual(len(units), 2, labels)
        self.assertTrue(any("CLAUDE.md" in label for label in labels))
        self.assertTrue(any("auto-memory" in label for label in labels))
        combined = " ".join(unit["text"] for unit in units)
        self.assertIn("prefers tabs", combined)
        self.assertNotIn("pointer", combined)  # MEMORY.md index is skipped

    def test_cursor_skips_links_own_rule(self):
        units = collect_import_units("cursor", home=self.home)
        self.assertEqual(len(units), 1)
        self.assertIn("style.mdc", units[0]["label"])

    def test_file_source_requires_a_real_file(self):
        with self.assertRaises(ImportError_):
            collect_import_units("file", home=self.home, file_path=self.home / "missing.txt")
        exported = self.home / "chatgpt.txt"
        exported.write_text("Prefers metric units.\nWorks from Lisbon.\n", encoding="utf-8")
        units = collect_import_units("file", home=self.home, file_path=exported)
        self.assertEqual(len(units), 1)

    def test_unknown_source_is_an_error(self):
        with self.assertRaises(ImportError_):
            collect_import_units("chatgpt", home=self.home)


class CuratedMiningTests(unittest.TestCase):
    def test_curated_lines_skip_structure_keep_statements(self):
        text = (
            "# Heading\n\n```bash\nrm -rf /\n```\n\n- Always use uv.\n"
            "1. Never push to main.\n\n> quoted\n\nIs this a question?\n"
        )
        lines = curated_candidate_lines(text)
        self.assertEqual(lines, ["Always use uv.", "Never push to main."])

    def test_curated_mode_keeps_lines_chat_rules_would_drop(self):
        text = "Use tabs, not spaces, in Go files.\nThe staging DB is postgres 16.\n"
        chat = propose_memories_from_text(text, records=[], source="s")
        curated = propose_memories_from_text(text, records=[], source="s", curated=True)
        self.assertLess(len(chat["proposals"]), len(curated["proposals"]))
        self.assertEqual(len(curated["proposals"]), 2)

    def test_curated_mode_still_dedups_against_existing_memory(self):
        records = [{
            "name": "always-use-uv", "title": "Always use uv.",
            "memory_type": "preference", "scope": "user", "status": "active",
            "memory": "Always use uv.", "tldr": "Always use uv.",
        }]
        result = propose_memories_from_text(
            "Always use uv.\n", records=records, source="s", curated=True
        )
        proposals = result["proposals"]
        if proposals:  # surfaced as duplicate-flagged, never as a clean new memory
            self.assertTrue(proposals[0].get("duplicate_candidates"))


if __name__ == "__main__":
    unittest.main()
