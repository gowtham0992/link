"""Stale agent instruction files: detected, refreshed, never invented."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.agent_instructions import (  # noqa: E402
    AGENT_INSTRUCTION_FILES,
    INSTRUCTIONS_TEMPLATE,
    find_link_section,
    instruction_file_status,
    refresh_instruction_file,
    upsert_link_section,
)

OLD_ERA_SECTION = (
    "## Link — Local Agent Memory\n\n"
    "Use MCP `link_status` when available, or run `link status --validate`.\n"
    "Start with MCP `query_link`; prime with `memory_brief`.\n"
)


class TemplatePinTests(unittest.TestCase):
    def test_embedded_template_matches_the_shipped_installer_template(self):
        source = ROOT / "integrations" / "_shared" / "link-instructions.md"
        if not source.exists():
            self.skipTest("installer template not present (installed package)")
        self.assertEqual(
            INSTRUCTIONS_TEMPLATE.rstrip(),
            source.read_text(encoding="utf-8").rstrip(),
            "link_core.agent_instructions.INSTRUCTIONS_TEMPLATE has drifted from "
            "integrations/_shared/link-instructions.md — regenerate the constant.",
        )

    def test_template_carries_the_section_marker(self):
        self.assertIsNotNone(find_link_section(INSTRUCTIONS_TEMPLATE))


class SectionUpsertTests(unittest.TestCase):
    def test_replaces_old_section_and_preserves_user_content(self):
        shared_file = (
            "# My own notes\n\nAlways run tests before pushing.\n\n"
            + OLD_ERA_SECTION
            + "\n## Another section\n\nUnrelated.\n"
        )
        updated = upsert_link_section(shared_file)
        self.assertIn("# My own notes", updated)
        self.assertIn("Always run tests before pushing.", updated)
        self.assertIn("## Another section", updated)
        self.assertNotIn("query_link", updated)
        self.assertIn("start with MCP `recall` when available", updated)

    def test_appends_when_no_section_exists(self):
        updated = upsert_link_section("# Just my file\n")
        self.assertTrue(updated.startswith("# Just my file"))
        self.assertIn("## Link — Local Agent Memory", updated)


class RefreshFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="link-instr-")
        self.home = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _write_kiro(self, text: str) -> Path:
        path = self.home / AGENT_INSTRUCTION_FILES["kiro"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_stale_old_era_file_is_detected_and_refreshed(self):
        self._write_kiro(OLD_ERA_SECTION)
        status = instruction_file_status("kiro", home=self.home)
        self.assertTrue(status["present"])
        self.assertTrue(status["stale"])
        result = refresh_instruction_file("kiro", home=self.home)
        self.assertTrue(result["refreshed"])
        after = instruction_file_status("kiro", home=self.home)
        self.assertFalse(after["stale"])

    def test_current_file_is_left_alone(self):
        path = self._write_kiro(INSTRUCTIONS_TEMPLATE)
        before = path.read_text(encoding="utf-8")
        result = refresh_instruction_file("kiro", home=self.home)
        self.assertFalse(result["refreshed"])
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_missing_file_is_never_created(self):
        result = refresh_instruction_file("kiro", home=self.home)
        self.assertFalse(result["refreshed"])
        self.assertFalse((self.home / AGENT_INSTRUCTION_FILES["kiro"]).exists())

    def test_non_link_file_is_never_touched(self):
        path = self._write_kiro("# Someone else's steering, no Link section\n")
        before = path.read_text(encoding="utf-8")
        result = refresh_instruction_file("kiro", home=self.home)
        self.assertFalse(result["refreshed"])
        self.assertEqual(path.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
