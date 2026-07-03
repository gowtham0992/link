"""HTML helpers for Link's local home page."""
from __future__ import annotations

import html
from collections.abc import Callable, Mapping, Sequence

from .web_ingest import copy_button


PageHref = Callable[[str], str]
PageLayout = Callable[[str, str], str]


def plural_type_label(page_type: str) -> str:
    irregular = {"entity": "entities", "memory": "memories"}
    if page_type in irregular:
        return irregular[page_type]
    return page_type if page_type.endswith("s") else page_type + "s"


def render_home_page(
    pages: Sequence[dict[str, object]],
    *,
    starter_prompts: Mapping[str, object],
    page_href: PageHref,
    layout: PageLayout,
) -> str:
    body = (
        "<h1>Link</h1><p>Local agent memory. Knowledge compounds here.</p>"
        f"{_render_product_lanes()}"
        f"{_render_prompt_strip(starter_prompts)}"
        f"{_render_next_steps()}"
        f"{_render_recent_pages(pages, page_href=page_href)}"
        f"{_render_stats(pages)}"
        f"{_render_page_sections(pages, page_href=page_href)}"
    )
    return layout("Link", body)


def _render_stats(pages: Sequence[dict[str, object]]) -> str:
    counts: dict[str, int] = {}
    for page in pages:
        page_type = str(page.get("type") or "other")
        counts[page_type] = counts.get(page_type, 0) + 1

    stats_items = f'<div class="stat"><span class="num">{len(pages)}</span><span class="label">pages</span></div>'
    for page_type in ["memory", "source", "concept", "entity", "comparison", "exploration"]:
        count = counts.get(page_type, 0)
        if count > 0:
            stats_items += (
                f'<div class="stat"><span class="num">{count}</span>'
                f'<span class="label">{plural_type_label(page_type)}</span></div>'
            )
    return f'<div class="home-stats">{stats_items}</div>'


def _render_page_sections(pages: Sequence[dict[str, object]], *, page_href: PageHref) -> str:
    categories: dict[str, list[dict[str, object]]] = {}
    for page in pages:
        category = str(page.get("category") or "")
        if category == "root":
            continue
        categories.setdefault(category, []).append(page)

    if not categories:
        return (
            '<div class="memory-next"><strong>Wiki is empty</strong>'
            "<ul>"
            '<li><a href="/ingest">Add the first raw source</a>.</li>'
            f"<li>{copy_button('ingest the new raw Link files', 'Copy ingest prompt')}</li>"
            "</ul></div>"
        )

    sections = ""
    for category in sorted(categories):
        items = "".join(
            f'<li><a href="{html.escape(page_href(str(page["name"])), quote=True)}">'
            f'{html.escape(str(page["title"]))}</a>'
            f'<span class="type">{html.escape(str(page.get("type") or ""))}</span></li>'
            for page in sorted(categories[category], key=lambda item: str(item.get("title") or ""))
        )
        sections += f'<h2>{html.escape(category)}</h2><ul class="page-list">{items}</ul>'
    return sections


def _render_recent_pages(pages: Sequence[dict[str, object]], *, page_href: PageHref, limit: int = 6) -> str:
    recent = [
        page for page in pages
        if str(page.get("category") or "") != "root" and str(page.get("date_updated") or "").strip()
    ]
    if not recent:
        return ""
    items = "".join(
        f'<li><a href="{html.escape(page_href(str(page["name"])), quote=True)}">'
        f'{html.escape(str(page["title"]))}</a>'
        f'<span class="type">{html.escape(str(page.get("type") or ""))} · updated {html.escape(str(page.get("date_updated") or ""))}</span></li>'
        for page in sorted(recent, key=_recent_page_key, reverse=True)[:limit]
    )
    return (
        '<section class="home-recent">'
        '<div class="section-heading"><h2>Recently Updated</h2><a href="/all">all pages</a></div>'
        f'<ul class="page-list">{items}</ul>'
        "</section>"
    )


def _recent_page_key(page: Mapping[str, object]) -> tuple[str, str]:
    return str(page.get("date_updated") or ""), str(page.get("title") or "")


def _render_product_lanes() -> str:
    return (
        '<div class="product-lanes" aria-label="How Link stores context">'
        '<section class="product-lane"><h2>1. Sources become wiki knowledge</h2>'
        '<p>Drop files into <code>raw/</code> and say <code>ingest raw/file.md into Link</code>. '
        'Link creates source-backed pages, concepts, backlinks, index entries, and logs.</p></section>'
        '<section class="product-lane"><h2>2. Remember saves agent memory</h2>'
        '<p>Say <code>remember that ...</code> when a preference, decision, or project fact should affect future agents. '
        'Ingest alone does not silently personalize recall.</p></section>'
        '<section class="product-lane"><h2>3. Query uses both safely</h2>'
        '<p>Ask <code>query Link for ...</code> or open a memory brief. Link combines reviewed memory, wiki pages, and graph context.</p></section>'
        '</div>'
    )


def _render_prompt_strip(starter_prompts: Mapping[str, object]) -> str:
    prompt_codes = ""
    for item in starter_prompts.get("prompts", []):
        if isinstance(item, dict):
            prompt = str(item.get("prompt") or "")
            prompt_codes += (
                '<div class="prompt-chip">'
                f"<code>{html.escape(prompt)}</code>"
                f"{copy_button(prompt, 'Copy')}"
                "</div>"
            )
    return (
        '<section class="prompt-strip" aria-label="First Link prompts">'
        '<h2>Try These Prompts</h2>'
        '<p>Ask from Codex, Claude, Cursor, Kiro, or any agent with Link installed. <a href="/prompts">Open starter prompts</a>.</p>'
        '<div class="prompt-grid">'
        f"{prompt_codes}</div></section>"
    )


def _render_next_steps() -> str:
    actions = [
        ("Onboard", "/onboard", "Health, first memory, agent wiring, and the daily prompt loop."),
        ("Check health", "/health", "Readiness, validation, interrupted writes, and safe repairs."),
        ("Add source", "/ingest", "Save raw notes locally, then ask your agent to ingest them."),
        ("Review memory", "/memory", "Inspect remembered preferences, decisions, and project context."),
        ("Explore graph", "/graph", "Open relationships, focused neighborhoods, and page evidence."),
    ]
    items = "".join(
        '<a class="home-next-card" href="'
        f'{html.escape(href, quote=True)}"><strong>{html.escape(label)}</strong>'
        f'<span>{html.escape(detail)}</span></a>'
        for label, href, detail in actions
    )
    return (
        '<section class="home-next" aria-label="Next steps">'
        "<h2>Next Steps</h2>"
        f'<div class="home-next-grid">{items}</div>'
        "</section>"
    )
