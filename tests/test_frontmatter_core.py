import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.frontmatter import (  # noqa: E402
    frontmatter_string,
    parse_frontmatter,
    update_frontmatter_fields,
)


class FrontmatterCoreTests(unittest.TestCase):
    def test_parse_frontmatter_preserves_colons_and_lists(self):
        meta, body = parse_frontmatter(
            "---\n"
            "title: \"My: Project\"\n"
            "tags: [memory, \"release:notes\", local-first]\n"
            "---\n\n"
            "# Body\n"
        )

        self.assertEqual(meta["title"], "My: Project")
        self.assertEqual(meta["tags"], ["memory", "release:notes", "local-first"])
        self.assertEqual(body, "\n# Body\n")

    def test_update_frontmatter_formats_lists_and_removes_fields(self):
        updated = update_frontmatter_fields(
            "---\n"
            "title: Old\n"
            "tags: [old]\n"
            "reviewed_at: \"2026-05-05T00:00:00Z\"\n"
            "---\n\n"
            "Body\n",
            {
                "tags": ["memory", "release:notes"],
                "review_status": "pending",
            },
            remove={"reviewed_at"},
        )

        self.assertIn("tags: [memory, \"release:notes\"]", updated)
        self.assertIn("review_status: pending", updated)
        self.assertNotIn("reviewed_at:", updated)
        self.assertTrue(updated.endswith("\nBody\n"))


if __name__ == "__main__":
    unittest.main()


class FrontmatterInjectionTests(unittest.TestCase):
    def test_frontmatter_string_neutralizes_newline_field_injection(self):
        # A newline in a quoted value would end the line and let the rest be
        # parsed as new frontmatter fields (e.g. an injected `remember:` key).
        out = frontmatter_string("recall\nremember: chained")
        self.assertNotIn("\n", out)
        out = frontmatter_string("---\ntitle: injected\n---\n# fake")
        self.assertNotIn("\n", out)

    def test_frontmatter_string_drops_control_characters(self):
        self.assertNotIn("\x00", frontmatter_string("a\x00b\x01c"))

    def test_frontmatter_string_keeps_ordinary_text(self):
        self.assertEqual(frontmatter_string('quotes "stay" escaped'), 'quotes \\"stay\\" escaped')
        self.assertEqual(frontmatter_string("café ☕ ok"), "café ☕ ok")
