import unittest

from mcp_package.link_core.cli_query import (
    render_graph_summary_text,
    render_query_text,
)


class CliQueryCoreTests(unittest.TestCase):
    def test_render_query_not_found(self):
        code, text = render_query_text({"found": False}, query_text="missing")

        self.assertEqual(code, 0)
        self.assertIn("No Link context found for: missing", text)
        self.assertIn("Next:", text)
        self.assertIn("ingest the new raw Link files", text)
        self.assertIn("Run: lnk ingest-status", text)
        self.assertIn("Then rerun: lnk query missing", text)

    def test_render_query_not_found_can_include_explicit_target(self):
        code, text = render_query_text({"found": False}, query_text="missing topic", command_target="/tmp/Link Demo")

        self.assertEqual(code, 0)
        self.assertIn("Run: lnk ingest-status", text)
        self.assertIn("Then rerun: lnk query", text)
        self.assertIn("missing topic", text)
        self.assertIn("/tmp/Link Demo", text)

    def test_render_query_error(self):
        code, text = render_query_text({"found": False, "error": "cache failed"}, query_text="missing")

        self.assertEqual(code, 1)
        self.assertIn("Error: cache failed", text)

    def test_render_query_packet(self):
        code, text = render_query_text({
            "found": True,
            "query": "agent memory",
            "project": "link",
            "budget": "small",
            "strategy": {"mode": "query"},
            "memory": {
                "count": 1,
                "items": [{
                    "title": "Prefer local memory",
                    "memory_type": "preference",
                    "scope": "user",
                    "summary": "Use local memory.",
                    "recall": {"state": "ready"},
                    "why_selected": "Matched memory.",
                }],
            },
            "wiki": {
                "primary": "agent-memory",
                "pages": [{
                    "relationship": "primary",
                    "title": "Agent memory",
                    "type": "concept",
                    "content": "Agent memory keeps context source backed.",
                    "why_selected": "Title match.",
                }],
            },
            "agent_guidance": ["Use memory_brief before work."],
        }, query_text="agent memory")

        self.assertEqual(code, 0)
        self.assertIn("Link context packet: agent memory", text)
        self.assertIn("Project: link", text)
        self.assertIn("Memory (1)", text)
        self.assertIn("Recall: ready · Matched memory.", text)
        self.assertIn("Wiki (1 pages · primary: agent-memory)", text)
        self.assertIn("Agent guidance", text)

    def test_render_graph_summary(self):
        code, text = render_graph_summary_text({
            "mode": "topic",
            "search_backend": "sqlite-fts",
            "node_count": 100,
            "edge_count": 200,
            "returned_nodes": 1,
            "returned_edges": 0,
            "truncated": True,
            "nodes": [{
                "title": "Agent memory",
                "id": "agent-memory",
                "degree": 5,
                "summary": "Durable context.",
                "why_selected": "Topic match.",
            }],
            "follow_up": [{
                "tool": "get_context",
                "arguments": {"topic": "agent memory"},
                "when": "need full context",
            }],
        }, topic="agent memory")

        self.assertEqual(code, 0)
        self.assertIn("Link graph summary: agent memory", text)
        self.assertIn("Scope: bounded for agent context", text)
        self.assertIn("Agent memory (agent-memory · degree 5)", text)
        self.assertIn('get_context {"topic": "agent memory"} — need full context', text)


if __name__ == "__main__":
    unittest.main()
