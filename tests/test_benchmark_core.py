import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.benchmark import (  # noqa: E402
    benchmark_health,
    benchmark_scale_notes,
    benchmark_value_evidence,
    build_benchmark_payload,
    render_benchmark_text,
)
from link_core.demo import create_demo_workspace  # noqa: E402


class BenchmarkCoreTests(unittest.TestCase):
    def test_build_benchmark_payload_times_demo_wiki(self):
        tmp = Path(tempfile.mkdtemp(prefix="link-benchmark-core-"))
        target = tmp / "demo"
        create_demo_workspace(target, source_root=ROOT)

        payload = build_benchmark_payload(
            target,
            target / "wiki",
            query_text="agent memory",
            budget="small",
            project="demo",
        )

        self.assertEqual(payload["target"], str(target))
        self.assertEqual(payload["project"], "demo")
        self.assertEqual(payload["pages"], 16)
        self.assertEqual(payload["memories"], 4)
        self.assertIn(payload["search_backend"], {"sqlite-fts", "token-index"})
        self.assertIn("persistent_cache", payload)
        self.assertTrue(payload["persistent_cache"]["enabled"])
        self.assertEqual(payload["persistent_cache"]["total_records"], 16)
        self.assertTrue(payload["found"])
        self.assertIn("value_evidence", payload)
        self.assertEqual(payload["value_evidence"]["baseline"]["pages"], 16)
        self.assertGreater(payload["value_evidence"]["baseline"]["estimated_chars"], 0)
        self.assertGreaterEqual(payload["value_evidence"]["avoidance"]["estimated_tokens"], 0)
        self.assertIn("health", payload)
        self.assertIn("cache", payload["timings"])

    def test_benchmark_value_evidence_reports_context_avoidance(self):
        payload = benchmark_value_evidence(
            {
                "body_index": {
                    "alpha": "A" * 4000,
                    "beta": "B" * 2000,
                }
            },
            {
                "budget_report": {
                    "context_packet": {
                        "estimated_chars": 1200,
                        "estimated_tokens": 300,
                        "has_more": False,
                    }
                },
                "recall_capsule": {
                    "count": 2,
                    "estimated_chars": 400,
                    "estimated_tokens": 100,
                },
                "context_packet": [{"kind": "memory"}, {"kind": "wiki"}],
                "memory": {"count": 1},
                "wiki": {"pages": [{"name": "alpha"}], "search_count": 3},
            },
        )

        self.assertEqual(payload["baseline"]["pages"], 2)
        self.assertEqual(payload["baseline"]["estimated_chars"], 6000)
        self.assertEqual(payload["baseline"]["estimated_tokens"], 1500)
        self.assertEqual(payload["context_packet"]["items"], 2)
        self.assertEqual(payload["recall_capsule"]["items"], 2)
        self.assertEqual(payload["selection"]["memory_items"], 1)
        self.assertEqual(payload["selection"]["wiki_pages"], 1)
        self.assertEqual(payload["selection"]["search_results"], 3)
        self.assertEqual(payload["avoidance"]["estimated_tokens"], 1200)
        self.assertEqual(payload["avoidance"]["compression_ratio"], 5.0)
        self.assertTrue(any("bounded packet" in note for note in payload["notes"]))

    def test_benchmark_value_evidence_warns_when_packet_is_empty(self):
        payload = benchmark_value_evidence(
            {"body_index": {"alpha": "A" * 100}},
            {"budget_report": {"context_packet": {"estimated_chars": 0, "estimated_tokens": 0}}},
        )

        self.assertTrue(any("query packet was empty" in note for note in payload["notes"]))

    def test_benchmark_health_passes_fast_sqlite_search(self):
        payload = {
            "pages": 1200,
            "search_backend": "sqlite-fts",
            "timings": {
                "cache": 0.2,
                "search": 0.01,
                "query": 0.03,
                "graph_summary": 0.01,
                "page_list": 0.01,
                "graph_initial": 0.01,
                "graph": 0.04,
            },
        }

        health = benchmark_health(payload)

        self.assertEqual(health["status"], "pass")
        self.assertEqual(health["label"], "interactive")
        self.assertEqual(health["summary"], "Ready for interactive local agent memory.")
        self.assertEqual(health["warnings"], [])
        self.assertEqual(health["recommendations"], [])

    def test_benchmark_health_warns_on_slow_paths(self):
        payload = {
            "pages": 20,
            "search_backend": "sqlite-fts",
            "timings": {
                "cache": 0.2,
                "search": 1.5,
                "query": 0.03,
                "graph_summary": 0.01,
                "page_list": 0.01,
                "graph_initial": 0.01,
                "graph": 0.04,
            },
        }

        health = benchmark_health(payload)

        self.assertEqual(health["status"], "warn")
        self.assertEqual(health["label"], "review")
        self.assertIn("search took 1.5000s", health["warnings"][0])
        self.assertIn("Review recommended", health["summary"])
        self.assertIn("Run lnk doctor --fix", health["recommendations"][0])
        self.assertIn("sqlite3/FTS5", health["recommendations"][1])

    def test_benchmark_health_warns_on_large_token_fallback(self):
        payload = {
            "pages": 1000,
            "search_backend": "token-index",
            "timings": {
                "cache": 0.2,
                "search": 0.01,
                "query": 0.03,
                "graph_summary": 0.01,
                "page_list": 0.01,
                "graph_initial": 0.01,
                "graph": 0.04,
            },
        }

        health = benchmark_health(payload)

        self.assertEqual(health["status"], "warn")
        self.assertIn("SQLite FTS", health["warnings"][0])
        self.assertIn("sqlite3/FTS5", health["recommendations"][1])

    def test_benchmark_health_gives_graph_specific_recommendations(self):
        payload = {
            "pages": 2000,
            "search_backend": "sqlite-fts",
            "timings": {
                "cache": 0.2,
                "search": 0.01,
                "query": 0.03,
                "graph_summary": 0.01,
                "page_list": 0.01,
                "graph_initial": 1.4,
                "graph": 2.4,
            },
        }

        health = benchmark_health(payload)

        self.assertEqual(health["status"], "warn")
        self.assertTrue(any("graph_initial took" in warning for warning in health["warnings"]))
        self.assertTrue(any("graph took" in warning for warning in health["warnings"]))
        self.assertIn("focused neighborhoods", " ".join(health["recommendations"]))

    def test_benchmark_scale_notes_explain_large_healthy_wikis(self):
        notes = benchmark_scale_notes({
            "pages": 10_000,
            "search_backend": "sqlite-fts",
            "graph_initial": {"mode": "summary", "nodes": 250, "total_nodes": 10_000},
        })

        self.assertTrue(any("10k+ page wiki" in note for note in notes))
        self.assertTrue(any("Graph opens as a bounded overview" in note for note in notes))
        self.assertTrue(any("SQLite FTS is active" in note for note in notes))

    def test_render_benchmark_text_includes_agent_safe_payloads_and_packet(self):
        payload = {
            "target": "/tmp/link",
            "query": "agent memory",
            "project": "link",
            "pages": 12,
            "memories": 1,
            "edges": 58,
            "search_backend": "sqlite-fts",
            "persistent_cache": {
                "enabled": True,
                "hit": False,
                "partial": True,
                "reused_records": 11,
                "total_records": 12,
            },
            "search_results": 4,
            "context_items": 3,
            "found": True,
            "graph_summary": {"returned_nodes": 5, "returned_edges": 6},
            "page_list": {"returned_count": 12},
            "graph_initial": {"mode": "full", "nodes": 12, "total_nodes": 12},
            "scale_notes": ["SQLite FTS is active, so search has headroom for larger local wikis."],
            "health": {
                "label": "interactive",
                "summary": "Ready for interactive local agent memory.",
                "warnings": [],
                "recommendations": [],
            },
            "timings": {
                "cache": 0.1,
                "search": 0.01,
                "query": 0.02,
                "graph_summary": 0.03,
                "page_list": 0.04,
                "graph_initial": 0.05,
                "graph": 0.06,
            },
            "budget_report": {
                "context_packet": {
                    "estimated_chars": 1200,
                    "estimated_tokens": 300,
                    "has_more": False,
                }
            },
            "value_evidence": {
                "baseline": {
                    "pages": 12,
                    "estimated_chars": 12_000,
                    "estimated_tokens": 3_000,
                },
                "context_packet": {
                    "items": 3,
                    "estimated_chars": 1200,
                    "estimated_tokens": 300,
                    "has_more": False,
                },
                "recall_capsule": {
                    "items": 2,
                    "estimated_chars": 600,
                    "estimated_tokens": 150,
                },
                "selection": {
                    "memory_items": 1,
                    "wiki_pages": 2,
                    "search_results": 4,
                },
                "avoidance": {
                    "estimated_chars": 10_800,
                    "estimated_tokens": 2_700,
                    "compression_ratio": 10.0,
                },
                "notes": [
                    "Context savings are estimated from local wiki body text versus the bounded query packet.",
                    "This does not score answer quality; use it to see whether Link is reducing context budget waste.",
                ],
            },
        }

        text = render_benchmark_text(payload)

        self.assertIn("Link benchmark: /tmp/link", text)
        self.assertIn("Project: link", text)
        self.assertIn("Persistent cache: enabled · 11/12 pages reused · hit=False · partial=True", text)
        self.assertIn("Agent-safe payloads: graph summary 5 nodes/6 edges · page list 12 pages", text)
        self.assertIn("Graph page initial load: full · 12/12 nodes", text)
        self.assertIn("Scale notes:", text)
        self.assertIn("SQLite FTS is active", text)
        self.assertIn("Verdict: interactive", text)
        self.assertIn("Value evidence", text)
        self.assertIn("Broad wiki baseline: 12 pages · 12000 chars · 3000 tokens", text)
        self.assertIn("Bounded query packet: 3 items · 1200 chars · 300 tokens · has_more=False", text)
        self.assertIn("Recall capsule: 2 items · 600 chars · 150 tokens", text)
        self.assertIn("Selected context: 1 memories · 2 wiki pages · 4 search results", text)
        self.assertIn("Estimated context avoided: 10800 chars · 2700 tokens · 10.0x smaller", text)
        self.assertIn("Value notes:", text)
        self.assertIn("Packet: 1200 chars · 300 tokens · has_more=False", text)
        self.assertIn("Result: found", text)


if __name__ == "__main__":
    unittest.main()
