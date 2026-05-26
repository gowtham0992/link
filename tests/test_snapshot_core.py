import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.snapshot import export_snapshot, render_snapshot_text  # noqa: E402


def _write_page(path: Path, title: str, page_type: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join([
            "---",
            f"title: {title}",
            f"type: {page_type}",
            "tags: [test]",
            "---",
            "",
            f"# {title}",
            "",
            body,
            "",
        ]),
        encoding="utf-8",
    )


class SnapshotCoreTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="link-snapshot-test-"))
        self.wiki = self.root / "wiki"
        for name in ("concepts", "entities", "sources", "memories", "comparisons", "explorations"):
            (self.wiki / name).mkdir(parents=True, exist_ok=True)
        (self.wiki / "index.md").write_text("# Index\n\n- [[agent-memory]]\n", encoding="utf-8")
        (self.wiki / "log.md").write_text("# Log\n\n", encoding="utf-8")
        (self.wiki / "_backlinks.json").write_text('{"backlinks": {}, "forward": {}}\n', encoding="utf-8")
        _write_page(
            self.wiki / "concepts/agent-memory.md",
            "Agent memory",
            "concept",
            "> **TLDR:** Memory that agents can inspect.\n\nLinks to [[source-note]] and [[prefer-local-memory]].",
        )
        _write_page(
            self.wiki / "sources/source-note.md",
            "Source note",
            "source",
            "> **TLDR:** A source note.\n\n## Summary\n\nSource-backed context.\n\n## Raw Source\n\n`raw/source-note.md`",
        )
        _write_page(
            self.wiki / "memories/prefer-local-memory.md",
            "Prefer local memory",
            "memory",
            "> **TLDR:** User prefers local memory.\n\nPrivate preference.",
        )
        private_text = (self.wiki / "memories/prefer-local-memory.md").read_text(encoding="utf-8")
        (self.wiki / "memories/prefer-local-memory.md").write_text(
            private_text.replace("type: memory\n", "type: memory\nscope: user\nvisibility: private\n"),
            encoding="utf-8",
        )
        _write_page(
            self.wiki / "memories/team-release-plan.md",
            "Team release plan",
            "memory",
            "> **TLDR:** Team-visible release memory.\n\nShared release context.",
        )
        team_text = (self.wiki / "memories/team-release-plan.md").read_text(encoding="utf-8")
        (self.wiki / "memories/team-release-plan.md").write_text(
            team_text.replace("type: memory\n", "type: memory\nscope: project\nvisibility: team\n"),
            encoding="utf-8",
        )

    def test_export_snapshot_excludes_memories_and_raw_by_default(self):
        output = self.root / "snapshot"

        payload = export_snapshot(self.wiki, output)

        self.assertTrue(payload["created"])
        self.assertEqual(payload["schema"], "link-snapshot-v1")
        self.assertFalse(payload["include_memories"])
        self.assertEqual(payload["page_count"], 2)
        self.assertTrue((output / "index.html").exists())
        self.assertTrue((output / "pages/agent-memory.html").exists())
        self.assertFalse((output / "pages/prefer-local-memory.html").exists())
        self.assertFalse((output / "raw").exists())
        page_html = (output / "pages/agent-memory.html").read_text(encoding="utf-8")
        self.assertIn('href="source-note.html"', page_html)
        self.assertNotIn('href="pages/source-note.html"', page_html)
        manifest = json.loads((output / "snapshot.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["page_count"], 2)
        self.assertNotIn("wiki", manifest)
        self.assertNotIn("output", manifest)
        self.assertNotIn(str(self.root), json.dumps(manifest))

    def test_export_snapshot_includes_only_non_private_memories_intentionally(self):
        output = self.root / "snapshot"

        payload = export_snapshot(self.wiki, output, include_memories=True)

        self.assertTrue(payload["created"])
        self.assertTrue(payload["include_memories"])
        self.assertEqual(payload["page_count"], 3)
        self.assertFalse((output / "pages/prefer-local-memory.html").exists())
        self.assertTrue((output / "pages/team-release-plan.html").exists())
        manifest = json.loads((output / "snapshot.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["excluded_counts"]["private_memories"], 1)

    def test_export_snapshot_can_include_private_memories_with_explicit_flag(self):
        output = self.root / "snapshot"

        payload = export_snapshot(
            self.wiki,
            output,
            include_memories=True,
            include_private_memories=True,
        )

        self.assertTrue(payload["created"])
        self.assertTrue(payload["include_memories"])
        self.assertTrue(payload["include_private_memories"])
        self.assertEqual(payload["page_count"], 4)
        self.assertTrue((output / "pages/prefer-local-memory.html").exists())

    def test_export_snapshot_blocks_secret_looking_wiki_values(self):
        fake_key = "AKIA" + ("A" * 16)
        _write_page(
            self.wiki / "concepts/leak.md",
            "Leak",
            "concept",
            f"> **TLDR:** Leaked key.\n\nkey = {fake_key}",
        )

        payload = export_snapshot(self.wiki, self.root / "snapshot")

        self.assertFalse(payload["created"])
        self.assertIn("secret-looking", payload["error"])
        self.assertTrue(payload["sensitive_values"])
        code, text = render_snapshot_text(payload)
        self.assertEqual(code, 1)
        self.assertIn("Secret-looking wiki contents", text)

    def test_export_snapshot_refuses_non_empty_output_without_force(self):
        output = self.root / "snapshot"
        output.mkdir()
        (output / "old.html").write_text("old", encoding="utf-8")

        blocked = export_snapshot(self.wiki, output)
        created = export_snapshot(self.wiki, output, force=True)

        self.assertFalse(blocked["created"])
        self.assertIn("not empty", blocked["error"])
        self.assertTrue(created["created"])
        self.assertFalse((output / "old.html").exists())


if __name__ == "__main__":
    unittest.main()
