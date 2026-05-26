import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.obsidian import import_obsidian_vault, render_import_obsidian_text  # noqa: E402


class ObsidianCoreTests(unittest.TestCase):
    def make_vault(self) -> Path:
        vault = Path(tempfile.mkdtemp(prefix="link-obsidian-vault-"))
        (vault / "Projects").mkdir()
        (vault / ".obsidian").mkdir()
        (vault / "Projects" / "Plan.md").write_text("# Plan\n\nShip Link.\n", encoding="utf-8")
        (vault / "Daily.md").write_text("# Daily\n\nRemember the launch notes.\n", encoding="utf-8")
        (vault / ".obsidian" / "workspace.json").write_text("{}", encoding="utf-8")
        (vault / "image.png").write_bytes(b"not markdown")
        return vault

    def test_import_obsidian_vault_copies_markdown_notes(self):
        target = Path(tempfile.mkdtemp(prefix="link-obsidian-target-"))
        vault = self.make_vault()

        payload = import_obsidian_vault(target, vault)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["note_count"], 2)
        self.assertEqual(payload["imported_count"], 2)
        raw_prefix = target / str(payload["raw_prefix"])
        self.assertTrue((raw_prefix / "Daily.md").exists())
        self.assertTrue((raw_prefix / "Projects/Plan.md").exists())
        self.assertFalse((raw_prefix / ".obsidian/workspace.json").exists())
        self.assertIn("ingest raw/obsidian", payload["next_prompt"])

    def test_import_obsidian_vault_blocks_secret_notes(self):
        target = Path(tempfile.mkdtemp(prefix="link-obsidian-target-"))
        vault = self.make_vault()
        (vault / "Secrets.md").write_text("token sk-ant-" + "a" * 30, encoding="utf-8")

        payload = import_obsidian_vault(target, vault)
        code, text = render_import_obsidian_text(payload)

        self.assertEqual(payload["status"], "needs_attention")
        self.assertEqual(payload["blocked_secret_count"], 1)
        self.assertEqual(code, 1)
        self.assertIn("Secrets.md", text)
        self.assertFalse((target / str(payload["raw_prefix"]) / "Secrets.md").exists())

    def test_import_obsidian_vault_dry_run_does_not_write(self):
        target = Path(tempfile.mkdtemp(prefix="link-obsidian-target-"))
        vault = self.make_vault()

        payload = import_obsidian_vault(target, vault, dry_run=True)

        self.assertEqual(payload["imported_count"], 2)
        self.assertTrue(payload["dry_run"])
        self.assertFalse((target / "raw").exists())


if __name__ == "__main__":
    unittest.main()
