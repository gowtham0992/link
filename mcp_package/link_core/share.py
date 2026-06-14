"""Local permalink helpers for Link wiki pages."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

from .mcp_verify import display_command
from .search import close_wiki_cache, search_pages
from .wiki import build_wiki_cache


def _page_summary(page: Mapping[str, Any]) -> dict[str, object]:
    return {
        "name": page.get("name", ""),
        "title": page.get("title", ""),
        "path": page.get("path", ""),
        "category": page.get("category", ""),
        "type": page.get("type", ""),
        "tldr": page.get("tldr", ""),
    }


def _identifier_keys(identifier: str) -> list[str]:
    text = identifier.strip().strip('"').strip("'")
    if not text:
        return []
    keys = {text.lower()}
    if text.startswith("/page/"):
        keys.add(text.removeprefix("/page/").lower())
    cleaned = text.removeprefix("wiki/").replace("\\", "/")
    keys.add(cleaned.lower())
    if cleaned.endswith(".md"):
        keys.add(Path(cleaned).stem.lower())
    keys.add(Path(cleaned).stem.lower())
    return [key for key in keys if key]


def _exact_page(pages: list[Mapping[str, Any]], identifier: str) -> Mapping[str, Any] | None:
    keys = set(_identifier_keys(identifier))
    if not keys:
        return None
    for page in pages:
        name = str(page.get("name") or "").lower()
        path = str(page.get("path") or "").lower()
        title = str(page.get("title") or "").lower()
        aliases = {str(alias).lower() for alias in page.get("aliases", []) if str(alias).strip()}
        if name in keys or path in keys or title in keys or keys & aliases:
            return page
    return None


def _page_url(page_name: str, *, host: str, port: int) -> str:
    return f"http://{host}:{port}/page/{quote(page_name)}"


def share_page_payload(
    wiki_dir: Path,
    identifier: str,
    *,
    host: str = "127.0.0.1",
    port: int = 3000,
    cache: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Resolve a page or memory identifier into a local viewer permalink."""
    query = identifier.strip()
    if not query:
        return {
            "found": False,
            "error": "page or memory identifier required",
            "query": query,
            "candidates": [],
        }

    owns_cache = cache is None
    resolved_cache = cache or build_wiki_cache(wiki_dir)
    try:
        pages = list(resolved_cache.get("pages") or [])
        page = _exact_page(pages, query)
        resolution = "exact"
        candidates: list[dict[str, object]] = []
        if page is None:
            results = search_pages(query, resolved_cache, limit=5)
            candidates = [_page_summary(result) | {"score": result.get("score", 0)} for result in results]
            page = results[0] if results else None
            resolution = "search"
        if page is None:
            return {
                "found": False,
                "error": "no matching Link page found",
                "query": query,
                "candidates": candidates,
            }

        summary = _page_summary(page)
        page_name = str(summary["name"])
        root = wiki_dir.parent if wiki_dir.name == "wiki" else wiki_dir
        serve_command = ["lnk", "serve", str(root), "--port", str(port)]
        return {
            "found": True,
            "query": query,
            "resolution": resolution,
            "page": summary,
            "url": _page_url(page_name, host=host, port=port),
            "serve_command": serve_command,
            "serve_command_text": display_command(serve_command),
            "agent_prompt": f"open Link page {page_name} and summarize why it matters",
            "candidates": candidates,
        }
    finally:
        if owns_cache:
            close_wiki_cache(resolved_cache)


def render_share_text(payload: Mapping[str, object]) -> tuple[int, str]:
    """Render a local permalink payload for CLI users."""
    if not payload.get("found"):
        lines = [
            "Link share: no matching page",
            "",
            f"Query: {payload.get('query') or ''}",
            f"Error: {payload.get('error') or 'not found'}",
        ]
        candidates = payload.get("candidates")
        if isinstance(candidates, list) and candidates:
            lines.extend(["", "Closest matches:"])
            for candidate in candidates[:5]:
                if isinstance(candidate, Mapping):
                    title = candidate.get("title") or candidate.get("name")
                    path = candidate.get("path") or ""
                    lines.append(f"- {title} ({path})")
        return 1, "\n".join(lines)

    page = payload.get("page") if isinstance(payload.get("page"), Mapping) else {}
    lines = [
        "Link share",
        "",
        f"Page: {page.get('title') or page.get('name')}",
        f"Path: {page.get('path')}",
        f"URL: {payload.get('url')}",
        "",
        "If the viewer is not running:",
        f"  {payload.get('serve_command_text')}",
        "",
        "Agent prompt:",
        f"  {payload.get('agent_prompt')}",
    ]
    if payload.get("resolution") == "search":
        lines.append("")
        lines.append("Resolved by search. Use the exact page name for a stable direct match.")
    return 0, "\n".join(lines)
