"""Stale agent instruction files: detected, refreshed, never invented."""
import os
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
    migrate_codex_instructions,
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



class CodexInstructionsMoveTests(unittest.TestCase):
    """Codex reads ~/.codex/AGENTS.md; ~/AGENTS.md was never read by it (and Claude Code read it instead)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self._codex_home = os.environ.pop("CODEX_HOME", None)

    def tearDown(self):
        if self._codex_home is not None:
            os.environ["CODEX_HOME"] = self._codex_home
        self.temp.cleanup()

    def _claude_has_link(self):
        claude = self.home / ".claude" / "CLAUDE.md"
        claude.parent.mkdir(parents=True, exist_ok=True)
        claude.write_text("# Mine\n\n" + INSTRUCTIONS_TEMPLATE, encoding="utf-8")

    def test_only_links_section_moves_and_everything_after_it_stays(self):
        self._claude_has_link()
        old = self.home / "AGENTS.md"
        mine_after = "# Personal rules (not Link)\n- Never push to main.\n\n### Shell\n- Use zsh.\n"
        old.write_text("   indented first line\n\n" + OLD_ERA_SECTION + "\n" + mine_after, encoding="utf-8")
        preview = migrate_codex_instructions(self.home, write=False)
        self.assertTrue(preview["needed"])
        self.assertFalse(preview["moved"])
        self.assertTrue(migrate_codex_instructions(self.home)["moved"])
        moved = (self.home / ".codex" / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(find_link_section(moved).rstrip(), INSTRUCTIONS_TEMPLATE.rstrip(), "current template")
        rest = old.read_text(encoding="utf-8")
        self.assertTrue(rest.startswith("   indented first line"), "nothing of the person's is stripped")
        self.assertIn(mine_after, rest, "headings of any level after Link's section are the person's")
        self.assertIsNone(find_link_section(rest))
        self.assertFalse(migrate_codex_instructions(self.home)["moved"], "nothing left to move")

    def test_claude_code_keeps_its_copy_when_it_has_no_other(self):
        old = self.home / "AGENTS.md"
        old.write_text(INSTRUCTIONS_TEMPLATE, encoding="utf-8")
        result = migrate_codex_instructions(self.home)
        self.assertTrue(result["moved"])
        self.assertTrue(result["kept_for_claude_code"])
        self.assertIsNotNone(find_link_section(old.read_text(encoding="utf-8")), "Claude Code still reads it here")
        self.assertIsNotNone(find_link_section((self.home / ".codex" / "AGENTS.md").read_text(encoding="utf-8")))

    def test_a_file_that_held_only_links_section_is_removed(self):
        self._claude_has_link()
        (self.home / "AGENTS.md").write_text(INSTRUCTIONS_TEMPLATE, encoding="utf-8")
        codex = self.home / ".codex" / "AGENTS.md"
        codex.parent.mkdir()
        codex.write_text("# Codex house rules\n", encoding="utf-8")
        self.assertTrue(migrate_codex_instructions(self.home)["moved"])
        self.assertFalse((self.home / "AGENTS.md").exists())
        text = codex.read_text(encoding="utf-8")
        self.assertIn("# Codex house rules", text, "what was already there is kept")
        self.assertIsNotNone(find_link_section(text))

    def test_line_endings_bytes_and_permissions_are_kept(self):
        self._claude_has_link()
        old = self.home / "AGENTS.md"
        old.write_bytes(("# Mine\r\n\r\n" + OLD_ERA_SECTION.replace("\n", "\r\n") + "\r\n# After\r\nok\r\n").encode())
        os.chmod(old, 0o644)
        migrate_codex_instructions(self.home)
        self.assertEqual(old.read_bytes(), b"# Mine\r\n\r\n# After\r\nok\r\n")
        if os.name != "nt":  # Windows has no Unix permission bits
            self.assertEqual(old.stat().st_mode & 0o777, 0o644)
        latin1 = self.home / "AGENTS.md"
        latin1.write_bytes(b"caf\xe9\n\n" + OLD_ERA_SECTION.encode())
        result = migrate_codex_instructions(self.home)
        self.assertFalse(result["moved"])
        self.assertIn("left alone", result["error"])
        self.assertEqual(latin1.read_bytes(), b"caf\xe9\n\n" + OLD_ERA_SECTION.encode(), "never rewritten")

    def test_codex_home_is_honoured(self):
        self._claude_has_link()
        (self.home / "AGENTS.md").write_text(INSTRUCTIONS_TEMPLATE, encoding="utf-8")
        os.environ["CODEX_HOME"] = str(self.home / "elsewhere")
        try:
            result = migrate_codex_instructions(self.home)
        finally:
            del os.environ["CODEX_HOME"]
        self.assertEqual(result["to"], str(self.home / "elsewhere" / "AGENTS.md"))
        self.assertTrue((self.home / "elsewhere" / "AGENTS.md").exists())

    def test_a_home_without_links_section_is_left_alone(self):
        (self.home / "AGENTS.md").write_text("# Mine only\n", encoding="utf-8")
        self.assertFalse(migrate_codex_instructions(self.home).get("needed"))
        self.assertFalse((self.home / ".codex").exists())
        self.assertEqual(AGENT_INSTRUCTION_FILES["codex"], ".codex/AGENTS.md")

if __name__ == "__main__":
    unittest.main()