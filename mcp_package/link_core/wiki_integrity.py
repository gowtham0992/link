"""Is the compiled wiki still standing on its sources? (`lnk stale --wiki`)

Memories are checked against the repository (staleness.py). The wiki layer
is written by agents from raw sources, and it goes wrong in its own ways,
the ones people building on the LLM-wiki pattern report most: a page keeps
asserting what a source said after the source was edited; a citation points
at nothing; a page cites only other wiki pages, so its claims rest on the
wiki itself rather than on anything a person put in raw/; and concurrent
ingests write the same concept twice under different names.

Every check is deterministic, reads only files, and reports evidence. Like
the memory checks it holds to a precision rule: a finding names a concrete
fact that can be verified by opening two files. Nothing is rewritten;
findings are for a person (or an agent the person asks) to act on.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .frontmatter import parse_frontmatter

# Directories inside wiki/ whose pages are not compiled knowledge.
_SKIP_DIRS = {"memories"}
_SKIP_FILES = {"index.md", "log.md"}
_SOURCE_LINE_RE = re.compile(r"Sources?:\s*((?:\[\[[^\]]+\]\][\s,;and&]*)+)", re.IGNORECASE)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
_SOURCES_SECTION_RE = re.compile(r"^##\s+Sources?\s*$(.*?)(?=^##\s|\Z)", re.IGNORECASE | re.MULTILINE | re.DOTALL)
_WORD_RE = re.compile(r"[a-z0-9]+")
SHINGLE = 5
DUPLICATE_OVERLAP = 0.5


@dataclass
class WikiPage:
    name: str
    rel: str
    kind: str
    title: str
    aliases: list[str]
    body: str
    mtime: float
    citations: list[str] = field(default_factory=list)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


def _citations(body: str) -> list[str]:
    cited: list[str] = []
    for match in _SOURCE_LINE_RE.finditer(body):
        cited += [_norm(link) for link in _WIKILINK_RE.findall(match.group(1))]
    for section in _SOURCES_SECTION_RE.finditer(body):
        cited += [_norm(link) for link in _WIKILINK_RE.findall(section.group(1))]
    return sorted(set(cited))


def load_pages(wiki_dir: Path) -> dict[str, WikiPage]:
    pages: dict[str, WikiPage] = {}
    for path in sorted(wiki_dir.rglob("*.md")):
        rel = path.relative_to(wiki_dir)
        if rel.parts[0] in _SKIP_DIRS or (len(rel.parts) == 1 and rel.name in _SKIP_FILES) or path.name.startswith("."):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            mtime = path.stat().st_mtime
        except OSError:
            continue
        meta, body = parse_frontmatter(text)
        raw_aliases = meta.get("aliases")
        aliases = raw_aliases if isinstance(raw_aliases, list) else []
        kind = str(meta.get("type") or (rel.parts[0].rstrip("s") if len(rel.parts) > 1 else "page"))
        page = WikiPage(name=_norm(path.stem), rel=f"wiki/{rel.as_posix()}", kind=kind,
                        title=str(meta.get("title") or path.stem), aliases=[str(a) for a in aliases],
                        body=body, mtime=mtime)
        page.citations = _citations(body)
        pages[page.name] = page
    return pages


def _shingles(text: str) -> set[tuple[str, ...]]:
    words = _WORD_RE.findall(text.lower())
    return {tuple(words[i:i + SHINGLE]) for i in range(max(0, len(words) - SHINGLE + 1))}


def _duplicates(pages: Iterable[WikiPage]) -> list[dict[str, object]]:
    knowledge = [page for page in pages if page.kind != "source"]
    findings: list[dict[str, object]] = []
    seen: dict[str, WikiPage] = {}
    for page in knowledge:
        for label in [page.title, *page.aliases]:
            key = _norm(label).removesuffix("s")
            other = seen.get(key)
            if other is not None and other.name != page.name:
                findings.append({"kind": "possible-duplicate", "page": page.rel, "other": other.rel,
                                 "evidence": f"both are titled or aliased \"{label}\""})
            seen.setdefault(key, page)
    shingled = [(page, _shingles(page.body)) for page in knowledge]
    named = {(str(f["page"]), str(f["other"])) for f in findings}
    for index, (page, mine) in enumerate(shingled):
        for other, theirs in shingled[index + 1:]:
            if not mine or not theirs or (page.rel, other.rel) in named or (other.rel, page.rel) in named:
                continue
            overlap = len(mine & theirs) / min(len(mine), len(theirs))
            if overlap >= DUPLICATE_OVERLAP:
                findings.append({"kind": "possible-duplicate", "page": other.rel, "other": page.rel,
                                 "evidence": f"{overlap:.0%} of the shorter page's text appears in the other"})
    return findings


def wiki_findings(target: Path) -> dict[str, object]:
    """Integrity findings for the compiled wiki at a Link workspace."""
    from .ingest import collect_ingest_status

    target = target.expanduser().resolve()
    wiki_dir = target / "wiki"
    pages = load_pages(wiki_dir)
    status = collect_ingest_status(target)
    changed: dict[str, str] = {}
    stale_raw = status.get("stale_raw")
    for item in stale_raw if isinstance(stale_raw, list) else []:
        sources = item.get("source_pages") if isinstance(item, dict) and item.get("stale") else None
        for source in sources if isinstance(sources, list) else []:
            changed[_norm(str(source))] = str(item.get("raw") or "")
    findings: list[dict[str, object]] = []
    for page in pages.values():
        if page.kind == "source":
            if page.name in changed:
                findings.append({"kind": "source-changed", "page": page.rel,
                                 "evidence": f"{changed[page.name]} changed after this source page was written"})
            continue
        for cited in page.citations:
            if cited in changed:
                findings.append({"kind": "cites-changed-source", "page": page.rel, "source": cited,
                                 "evidence": f"cites [[{cited}]], whose raw file {changed[cited]} changed after "
                                             "it was compiled; its claims may no longer match"})
            elif cited not in pages:
                findings.append({"kind": "cites-missing-source", "page": page.rel, "source": cited,
                                 "evidence": f"cites [[{cited}]], which is no page in the wiki"})
        cited_pages = [pages[c] for c in page.citations if c in pages]
        if cited_pages and all(c.kind != "source" for c in cited_pages):
            findings.append({"kind": "wiki-only-support", "page": page.rel,
                             "evidence": "every citation is another wiki page ("
                                         + ", ".join(f"[[{c.name}]]" for c in cited_pages)
                                         + "); none reaches a source in raw/"})
    findings += _duplicates(pages.values())
    order = {"cites-changed-source": 0, "source-changed": 1, "cites-missing-source": 2,
             "wiki-only-support": 3, "possible-duplicate": 4}
    findings.sort(key=lambda f: (order.get(str(f["kind"]), 9), str(f["page"])))
    return {"pages_checked": len(pages), "findings": findings}
