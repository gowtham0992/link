"""Shared wiki indexing, search, context, and graph helpers for Link."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .files import atomic_write_json, atomic_write_text
from .frontmatter import parse_frontmatter
from .search import (
    build_fts_index,
    close_wiki_cache,
    normalized_search_text,
    search_pages,
    search_words,
)


WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
PERSISTENT_CACHE_SCHEMA_VERSION = 2
INDEX_CATEGORY_ORDER = (
    "memories",
    "concepts",
    "entities",
    "sources",
    "comparisons",
    "explorations",
    "root",
)
INDEX_CATEGORY_TITLES = {
    "memories": "Memories",
    "concepts": "Concepts",
    "entities": "Entities",
    "sources": "Sources",
    "comparisons": "Comparisons",
    "explorations": "Explorations",
    "root": "Other Pages",
}


def wiki_mtime(wiki_dir: Path) -> float:
    """Return an mtime signal for files that affect wiki indexes."""
    try:
        timestamp = wiki_dir.stat().st_mtime
        for path in wiki_dir.rglob("*"):
            try:
                if path.is_dir() or path.suffix == ".md" or path.name == "_backlinks.json":
                    timestamp = max(timestamp, path.stat().st_mtime)
            except OSError:
                continue
        return timestamp
    except Exception:
        return 0.0


def _heading_title(body: str) -> str:
    match = re.search(r"^#\s+(.+)", body, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _tldr(body: str) -> str:
    match = re.search(r">\s*\*\*TLDR:\*\*\s*(.+)", body)
    return match.group(1).strip() if match else ""


def _list_value(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _body_snippet(body: str) -> str:
    body_lines = [
        line.strip()
        for line in body.split("\n")
        if line.strip() and not line.startswith("#") and not line.startswith(">")
    ]
    return body_lines[0][:200] if body_lines else ""


def _markdown_page_paths(wiki_dir: Path) -> list[Path]:
    return sorted(path for path in wiki_dir.rglob("*.md") if not path.name.startswith("."))


def _persistent_cache_path(wiki_dir: Path) -> Path:
    return wiki_dir.parent / ".link-cache" / f"wiki-cache-v{PERSISTENT_CACHE_SCHEMA_VERSION}.json"


def _persistent_fts_path(wiki_dir: Path) -> Path:
    return wiki_dir.parent / ".link-cache" / "page-fts-v1.sqlite"


def _page_signatures(wiki_dir: Path, page_paths: list[Path]) -> list[dict[str, Any]]:
    signatures: list[dict[str, Any]] = []
    for path in page_paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        signatures.append({
            "path": path.relative_to(wiki_dir).as_posix(),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "mode": stat.st_mode,
        })
    return signatures


def _signature_key(signature: dict[str, Any]) -> tuple[Any, ...]:
    return (
        signature.get("path"),
        signature.get("size"),
        signature.get("mtime_ns"),
        signature.get("mode"),
    )


def _load_persistent_record_map(
    cache_path: Path,
    signatures: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    if payload.get("schema_version") != PERSISTENT_CACHE_SCHEMA_VERSION:
        return {}
    if payload.get("signatures") != signatures:
        # Schema v2 supports partial reuse when only some page signatures changed.
        pass
    records = payload.get("records")
    if not isinstance(records, list):
        return {}
    current_by_path = {
        str(signature.get("path")): signature
        for signature in signatures
        if isinstance(signature.get("path"), str)
    }
    loaded: dict[str, dict[str, Any]] = {}
    for item in records:
        if not isinstance(item, dict):
            continue
        rel = item.get("path")
        text = item.get("text")
        signature = item.get("signature")
        if not isinstance(rel, str) or not isinstance(text, str) or not isinstance(signature, dict):
            continue
        current_signature = current_by_path.get(rel)
        if current_signature and _signature_key(current_signature) == _signature_key(signature):
            loaded[rel] = {"path": rel, "text": text, "signature": signature}
    return loaded


def _write_persistent_records(
    cache_path: Path,
    signatures: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> bool:
    try:
        atomic_write_json(
            cache_path,
            {
                "schema_version": PERSISTENT_CACHE_SCHEMA_VERSION,
                "signatures": signatures,
                "records": records,
            },
        )
    except OSError:
        return False
    return True


def build_wiki_cache(wiki_dir: Path, *, use_persistent_cache: bool = True) -> dict[str, Any]:
    use_persistent_cache = use_persistent_cache and wiki_dir.exists()
    page_paths = _markdown_page_paths(wiki_dir)
    signatures = _page_signatures(wiki_dir, page_paths)
    persistent_cache_path = _persistent_cache_path(wiki_dir)
    cached_by_path = (
        _load_persistent_record_map(persistent_cache_path, signatures)
        if use_persistent_cache
        else {}
    )
    reused_records = 0

    records: list[dict[str, Any]] = []
    read_warnings: list[dict[str, str]] = []
    signatures_by_path = {str(item.get("path")): item for item in signatures}
    for md in page_paths:
        rel = md.relative_to(wiki_dir)
        rel_text = rel.as_posix()
        cached = cached_by_path.get(rel_text)
        if cached is not None:
            records.append(cached)
            reused_records += 1
            continue
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            read_warnings.append({
                "page": f"wiki/{rel.as_posix()}",
                "error": str(exc) or exc.__class__.__name__,
            })
            continue
        signature = signatures_by_path.get(rel_text, {"path": rel_text})
        records.append({"path": rel_text, "text": text, "signature": signature})
    cache_hit = bool(signatures) and reused_records == len(signatures) and not read_warnings
    cache_partial = bool(reused_records) and not cache_hit
    cache_written = False
    if use_persistent_cache and not read_warnings and reused_records < len(signatures):
        cache_written = _write_persistent_records(persistent_cache_path, signatures, records)

    pages: list[dict[str, Any]] = []
    page_index: dict[str, Path] = {}
    fulltext: dict[str, str] = {}
    body_index: dict[str, str] = {}
    meta_index: dict[str, dict[str, Any]] = {}
    normalized_fulltext: dict[str, str] = {}
    text_words_index: dict[str, set[str]] = {}
    meta_words_index: dict[str, set[str]] = {}
    snippet_index: dict[str, str] = {}
    token_index: dict[str, set[str]] = {}
    meta_token_index: dict[str, set[str]] = {}
    raw_forward_links: dict[str, list[str]] = {}
    raw_all_forward_links: dict[str, list[str]] = {}

    for record in records:
        rel = Path(record["path"])
        md = wiki_dir / rel
        text = record["text"]
        meta, body = parse_frontmatter(text)

        title = str(meta.get("title") or _heading_title(body) or md.stem)
        tldr = _tldr(body)
        aliases_raw = _list_value(meta.get("aliases", []))
        aliases = [str(alias).lower() for alias in aliases_raw]
        tags_raw = _list_value(meta.get("tags", []))
        category = rel.parts[0] if len(rel.parts) > 1 else "root"
        stem = md.stem.lower()

        page = {
            "name": md.stem,
            "path": f"wiki/{rel.as_posix()}",
            "title": title,
            "category": category,
            "type": meta.get("type", ""),
            "tags": tags_raw,
            "aliases": aliases,
            "maturity": meta.get("maturity", ""),
            "source_count": meta.get("source_count", ""),
            "tldr": tldr,
            "date_updated": meta.get("date_updated", ""),
            "date_published": meta.get("date_published", ""),
        }
        pages.append(page)
        page_index[stem] = md
        raw_forward_links[stem] = [
            match.group(1).strip().lower()
            for match in WIKILINK_RE.finditer(body)
            if match.group(1).strip()
        ]
        raw_all_forward_links[stem] = [
            match.group(1).strip().lower()
            for match in WIKILINK_RE.finditer(text)
            if match.group(1).strip()
        ]
        for alias in aliases:
            if alias not in page_index:
                page_index[alias] = md

        text_lower = text.lower()
        fulltext[stem] = text_lower
        body_index[stem] = body
        meta_index[stem] = dict(meta)
        text_normalized = normalized_search_text(text_lower)
        normalized_fulltext[stem] = text_normalized
        text_words_index[stem] = search_words(text_normalized)
        snippet_index[stem] = _body_snippet(body)

        for token in re.split(r"\W+", text_lower):
            if len(token) >= 3:
                token_index.setdefault(token, set()).add(stem)

        meta_tokens: set[str] = set()
        for word in re.split(r"\W+", title.lower()):
            if len(word) >= 3:
                meta_tokens.add(word)
        for alias in aliases:
            for word in re.split(r"\W+", alias):
                if len(word) >= 3:
                    meta_tokens.add(word)
        for tag in tags_raw:
            for word in re.split(r"\W+", str(tag).lower()):
                if len(word) >= 3:
                    meta_tokens.add(word)
        if tldr:
            for word in re.split(r"\W+", tldr.lower()):
                if len(word) >= 3:
                    meta_tokens.add(word)
        for token in meta_tokens:
            meta_token_index.setdefault(token, set()).add(stem)
        meta_words_index[stem] = search_words(" ".join([
            title,
            stem,
            tldr,
            " ".join(str(alias) for alias in aliases),
            " ".join(str(tag) for tag in tags_raw),
        ]))

    page_ids = {page["name"].lower(): page["name"] for page in pages}
    forward_links_index: dict[str, list[str]] = {}
    for source, raw_targets in raw_forward_links.items():
        source_name = page_ids.get(source, source)
        seen_targets: set[str] = set()
        for target_key in raw_targets:
            target = page_ids.get(target_key)
            if not target or target_key == source:
                continue
            if target in seen_targets:
                continue
            seen_targets.add(target)
            forward_links_index.setdefault(source_name, []).append(target)

    persistent_fts_path = _persistent_fts_path(wiki_dir)
    fts_index = build_fts_index(
        pages,
        fulltext,
        db_path=persistent_fts_path if use_persistent_cache else None,
        signatures=signatures,
    )
    fts_info = {"available": False, "persistent": False, "reused": False, "path": str(persistent_fts_path)}
    info = getattr(fts_index, "info", None)
    if callable(info):
        fts_info = dict(info())
    return {
        "mtime": wiki_mtime(wiki_dir),
        "pages": pages,
        "page_index": page_index,
        "fulltext": fulltext,
        "body_index": body_index,
        "meta_index": meta_index,
        "normalized_fulltext": normalized_fulltext,
        "text_words_index": text_words_index,
        "meta_words_index": meta_words_index,
        "snippet_index": snippet_index,
        "token_index": token_index,
        "meta_token_index": meta_token_index,
        "page_map": {page["name"].lower(): page for page in pages},
        "raw_forward_links_index": raw_forward_links,
        "raw_all_forward_links_index": raw_all_forward_links,
        "forward_links_index": forward_links_index,
        "fts_index": fts_index,
        "fts_index_info": fts_info,
        "search_backend": "sqlite-fts" if fts_index is not None else "token-index",
        "read_warning_count": len(read_warnings),
        "read_warnings": read_warnings,
        "persistent_cache": {
            "enabled": use_persistent_cache,
            "hit": cache_hit,
            "partial": cache_partial,
            "reused_records": reused_records,
            "total_records": len(signatures),
            "written": cache_written,
            "path": str(persistent_cache_path),
            "schema_version": PERSISTENT_CACHE_SCHEMA_VERSION,
        },
    }


def load_backlinks_index(
    backlinks_path: Path,
    missing_error: str | None = None,
    invalid_prefix: str = "invalid backlinks index",
) -> tuple[dict[str, dict[str, list[str]]], str | None]:
    empty: dict[str, dict[str, list[str]]] = {"backlinks": {}, "forward": {}}
    if not backlinks_path.exists():
        return empty, missing_error
    try:
        raw = json.loads(backlinks_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return empty, f"{invalid_prefix}: {exc}"
    if not isinstance(raw, dict):
        return empty, f"{invalid_prefix}: root must be an object"
    if "backlinks" not in raw:
        return {"backlinks": raw, "forward": {}}, None
    backlinks = raw.get("backlinks", {})
    forward = raw.get("forward", {})
    if not isinstance(backlinks, dict) or not isinstance(forward, dict):
        return empty, f"{invalid_prefix}: backlinks and forward must be objects"
    return {"backlinks": backlinks, "forward": forward}, None


def build_backlinks(wiki_dir: Path, body_only: bool = True) -> dict[str, dict[str, list[str]]]:
    backlinks: dict[str, list[str]] = {}
    forward_links: dict[str, list[str]] = {}
    for md in sorted(wiki_dir.rglob("*.md")):
        if md.name.startswith("."):
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        if body_only:
            _, text = parse_frontmatter(text)
        source = md.stem.lower()
        for match in WIKILINK_RE.finditer(text):
            target = match.group(1).strip().lower()
            if not target or target == source:
                continue
            backlinks.setdefault(target, [])
            if source not in backlinks[target]:
                backlinks[target].append(source)
            forward_links.setdefault(source, [])
            if target not in forward_links[source]:
                forward_links[source].append(target)
    return {"backlinks": backlinks, "forward": forward_links}


def _raise_for_cache_read_warnings(cache: dict[str, Any]) -> None:
    read_warning_count = int(cache.get("read_warning_count") or 0)
    if not read_warning_count:
        return
    read_warnings = cache.get("read_warnings") or []
    first_warning = read_warnings[0] if isinstance(read_warnings, list) and read_warnings else {}
    page = first_warning.get("page") if isinstance(first_warning, dict) else ""
    detail = f" starting at {page}" if page else ""
    raise OSError(f"could not read {read_warning_count} wiki page(s){detail}")


def build_backlinks_from_cache(
    cache: dict[str, Any],
    body_only: bool = True,
) -> dict[str, dict[str, list[str]]]:
    """Build backlink indexes from the parsed wiki cache instead of rereading pages."""
    _raise_for_cache_read_warnings(cache)
    cache_key = "raw_forward_links_index" if body_only else "raw_all_forward_links_index"
    forward_source = cache.get(cache_key)
    if not isinstance(forward_source, dict):
        return {"backlinks": {}, "forward": {}}
    backlinks: dict[str, list[str]] = {}
    forward_links: dict[str, list[str]] = {}
    for raw_source, raw_targets in forward_source.items():
        source = str(raw_source or "").lower()
        if not isinstance(raw_targets, list):
            continue
        for raw_target in raw_targets:
            target = str(raw_target or "").lower()
            if not target or target == source:
                continue
            backlinks.setdefault(target, [])
            if source not in backlinks[target]:
                backlinks[target].append(source)
            forward_links.setdefault(source, [])
            if target not in forward_links[source]:
                forward_links[source].append(target)
    return {"backlinks": backlinks, "forward": forward_links}


def context_for_topic(
    wiki_dir: Path,
    topic: str,
    cache: dict[str, Any],
    limit: int = 10,
    empty_error: str | None = None,
) -> dict[str, Any]:
    q = topic.strip()
    if not q:
        result: dict[str, Any] = {"topic": "", "found": False, "pages": []}
        if empty_error:
            result["error"] = empty_error
        return result

    matches = search_pages(q, cache, limit=5)
    if not matches:
        return {"topic": topic, "found": False, "pages": []}

    primary = matches[0]
    primary_name = primary["name"].lower()
    backlinks_data, _ = load_backlinks_index(wiki_dir / "_backlinks.json")
    inbound = backlinks_data.get("backlinks", {}).get(primary_name, [])

    forward: list[str] = []
    forward_seen: set[str] = set()
    page_set = {page["name"].lower() for page in cache["pages"]}
    forward_links_index = cache.get("forward_links_index")
    if isinstance(forward_links_index, dict):
        cached_forward = (
            forward_links_index.get(str(primary.get("name") or ""))
            or forward_links_index.get(primary_name)
            or []
        )
        for target_name in cached_forward:
            target = str(target_name).lower()
            if target in page_set and target != primary_name and target not in forward_seen:
                forward_seen.add(target)
                forward.append(target)
    else:
        path = cache["page_index"].get(primary_name)
        if path and path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
            _, body = parse_frontmatter(text)
            for match in WIKILINK_RE.finditer(body):
                target = match.group(1).strip().lower()
                if target in page_set and target != primary_name and target not in forward_seen:
                    forward_seen.add(target)
                    forward.append(target)

    seen = {primary_name}
    context_names = [primary_name]
    for name in inbound + forward:
        if name not in seen:
            seen.add(name)
            context_names.append(name)

    context_pages = []
    body_index = cache.get("body_index") if isinstance(cache.get("body_index"), dict) else {}
    meta_index = cache.get("meta_index") if isinstance(cache.get("meta_index"), dict) else {}
    for name in context_names[:limit]:
        page_path = cache["page_index"].get(name)
        if not page_path or not page_path.exists():
            continue
        cached_page = cache.get("page_map", {}).get(name, {})
        body = str(body_index.get(name) or "")
        meta = dict(meta_index.get(name) or {})
        if not body and not meta:
            text = page_path.read_text(encoding="utf-8", errors="replace")
            meta, body = parse_frontmatter(text)
        is_primary = name == primary_name
        if is_primary:
            content = body
        else:
            summary_lines = []
            for line in body.split("\n")[:20]:
                summary_lines.append(line)
                if line.startswith("## ") and len(summary_lines) > 3:
                    break
            content = "\n".join(summary_lines)
        context_pages.append({
            "name": name,
            "path": cached_page.get("path") or f"wiki/{page_path.relative_to(wiki_dir).as_posix()}",
            "title": meta.get("title", name),
            "category": cached_page.get("category", ""),
            "type": meta.get("type", ""),
            "source_count": cached_page.get("source_count", ""),
            "tldr": cached_page.get("tldr", ""),
            "date_updated": cached_page.get("date_updated", ""),
            "date_published": cached_page.get("date_published", ""),
            "is_primary": is_primary,
            "relationship": "primary" if is_primary else ("inbound" if name in inbound else "forward"),
            "content": content,
        })

    return {
        "topic": topic,
        "found": True,
        "primary": primary["name"],
        "inbound_count": len(inbound),
        "forward_count": len(forward),
        "pages": context_pages,
    }


def graph_data(cache: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    pages = cache["pages"]
    page_ids = {page["name"].lower(): page["name"] for page in pages}
    valid_ids = set(page_ids.values())
    nodes = [
        {"id": page["name"], "title": page["title"], "category": page["category"], "type": page["type"]}
        for page in pages
    ]
    edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str]] = set()
    forward_links = cache.get("forward_links_index")
    if isinstance(forward_links, dict):
        for source, targets in forward_links.items():
            source_id = page_ids.get(str(source).lower(), str(source))
            if source_id not in valid_ids:
                continue
            if not isinstance(targets, list):
                continue
            for target_raw in targets:
                target_key = str(target_raw).lower()
                target = page_ids.get(target_key, str(target_raw))
                if target not in valid_ids or target == source_id:
                    continue
                edge_key = (source_id, target)
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                edges.append({"source": source_id, "target": target})
        return {"nodes": nodes, "edges": edges}

    for page in pages:
        source = page["name"]
        path = cache["page_index"].get(source.lower())
        if not path or not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        _, body = parse_frontmatter(text)
        for match in WIKILINK_RE.finditer(body):
            target_key = match.group(1).strip().lower()
            target = page_ids.get(target_key)
            if not target or target_key == source.lower():
                continue
            edge_key = (source, target)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            edges.append({"source": source, "target": target})
    return {"nodes": nodes, "edges": edges}


def _bounded_int(value: object, default: int, lower: int, upper: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return min(max(parsed, lower), upper)


def _count_by(nodes: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in nodes:
        value = str(node.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _trim_summary(value: object, max_chars: int = 180) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)].rstrip() + "..."


def graph_summary(
    cache: dict[str, Any],
    topic: str = "",
    limit: int = 40,
    depth: int = 1,
    max_edges: int = 120,
) -> dict[str, Any]:
    """Return a token-safe graph packet for agents and large local wikis.

    ``graph_data`` intentionally returns the full graph for visualization and
    exports. This summary keeps the same source graph but selects a bounded set
    of high-signal nodes so MCP clients do not accidentally pull a 1000+ page
    graph into model context.
    """
    limit = _bounded_int(limit, 40, 1, 250)
    depth = _bounded_int(depth, 1, 0, 3)
    max_edges = _bounded_int(max_edges, 120, 0, 1000)
    topic = str(topic or "").strip()

    graph = graph_data(cache)
    all_nodes = list(graph.get("nodes", []))
    all_edges = list(graph.get("edges", []))
    node_by_id = {str(node.get("id") or ""): node for node in all_nodes}
    generated_node_ids = {"index", "log"}
    selectable_ids = {
        node_id
        for node_id, node in node_by_id.items()
        if node_id.lower() not in generated_node_ids and str(node.get("category") or "") != "root"
    }
    page_map = cache.get("page_map", {})
    snippet_index = cache.get("snippet_index", {})

    in_degree = {node_id: 0 for node_id in node_by_id}
    out_degree = {node_id: 0 for node_id in node_by_id}
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_by_id}
    for edge in all_edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source not in node_by_id or target not in node_by_id:
            continue
        out_degree[source] = out_degree.get(source, 0) + 1
        in_degree[target] = in_degree.get(target, 0) + 1
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set()).add(source)

    degree = {node_id: in_degree.get(node_id, 0) + out_degree.get(node_id, 0) for node_id in node_by_id}

    def node_rank(node_id: str) -> tuple[int, str, str]:
        node = node_by_id[node_id]
        return (-degree.get(node_id, 0), str(node.get("title") or "").lower(), node_id)

    top_hubs = [
        {
            "id": node_id,
            "title": node_by_id[node_id].get("title", ""),
            "category": node_by_id[node_id].get("category", ""),
            "type": node_by_id[node_id].get("type", ""),
            "degree": degree.get(node_id, 0),
        }
        for node_id in sorted(selectable_ids, key=node_rank)[:10]
    ]

    selected_ids: list[str] = []
    selection_reasons: dict[str, str] = {}
    distances: dict[str, int] = {}
    found = False
    mode = "overview"

    if topic:
        search_results = search_pages(topic, cache, limit=min(max(limit, 10), 50))
        seeds = [
            str(result.get("name") or "")
            for result in search_results
            if str(result.get("name") or "") in selectable_ids
        ]
        if seeds:
            found = True
            mode = "topic-neighborhood"
            frontier = list(dict.fromkeys(seeds))
            for seed in frontier:
                distances[seed] = 0
                selection_reasons[seed] = "matched topic"
            for current_depth in range(1, depth + 1):
                candidates: list[str] = []
                for node_id in frontier:
                    candidates.extend(
                        neighbor for neighbor in adjacency.get(node_id, set())
                        if neighbor in selectable_ids
                    )
                next_frontier = []
                for candidate in sorted(set(candidates), key=node_rank):
                    if candidate in distances:
                        continue
                    distances[candidate] = current_depth
                    selection_reasons[candidate] = f"within {current_depth} hop{'s' if current_depth != 1 else ''} of a topic match"
                    next_frontier.append(candidate)
                frontier = next_frontier
            selected_ids = sorted(distances, key=lambda node_id: (distances[node_id],) + node_rank(node_id))[:limit]

    if not selected_ids:
        selected_ids = sorted(selectable_ids, key=node_rank)[:limit]
        selection_reasons = {node_id: "high-degree overview node" for node_id in selected_ids}

    selected = set(selected_ids)
    selected_edges = [
        {"source": str(edge.get("source") or ""), "target": str(edge.get("target") or "")}
        for edge in all_edges
        if str(edge.get("source") or "") in selected and str(edge.get("target") or "") in selected
    ]
    selected_edges.sort(key=lambda edge: (
        -degree.get(edge["source"], 0) - degree.get(edge["target"], 0),
        edge["source"],
        edge["target"],
    ))
    edge_truncated = len(selected_edges) > max_edges
    selected_edges = selected_edges[:max_edges]

    nodes_payload: list[dict[str, Any]] = []
    for node_id in selected_ids:
        node = node_by_id[node_id]
        page = page_map.get(node_id.lower(), {}) if isinstance(page_map, dict) else {}
        summary = ""
        if isinstance(page, dict):
            summary = str(page.get("tldr") or "")
        if not summary and isinstance(snippet_index, dict):
            summary = str(snippet_index.get(node_id.lower(), ""))
        item = {
            "id": node_id,
            "title": node.get("title", ""),
            "category": node.get("category", ""),
            "type": node.get("type", ""),
            "degree": degree.get(node_id, 0),
            "in_degree": in_degree.get(node_id, 0),
            "out_degree": out_degree.get(node_id, 0),
            "summary": _trim_summary(summary),
            "why_selected": selection_reasons.get(node_id, "selected for graph summary"),
        }
        if node_id in distances:
            item["distance"] = distances[node_id]
        nodes_payload.append(item)

    if mode == "topic-neighborhood":
        agent_guidance = [
            "Use this bounded graph summary for orientation before requesting full pages.",
            "Call get_context on the best matching node when you need source-backed page content.",
            "Do not call get_graph unless the user explicitly asks for a full graph export.",
        ]
    else:
        agent_guidance = [
            "This is a high-degree overview, not the full graph.",
            "Pass a topic to get_graph_summary to inspect a bounded neighborhood.",
            "Use query_link or get_context for answer-ready source-backed context.",
        ]

    follow_up: list[dict[str, Any]] = []
    if topic and found and selected_ids:
        follow_up.append({"tool": "get_context", "arguments": {"topic": selected_ids[0]}})
        follow_up.append({"tool": "get_backlinks", "arguments": {"page_name": selected_ids[0]}})
    elif topic and not found:
        follow_up.append({"tool": "search_wiki", "arguments": {"query": topic, "limit": 10}})
    else:
        follow_up.append({"tool": "get_graph_summary", "arguments": {"topic": "<topic>", "limit": limit, "depth": depth}})

    considered_nodes = len(distances) if distances else len(selectable_ids)
    if len(nodes_payload) < considered_nodes or edge_truncated:
        follow_up.append({
            "tool": "get_graph_summary",
            "arguments": {"topic": topic, "limit": min(limit * 2, 250), "depth": depth, "max_edges": min(max_edges * 2, 1000)},
            "when": "Use only if the bounded graph is insufficient.",
        })
    follow_up.append({"tool": "get_graph", "when": "Only for an explicit full graph export or offline analysis."})

    return {
        "topic": topic,
        "mode": mode,
        "found": found if topic else True,
        "node_count": len(all_nodes),
        "edge_count": len(all_edges),
        "returned_nodes": len(nodes_payload),
        "returned_edges": len(selected_edges),
        "considered_nodes": considered_nodes,
        "generated_nodes_excluded": len(node_by_id) - len(selectable_ids),
        "limit": limit,
        "depth": depth,
        "max_edges": max_edges,
        "truncated": len(nodes_payload) < considered_nodes or edge_truncated,
        "edge_truncated": edge_truncated,
        "search_backend": str(cache.get("search_backend") or "token-index"),
        "category_counts": _count_by(all_nodes, "category"),
        "type_counts": _count_by(all_nodes, "type"),
        "top_hubs": top_hubs,
        "nodes": nodes_payload,
        "edges": selected_edges,
        "agent_guidance": agent_guidance,
        "follow_up": follow_up,
    }


def list_pages(
    cache: dict[str, Any],
    category: str = "",
    page_type: str = "",
    maturity: str = "",
    limit: int = 100,
    offset: int = 0,
    include_all: bool = False,
) -> dict[str, Any]:
    """Return filtered page metadata, bounded by default for agent context."""
    pages = list(cache.get("pages", []))
    category = str(category or "").strip().lower()
    page_type = str(page_type or "").strip().lower()
    maturity = str(maturity or "").strip().lower()
    if category:
        pages = [page for page in pages if str(page.get("category") or "").lower() == category]
    if page_type:
        pages = [page for page in pages if str(page.get("type") or "").lower() == page_type]
    if maturity:
        pages = [page for page in pages if str(page.get("maturity") or "").lower() == maturity]

    total = len(pages)
    offset = _bounded_int(offset, 0, 0, max(total, 0))
    limit = _bounded_int(limit, 100, 1, 1000)
    if include_all:
        returned_pages = pages[offset:]
        effective_limit: int | None = None
    else:
        returned_pages = pages[offset: offset + limit]
        effective_limit = limit
    next_offset = offset + len(returned_pages)
    truncated = next_offset < total

    follow_up: list[dict[str, Any]] = []
    if truncated:
        follow_up.append({
            "tool": "get_pages",
            "arguments": {
                "category": category,
                "page_type": page_type,
                "maturity": maturity,
                "limit": limit,
                "offset": next_offset,
            },
        })
    follow_up.append({"tool": "search_wiki", "when": "Use when you know what topic or text you need."})
    follow_up.append({"tool": "query_link", "when": "Use for answer-ready memory plus wiki context."})

    return {
        "count": total,
        "total": total,
        "returned_count": len(returned_pages),
        "offset": offset,
        "limit": effective_limit,
        "truncated": truncated,
        "filters": {
            "category": category,
            "page_type": page_type,
            "maturity": maturity,
        },
        "pages": returned_pages,
        "agent_guidance": [
            "This page list is metadata only and may be paginated for context safety.",
            "Use search_wiki, query_link, or get_context instead of paging through the whole wiki when answering a question.",
        ],
        "follow_up": follow_up,
    }


def page_link_summary(
    backlinks_data: dict[str, dict[str, list[str]]],
    page_name: str,
    limit: int = 100,
    offset: int = 0,
    include_all: bool = False,
) -> dict[str, Any]:
    """Return bounded inbound/forward links for one page."""
    display_name = str(page_name or "").strip()
    name = display_name.lower().replace(" ", "-")
    limit = _bounded_int(limit, 100, 1, 1000)
    inbound_all = list(backlinks_data.get("backlinks", {}).get(name, []))
    forward_all = list(backlinks_data.get("forward", {}).get(name, []))
    max_count = max(len(inbound_all), len(forward_all))
    offset = _bounded_int(offset, 0, 0, max(max_count, 0))

    if include_all:
        inbound = inbound_all[offset:]
        forward = forward_all[offset:]
        effective_limit: int | None = None
    else:
        inbound = inbound_all[offset: offset + limit]
        forward = forward_all[offset: offset + limit]
        effective_limit = limit

    next_offset = offset + max(len(inbound), len(forward))
    truncated = next_offset < max_count
    follow_up: list[dict[str, Any]] = []
    if truncated:
        follow_up.append({
            "tool": "get_backlinks",
            "arguments": {
                "page_name": display_name,
                "limit": limit,
                "offset": next_offset,
            },
        })
    follow_up.append({"tool": "get_context", "arguments": {"topic": display_name}})
    follow_up.append({"tool": "get_graph_summary", "arguments": {"topic": display_name}})

    return {
        "page": display_name,
        "key": name,
        "inbound_count": len(inbound_all),
        "forward_count": len(forward_all),
        "returned_inbound": len(inbound),
        "returned_forward": len(forward),
        "offset": offset,
        "limit": effective_limit,
        "truncated": truncated,
        "inbound": inbound,
        "forward": forward,
        "agent_guidance": [
            "This page link list may be paginated for context safety.",
            "Use get_context or query_link when you need source-backed content, not only graph links.",
        ],
        "follow_up": follow_up,
    }


def _index_pages(cache: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        page for page in cache["pages"]
        if str(page.get("name") or "").lower() not in {"index", "log"}
    ]


def _category_sort_key(category: str) -> tuple[int, str]:
    try:
        index = INDEX_CATEGORY_ORDER.index(category)
    except ValueError:
        index = len(INDEX_CATEGORY_ORDER)
    return index, category


def _page_sort_key(page: dict[str, Any]) -> tuple[tuple[int, str], str]:
    return _category_sort_key(str(page.get("category") or "root")), str(page.get("title") or "").lower()


def _page_summary(page: dict[str, Any], cache: dict[str, Any]) -> str:
    name = str(page.get("name") or "").lower()
    tldr = str(page.get("tldr") or "").strip()
    snippet = str(cache.get("snippet_index", {}).get(name, "")).strip()
    title = str(page.get("title") or page.get("name") or "").strip()
    return tldr or snippet or title


def _index_entry(page: dict[str, Any], cache: dict[str, Any]) -> str:
    name = str(page.get("name") or "")
    title = str(page.get("title") or name)
    summary = _page_summary(page, cache)
    metadata = [
        value for value in (
            str(page.get("type") or "").strip(),
            str(page.get("maturity") or "").strip(),
        )
        if value
    ]
    meta = f" ({', '.join(metadata)})" if metadata else ""
    if summary and summary != title:
        return f"- [[{name}]] - {summary}{meta}"
    return f"- [[{name}]]{meta}"


def build_index_markdown(
    wiki_dir: Path,
    cache: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> str:
    """Build a deterministic, human-readable catalog for a Link wiki."""
    owns_cache = cache is None
    cache = cache or build_wiki_cache(wiki_dir)
    try:
        pages = sorted(_index_pages(cache), key=_page_sort_key)
        generated_at = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        source_count = sum(
            1 for page in pages
            if str(page.get("category") or "") == "sources" or str(page.get("type") or "") == "source"
        )
        memory_count = sum(
            1 for page in pages
            if str(page.get("category") or "") == "memories" or str(page.get("type") or "") == "memory"
        )

        categories: dict[str, list[dict[str, Any]]] = {}
        for page in pages:
            categories.setdefault(str(page.get("category") or "root"), []).append(page)

        lines = [
            "# Link Wiki Index",
            "",
            f"> Last updated: {generated_at} | {len(pages)} pages | {source_count} sources | {memory_count} memories",
            "",
            "## Categories",
            "",
        ]
        for category in sorted(categories, key=_category_sort_key):
            title = INDEX_CATEGORY_TITLES.get(category, category.replace("-", " ").title())
            lines.append(f"- {title}: {len(categories[category])}")
        if not categories:
            lines.append("- No pages yet")

        for category in sorted(categories, key=_category_sort_key):
            title = INDEX_CATEGORY_TITLES.get(category, category.replace("-", " ").title())
            lines.extend(["", f"### {category}", ""])
            for page in categories[category]:
                lines.append(_index_entry(page, cache))

        lines.extend([
            "",
            "## Recent",
            "",
            "See [[log]] for the append-only local audit trail.",
            "",
        ])
        return "\n".join(lines)
    finally:
        if owns_cache:
            close_wiki_cache(cache)


def rebuild_index(
    wiki_dir: Path,
    cache: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Regenerate wiki/index.md from the current Markdown pages."""
    owns_cache = cache is None
    cache = cache or build_wiki_cache(wiki_dir)
    try:
        _raise_for_cache_read_warnings(cache)
        markdown = build_index_markdown(wiki_dir, cache=cache, generated_at=generated_at)
        index_path = wiki_dir / "index.md"
        atomic_write_text(index_path, markdown)
        pages = _index_pages(cache)
        category_counts: dict[str, int] = {}
        for page in pages:
            category = str(page.get("category") or "root")
            category_counts[category] = category_counts.get(category, 0) + 1
        return {
            "rebuilt": True,
            "path": "wiki/index.md",
            "page_count": len(pages),
            "source_count": sum(
                1 for page in pages
                if str(page.get("category") or "") == "sources" or str(page.get("type") or "") == "source"
            ),
            "memory_count": sum(
                1 for page in pages
                if str(page.get("category") or "") == "memories" or str(page.get("type") or "") == "memory"
            ),
            "category_counts": dict(sorted(category_counts.items(), key=lambda item: _category_sort_key(item[0]))),
            "next_actions": [
                {
                    "tool": "rebuild_backlinks",
                    "command": "lnk rebuild-backlinks",
                    "reason": "Regenerated index links change graph edges; rebuild backlinks before validation.",
                }
            ],
        }
    finally:
        if owns_cache:
            close_wiki_cache(cache)
