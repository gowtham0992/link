import tempfile
import unittest
from pathlib import Path

from mcp_package.link_core.share import render_share_text, share_page_payload


class ShareCoreTests(unittest.TestCase):
    def make_wiki(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="link-share-core-"))
        wiki = root / "wiki"
        (wiki / "memories").mkdir(parents=True)
        (wiki / "concepts").mkdir(parents=True)
        (wiki / "memories" / "prefer-local-memory.md").write_text(
            "---\n"
            "type: memory\n"
            "title: Prefer local memory\n"
            "aliases: [local preference]\n"
            "memory_type: preference\n"
            "scope: user\n"
            "status: active\n"
            "date_captured: \"2026-05-25T00:00:00Z\"\n"
            "source: unit test\n"
            "review_status: reviewed\n"
            "---\n\n"
            "# Prefer local memory\n\n"
            "> **TLDR:** User prefers local agent memory.\n\n"
            "## Memory\n\nUser prefers local agent memory.\n\n"
            "## Source\n\nunit test\n",
            encoding="utf-8",
        )
        (wiki / "concepts" / "agent-memory.md").write_text(
            "---\n"
            "type: concept\n"
            "title: Agent memory\n"
            "aliases: [AI memory]\n"
            "---\n\n"
            "# Agent memory\n\n"
            "> **TLDR:** Durable context for AI agents.\n\n"
            "## Overview\n\nAgent memory helps agents recall project context.\n",
            encoding="utf-8",
        )
        return wiki

    def test_share_resolves_exact_memory_title(self):
        wiki = self.make_wiki()

        payload = share_page_payload(wiki, "Prefer local memory", port=3456)

        self.assertTrue(payload["found"])
        self.assertEqual(payload["resolution"], "exact")
        self.assertEqual(payload["page"]["name"], "prefer-local-memory")
        self.assertEqual(payload["url"], "http://127.0.0.1:3456/page/prefer-local-memory")
        self.assertIn("link serve", payload["serve_command_text"])

    def test_share_resolves_path_alias_and_search(self):
        wiki = self.make_wiki()

        path_payload = share_page_payload(wiki, "wiki/memories/prefer-local-memory.md")
        alias_payload = share_page_payload(wiki, "AI memory")
        search_payload = share_page_payload(wiki, "durable context")

        self.assertEqual(path_payload["page"]["name"], "prefer-local-memory")
        self.assertEqual(alias_payload["page"]["name"], "agent-memory")
        self.assertEqual(search_payload["resolution"], "search")
        self.assertEqual(search_payload["page"]["name"], "agent-memory")

    def test_share_missing_page_returns_candidates(self):
        wiki = self.make_wiki()

        payload = share_page_payload(wiki, "local")
        code, text = render_share_text(payload)

        self.assertTrue(payload["found"])
        self.assertEqual(code, 0)
        self.assertIn("Link share", text)

    def test_render_share_not_found(self):
        code, text = render_share_text({
            "found": False,
            "query": "missing",
            "error": "no matching Link page found",
            "candidates": [{"title": "Agent memory", "path": "wiki/concepts/agent-memory.md"}],
        })

        self.assertEqual(code, 1)
        self.assertIn("no matching page", text)
        self.assertIn("Closest matches", text)
