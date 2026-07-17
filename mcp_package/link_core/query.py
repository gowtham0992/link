"""Smart query packet construction for Link agents.

This module keeps retrieval planning shared across CLI, HTTP, and MCP. It does
not answer the user directly; it returns a compact, source-backed packet an
agent can read before answering.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from .memory import (
    memory_brief,
    normalize_project,
    recall_memories,
)
from .semantic import semantic_memory_scores
from .wiki import context_for_topic, search_pages


BUDGETS: dict[str, dict[str, int]] = {
    "micro": {
        "memories": 1,
        "search_results": 2,
        "context_pages": 1,
        "primary_chars": 650,
        "neighbor_chars": 220,
        "capsule_items": 3,
        "capsule_chars": 420,
    },
    "small": {
        "memories": 3,
        "search_results": 4,
        "context_pages": 3,
        "primary_chars": 1200,
        "neighbor_chars": 450,
        "capsule_items": 5,
        "capsule_chars": 550,
    },
    "medium": {
        "memories": 6,
        "search_results": 6,
        "context_pages": 5,
        "primary_chars": 2400,
        "neighbor_chars": 700,
        "capsule_items": 7,
        "capsule_chars": 750,
    },
    "large": {
        "memories": 10,
        "search_results": 10,
        "context_pages": 8,
        "primary_chars": 5000,
        "neighbor_chars": 1200,
        "capsule_items": 10,
        "capsule_chars": 950,
    },
}


def normalize_budget(value: object | None) -> str:
    budget = str(value if value is not None else "medium").strip().lower()[:20]
    if budget in {"tiny", "capsule"}:
        return "micro"
    return budget if budget in BUDGETS else "medium"


def _trim_text(value: object, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)].rstrip() + "..."


def _memory_reason(memory: Mapping[str, object]) -> str:
    parts = ["matched the query"]
    recall = memory.get("recall")
    if isinstance(recall, Mapping):
        state = str(recall.get("state") or "")
        if state and state != "ready":
            parts.append(f"recall state: {state}")
        elif state == "ready":
            parts.append("recall-ready")
    if str(memory.get("review_status") or "").lower() == "reviewed":
        parts.append("reviewed")
    if memory.get("project"):
        parts.append(f"project: {memory['project']}")
    return "; ".join(parts)


def _drop_empty(data: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in data.items() if value not in ("", [], {})}


def _memory_provenance(memory: Mapping[str, object]) -> dict[str, object]:
    return _drop_empty({
        "path": memory.get("path", ""),
        "source": memory.get("source", ""),
        "date_captured": memory.get("date_captured", ""),
        "updated_at": memory.get("updated_at", ""),
        "last_update_source": memory.get("last_update_source", ""),
        "review_status": memory.get("review_status", ""),
        "reviewed_at": memory.get("reviewed_at", ""),
        "status": memory.get("status", ""),
    })


def _page_reason(page: Mapping[str, object]) -> str:
    relationship = str(page.get("relationship") or "")
    if relationship == "primary":
        return "best matching wiki page"
    if relationship == "inbound":
        return "links to the primary page"
    if relationship == "forward":
        return "linked from the primary page"
    return "related wiki page"


def _page_provenance(page: Mapping[str, object]) -> dict[str, object]:
    return _drop_empty({
        "path": page.get("path", ""),
        "relationship": page.get("relationship", ""),
        "type": page.get("type", ""),
        "category": page.get("category", ""),
        "source_count": page.get("source_count", ""),
        "date_updated": page.get("date_updated", ""),
        "date_published": page.get("date_published", ""),
    })


def _compact_memory(memory: Mapping[str, object]) -> dict[str, object]:
    item = {
        "kind": "memory",
        "name": memory.get("name", ""),
        "title": memory.get("title", ""),
        "memory_type": memory.get("memory_type", ""),
        "scope": memory.get("scope", ""),
        "project": memory.get("project", ""),
        "status": memory.get("status", ""),
        "review_status": memory.get("review_status", ""),
        "summary": memory.get("tldr") or memory.get("snippet") or "",
        "trigger": memory.get("trigger", ""),
        "steps": memory.get("steps", ""),
        "score": memory.get("score", 0),
        "rank_score": memory.get("rank_score", 0),
        "confidence": memory.get("confidence", ""),
        "recall": memory.get("recall", {}),
        "review_issue_count": memory.get("review_issue_count", 0),
        "highest_review_severity": memory.get("highest_review_severity", "none"),
        "provenance": _memory_provenance(memory),
        "why_selected": _memory_reason(memory),
    }
    return _drop_empty(item)


def _compact_page(page: Mapping[str, object], primary_chars: int, neighbor_chars: int) -> dict[str, object]:
    relationship = str(page.get("relationship") or "")
    max_chars = primary_chars if relationship == "primary" else neighbor_chars
    return {
        "kind": "page",
        "name": page.get("name", ""),
        "title": page.get("title", ""),
        "type": page.get("type", ""),
        "relationship": relationship,
        "is_primary": bool(page.get("is_primary")),
        "content": _trim_text(page.get("content", ""), max_chars),
        "provenance": _page_provenance(page),
        "why_selected": _page_reason(page),
    }


def _compact_search_result(page: Mapping[str, object]) -> dict[str, object]:
    return {
        "name": page.get("name", ""),
        "title": page.get("title", ""),
        "type": page.get("type", ""),
        "category": page.get("category", ""),
        "score": page.get("score", 0),
        "snippet": page.get("snippet", ""),
        "provenance": _page_provenance(page),
    }


def _slug_key(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    name = Path(text).stem if "/" in text or "\\" in text else text
    return re.sub(r"[^a-z0-9]+", "-", name).strip("-")


def _memory_source_keys(memory: Mapping[str, object]) -> set[str]:
    keys = {
        _slug_key(memory.get("name")),
        _slug_key(memory.get("source")),
        _slug_key(memory.get("provenance", {}).get("source") if isinstance(memory.get("provenance"), Mapping) else ""),
    }
    provenance = memory.get("provenance")
    if isinstance(provenance, Mapping):
        keys.add(_slug_key(provenance.get("path")))
    return {key for key in keys if key}


def _hybrid_ranked_items(
    memories: list[dict[str, object]],
    pages: list[dict[str, object]],
    search_results: list[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Fuse memory, search, and graph signals into one token-safe ranking."""
    search_rank = {_slug_key(page.get("name")): index for index, page in enumerate(search_results)}
    search_score = {
        _slug_key(page.get("name")): int(page.get("score") or 0)
        for page in search_results
    }
    page_keys = {_slug_key(page.get("name")) for page in pages}
    ranked: list[tuple[float, int, dict[str, object]]] = []

    for index, memory in enumerate(memories):
        score = float(memory.get("rank_score") or memory.get("score") or 0)
        signals = ["memory-match"]
        recall = memory.get("recall")
        if isinstance(recall, Mapping) and recall.get("state") == "ready":
            score += 12
            signals.append("recall-ready")
        if str(memory.get("review_status") or "").lower() == "reviewed":
            score += 8
            signals.append("reviewed")
        if memory.get("project"):
            score += 4
            signals.append("project-scoped")
        issue_count = int(memory.get("review_issue_count") or 0)
        if issue_count:
            score -= min(issue_count * 3, 12)
            signals.append("review-needed")
        if _memory_source_keys(memory) & page_keys:
            score += 10
            signals.append("source-linked-to-graph-context")
        ranked.append((score, index, {**memory, "hybrid_rank": round(score, 3), "rank_signals": signals}))

    offset = len(memories)
    for index, page in enumerate(pages):
        key = _slug_key(page.get("name"))
        score = float(search_score.get(key, 0))
        signals = ["graph-context"]
        relationship = str(page.get("relationship") or "")
        if relationship == "primary":
            score += 34
            signals.append("primary-topic")
        elif relationship in {"inbound", "forward"}:
            score += 14
            signals.append(f"{relationship}-link")
        if key in search_rank:
            score += 30 / (search_rank[key] + 1)
            signals.append("fts-ranked")
        ranked.append((score, offset + index, {**page, "hybrid_rank": round(score, 3), "rank_signals": signals}))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item for _, _, item in ranked]


def _capsule_item(item: Mapping[str, object], max_chars: int) -> dict[str, object]:
    content = item.get("summary") or item.get("content") or item.get("snippet") or ""
    return _drop_empty({
        "kind": item.get("kind", ""),
        "name": item.get("name", ""),
        "title": item.get("title", ""),
        "summary": _trim_text(content, max_chars),
        "why_selected": item.get("why_selected", ""),
        "rank_signals": item.get("rank_signals", []),
        "hybrid_rank": item.get("hybrid_rank", 0),
        "provenance": item.get("provenance", {}),
    })


def _recall_capsule(
    ranked_items: list[dict[str, object]],
    limits: Mapping[str, int],
) -> dict[str, object]:
    items = [
        _capsule_item(item, limits["capsule_chars"])
        for item in ranked_items[: limits["capsule_items"]]
    ]
    chars = _estimated_json_chars(items)
    return {
        "purpose": "read this first; it is the smallest fused memory/wiki packet",
        "ranking": "hybrid memory score + review state + recency + FTS + graph proximity",
        "count": len(items),
        "estimated_chars": chars,
        "estimated_tokens": _estimated_tokens(chars),
        "items": items,
    }


def _compact_review(review: object, limit: int) -> dict[str, object]:
    if not isinstance(review, Mapping):
        return {"count": 0, "counts_by_severity": {}, "items": []}
    items = []
    for item in list(review.get("items", []))[:limit]:
        if not isinstance(item, Mapping):
            continue
        primary_action = item.get("primary_action")
        action_kind = ""
        if isinstance(primary_action, Mapping):
            action_kind = str(primary_action.get("kind") or "")
        items.append({
            "name": item.get("name", ""),
            "title": item.get("title", ""),
            "memory_type": item.get("memory_type", ""),
            "scope": item.get("scope", ""),
            "issue_count": item.get("issue_count", 0),
            "highest_severity": item.get("highest_severity", "none"),
            "primary_action": action_kind,
        })
    return {
        "count": review.get("count", 0),
        "counts_by_severity": review.get("counts_by_severity", {}),
        "items": items,
    }


def _next_budget(current: str) -> str:
    order = ["micro", "small", "medium", "large"]
    try:
        index = order.index(current)
    except ValueError:
        return "medium"
    return order[min(index + 1, len(order) - 1)]


def _budget_item(selected: int, limit: int, has_more: bool) -> dict[str, object]:
    return {
        "selected": selected,
        "limit": limit,
        "has_more": has_more,
    }


def _estimated_json_chars(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _estimated_tokens(chars: int) -> int:
    # Practical rough count for agent budgeting; exact tokenizers vary by model.
    return max(1, (chars + 3) // 4) if chars else 0


def _context_packet_budget_item(packet: list[dict[str, object]], limit: int) -> dict[str, object]:
    chars = _estimated_json_chars(packet)
    item = _budget_item(len(packet), limit, False)
    item["estimated_chars"] = chars
    item["estimated_tokens"] = _estimated_tokens(chars)
    return item


def _follow_up_actions(
    query: str,
    budget_name: str,
    project: str,
    primary: object,
    budget_report: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    actions: list[dict[str, object]] = []
    if any(bool(section.get("has_more")) for section in budget_report.values()):
        next_budget = _next_budget(budget_name)
        if next_budget != budget_name:
            args: dict[str, object] = {"query": query, "budget": next_budget}
            if project:
                args["project"] = project
            actions.append({
                "when": "packet is relevant but too thin",
                "tool": "recall",
                "arguments": args,
            })
    if primary:
        actions.append({
            "when": "need the full source-backed topic neighborhood",
            "tool": "admin",
            "arguments": {"action": "context", "topic": primary},
        })
    actions.append({
        "when": "need a different angle or exact page candidates",
        "tool": "admin",
        "arguments": {"action": "search", "query": query, "limit": 10},
    })
    return actions


def query_link(
    wiki_dir: Path,
    query: str,
    cache: dict[str, Any],
    records: Iterable[Mapping[str, object]],
    *,
    budget: str = "medium",
    project: str | None = None,
    review_command: str = "review-memory",
) -> dict[str, object]:
    """Return a compact context packet for an agent query.

    The packet combines relevant local memory, ranked wiki search results, and
    graph-neighborhood context without forcing the agent to read the whole wiki.
    """
    q = str(query or "").strip()
    budget_name = normalize_budget(budget)
    limits = BUDGETS[budget_name]
    project_name = normalize_project(project)
    record_list = list(records)

    if not q:
        return {
            "query": "",
            "project": project_name,
            "budget": budget_name,
            "found": False,
            "error": "query required",
            "context_packet": [],
        }

    semantic_scores = semantic_memory_scores(wiki_dir.parent, q, record_list)
    raw_memories = recall_memories(
        record_list,
        q,
        limit=limits["memories"] + 1,
        project=project_name,
        semantic_scores=semantic_scores,
    )
    memory_has_more = len(raw_memories) > limits["memories"]
    memories = [_compact_memory(memory) for memory in raw_memories[: limits["memories"]]]
    brief = memory_brief(
        record_list,
        query=q,
        limit=limits["memories"],
        review_command=review_command,
        project=project_name,
        semantic_scores=semantic_scores,
    )
    raw_search_results = search_pages(q, cache, limit=limits["search_results"] + 1)
    search_has_more = len(raw_search_results) > limits["search_results"]
    search_results = raw_search_results[: limits["search_results"]]
    context = context_for_topic(
        wiki_dir,
        q,
        cache,
        limit=limits["context_pages"] + 1,
    )
    raw_context_pages = [page for page in context.get("pages", []) if isinstance(page, Mapping)]
    context_has_more = len(raw_context_pages) > limits["context_pages"]
    pages = [
        _compact_page(page, limits["primary_chars"], limits["neighbor_chars"])
        for page in raw_context_pages[: limits["context_pages"]]
    ]
    ranked_packet = _hybrid_ranked_items(memories, pages, search_results)
    packet = ranked_packet
    capsule = _recall_capsule(ranked_packet, limits)
    mode_parts = []
    if memories:
        mode_parts.append("memory")
    if pages:
        mode_parts.append("wiki")
    mode = "+".join(mode_parts) if mode_parts else "none"

    guidance = [
        "Read recall_capsule first; do not read the whole wiki unless the capsule and packet are insufficient.",
        "Prefer recall-ready reviewed memories for personalization and source-backed wiki pages for factual claims.",
        "Use provenance.path/source/date fields to explain why Link knows something.",
        "If important context appears missing, call recall with a larger budget or admin(action='context') on the primary page.",
        "Do not create or update memory from this packet unless the user explicitly asks.",
    ]
    review = _compact_review(brief.get("review", {}), limit=limits["memories"])
    if review.get("count"):
        guidance.insert(2, "Some memories need review; treat provisional memories carefully.")
    if memories and all(str(memory.get("confidence") or "") == "weak" for memory in memories):
        guidance.insert(
            1,
            "Memory matches are weak (shared words only); verify with the user "
            "before acting on them and do not present them as known preferences.",
        )
    budget_report = {
        "memories": _budget_item(len(memories), limits["memories"], memory_has_more),
        "wiki_search": _budget_item(len(search_results), limits["search_results"], search_has_more),
        "graph_context": _budget_item(len(pages), limits["context_pages"], context_has_more),
        "context_packet": _context_packet_budget_item(packet, limits["memories"] + limits["context_pages"]),
    }
    if any(bool(section.get("has_more")) for section in budget_report.values()):
        guidance.insert(1, "This packet is budget-limited; use follow_up instead of scanning files manually.")

    return {
        "query": q,
        "project": project_name,
        "budget": budget_name,
        "found": bool(packet or search_results),
        "strategy": {
            "mode": mode,
            "selection": "hybrid-ranked memory + FTS wiki + graph neighborhood",
            "limits": limits,
        },
        "budget_report": budget_report,
        "recall_capsule": capsule,
        "follow_up": _follow_up_actions(
            q,
            budget_name,
            project_name,
            context.get("primary", ""),
            budget_report,
        ),
        "memory": {
            "count": len(memories),
            "review": review,
            "items": memories,
        },
        "wiki": {
            "found": bool(context.get("found")),
            "primary": context.get("primary", ""),
            "inbound_count": context.get("inbound_count", 0),
            "forward_count": context.get("forward_count", 0),
            "search_count": len(search_results),
            "search_results": [_compact_search_result(page) for page in search_results],
            "pages": pages,
        },
        "context_packet": packet,
        "agent_guidance": guidance,
    }
