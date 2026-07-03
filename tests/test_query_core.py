import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.memory import memory_records  # noqa: E402
from link_core.query import normalize_budget, query_link  # noqa: E402
from link_core.wiki import build_backlinks, build_wiki_cache  # noqa: E402


def write_page(wiki: Path, rel: str, text: str) -> None:
    path = wiki / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class QueryCoreTests(unittest.TestCase):
    def test_normalize_budget_accepts_only_bounded_known_values(self):
        self.assertEqual(normalize_budget("micro"), "micro")
        self.assertEqual(normalize_budget("capsule"), "micro")
        self.assertEqual(normalize_budget(" SMALL "), "small")
        self.assertEqual(normalize_budget("large"), "large")
        self.assertEqual(normalize_budget("x" * 1000), "medium")
        self.assertEqual(normalize_budget(123), "medium")
        self.assertEqual(normalize_budget(None), "medium")

    def test_query_link_returns_budgeted_memory_and_graph_context(self):
        root = Path(tempfile.mkdtemp(prefix="link-query-core-"))
        wiki = root / "wiki"
        wiki.mkdir()
        write_page(wiki, "index.md", "# Index\n")
        write_page(wiki, "log.md", "# Log\n")
        write_page(
            wiki,
            "concepts/agent-memory.md",
            "---\n"
            "type: concept\n"
            "title: Agent memory\n"
            "tags: [agents, memory]\n"
            "source_count: 2\n"
            "date_updated: \"2026-05-06\"\n"
            "---\n\n"
            "# Agent memory\n\n"
            "> **TLDR:** Agents use durable memory to preserve context.\n\n"
            "## Overview\n\n"
            "Agent memory links to [[retrieval-augmented-generation]] for source-backed recall.\n",
        )
        write_page(
            wiki,
            "concepts/retrieval-augmented-generation.md",
            "---\n"
            "type: concept\n"
            "title: Retrieval-augmented generation\n"
            "---\n\n"
            "# Retrieval-augmented generation\n\n"
            "> **TLDR:** Retrieval adds external context before generation.\n",
        )
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
            "tags: [memory]\n"
            "---\n\n"
            "# Prefer local memory\n\n"
            "> **TLDR:** User prefers local agent memory over cloud memory.\n\n"
            "## Memory\n\nUser prefers local agent memory over cloud memory.\n",
        )
        (wiki / "_backlinks.json").write_text(json.dumps(build_backlinks(wiki)), encoding="utf-8")

        payload = query_link(
            wiki,
            "agent memory",
            build_wiki_cache(wiki),
            memory_records(wiki),
            budget="small",
        )

        self.assertTrue(payload["found"])
        self.assertEqual(payload["budget"], "small")
        self.assertEqual(payload["strategy"]["mode"], "memory+wiki")
        self.assertEqual(payload["memory"]["items"][0]["name"], "prefer-local-memory")
        self.assertEqual(payload["memory"]["items"][0]["recall"]["state"], "ready")
        self.assertEqual(payload["memory"]["items"][0]["provenance"]["path"], "wiki/memories/prefer-local-memory.md")
        self.assertEqual(payload["memory"]["items"][0]["provenance"]["source"], "unit-test")
        self.assertEqual(payload["memory"]["items"][0]["provenance"]["date_captured"], "2026-05-05T00:00:00Z")
        self.assertEqual(payload["memory"]["items"][0]["provenance"]["review_status"], "reviewed")
        self.assertEqual(payload["memory"]["review"]["items"], [])
        self.assertEqual(payload["wiki"]["primary"], "agent-memory")
        self.assertEqual(payload["wiki"]["pages"][0]["provenance"]["path"], "wiki/concepts/agent-memory.md")
        self.assertEqual(payload["wiki"]["pages"][0]["provenance"]["source_count"], "2")
        self.assertEqual(payload["wiki"]["pages"][0]["provenance"]["date_updated"], "2026-05-06")
        self.assertEqual(payload["wiki"]["search_results"][0]["provenance"]["path"], "wiki/concepts/agent-memory.md")
        self.assertLessEqual(len(payload["context_packet"]), 4)
        self.assertIn("why_selected", payload["context_packet"][0])
        self.assertIn("provenance", payload["context_packet"][0])
        self.assertIn("recall_capsule", payload)
        self.assertGreater(payload["recall_capsule"]["estimated_tokens"], 0)
        self.assertIn("hybrid", payload["recall_capsule"]["ranking"])
        self.assertIn("do not read the whole wiki", payload["agent_guidance"][0])
        self.assertIn("provenance.path/source/date", payload["agent_guidance"][2])
        self.assertIn("budget_report", payload)
        self.assertGreater(payload["budget_report"]["context_packet"]["estimated_chars"], 0)
        self.assertGreater(payload["budget_report"]["context_packet"]["estimated_tokens"], 0)
        self.assertEqual(payload["follow_up"][0]["tool"], "admin")
        self.assertEqual(payload["follow_up"][0]["arguments"], {"action": "context", "topic": "agent-memory"})

    def test_query_link_flags_weak_only_memory_matches(self):
        root = Path(tempfile.mkdtemp(prefix="link-query-weak-"))
        wiki = root / "wiki"
        wiki.mkdir()
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
            "tags: [memory]\n"
            "---\n\n"
            "# Prefer local memory\n\n"
            "> **TLDR:** The wiki is the inspectable storage format.\n\n"
            "## Memory\n\nThe wiki is the inspectable storage format.\n",
        )
        (wiki / "_backlinks.json").write_text(json.dumps(build_backlinks(wiki)), encoding="utf-8")

        payload = query_link(
            wiki,
            "how should I format my responses",
            build_wiki_cache(wiki),
            memory_records(wiki),
            budget="small",
        )

        memories = payload["memory"]["items"]
        self.assertTrue(memories)
        self.assertTrue(all(item["confidence"] == "weak" for item in memories))
        self.assertTrue(
            any("Memory matches are weak" in line for line in payload["agent_guidance"])
        )

    def test_micro_budget_returns_tiny_recall_capsule(self):
        root = Path(tempfile.mkdtemp(prefix="link-query-core-"))
        wiki = root / "wiki"
        wiki.mkdir()
        write_page(wiki, "index.md", "# Index\n")
        write_page(wiki, "log.md", "# Log\n")
        write_page(
            wiki,
            "concepts/login-flow.md",
            "---\n"
            "type: concept\n"
            "title: Login flow\n"
            "aliases: [auth setup]\n"
            "tags: [authentication]\n"
            "---\n\n"
            "# Login flow\n\n"
            "> **TLDR:** OAuth login setup for the app.\n\n"
            "## Overview\n\nAuthentication setup uses OAuth login configuration.\n",
        )
        write_page(
            wiki,
            "memories/prefer-oauth-login.md",
            "---\n"
            "type: memory\n"
            "title: Prefer OAuth login\n"
            "memory_type: preference\n"
            "scope: project\n"
            "project: link\n"
            "status: active\n"
            "date_captured: \"2026-05-05T00:00:00Z\"\n"
            "source: wiki/concepts/login-flow.md\n"
            "review_status: reviewed\n"
            "tags: [authentication]\n"
            "---\n\n"
            "# Prefer OAuth login\n\n"
            "> **TLDR:** User prefers OAuth login setup.\n\n"
            "## Memory\n\nUser prefers OAuth login setup for authentication work.\n",
        )
        (wiki / "_backlinks.json").write_text(json.dumps(build_backlinks(wiki)), encoding="utf-8")

        payload = query_link(
            wiki,
            "auth setup",
            build_wiki_cache(wiki),
            memory_records(wiki),
            budget="micro",
            project="link",
        )

        self.assertEqual(payload["budget"], "micro")
        self.assertLessEqual(payload["budget_report"]["memories"]["selected"], 1)
        self.assertLess(payload["recall_capsule"]["estimated_tokens"], 700)
        self.assertEqual(payload["recall_capsule"]["items"][0]["name"], "prefer-oauth-login")
        self.assertIn("rank_signals", payload["recall_capsule"]["items"][0])

    def test_query_link_reports_budget_overflow_and_followups(self):
        root = Path(tempfile.mkdtemp(prefix="link-query-core-"))
        wiki = root / "wiki"
        wiki.mkdir()
        write_page(wiki, "index.md", "# Index\n")
        write_page(wiki, "log.md", "# Log\n")
        for index in range(6):
            write_page(
                wiki,
                f"concepts/agent-memory-{index}.md",
                "---\n"
                "type: concept\n"
                f"title: Agent memory {index}\n"
                "tags: [agents, memory]\n"
                "---\n\n"
                f"# Agent memory {index}\n\n"
                "> **TLDR:** Agents use durable memory.\n\n"
                "## Overview\n\n"
                "Agent memory supports source-backed local recall.\n",
            )
        for index in range(4):
            write_page(
                wiki,
                f"memories/prefer-local-memory-{index}.md",
                "---\n"
                "type: memory\n"
                f"title: Prefer local memory {index}\n"
                "memory_type: preference\n"
                "scope: user\n"
                "status: active\n"
                "date_captured: \"2026-05-05T00:00:00Z\"\n"
                "source: unit-test\n"
                "review_status: reviewed\n"
                "tags: [memory]\n"
                "---\n\n"
                f"# Prefer local memory {index}\n\n"
                "> **TLDR:** User prefers local agent memory.\n\n"
                "## Memory\n\nUser prefers local agent memory.\n",
            )
        (wiki / "_backlinks.json").write_text(json.dumps(build_backlinks(wiki)), encoding="utf-8")

        payload = query_link(
            wiki,
            "agent memory",
            build_wiki_cache(wiki),
            memory_records(wiki),
            budget="small",
        )

        self.assertTrue(payload["budget_report"]["memories"]["has_more"])
        self.assertTrue(payload["budget_report"]["wiki_search"]["has_more"])
        self.assertLessEqual(payload["budget_report"]["memories"]["selected"], 3)
        self.assertLess(payload["budget_report"]["context_packet"]["estimated_tokens"], 2000)
        self.assertEqual(payload["follow_up"][0]["tool"], "recall")
        self.assertEqual(payload["follow_up"][0]["arguments"]["budget"], "medium")
        self.assertIn("budget-limited", payload["agent_guidance"][1])

    def test_large_budget_followup_does_not_repeat_large_budget(self):
        root = Path(tempfile.mkdtemp(prefix="link-query-core-"))
        wiki = root / "wiki"
        wiki.mkdir()
        write_page(wiki, "index.md", "# Index\n")
        write_page(wiki, "log.md", "# Log\n")
        for index in range(12):
            write_page(
                wiki,
                f"concepts/agent-memory-{index}.md",
                "---\n"
                "type: concept\n"
                f"title: Agent memory {index}\n"
                "tags: [agents, memory]\n"
                "---\n\n"
                f"# Agent memory {index}\n\n"
                "> **TLDR:** Agents use durable memory.\n\n"
                "## Overview\n\nAgent memory supports source-backed local recall.\n",
            )
        (wiki / "_backlinks.json").write_text(json.dumps(build_backlinks(wiki)), encoding="utf-8")

        payload = query_link(
            wiki,
            "agent memory",
            build_wiki_cache(wiki),
            memory_records(wiki),
            budget="large",
        )

        self.assertTrue(payload["budget_report"]["wiki_search"]["has_more"])
        self.assertFalse(
            any(
                action["tool"] == "recall" and action.get("arguments", {}).get("budget") == "large"
                for action in payload["follow_up"]
            )
        )
        self.assertEqual(payload["follow_up"][0]["tool"], "admin")
        self.assertEqual(payload["follow_up"][0]["arguments"], {"action": "context", "topic": "agent-memory-0"})


if __name__ == "__main__":
    unittest.main()
