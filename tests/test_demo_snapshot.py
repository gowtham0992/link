import importlib.util
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import serve


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("link_cli", ROOT / "link.py")
link_cli = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(link_cli)


EXPECTED_RAW_FILES = {
    "agent-memory-session.md",
    "local-release-notes.md",
    "transformer-reading-notes.md",
}

EXPECTED_WIKI_PAGES = {
    "agent-memory",
    "agent-memory-session",
    "index",
    "knowledge-graph",
    "link",
    "local-first-software",
    "local-release-notes",
    "log",
    "keep-agent-memory-in-local-markdown",
    "keep-answers-short-and-cite-wiki-sources",
    "local-viewer-runs-on-port-3000",
    "prefer-local-personal-memory",
    "retrieval-augmented-generation",
    "transformer-reading-notes",
    "transformers",
    "why-link-helps-agents",
}

EXPECTED_KEY_EDGES = {
    ("agent-memory", "agent-memory-session"),
    ("agent-memory", "link"),
    ("agent-memory", "retrieval-augmented-generation"),
    ("agent-memory", "local-first-software"),
    ("knowledge-graph", "agent-memory"),
    ("link", "knowledge-graph"),
    ("link", "retrieval-augmented-generation"),
    ("prefer-local-personal-memory", "agent-memory"),
    ("prefer-local-personal-memory", "link"),
    ("retrieval-augmented-generation", "transformers"),
    ("why-link-helps-agents", "agent-memory"),
}


def create_demo_quiet(target: Path) -> None:
    with redirect_stdout(StringIO()):
        link_cli.create_demo(target, force=False)


def reset_serve_wiki(wiki_dir: Path) -> None:
    close = getattr(getattr(serve, "_fts_index", None), "close", None)
    if callable(close):
        close()
    serve.WIKI_DIR = wiki_dir
    serve.RAW_DIR = wiki_dir.parent / "raw"
    serve._pages_cache = None
    serve._pages_cache_mtime = 0.0
    serve._page_index = {}
    serve._fulltext_index = {}
    serve._normalized_fulltext_index = {}
    serve._text_words_index = {}
    serve._meta_words_index = {}
    serve._snippet_index = {}
    serve._token_index = {}
    serve._page_map = {}
    serve._meta_token_index = {}
    serve._fts_index = None
    serve._search_backend = "token-index"


class DemoSnapshotTests(unittest.TestCase):
    def make_demo(self) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="link-demo-snapshot-"))
        target = tmp / "demo"
        create_demo_quiet(target)
        return target

    def test_demo_file_snapshot_and_health(self):
        target = self.make_demo()

        raw_files = {path.name for path in (target / "raw").iterdir() if path.is_file() and not path.name.startswith(".")}
        wiki_pages = {path.stem for path in (target / "wiki").rglob("*.md") if not path.name.startswith(".")}

        self.assertEqual(raw_files, EXPECTED_RAW_FILES)
        self.assertEqual(wiki_pages, EXPECTED_WIKI_PAGES)
        self.assertTrue((target / "logo.svg").exists())
        self.assertTrue((target / "wiki/memories/prefer-local-personal-memory.md").exists())
        self.assertTrue((target / "wiki/explorations/why-link-helps-agents.md").exists())

        memory = (target / "wiki/memories/prefer-local-personal-memory.md").read_text(encoding="utf-8")
        self.assertIn("review_status: pending", memory)
        self.assertIn("## Source", memory)
        self.assertIn("[[link]]", memory)

        log_text = (target / "wiki/log.md").read_text(encoding="utf-8")
        self.assertIn("Created: memories/prefer-local-personal-memory.md", log_text)
        self.assertIn("Created: explorations/why-link-helps-agents.md", log_text)

        raw_refs = set()
        for source_page in (target / "wiki/sources").glob("*.md"):
            source_text = source_page.read_text(encoding="utf-8")
            page_refs = set(re.findall(r"`(raw/[^`]+)`", source_text))
            self.assertTrue(page_refs, source_page)
            raw_refs.update(page_refs)
        self.assertEqual(raw_refs, {f"raw/{name}" for name in EXPECTED_RAW_FILES})

        status = link_cli._collect_ingest_status(target)
        self.assertEqual(status["raw_count"], 3)
        self.assertEqual(status["source_page_count"], 3)
        self.assertEqual(status["pending_count"], 0)
        self.assertEqual(status["backlinks_status"], "current")

        with redirect_stdout(StringIO()):
            self.assertEqual(link_cli.doctor(target), 0)

    def test_demo_graph_snapshot(self):
        target = self.make_demo()
        reset_serve_wiki(target / "wiki")

        graph = serve._get_graph_data()
        node_ids = {node["id"] for node in graph["nodes"]}
        edges = {(edge["source"], edge["target"]) for edge in graph["edges"]}

        self.assertEqual(node_ids, EXPECTED_WIKI_PAGES)
        self.assertEqual(len(graph["nodes"]), 16)
        self.assertEqual(len(graph["edges"]), 64)
        self.assertEqual(len(edges), len(graph["edges"]))
        self.assertTrue(EXPECTED_KEY_EDGES.issubset(edges))

    def test_demo_home_shows_memories(self):
        target = self.make_demo()
        reset_serve_wiki(target / "wiki")

        html = serve._render_home()

        self.assertIn('<span class="label">memories</span>', html)
        self.assertIn("Prefer local personal memory", html)

    def test_demo_search_matches_hyphenated_pages_with_natural_query(self):
        target = self.make_demo()
        reset_serve_wiki(target / "wiki")

        results = serve._search_pages("local first software")
        context = serve._get_context("local first software")

        self.assertEqual(results[0]["name"], "local-first-software")
        self.assertTrue(context["found"])
        self.assertEqual(context["primary"], "local-first-software")

    def test_demo_profile_snapshot(self):
        target = self.make_demo()
        reset_serve_wiki(target / "wiki")

        profile = serve._memory_profile()
        html = serve._render_profile()

        self.assertEqual(profile["memory_count"], 4)
        self.assertEqual(profile["active_count"], 4)
        self.assertEqual(profile["review_count"], 1)
        self.assertEqual(profile["by_type"]["preference"], 2)
        self.assertEqual(profile["recent"][0]["name"], "prefer-local-personal-memory")
        self.assertIn("Memory Profile", html)
        self.assertIn("Prefer local personal memory", html)

    def test_demo_inbox_snapshot(self):
        target = self.make_demo()
        reset_serve_wiki(target / "wiki")

        inbox = serve._memory_inbox()
        html = serve._render_inbox()

        self.assertEqual(inbox["review_count"], 1)
        self.assertEqual(inbox["counts_by_severity"]["medium"], 1)
        self.assertEqual(inbox["items"][0]["name"], "prefer-local-personal-memory")
        self.assertEqual(inbox["items"][0]["issues"][0]["code"], "pending_review")
        self.assertIn("Memory Review Inbox", html)
        self.assertIn("pending_review", html)

    def test_demo_memory_dashboard_snapshot(self):
        target = self.make_demo()
        reset_serve_wiki(target / "wiki")

        dashboard = serve._memory_dashboard()
        html = serve._render_memory_dashboard()

        self.assertEqual(dashboard["memory_count"], 4)
        self.assertEqual(dashboard["active_count"], 4)
        self.assertEqual(dashboard["review_count"], 1)
        self.assertEqual(dashboard["next_actions"][0]["label"], "Review pending memories")
        self.assertEqual(dashboard["review"][0]["name"], "prefer-local-personal-memory")
        self.assertEqual(dashboard["review"][0]["actions"][0]["label"], "Review")
        self.assertIn("Memory Dashboard", html)
        self.assertIn("Next actions", html)
        self.assertIn("Review needed", html)
        self.assertIn("Prefer local personal memory", html)
        self.assertIn("review-memory", html)
        self.assertIn("update-memory", html)
        self.assertIn("archive-memory", html)

    def test_demo_memory_dashboard_shows_recent_updates(self):
        target = self.make_demo()
        with redirect_stdout(StringIO()):
            link_cli.update_memory(
                target,
                "prefer-local-personal-memory",
                "Also prefer checking the web memory dashboard for review status.",
                source="snapshot test",
            )
        reset_serve_wiki(target / "wiki")

        dashboard = serve._memory_dashboard()
        html = serve._render_memory_dashboard()

        self.assertEqual(dashboard["updated_count"], 1)
        self.assertEqual(dashboard["recent_updates"][0]["name"], "prefer-local-personal-memory")
        self.assertEqual(dashboard["recent_updates"][0]["update_count"], "1")
        self.assertEqual(dashboard["next_actions"][0]["label"], "Review pending memories")
        self.assertEqual(dashboard["next_actions"][1]["label"], "Audit recent memory updates")
        self.assertIn("Recent updates", html)
        self.assertIn("snapshot test", dashboard["recent_updates"][0]["last_update_source"])

    def test_demo_explain_memory_snapshot(self):
        target = self.make_demo()
        reset_serve_wiki(target / "wiki")

        explanation = serve._memory_explanation("prefer-local-personal-memory")
        html = serve._render_explain_memory("prefer-local-personal-memory")

        self.assertTrue(explanation["found"])
        self.assertEqual(explanation["memory"]["name"], "prefer-local-personal-memory")
        self.assertEqual(explanation["provenance"]["source"], "demo")
        self.assertEqual(explanation["recall"]["state"], "needs_review")
        self.assertIn("agent-memory", explanation["graph"]["forward"])
        self.assertIn("Explain: Prefer local personal memory", html)
        self.assertIn("pending_review", html)

    def test_demo_profile_separates_archived_memories(self):
        target = self.make_demo()
        with redirect_stdout(StringIO()):
            link_cli.archive_memory(target, "prefer-local-personal-memory", reason="snapshot test")
        reset_serve_wiki(target / "wiki")

        profile = serve._memory_profile()
        html = serve._render_profile()

        self.assertEqual(profile["memory_count"], 4)
        self.assertEqual(profile["active_count"], 3)
        self.assertEqual(profile["review_count"], 0)
        self.assertEqual(profile["by_status"]["archived"], 1)
        recent_names = {memory["name"] for memory in profile["recent"]}
        self.assertNotIn("prefer-local-personal-memory", recent_names)
        self.assertEqual(profile["archived"][0]["name"], "prefer-local-personal-memory")
        self.assertIn("Archived memories", html)
        self.assertIn("Prefer local personal memory", html)

    def test_demo_context_snapshot(self):
        target = self.make_demo()
        reset_serve_wiki(target / "wiki")

        ctx = serve._get_context("agent memory")
        page_names = [page["name"] for page in ctx["pages"]]
        relationships = {page["name"]: page["relationship"] for page in ctx["pages"]}

        self.assertTrue(ctx["found"])
        self.assertEqual(ctx["primary"], "agent-memory")
        self.assertEqual(ctx["inbound_count"], 10)
        self.assertEqual(ctx["forward_count"], 5)
        self.assertEqual(page_names[0], "agent-memory")
        self.assertIn("link", page_names)
        self.assertIn("agent-memory-session", page_names)
        self.assertIn("retrieval-augmented-generation", page_names)
        self.assertEqual(relationships["agent-memory"], "primary")
        self.assertEqual(relationships["link"], "inbound")


if __name__ == "__main__":
    unittest.main()
