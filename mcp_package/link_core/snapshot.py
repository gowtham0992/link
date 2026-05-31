"""Read-only static snapshot export for Link wikis."""
from __future__ import annotations

import html
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

from .files import atomic_write_json, atomic_write_text
from .markdown import markdown_to_html
from .memory import default_memory_visibility
from .search import close_wiki_cache
from .security import find_sensitive_values
from .wiki import build_wiki_cache


SNAPSHOT_SCHEMA = "link-snapshot-v1"
SNAPSHOT_CSS = """
:root {
  color-scheme: light;
  --bg: #fbf7df;
  --ink: #17130d;
  --muted: #5f5a50;
  --line: #1b1711;
  --panel: #fffdf1;
  --accent: #ffd84d;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background:
    linear-gradient(rgba(0,0,0,.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,0,0,.035) 1px, transparent 1px),
    var(--bg);
  background-size: 24px 24px;
  color: var(--ink);
  font: 16px/1.55 Georgia, "Times New Roman", serif;
}
a { color: #064fb0; text-decoration-thickness: 1px; text-underline-offset: 2px; }
header, main, footer { max-width: 1040px; margin: 0 auto; padding: 24px; }
header { border-bottom: 3px solid var(--line); background: rgba(255,253,241,.88); }
.brand { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.brand h1 { margin: 0; font-size: clamp(2.2rem, 6vw, 5rem); line-height: .95; }
.brand span { color: var(--muted); font-size: 1.05rem; }
.notice, .card {
  background: var(--panel);
  border: 2px solid var(--line);
  box-shadow: 6px 6px 0 var(--line);
  padding: 18px;
  margin: 18px 0;
}
.notice { border-color: #8c6a00; box-shadow: 5px 5px 0 #8c6a00; }
.meta { color: var(--muted); font-size: .94rem; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 18px; }
.page-list { list-style: none; margin: 0; padding: 0; }
.page-list li { padding: 10px 0; border-bottom: 1px solid rgba(23,19,13,.18); }
.page-list small { display: block; color: var(--muted); }
article {
  background: rgba(255,253,241,.76);
  border-left: 4px solid var(--line);
  padding: 8px 0 8px 20px;
}
article h1, article h2, article h3 { line-height: 1.15; }
article code, pre {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  background: rgba(0,0,0,.075);
}
article code { padding: 2px 4px; }
pre { overflow: auto; padding: 14px; }
blockquote { margin-left: 0; padding-left: 14px; border-left: 3px solid #aaa; color: #3f3a32; }
table { border-collapse: collapse; width: 100%; display: block; overflow-x: auto; }
th, td { border: 1px solid rgba(23,19,13,.22); padding: 6px 8px; text-align: left; }
footer { color: var(--muted); border-top: 2px solid rgba(23,19,13,.18); }
""".strip() + "\n"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _page_filename(name: object) -> str:
    return quote(str(name).strip(), safe="") + ".html"


def _category_title(category: str) -> str:
    return {
        "concepts": "Concepts",
        "entities": "Entities",
        "sources": "Sources",
        "comparisons": "Comparisons",
        "explorations": "Explorations",
        "memories": "Memories",
        "root": "Other Pages",
    }.get(category, category.replace("-", " ").title())


def _include_page(
    page: Mapping[str, Any],
    *,
    include_memories: bool,
    include_private_memories: bool,
    meta_index: Mapping[str, Mapping[str, Any]],
) -> bool:
    name = str(page.get("name") or "").lower()
    category = str(page.get("category") or "")
    if name in {"index", "log"}:
        return False
    if category == "memories":
        if not include_memories:
            return False
        if _memory_visibility(name, meta_index) == "private" and not include_private_memories:
            return False
    return True


def _memory_visibility(name: str, meta_index: Mapping[str, Mapping[str, Any]]) -> str:
    meta = meta_index.get(name.lower(), {})
    if not isinstance(meta, Mapping):
        meta = {}
    scope = str(meta.get("scope") or "user").lower()
    return str(meta.get("visibility") or default_memory_visibility(scope)).lower()


def _metadata_line(page: Mapping[str, Any]) -> str:
    parts = [
        str(page.get("category") or ""),
        str(page.get("type") or ""),
        f"{page.get('source_count')} sources" if str(page.get("source_count") or "").strip() else "",
        f"updated {page.get('date_updated')}" if str(page.get("date_updated") or "").strip() else "",
    ]
    return " · ".join(part for part in parts if part)


def _html_shell(title: str, body: str, *, root_prefix: str = "") -> str:
    safe_title = html.escape(title)
    return (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\">\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"  <title>{safe_title}</title>\n"
        f"  <link rel=\"stylesheet\" href=\"{root_prefix}assets/snapshot.css\">\n"
        "</head>\n"
        "<body>\n"
        f"{body}\n"
        "<footer>Generated by Link snapshot. Static, read-only, and local-first.</footer>\n"
        "</body>\n"
        "</html>\n"
    )


def _index_html(
    *,
    title: str,
    pages: list[Mapping[str, Any]],
    page_href: Mapping[str, str],
    created_at: str,
    include_memories: bool,
    excluded_counts: Mapping[str, int],
) -> str:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for page in pages:
        grouped.setdefault(str(page.get("category") or "root"), []).append(page)
    sections: list[str] = []
    for category in sorted(grouped):
        items = []
        for page in sorted(grouped[category], key=lambda item: str(item.get("title") or item.get("name")).lower()):
            name = str(page.get("name") or "")
            href = page_href.get(name.lower(), "#")
            summary = str(page.get("tldr") or _metadata_line(page))
            items.append(
                "<li>"
                f"<a href=\"{html.escape(href, quote=True)}\">{html.escape(str(page.get('title') or name))}</a>"
                f"<small>{html.escape(summary)}</small>"
                "</li>"
            )
        sections.append(
            "<section class=\"card\">"
            f"<h2>{html.escape(_category_title(category))}</h2>"
            f"<ul class=\"page-list\">{''.join(items)}</ul>"
            "</section>"
        )
    if not include_memories:
        memory_note = "excluded by default"
    elif excluded_counts.get("private_memories"):
        memory_note = "non-private included"
    else:
        memory_note = "included"
    body = (
        "<header>"
        f"<div class=\"brand\"><h1>{html.escape(title)}</h1><span>Link read-only snapshot</span></div>"
        f"<p class=\"meta\">Created {html.escape(created_at)} · {len(pages)} exported pages · memories {memory_note}</p>"
        "</header>"
        "<main>"
        "<section class=\"notice\">"
        "<strong>Safe sharing note:</strong> this snapshot contains rendered wiki pages only. "
        "It does not include raw sources, raw captures, live MCP state, operation markers, or the local web server. "
        "Secret-looking wiki contents are blocked before export unless explicitly overridden."
        "</section>"
        f"<p class=\"meta\">Excluded: {int(excluded_counts.get('memories', 0))} memories, "
        f"{int(excluded_counts.get('private_memories', 0))} private memories, "
        f"{int(excluded_counts.get('root', 0))} generated root pages.</p>"
        f"<div class=\"grid\">{''.join(sections)}</div>"
        "</main>"
    )
    return _html_shell(title, body)


def _page_html(page: Mapping[str, Any], body_markdown: str, page_href: Mapping[str, str]) -> str:
    name = str(page.get("name") or "")
    title = str(page.get("title") or name)

    def href_for(target: str) -> str:
        href = page_href.get(target.strip().lower())
        if not href:
            return "#not-in-snapshot"
        return href.removeprefix("pages/")

    rendered = markdown_to_html(body_markdown, page_href=href_for)
    body = (
        "<header>"
        f"<p><a href=\"../index.html\">Link snapshot</a> / {html.escape(str(page.get('category') or 'page'))}</p>"
        f"<div class=\"brand\"><h1>{html.escape(title)}</h1><span>{html.escape(_metadata_line(page))}</span></div>"
        "</header>"
        "<main>"
        f"<article>{rendered}</article>"
        "</main>"
    )
    return _html_shell(title, body, root_prefix="../")


def export_snapshot(
    wiki_dir: Path,
    output_dir: Path,
    *,
    include_memories: bool = False,
    include_private_memories: bool = False,
    allow_sensitive: bool = False,
    force: bool = False,
    title: str = "Link",
    cache: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Export a read-only HTML snapshot of safe wiki pages."""
    wiki_dir = wiki_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not wiki_dir.exists():
        return {"created": False, "error": f"missing wiki directory: {wiki_dir}", "output": str(output_dir)}
    if _is_relative_to(output_dir, wiki_dir):
        return {
            "created": False,
            "error": "snapshot output cannot be inside wiki/",
            "output": str(output_dir),
        }
    if output_dir.exists() and any(output_dir.iterdir()):
        if not force:
            return {
                "created": False,
                "error": "snapshot output directory is not empty; choose another path or use --force",
                "output": str(output_dir),
            }
        shutil.rmtree(output_dir)

    sensitive_values: list[str] = []
    sensitive_read_errors: list[str] = []
    if not allow_sensitive:
        sensitive_values, sensitive_read_errors = find_sensitive_values(
            wiki_dir,
            skip_dirs={".link-operations", ".link-cache", ".link-backups"},
            skip_suffixes={".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".zip", ".gz"},
        )
        if sensitive_values or sensitive_read_errors:
            return {
                "created": False,
                "error": "wiki contains secret-looking values or unreadable files; run lnk doctor before exporting",
                "output": str(output_dir),
                "sensitive_values": sensitive_values,
                "read_errors": sensitive_read_errors,
            }

    owns_cache = cache is None
    resolved_cache = cache or build_wiki_cache(wiki_dir)
    try:
        all_pages = [page for page in list(resolved_cache.get("pages") or []) if isinstance(page, Mapping)]
        meta_index = resolved_cache.get("meta_index") if isinstance(resolved_cache.get("meta_index"), dict) else {}
        included_pages = [
            page for page in all_pages
            if _include_page(
                page,
                include_memories=include_memories,
                include_private_memories=include_private_memories,
                meta_index=meta_index,
            )
        ]
        excluded_counts = {
            "memories": sum(
                1
                for page in all_pages
                if str(page.get("category") or "") == "memories" and page not in included_pages
            ),
            "private_memories": sum(
                1
                for page in all_pages
                if str(page.get("category") or "") == "memories"
                and _memory_visibility(str(page.get("name") or ""), meta_index) == "private"
            ),
            "root": sum(1 for page in all_pages if str(page.get("name") or "").lower() in {"index", "log"}),
        }
        page_href = {
            str(page.get("name") or "").lower(): f"pages/{_page_filename(page.get('name'))}"
            for page in included_pages
        }
        body_index = resolved_cache.get("body_index") if isinstance(resolved_cache.get("body_index"), dict) else {}
        output_dir.mkdir(parents=True, exist_ok=True)
        pages_dir = output_dir / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        assets_dir = output_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        created_at = _utc_now()

        for page in included_pages:
            name = str(page.get("name") or "")
            body = str(body_index.get(name.lower()) or "")
            atomic_write_text(pages_dir / _page_filename(name), _page_html(page, body, page_href))

        atomic_write_text(
            output_dir / "index.html",
            _index_html(
                title=title,
                pages=included_pages,
                page_href=page_href,
                created_at=created_at,
                include_memories=include_memories,
                excluded_counts=excluded_counts,
            ),
        )
        atomic_write_text(assets_dir / "snapshot.css", SNAPSHOT_CSS)
        public_manifest = {
            "schema": SNAPSHOT_SCHEMA,
            "created": True,
            "created_at": created_at,
            "page_count": len(included_pages),
            "include_memories": include_memories,
            "include_private_memories": include_private_memories,
            "excluded_counts": excluded_counts,
            "privacy_note": (
                "Snapshot includes rendered wiki pages only. Raw sources, raw captures, operation markers, "
                "and live MCP state are not exported."
            ),
        }
        atomic_write_json(output_dir / "snapshot.json", public_manifest)
        return public_manifest | {
            "wiki": str(wiki_dir),
            "output": str(output_dir),
            "index": str(output_dir / "index.html"),
        }
    finally:
        if owns_cache:
            close_wiki_cache(resolved_cache)


def render_snapshot_text(payload: Mapping[str, object]) -> tuple[int, str]:
    """Render snapshot export status for CLI users."""
    if not payload.get("created"):
        lines = [
            "Link snapshot: not created",
            "",
            f"Output: {payload.get('output') or ''}",
            f"Reason: {payload.get('error') or 'unknown error'}",
        ]
        sensitive = payload.get("sensitive_values")
        if isinstance(sensitive, list) and sensitive:
            lines.append("")
            lines.append("Secret-looking wiki contents:")
            lines.extend(f"- {item}" for item in sensitive[:8])
        read_errors = payload.get("read_errors")
        if isinstance(read_errors, list) and read_errors:
            lines.append("")
            lines.append("Unreadable files:")
            lines.extend(f"- {item}" for item in read_errors[:8])
        lines.extend(["", "Next:", "  lnk doctor"])
        return 1, "\n".join(lines)

    lines = [
        "Link snapshot created",
        "",
        f"Output: {payload.get('output')}",
        f"Open: {payload.get('index')}",
        f"Pages: {payload.get('page_count')}",
        f"Memories included: {'yes' if payload.get('include_memories') else 'no'}",
        f"Private memories included: {'yes' if payload.get('include_private_memories') else 'no'}",
        "",
        "Safe sharing note:",
        f"  {payload.get('privacy_note')}",
    ]
    if not payload.get("include_memories"):
        lines.extend(["", "To include memory pages intentionally, rerun with --include-memories."])
    return 0, "\n".join(lines)
