"""Shared benchmark health helpers for Link."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable
from typing import Mapping

from .memory import memory_records
from .query import query_link
from .web_graph import (
    GRAPH_INITIAL_SUMMARY_EDGE_LIMIT,
    GRAPH_INITIAL_SUMMARY_NODE_LIMIT,
    graph_initial_payload,
    graph_needs_bounded_overview,
)
from .wiki import (
    build_wiki_cache,
    close_wiki_cache,
    graph_data,
    graph_summary,
    list_pages,
    search_pages,
)


BENCHMARK_THRESHOLDS_SECONDS = {
    "cache": 5.0,
    "search": 1.0,
    "query": 3.0,
    "graph_summary": 1.0,
    "page_list": 0.5,
    "graph_initial": 1.0,
    "graph": 2.0,
}


def timed(label: str, fn: Callable[[], object]) -> tuple[str, object, float]:
    start = time.perf_counter()
    value = fn()
    return label, value, time.perf_counter() - start


def benchmark_graph_initial_payload(cache: dict[str, object], full_graph: object) -> dict[str, object]:
    if not isinstance(full_graph, Mapping):
        return graph_initial_payload({"nodes": [], "edges": []})
    summary_graph = None
    if graph_needs_bounded_overview(full_graph):
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
    return graph_initial_payload(full_graph, summary_graph=summary_graph)


def build_benchmark_payload(
    target: Path,
    wiki_dir: Path,
    *,
    query_text: str,
    budget: str,
    project: str,
    review_command: str = "review-memory",
) -> dict[str, object]:
    """Build benchmark timings and scale metadata for a Link wiki."""
    timings: dict[str, float] = {}
    cache: dict[str, object] | None = None

    label, cache_value, elapsed = timed("cache", lambda: build_wiki_cache(wiki_dir))
    timings[label] = elapsed
    if not isinstance(cache_value, dict):
        cache_value = {}
    cache = cache_value
    try:
        records = memory_records(wiki_dir)
        label, results, elapsed = timed("search", lambda: search_pages(query_text, cache, limit=20))
        timings[label] = elapsed
        label, packet, elapsed = timed(
            "query",
            lambda: query_link(
                wiki_dir,
                query_text,
                cache,
                records,
                budget=budget,
                project=project,
                review_command=review_command,
            ),
        )
        timings[label] = elapsed
        label, graph_summary_payload, elapsed = timed(
            "graph_summary",
            lambda: graph_summary(cache, topic=query_text, limit=40, depth=1, max_edges=120),
        )
        timings[label] = elapsed
        label, page_list_payload, elapsed = timed(
            "page_list",
            lambda: list_pages(cache, limit=100),
        )
        timings[label] = elapsed
        label, graph, elapsed = timed("graph", lambda: graph_data(cache))
        timings[label] = elapsed
        label, graph_initial, elapsed = timed(
            "graph_initial",
            lambda: benchmark_graph_initial_payload(cache, graph),
        )
        timings[label] = elapsed

        budget_report = packet.get("budget_report", {}) if isinstance(packet, dict) else {}
        graph_summary_info = graph_summary_payload if isinstance(graph_summary_payload, Mapping) else {}
        page_list_info = page_list_payload if isinstance(page_list_payload, Mapping) else {}
        graph_initial_info = graph_initial if isinstance(graph_initial, Mapping) else {}
        persistent_cache_info = cache.get("persistent_cache")
        if not isinstance(persistent_cache_info, Mapping):
            persistent_cache_info = {}
        payload = {
            "target": str(target),
            "wiki": str(wiki_dir),
            "query": query_text,
            "budget": budget,
            "project": project,
            "pages": len(cache.get("pages", [])),
            "memories": len(records),
            "edges": len(graph.get("edges", [])) if isinstance(graph, dict) else 0,
            "graph_summary": {
                "returned_nodes": graph_summary_info.get("returned_nodes", 0),
                "returned_edges": graph_summary_info.get("returned_edges", 0),
                "truncated": bool(graph_summary_info.get("truncated")),
            },
            "page_list": {
                "returned_count": page_list_info.get("returned_count", 0),
                "truncated": bool(page_list_info.get("truncated")),
            },
            "graph_initial": {
                "mode": graph_initial_info.get("graph_mode", "unknown"),
                "nodes": graph_initial_info.get("node_count", 0),
                "edges": graph_initial_info.get("edge_count", 0),
                "total_nodes": graph_initial_info.get("total_node_count", 0),
                "total_edges": graph_initial_info.get("total_edge_count", 0),
            },
            "search_backend": str(cache.get("search_backend") or "token-index"),
            "persistent_cache": {
                "enabled": bool(persistent_cache_info.get("enabled")),
                "hit": bool(persistent_cache_info.get("hit")),
                "partial": bool(persistent_cache_info.get("partial")),
                "reused_records": int(persistent_cache_info.get("reused_records") or 0),
                "total_records": int(persistent_cache_info.get("total_records") or 0),
            },
            "search_results": len(results) if isinstance(results, list) else 0,
            "context_items": len(packet.get("context_packet", [])) if isinstance(packet, dict) else 0,
            "found": bool(packet.get("found")) if isinstance(packet, dict) else False,
            "timings": {key: round(value, 4) for key, value in timings.items()},
            "budget_report": budget_report,
        }
        payload["scale_notes"] = benchmark_scale_notes(payload)
        payload["health"] = benchmark_health(payload)
        return payload
    finally:
        if cache is not None:
            close_wiki_cache(cache)


def benchmark_health(payload: Mapping[str, object]) -> dict[str, object]:
    """Return a compact interactive-readiness verdict for benchmark output."""
    timings = payload.get("timings")
    if not isinstance(timings, Mapping):
        timings = {}
    warnings: list[str] = []
    slow_paths: list[str] = []
    for label, ceiling in BENCHMARK_THRESHOLDS_SECONDS.items():
        elapsed = timings.get(label)
        if isinstance(elapsed, (int, float)) and elapsed > ceiling:
            warnings.append(f"{label} took {elapsed:.4f}s, above the {ceiling:.1f}s interactive target")
            slow_paths.append(label)
    large_token_fallback = int(payload.get("pages") or 0) >= 1000 and payload.get("search_backend") != "sqlite-fts"
    if large_token_fallback:
        warnings.append("large wiki is using token-index fallback; SQLite FTS would improve search headroom")
    if warnings:
        summary = "Review recommended before relying on this wiki for interactive agent work."
        recommendations = [
            "Run lnk doctor --fix and lnk benchmark again after repairing wiki/index state.",
        ]
        if large_token_fallback or "search" in slow_paths or "query" in slow_paths:
            recommendations.append("Use a Python build with sqlite3/FTS5 enabled for large local wikis.")
        if "cache" in slow_paths:
            recommendations.append("Inspect unusually large pages or raw-source references; cache time is dominated by local file reads.")
        if "graph_initial" in slow_paths or "graph" in slow_paths:
            recommendations.append("Use graph-summary, search, and focused neighborhoods instead of loading the full graph first.")
        if "page_list" in slow_paths:
            recommendations.append("Use bounded page-list pagination instead of asking an agent to enumerate every page.")
        if not any(path in slow_paths for path in ("cache", "search", "query", "graph_summary", "page_list", "graph_initial", "graph")):
            recommendations.append("Inspect unusually large pages or raw-source references if interaction still feels slow.")
    else:
        summary = "Ready for interactive local agent memory."
        recommendations = []
    return {
        "status": "warn" if warnings else "pass",
        "label": "review" if warnings else "interactive",
        "summary": summary,
        "thresholds_seconds": BENCHMARK_THRESHOLDS_SECONDS,
        "warnings": warnings,
        "recommendations": recommendations,
    }


def benchmark_scale_notes(payload: Mapping[str, object]) -> list[str]:
    """Return non-alarmist scale guidance for otherwise healthy local wikis."""
    pages = int(payload.get("pages") or 0)
    graph_initial = payload.get("graph_initial")
    graph_mode = ""
    graph_nodes = 0
    graph_total_nodes = 0
    if isinstance(graph_initial, Mapping):
        graph_mode = str(graph_initial.get("mode") or "")
        graph_nodes = int(graph_initial.get("nodes") or 0)
        graph_total_nodes = int(graph_initial.get("total_nodes") or 0)

    notes: list[str] = []
    if pages >= 10_000:
        notes.append(
            "10k+ page wiki: prefer query, brief, search, graph-summary, and focused graph neighborhoods for daily work."
        )
    elif pages >= 1_000:
        notes.append(
            "1k+ page wiki: keep using bounded query packets and graph neighborhoods instead of asking agents to enumerate everything."
        )
    if graph_mode == "summary" or (graph_total_nodes and graph_nodes < graph_total_nodes):
        notes.append(
            "Graph opens as a bounded overview; load all data only when you need global search or filtering."
        )
    if payload.get("search_backend") == "sqlite-fts":
        notes.append("SQLite FTS is active, so search has headroom for larger local wikis.")
    return notes


def render_benchmark_text(payload: Mapping[str, object]) -> str:
    """Render human-readable benchmark output."""
    lines = [
        f"Link benchmark: {payload.get('target', '')}",
        f"Query: {payload.get('query', '')}",
    ]
    project = payload.get("project")
    if project:
        lines.append(f"Project: {project}")
    lines.append("")
    lines.append(
        f"Scale: {payload.get('pages', 0)} pages · "
        f"{payload.get('memories', 0)} memories · "
        f"{payload.get('edges', 0)} edges"
    )
    lines.append(f"Search backend: {payload.get('search_backend', 'unknown')}")
    persistent_cache = payload.get("persistent_cache")
    if isinstance(persistent_cache, Mapping):
        lines.append(
            "Persistent cache: "
            f"{'enabled' if persistent_cache.get('enabled') else 'disabled'} · "
            f"{persistent_cache.get('reused_records', 0)}/{persistent_cache.get('total_records', 0)} pages reused · "
            f"hit={bool(persistent_cache.get('hit'))} · partial={bool(persistent_cache.get('partial'))}"
        )
    lines.append(
        f"Results: {payload.get('search_results', 0)} search results · "
        f"{payload.get('context_items', 0)} context items"
    )

    graph_summary = payload.get("graph_summary")
    page_list = payload.get("page_list")
    graph_initial = payload.get("graph_initial")
    if isinstance(graph_summary, Mapping) and isinstance(page_list, Mapping):
        lines.append(
            "Agent-safe payloads: "
            f"graph summary {graph_summary.get('returned_nodes', 0)} nodes/"
            f"{graph_summary.get('returned_edges', 0)} edges · "
            f"page list {page_list.get('returned_count', 0)} pages"
        )
    if isinstance(graph_initial, Mapping):
        lines.append(
            "Graph page initial load: "
            f"{graph_initial.get('mode', 'unknown')} · "
            f"{graph_initial.get('nodes', 0)}/{graph_initial.get('total_nodes', 0)} nodes"
        )
    scale_notes = payload.get("scale_notes")
    if isinstance(scale_notes, list) and scale_notes:
        lines.append("Scale notes:")
        for note in scale_notes:
            lines.append(f"- {note}")

    health = payload.get("health")
    if isinstance(health, Mapping):
        lines.append(f"Verdict: {health.get('label', 'unknown')}")
        if health.get("summary"):
            lines.append(f"Health: {health.get('summary')}")

    lines.append("")
    lines.append("Timings")
    timings = payload.get("timings")
    if not isinstance(timings, Mapping):
        timings = {}
    for key in ("cache", "search", "query", "graph_summary", "page_list", "graph_initial", "graph"):
        value = timings.get(key, 0)
        if not isinstance(value, (int, float)):
            value = 0
        lines.append(f"- {key}: {value:.4f}s")

    if isinstance(health, Mapping) and health.get("warnings"):
        lines.append("")
        lines.append("Warnings")
        for warning in health["warnings"]:
            lines.append(f"- {warning}")
        recommendations = health.get("recommendations")
        if isinstance(recommendations, list) and recommendations:
            lines.append("")
            lines.append("Recommendations")
            for recommendation in recommendations:
                lines.append(f"- {recommendation}")

    budget_report = payload.get("budget_report")
    if isinstance(budget_report, Mapping):
        packet_report = budget_report.get("context_packet")
        if isinstance(packet_report, Mapping):
            lines.append("")
            lines.append(
                "Packet: "
                f"{packet_report.get('estimated_chars', 0)} chars · "
                f"{packet_report.get('estimated_tokens', 0)} tokens · "
                f"has_more={packet_report.get('has_more', False)}"
            )

    lines.append("")
    lines.append(f"Result: {'found' if payload.get('found') else 'no matching context'}")
    return "\n".join(lines)
