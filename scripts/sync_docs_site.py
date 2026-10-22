#!/usr/bin/env python3
"""Keep the docs site's shared chrome in one place.

The docs are plain HTML pages with no build step, which is the point: they
ship with the repo and work from a file:// URL. The price is that every page
carries its own copy of the top nav and the docs sidebar. This script is the
single source of truth for both: it stamps the same blocks into every page
(marking the current page) and writes the client-side search index that
``assets/site.js`` loads on demand.

    python3 scripts/sync_docs_site.py          # rewrite the pages and the index
    python3 scripts/sync_docs_site.py --check  # exit 1 if anything is out of date
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
INDEX_PATH = DOCS / "assets" / "search-index.json"
GITHUB = "https://github.com/gowtham0992/link"

# The sidebar, in reading order. Titles here are the short names a sidebar
# needs; each page's <title> stays its own.
GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Start here", [
        ("getting-started.html", "Getting started"),
        ("why-link.html", "Why Link"),
        ("concepts.html", "Concepts"),
    ]),
    ("Use it", [
        ("cli.html", "CLI reference"),
        ("mcp.html", "MCP setup"),
        ("skills.html", "Skills"),
        ("ui.html", "Web UI"),
        ("obsidian.html", "Obsidian"),
        ("troubleshooting.html", "Troubleshooting"),
    ]),
    ("Trust it", [
        ("memory-contract.html", "Memory contract"),
        ("security.html", "Security"),
        ("team-security.html", "Team security"),
        ("scale.html", "Scale"),
    ]),
    ("Project", [
        ("api.html", "HTTP API"),
        ("contributing.html", "Contributing"),
    ]),
]

# The top nav stays short; the sidebar carries the full map.
TOP_LINKS = [
    ("getting-started.html", "Start"),
    ("concepts.html", "Concepts"),
    ("cli.html", "CLI"),
    ("mcp.html", "MCP"),
    ("security.html", "Security"),
    ("contributing.html", "Contribute"),
]

NAV_RE = re.compile(r'<nav class="site-nav"[^>]*>.*?</nav>', re.DOTALL)
SIDEBAR_RE = re.compile(r'\s*<aside class="docs-sidebar"[^>]*>.*?</aside>', re.DOTALL)
GRID_OPEN = '<div class="section-inner doc-grid">'
TAG_RE = re.compile(r"<[^>]+>")
H2_RE = re.compile(r'<h2 id="([^"]+)"[^>]*>(.*?)</h2>', re.DOTALL)
H3_RE = re.compile(r'<h3(?: id="([^"]*)")?[^>]*>(.*?)</h3>', re.DOTALL)
SNIPPET_CHARS = 220
BODY_CHARS = 2400  # matched against, never shown
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL)
EYEBROW_RE = re.compile(r'<span class="eyebrow">(.*?)</span>', re.DOTALL)
LEAD_RE = re.compile(r'<header class="page-hero">.*?<p>(.*?)</p>', re.DOTALL)
TOC_RE = re.compile(r'<aside class="toc">.*?</aside>', re.DOTALL)


def all_pages() -> list[tuple[str, str]]:
    return [page for _, pages in GROUPS for page in pages]


def render_nav(current: str) -> str:
    links = []
    for href, label in TOP_LINKS:
        mark = ' aria-current="page"' if href == current else ""
        links.append(f'      <a href="{href}"{mark}>{label}</a>')
    links.append(f'      <a href="{GITHUB}">GitHub</a>')
    links.append('      <button type="button" class="site-search" aria-label="Search the docs">'
                 'Search <kbd>/</kbd></button>')
    return ('<nav class="site-nav" aria-label="Main">\n'
            '    <a class="brand" href="index.html"><img src="assets/logo.svg" alt="">Link</a>\n'
            '    <div class="nav-links">\n' + "\n".join(links) + "\n    </div>\n  </nav>")


def render_sidebar(current: str) -> str:
    lines = ['      <aside class="docs-sidebar" aria-label="Documentation">',
             '        <button type="button" class="docs-sidebar-toggle" aria-expanded="false">Docs menu</button>',
             '        <div class="docs-sidebar-groups">']
    for group, pages in GROUPS:
        lines.append(f'          <div class="docs-group"><strong>{group}</strong>')
        for href, label in pages:
            mark = ' aria-current="page"' if href == current else ""
            lines.append(f'            <a href="{href}"{mark}>{label}</a>')
        lines.append('          </div>')
    lines.append('        </div>')
    lines.append('      </aside>')
    return "\n".join(lines)


def _text(fragment: str, limit: int) -> str:
    text = html.unescape(TAG_RE.sub(" ", fragment))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0]
        text = cut + "…"
    return text


def index_entry(page: str, label: str, content: str) -> dict[str, object]:
    title_match = TITLE_RE.search(content)
    title = _text(title_match.group(1), 120) if title_match else label
    title = re.sub(r"^Link\s*[-–—]\s*", "", title)
    eyebrow_match = EYEBROW_RE.search(content)
    lead_match = LEAD_RE.search(content)
    body = TOC_RE.sub("", content)
    sections = []
    headings = list(H2_RE.finditer(body))
    for position, match in enumerate(headings):
        end = headings[position + 1].start() if position + 1 < len(headings) else len(body)
        section = body[match.end():end]
        sections.append({
            "id": match.group(1),
            "heading": _text(match.group(2), 120),
            "text": _text(section, SNIPPET_CHARS),
            "body": _text(section, BODY_CHARS),
        })
        # Sub-headings (a command, a field, a tool) get their own hit, so a
        # search for `enforce` lands on the command, not just its chapter.
        subs = list(H3_RE.finditer(section))
        for index, sub in enumerate(subs):
            sub_end = subs[index + 1].start() if index + 1 < len(subs) else len(section)
            sub_text = section[sub.end():sub_end]
            sections.append({
                "id": sub.group(1) or match.group(1),
                "heading": _text(sub.group(2), 120),
                "text": _text(sub_text, SNIPPET_CHARS),
                "body": _text(sub_text, BODY_CHARS),
                "under": _text(match.group(2), 120),
            })
    return {
        "page": page,
        "title": title,
        "label": label,
        "eyebrow": _text(eyebrow_match.group(1), 80) if eyebrow_match else "",
        "lead": _text(lead_match.group(1), 240) if lead_match else "",
        "sections": sections,
    }


def stamp(content: str, page: str) -> str:
    if not NAV_RE.search(content):
        raise SystemExit(f"{page}: no <nav class=\"site-nav\"> to replace")
    content = NAV_RE.sub(lambda _: render_nav(page), content, count=1)
    content = SIDEBAR_RE.sub("", content, count=1)
    if GRID_OPEN not in content:
        raise SystemExit(f"{page}: no {GRID_OPEN} to anchor the sidebar on")
    return content.replace(GRID_OPEN, GRID_OPEN + "\n" + render_sidebar(page), 1)


def build() -> tuple[dict[str, str], str]:
    pages: dict[str, str] = {}
    entries = []
    for page, label in all_pages():
        path = DOCS / page
        if not path.exists():
            raise SystemExit(f"sidebar names a page that does not exist: {page}")
        original = path.read_text(encoding="utf-8")
        stamped = stamp(original, page)
        pages[page] = stamped
        entries.append(index_entry(page, label, stamped))
    index = json.dumps(entries, ensure_ascii=False, indent=1) + "\n"
    return pages, index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="report pages that are out of date; write nothing")
    args = parser.parse_args()
    unlisted = sorted(p.name for p in DOCS.glob("*.html")
                      if p.name != "index.html" and p.name not in {page for page, _ in all_pages()})
    if unlisted:
        print(f"docs pages missing from the sidebar: {', '.join(unlisted)}")
        return 1
    pages, index = build()
    stale = [page for page, content in pages.items() if (DOCS / page).read_text(encoding="utf-8") != content]
    if not INDEX_PATH.exists() or INDEX_PATH.read_text(encoding="utf-8") != index:
        stale.append(INDEX_PATH.name)
    if args.check:
        if stale:
            print("out of date (run scripts/sync_docs_site.py): " + ", ".join(stale))
            return 1
        print("docs site chrome and search index are current")
        return 0
    for page, content in pages.items():
        (DOCS / page).write_text(content, encoding="utf-8")
    INDEX_PATH.write_text(index, encoding="utf-8")
    print(f"stamped {len(pages)} pages, wrote {INDEX_PATH.relative_to(ROOT)}"
          + (f" ({len(stale)} changed)" if stale else " (no changes)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
