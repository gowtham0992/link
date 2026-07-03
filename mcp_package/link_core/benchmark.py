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


def _estimated_tokens(chars: int) -> int:
    # Practical rough count for agent budgeting; exact tokenizers vary by model.
    return max(1, (chars + 3) // 4) if chars else 0


def _safe_int(value: object) -> int:
    return int(value) if isinstance(value, (int, float)) else 0


def benchmark_value_evidence(cache: Mapping[str, object], packet: Mapping[str, object]) -> dict[str, object]:
    """Estimate how much broad local context the query packet avoided sending.

    This is a context-budget metric, not an answer-quality score. It compares
    the bounded Link query packet against the body text currently indexed in
    the local wiki.
    """
    body_index = cache.get("body_index")
    if not isinstance(body_index, Mapping):
        body_index = {}
    broad_chars = sum(len(str(body)) for body in body_index.values())
    broad_tokens = _estimated_tokens(broad_chars)

    budget_report = packet.get("budget_report")
    if not isinstance(budget_report, Mapping):
        budget_report = {}
    packet_report = budget_report.get("context_packet")
    if not isinstance(packet_report, Mapping):
        packet_report = {}
    packet_chars = _safe_int(packet_report.get("estimated_chars"))
    packet_tokens = _safe_int(packet_report.get("estimated_tokens"))

    recall_capsule = packet.get("recall_capsule")
    if not isinstance(recall_capsule, Mapping):
        recall_capsule = {}
    capsule_chars = _safe_int(recall_capsule.get("estimated_chars"))
    capsule_tokens = _safe_int(recall_capsule.get("estimated_tokens"))

    context_packet = packet.get("context_packet")
    packet_items = len(context_packet) if isinstance(context_packet, list) else 0
    memory = packet.get("memory")
    memory_count = 0
    if isinstance(memory, Mapping):
        memory_count = _safe_int(memory.get("count"))
    wiki = packet.get("wiki")
    wiki_pages = 0
    search_count = 0
    if isinstance(wiki, Mapping):
        pages = wiki.get("pages")
        wiki_pages = len(pages) if isinstance(pages, list) else 0
        search_count = _safe_int(wiki.get("search_count"))

    avoided_chars = max(0, broad_chars - packet_chars)
    avoided_tokens = max(0, broad_tokens - packet_tokens)
    compression_ratio = round(broad_chars / max(packet_chars, 1), 1) if broad_chars else 0.0

    notes = [
        "Context savings are estimated from local wiki body text versus the bounded query packet.",
        "This does not score answer quality; use it to see whether Link is reducing context budget waste.",
    ]
    if broad_chars == 0:
        notes.append("No wiki body text was indexed yet, so there is no broad-context baseline.")
    elif packet_chars == 0:
        notes.append("The query packet was empty; seed or ingest sources before using this as a value signal.")
    elif compression_ratio < 2:
        notes.append("This wiki is still small or the packet is broad; savings become more useful as sources accumulate.")
    else:
        notes.append("The query returned a bounded packet instead of asking the agent to scan broad wiki context.")

    return {
        "baseline": {
            "label": "broad wiki body text",
            "pages": len(body_index),
            "estimated_chars": broad_chars,
            "estimated_tokens": broad_tokens,
        },
        "context_packet": {
            "items": packet_items,
            "estimated_chars": packet_chars,
            "estimated_tokens": packet_tokens,
            "has_more": bool(packet_report.get("has_more")),
        },
        "recall_capsule": {
            "items": _safe_int(recall_capsule.get("count")),
            "estimated_chars": capsule_chars,
            "estimated_tokens": capsule_tokens,
        },
        "selection": {
            "memory_items": memory_count,
            "wiki_pages": wiki_pages,
            "search_results": search_count,
        },
        "avoidance": {
            "estimated_chars": avoided_chars,
            "estimated_tokens": avoided_tokens,
            "compression_ratio": compression_ratio,
        },
        "notes": notes,
    }


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
        fts_index_info = cache.get("fts_index_info")
        if not isinstance(fts_index_info, Mapping):
            fts_index_info = {}
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
            "fts_index": {
                "available": bool(fts_index_info.get("available")),
                "persistent": bool(fts_index_info.get("persistent")),
                "reused": bool(fts_index_info.get("reused")),
                "path": str(fts_index_info.get("path") or ""),
            },
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
        if isinstance(packet, Mapping):
            payload["value_evidence"] = benchmark_value_evidence(cache, packet)
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
    fts_index = payload.get("fts_index")
    if isinstance(fts_index, Mapping) and fts_index.get("available"):
        lines.append(
            "FTS sidecar: "
            f"{'persistent' if fts_index.get('persistent') else 'memory'} · "
            f"reused={bool(fts_index.get('reused'))}"
        )
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

    value_evidence = payload.get("value_evidence")
    if isinstance(value_evidence, Mapping):
        baseline = value_evidence.get("baseline")
        context_packet = value_evidence.get("context_packet")
        recall_capsule = value_evidence.get("recall_capsule")
        selection = value_evidence.get("selection")
        avoidance = value_evidence.get("avoidance")
        if (
            isinstance(baseline, Mapping)
            and isinstance(context_packet, Mapping)
            and isinstance(recall_capsule, Mapping)
            and isinstance(selection, Mapping)
            and isinstance(avoidance, Mapping)
        ):
            lines.append("")
            lines.append("Value evidence")
            lines.append(
                "Broad wiki baseline: "
                f"{baseline.get('pages', 0)} pages · "
                f"{baseline.get('estimated_chars', 0)} chars · "
                f"{baseline.get('estimated_tokens', 0)} tokens"
            )
            lines.append(
                "Bounded query packet: "
                f"{context_packet.get('items', 0)} items · "
                f"{context_packet.get('estimated_chars', 0)} chars · "
                f"{context_packet.get('estimated_tokens', 0)} tokens · "
                f"has_more={context_packet.get('has_more', False)}"
            )
            lines.append(
                "Recall capsule: "
                f"{recall_capsule.get('items', 0)} items · "
                f"{recall_capsule.get('estimated_chars', 0)} chars · "
                f"{recall_capsule.get('estimated_tokens', 0)} tokens"
            )
            lines.append(
                "Selected context: "
                f"{selection.get('memory_items', 0)} memories · "
                f"{selection.get('wiki_pages', 0)} wiki pages · "
                f"{selection.get('search_results', 0)} search results"
            )
            lines.append(
                "Estimated context avoided: "
                f"{avoidance.get('estimated_chars', 0)} chars · "
                f"{avoidance.get('estimated_tokens', 0)} tokens · "
                f"{avoidance.get('compression_ratio', 0)}x smaller than broad wiki text"
            )
        notes = value_evidence.get("notes")
        if isinstance(notes, list) and notes:
            lines.append("Value notes:")
            for note in notes:
                lines.append(f"- {note}")

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
