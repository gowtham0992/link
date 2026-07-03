#!/usr/bin/env python3
"""Exercise Link's query and graph path against a synthetic large wiki."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.benchmark import benchmark_health  # noqa: E402
from link_core.memory import memory_records  # noqa: E402
from link_core.query import query_link  # noqa: E402
from link_core.web_graph import (  # noqa: E402
    GRAPH_INITIAL_SUMMARY_EDGE_LIMIT,
    GRAPH_INITIAL_SUMMARY_NODE_LIMIT,
    graph_initial_payload,
    graph_needs_bounded_overview,
)
from link_core.wiki import (  # noqa: E402
    build_backlinks,
    build_wiki_cache,
    close_wiki_cache,
    graph_data,
    graph_summary,
    list_pages,
    search_pages,
)

DEFAULT_MAX_SECONDS = {
    "cache": 5.0,
    "search": 2.0,
    "query": 5.0,
    "graph_summary": 1.0,
    "page_list": 0.5,
    "graph_initial": 1.0,
    "graph": 3.0,
}


class SmokeFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def write_page(wiki: Path, rel: str, text: str) -> None:
    path = wiki / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_large_wiki(root: Path, page_count: int) -> Path:
    wiki = root / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    write_page(wiki, "index.md", "# Index\n")
    write_page(wiki, "log.md", "# Log\n")

    source_count = max(12, min(40, page_count // 20))
    for index in range(source_count):
        write_page(
            wiki,
            f"sources/source-{index}.md",
            "---\n"
            "type: source\n"
            f"title: Source {index}\n"
            "---\n\n"
            f"# Source {index}\n\n"
            f"> **TLDR:** Source {index} covers local agent memory topic {index}.\n\n"
            "## Summary\n\nSynthetic source for large-wiki smoke coverage.\n\n"
            f"## Raw Source\n\n`raw/source-{index}.md`\n",
        )

    for index in range(page_count):
        next_index = (index + 1) % page_count
        skip_index = (index + 17) % page_count
        source_index = index % source_count
        write_page(
            wiki,
            f"concepts/topic-{index}.md",
            "---\n"
            "type: concept\n"
            f"title: Topic {index} Agent Memory\n"
            "tags: [agent-memory, large-wiki]\n"
            "---\n\n"
            f"# Topic {index} Agent Memory\n\n"
            f"> **TLDR:** Topic {index} describes local agent memory behavior.\n\n"
            "## Overview\n\n"
            f"Topic {index} links to [[topic-{next_index}]], [[topic-{skip_index}]], "
            f"and [[source-{source_index}]]. The repeated phrase keeps search realistic "
            "without requiring an unbounded context packet.\n\n"
            "## Sources\n\n"
            f"- [[source-{source_index}]]\n",
        )

    memory_count = max(16, min(40, page_count // 25))
    for index in range(memory_count):
        topic = 42 if index == 0 else index
        write_page(
            wiki,
            f"memories/prefer-topic-{topic}.md",
            "---\n"
            "type: memory\n"
            f"title: Prefer topic {topic}\n"
            "memory_type: preference\n"
            "scope: project\n"
            "project: large-wiki\n"
            "status: active\n"
            "date_captured: \"2026-05-06T00:00:00Z\"\n"
            "source: large-wiki-smoke\n"
            "review_status: reviewed\n"
            "---\n\n"
            f"# Prefer topic {topic}\n\n"
            f"> **TLDR:** User prefers topic {topic} local agent memory notes.\n\n"
            f"## Memory\n\nUser prefers topic {topic} local agent memory notes.\n",
        )

    (wiki / "_backlinks.json").write_text(json.dumps(build_backlinks(wiki)), encoding="utf-8")
    return wiki


def timed(label: str, fn):
    start = time.perf_counter()
    value = fn()
    elapsed = time.perf_counter() - start
    return label, value, elapsed


def check_timing_thresholds(timings: dict[str, float], max_seconds: dict[str, float]) -> None:
    for label, elapsed in sorted(timings.items()):
        ceiling = max_seconds.get(label)
        if ceiling is None:
            continue
        require(
            elapsed <= ceiling,
            f"{label} path took {elapsed:.4f}s, above {ceiling:.4f}s threshold",
        )


def initial_graph_payload_for_smoke(cache: dict[str, object], graph: dict[str, object]) -> dict[str, object]:
    summary_graph = None
    if graph_needs_bounded_overview(graph):
        summary = graph_summary(
            cache,
            limit=GRAPH_INITIAL_SUMMARY_NODE_LIMIT,
            depth=1,
            max_edges=GRAPH_INITIAL_SUMMARY_EDGE_LIMIT,
        )
        summary_graph = {
            "nodes": summary.get("nodes", []),
            "edges": summary.get("edges", []),
        }
    return graph_initial_payload(graph, summary_graph=summary_graph)


def run_smoke(work_dir: Path, page_count: int, max_seconds: dict[str, float] | None = None) -> dict[str, object]:
    wiki = build_large_wiki(work_dir, page_count)
    timings: dict[str, float] = {}

    label, cache, elapsed = timed("cache", lambda: build_wiki_cache(wiki))
    timings[label] = elapsed
    label, results, elapsed = timed("search", lambda: search_pages("agent memory", cache, limit=20))
    timings[label] = elapsed
    label, packet, elapsed = timed(
        "query",
        lambda: query_link(
            wiki,
            "agent memory",
            cache,
            memory_records(wiki),
            budget="small",
            project="large-wiki",
        ),
    )
    timings[label] = elapsed
    label, graph_packet, elapsed = timed(
        "graph_summary",
        lambda: graph_summary(cache, topic="agent memory", limit=40, depth=1, max_edges=120),
    )
    timings[label] = elapsed
    label, page_list, elapsed = timed("page_list", lambda: list_pages(cache, limit=100))
    timings[label] = elapsed
    label, graph, elapsed = timed("graph", lambda: graph_data(cache))
    timings[label] = elapsed
    label, initial_graph, elapsed = timed(
        "graph_initial",
        lambda: initial_graph_payload_for_smoke(cache, graph),
    )
    timings[label] = elapsed

    expected_pages = page_count + max(12, min(40, page_count // 20)) + max(16, min(40, page_count // 25)) + 2
    require(len(cache["pages"]) == expected_pages, f"expected {expected_pages} cached pages, got {len(cache['pages'])}")
    require(len(results) == 20, f"expected capped search results, got {len(results)}")
    require(packet.get("found") is True, "recall did not find large-wiki context")
    require(len(packet.get("context_packet", [])) <= 6, "small query budget was not enforced")
    require(packet.get("budget_report", {}).get("wiki_search", {}).get("has_more") is True, "query did not report additional matches")
    require(packet.get("follow_up", [{}])[0].get("tool") == "recall", "query did not return recall follow-up guidance")
    require(graph_packet.get("returned_nodes", 0) <= 40, "graph_summary did not enforce node limit")
    if expected_pages > 40:
        require(graph_packet.get("truncated") is True, "graph_summary did not report truncation for large wiki")
    expected_page_list_count = min(100, expected_pages)
    require(
        page_list.get("returned_count") == expected_page_list_count,
        "page list did not enforce default agent-safe limit",
    )
    require(
        page_list.get("truncated") is (expected_pages > 100),
        "page list did not report truncation state correctly",
    )
    require(len(graph["nodes"]) == expected_pages, f"expected {expected_pages} graph nodes, got {len(graph['nodes'])}")
    require(len(graph["edges"]) >= page_count * 2, "graph edge count is unexpectedly low")
    visible_graph_nodes = [
        node for node in graph.get("nodes", [])
        if str(node.get("category") or "") != "root"
    ]
    if graph_needs_bounded_overview(graph):
        require(initial_graph.get("graph_mode") == "summary", "large graph did not start with bounded overview")
        require(initial_graph.get("node_count", 0) <= GRAPH_INITIAL_SUMMARY_NODE_LIMIT, "initial graph payload exceeded node cap")
    else:
        require(initial_graph.get("graph_mode") == "full", "small graph should start with full payload")
    require(initial_graph.get("total_node_count") == len(visible_graph_nodes), "initial graph total node count is incorrect")
    max_seconds = max_seconds or DEFAULT_MAX_SECONDS
    check_timing_thresholds(timings, max_seconds)

    payload = {
        "work_dir": str(work_dir),
        "wiki": str(wiki),
        "viewer": {
            "serve_command": f"python3 link.py serve {work_dir}",
            "home_url": "http://127.0.0.1:3000",
            "onboard_url": "http://127.0.0.1:3000/onboard",
            "graph_url": "http://127.0.0.1:3000/graph",
            "health_url": "http://127.0.0.1:3000/health",
        },
        "pages": len(cache["pages"]),
        "edges": len(graph["edges"]),
        "search_backend": str(cache.get("search_backend") or "token-index"),
        "context_items": len(packet.get("context_packet", [])),
        "search_results": len(results),
        "graph_summary": {
            "returned_nodes": graph_packet.get("returned_nodes", 0),
            "returned_edges": graph_packet.get("returned_edges", 0),
            "truncated": graph_packet.get("truncated", False),
        },
        "page_list": {
            "returned_count": page_list.get("returned_count", 0),
            "truncated": page_list.get("truncated", False),
        },
        "graph_initial": {
            "mode": initial_graph.get("graph_mode", "unknown"),
            "nodes": initial_graph.get("node_count", 0),
            "edges": initial_graph.get("edge_count", 0),
            "total_nodes": initial_graph.get("total_node_count", 0),
            "total_edges": initial_graph.get("total_edge_count", 0),
        },
        "timings": {key: round(value, 4) for key, value in timings.items()},
        "max_seconds": max_seconds,
    }
    payload["health"] = benchmark_health(payload)
    require(payload["health"]["status"] == "pass", "large-wiki benchmark health did not pass")
    close_wiki_cache(cache)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Link against a synthetic large wiki.")
    parser.add_argument("--pages", type=int, default=1000, help="number of synthetic concept pages")
    parser.add_argument("--work-dir", default="", help="directory for generated wiki artifacts")
    parser.add_argument("--max-cache-seconds", type=float, default=DEFAULT_MAX_SECONDS["cache"])
    parser.add_argument("--max-search-seconds", type=float, default=DEFAULT_MAX_SECONDS["search"])
    parser.add_argument("--max-query-seconds", type=float, default=DEFAULT_MAX_SECONDS["query"])
    parser.add_argument("--max-graph-summary-seconds", type=float, default=DEFAULT_MAX_SECONDS["graph_summary"])
    parser.add_argument("--max-page-list-seconds", type=float, default=DEFAULT_MAX_SECONDS["page_list"])
    parser.add_argument("--max-graph-initial-seconds", type=float, default=DEFAULT_MAX_SECONDS["graph_initial"])
    parser.add_argument("--max-graph-seconds", type=float, default=DEFAULT_MAX_SECONDS["graph"])
    args = parser.parse_args()

    if args.pages < 1:
        print("Large-wiki smoke failed: --pages must be at least 1", file=sys.stderr)
        return 2

    work_dir = Path(args.work_dir).expanduser().resolve() if args.work_dir else Path(tempfile.mkdtemp(prefix="link-large-wiki-"))
    max_seconds = {
        "cache": args.max_cache_seconds,
        "search": args.max_search_seconds,
        "query": args.max_query_seconds,
        "graph_summary": args.max_graph_summary_seconds,
        "page_list": args.max_page_list_seconds,
        "graph_initial": args.max_graph_initial_seconds,
        "graph": args.max_graph_seconds,
    }
    try:
        payload = run_smoke(work_dir, args.pages, max_seconds=max_seconds)
    except SmokeFailure as exc:
        print(f"Large-wiki smoke failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(payload, indent=2))
    print(f"Large-wiki smoke passed for {payload['pages']} pages")
    print(f"View it: {payload['viewer']['serve_command']}")
    print(f"Graph: {payload['viewer']['graph_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
