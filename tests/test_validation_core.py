import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.validation import validate_wiki  # noqa: E402
from link_core.wiki import build_backlinks  # noqa: E402


def write_page(wiki: Path, rel: str, text: str) -> None:
    path = wiki / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class ValidationCoreTests(unittest.TestCase):
    def make_wiki(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="link-validation-core-"))
        wiki = root / "wiki"
        for dirname in ("sources", "concepts", "entities", "memories", "comparisons", "explorations"):
            (wiki / dirname).mkdir(parents=True, exist_ok=True)
        write_page(wiki, "index.md", "# Index\n")
        write_page(wiki, "log.md", "# Log\n")
        return wiki

    def test_validate_wiki_accepts_well_formed_pages(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "sources/example-source.md",
            "---\ntype: source\ntitle: Example Source\n---\n\n"
            "# Example Source\n\n"
            "> **TLDR:** A valid source page.\n\n"
            "## Summary\n\nUseful source.\n\n"
            "## Raw Source\n\n`raw/example.md`\n",
        )
        write_page(
            wiki,
            "concepts/example-concept.md",
            "---\ntype: concept\ntitle: Example Concept\n---\n\n"
            "# Example Concept\n\n"
            "> **TLDR:** A valid concept page.\n\n"
            "## Overview\n\nConcept overview cites [[example-source]].\n\n"
            "## Sources\n\n- [[example-source]]\n",
        )
        (wiki / "_backlinks.json").write_text(json.dumps(build_backlinks(wiki, body_only=False)), encoding="utf-8")

        read_counts: dict[str, int] = {}
        original_read_text = Path.read_text
        resolved_wiki = wiki.resolve()

        def counting_read_text(path: Path, *args, **kwargs):
            if path.suffix == ".md":
                rel = path.relative_to(resolved_wiki).as_posix()
                read_counts[rel] = read_counts.get(rel, 0) + 1
            return original_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", counting_read_text):
            payload = validate_wiki(wiki)

        self.assertTrue(payload["passed"])
        self.assertEqual(payload["error_count"], 0)
        self.assertEqual(
            read_counts,
            {
                "concepts/example-concept.md": 1,
                "index.md": 1,
                "log.md": 1,
                "sources/example-source.md": 1,
            },
        )

    def test_validate_wiki_rejects_malformed_agent_pages(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/bad-page.md",
            "---\ntype: source\n---\n\n"
            "# Bad Page\n\n"
            "Mentions [[missing-page]].\n",
        )
        (wiki / "_backlinks.json").write_text("{}", encoding="utf-8")

        payload = validate_wiki(wiki)
        codes = {finding["code"] for finding in payload["findings"]}

        self.assertFalse(payload["passed"])
        self.assertIn("type_directory_mismatch", codes)
        self.assertIn("missing_frontmatter_field", codes)
        self.assertIn("missing_required_section", codes)
        self.assertIn("dead_wikilink", codes)
        self.assertIn("stale_backlinks", codes)

    def test_validate_wiki_rejects_invalid_memory_review_after(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "memories/bad-review-date.md",
            "---\n"
            "type: memory\n"
            "title: Bad Review Date\n"
            "memory_type: preference\n"
            "scope: user\n"
            "status: active\n"
            "source: unit test\n"
            "review_status: reviewed\n"
            "review_after: tomorrow\n"
            "---\n\n"
            "# Bad Review Date\n\n"
            "> **TLDR:** A memory with a bad review date.\n\n"
            "## Memory\n\nReview later.\n\n"
            "## Source\n\nunit test\n",
        )
        (wiki / "_backlinks.json").write_text(json.dumps(build_backlinks(wiki, body_only=False)), encoding="utf-8")

        payload = validate_wiki(wiki)

        self.assertFalse(payload["passed"])
        self.assertIn("invalid_review_after", {finding["code"] for finding in payload["findings"]})

    def test_validate_wiki_rejects_invalid_memory_expires_at(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "memories/bad-expiry-date.md",
            "---\n"
            "type: memory\n"
            "title: Bad Expiry Date\n"
            "memory_type: preference\n"
            "scope: user\n"
            "status: active\n"
            "source: unit test\n"
            "review_status: reviewed\n"
            "expires_at: someday\n"
            "---\n\n"
            "# Bad Expiry Date\n\n"
            "> **TLDR:** A memory with a bad expiry date.\n\n"
            "## Memory\n\nExpire later.\n\n"
            "## Source\n\nunit test\n",
        )
        (wiki / "_backlinks.json").write_text(json.dumps(build_backlinks(wiki, body_only=False)), encoding="utf-8")

        payload = validate_wiki(wiki)

        self.assertFalse(payload["passed"])
        self.assertIn("invalid_expires_at", {finding["code"] for finding in payload["findings"]})

    def test_validate_wiki_reports_unreadable_pages(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/locked-page.md",
            "---\ntype: concept\ntitle: Locked Page\n---\n\n"
            "# Locked Page\n\n"
            "> **TLDR:** A locked page.\n\n"
            "## Overview\n\nCannot read this.\n\n"
            "## Sources\n\n- [[locked-page]]\n",
        )
        (wiki / "_backlinks.json").write_text(json.dumps(build_backlinks(wiki, body_only=False)), encoding="utf-8")
        original_read_text = Path.read_text

        def flaky_read_text(path: Path, *args, **kwargs):
            if path.name == "locked-page.md":
                raise OSError("permission denied")
            return original_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", flaky_read_text):
            payload = validate_wiki(wiki)

        self.assertFalse(payload["passed"])
        self.assertIn("unreadable_page", {finding["code"] for finding in payload["findings"]})
        self.assertNotIn("stale_backlinks", {finding["code"] for finding in payload["findings"]})

    def test_validate_wiki_rejects_secret_values_without_echoing_them(self):
        wiki = self.make_wiki()
        fake_key = "sk-" + ("A" * 24)
        write_page(
            wiki,
            "sources/leaky-source.md",
            "---\ntype: source\ntitle: Leaky Source\n---\n\n"
            "# Leaky Source\n\n"
            "> **TLDR:** A source with a secret-looking value.\n\n"
            "## Summary\n\nDo not keep this token here.\n\n"
            f"{fake_key}\n\n"
            "## Raw Source\n\n`raw/leaky-source.md`\n",
        )
        (wiki / "_backlinks.json").write_text(json.dumps(build_backlinks(wiki, body_only=False)), encoding="utf-8")

        payload = validate_wiki(wiki)
        secret_findings = [finding for finding in payload["findings"] if finding["code"] == "secret_value"]

        self.assertFalse(payload["passed"])
        self.assertEqual(len(secret_findings), 1)
        self.assertEqual(secret_findings[0]["path"], "sources/leaky-source.md")
        self.assertIn("OpenAI API key", secret_findings[0]["message"])
        self.assertNotIn(fake_key, secret_findings[0]["message"])


if __name__ == "__main__":
    unittest.main()
