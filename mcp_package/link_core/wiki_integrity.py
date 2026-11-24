"""Is the compiled wiki still standing on its sources? (`lnk stale --wiki`)

Memories are checked against the repository (staleness.py). The wiki layer
is written by agents from raw sources, and it goes wrong in its own ways,
the ones people building on the LLM-wiki pattern report most: a page keeps
asserting what a source said after the source was edited or deleted; a
citation points at nothing; a page cites only other wiki pages, so its
claims rest on the wiki itself rather than on anything a person put in
raw/; and concurrent ingests write the same concept twice under different
names.

Every check is deterministic, reads only files, and reports evidence. Like
the memory checks it holds to a precision rule: a finding names a concrete
fact that can be verified by opening two files. A changed source is the one
check with only file times to go on (source pages record no checksum of
their raw files), so it names the raw file whose modified time is newer and
says no more: a copy or a `touch` moves that time too. Nothing is
rewritten; findings are for a person (or an agent the person asks) to act on.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .frontmatter import parse_frontmatter

# Directories inside wiki/ whose pages are not compiled knowledge (but are valid link targets).
_SKIP_DIRS = {"memories"}
_SKIP_FILES = {"index.md", "log.md"}
_LINKS = r"((?:\[\[[^\]]+\]\](?:\s*(?:,|;|&|\band\b)\s*|\s*)?)+)"
# "Source: [[a]]", "Sources: [[a]], [[b]] and [[c]]", "**Source:** [[a]]", "**Sources**: [[a]]";
# never the tail of another word ("Resources: [[x]]" is not a citation).
_SOURCE_LINE_RE = re.compile(r"(?<![^\W\d_])Sources?\s*(?:\*\*|__)?\s*:\s*(?:\*\*|__)?\s*" + _LINKS, re.IGNORECASE)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
_SOURCES_SECTION_RE = re.compile(r"^#{2,6}\s+Sources?\s*$(.*?)(?=^#{1,6}\s|\Z)", re.IGNORECASE | re.MULTILINE | re.DOTALL)
_RAW_PATH_RE = re.compile(r"(?<![\w/])raw/[^\s)\]>`'\"|,;*]+\.[A-Za-z0-9]{1,8}\b")
# A raw path may hold spaces ("raw/Meeting notes.md") when something delimits it: backticks, quotes, a
# Markdown link target, or a whole frontmatter value. Bare in prose, it ends at the first space.
_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)^---\s*$", re.DOTALL | re.MULTILINE)
_RAW_EXT = r"\.[A-Za-z0-9]{1,8}"
_MARKDOWN_LINK_RAW_RE = re.compile(r"\]\(\s*<?/?(raw/[^)>\n]+?" + _RAW_EXT + r")>?(?:\s+\"[^\"\n]*\")?\s*\)")
_DELIMITED_RAW_RES = (
    _MARKDOWN_LINK_RAW_RE,
    re.compile(r"`\s*/?(raw/[^`\n]+?" + _RAW_EXT + r")\s*`"),
    re.compile(r"\"/?(raw/[^\"\n]+?" + _RAW_EXT + r")\""),
    re.compile(r"(?<![\w])'/?(raw/[^'\n]+?" + _RAW_EXT + r")'(?![\w])"),
)
_FRONTMATTER_VALUE_RE = re.compile(r"^\s*(?:[\w-]+:|-)\s*/?(raw/(?:(?!raw/)[^\n\"'`,#])+?" + _RAW_EXT + r")\s*$",
                                   re.MULTILINE)
_CODE_RE = re.compile(r"```.*?```|~~~.*?~~~|`[^`\n]*`", re.DOTALL)
_URL_RE = re.compile(r"https?://\S+")
_WORD_RE = re.compile(r"[^\W_]+")
SHINGLE = 5
DUPLICATE_OVERLAP = 0.5
MIN_SHINGLES = 20       # a page this short has too little prose to call it a copy of anything
MIN_SHARED = 10         # and two pages must share at least this much distinctive text
COMMON_SHARE = 0.1      # a shingle on more than this share of pages (and more than 3) is boilerplate


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


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _norm(name: str) -> str:
    """A link target's identity: its last path segment, case-folded, any script, composed (NFC).

    macOS file names often arrive decomposed (NFD) while the same name typed
    in a link is composed; both must reach the same page.
    """
    stem = _nfc(name).strip().replace("\\", "/").rsplit("/", 1)[-1]
    stem = stem[:-3] if stem.lower().endswith(".md") else stem
    return re.sub(r"[\W_]+", "-", stem.casefold()).strip("-")


def _citations(body: str) -> list[str]:
    cited: list[str] = []
    for match in _SOURCE_LINE_RE.finditer(body):
        cited += [_norm(link) for link in _WIKILINK_RE.findall(match.group(1))]
    for section in _SOURCES_SECTION_RE.finditer(body):
        cited += [_norm(link) for link in _WIKILINK_RE.findall(section.group(1))]
    return sorted({c for c in cited if c})


def _read_page(path: Path) -> tuple[dict[str, object], str, float] | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        mtime = path.stat().st_mtime
    except OSError:
        return None
    meta, body = parse_frontmatter(text)
    return meta, body, mtime


def _aliases(meta: dict[str, object]) -> list[str]:
    raw = meta.get("aliases")
    if isinstance(raw, list):
        return [str(a) for a in raw]
    return [str(raw)] if isinstance(raw, str) and raw.strip() else []


@dataclass
class Wiki:
    pages: dict[str, WikiPage]  # knowledge pages, by wiki-relative path
    targets: dict[str, set[str]]  # every link target name (file stem or alias) -> the paths it reaches
    other_kinds: dict[str, str]  # memory pages, index.md, log.md: valid targets, not checked

    def kind_of(self, rel: str) -> str:
        page = self.pages.get(rel)
        return page.kind if page else self.other_kinds.get(rel, "page")


def load_pages(wiki_dir: Path) -> Wiki:
    pages: dict[str, WikiPage] = {}
    targets: dict[str, set[str]] = defaultdict(set)
    other_kinds: dict[str, str] = {}
    if not wiki_dir.exists():
        return Wiki(pages, targets, other_kinds)
    for path in sorted(wiki_dir.rglob("*.md")):
        rel = path.relative_to(wiki_dir)
        # Hidden files and folders (an Obsidian vault's .trash/, .obsidian/) hold no live pages.
        if any(part.startswith(".") for part in rel.parts):
            continue
        rel_text = f"wiki/{rel.as_posix()}"
        checked = not (rel.parts[0] in _SKIP_DIRS or (len(rel.parts) == 1 and rel.name in _SKIP_FILES))
        read = _read_page(path)
        if read is None:
            continue
        meta, body, mtime = read
        aliases = _aliases(meta)
        for label in [path.stem, *aliases]:
            if _norm(label):
                targets[_norm(label)].add(rel_text)
        if not checked:
            other_kinds[rel_text] = "memory" if rel.parts[0] == "memories" else "page"
            continue
        kind = str(meta.get("type") or (rel.parts[0].rstrip("s") if len(rel.parts) > 1 else "page"))
        page = WikiPage(name=_norm(path.stem), rel=rel_text, kind=kind,
                        title=str(meta.get("title") or path.stem), aliases=aliases, body=body, mtime=mtime)
        page.citations = _citations(body)
        pages[rel_text] = page
    return Wiki(pages, targets, other_kinds)


def _prose(body: str) -> str:
    text = _CODE_RE.sub(" ", body)
    text = _URL_RE.sub(" ", text)
    text = _SOURCES_SECTION_RE.sub(" ", text)
    return _WIKILINK_RE.sub(" ", text)


def _shingles(text: str) -> set[tuple[str, ...]]:
    words = [w.casefold() for w in _WORD_RE.findall(_prose(text))]
    return {tuple(words[i:i + SHINGLE]) for i in range(max(0, len(words) - SHINGLE + 1))}


def _duplicates(pages: Iterable[WikiPage]) -> list[dict[str, object]]:
    knowledge = [page for page in pages if page.kind != "source"]
    findings: list[dict[str, object]] = []
    named: set[frozenset[str]] = set()
    seen: dict[str, WikiPage] = {}
    for page in knowledge:
        labels = {_norm(page.title): page.title, page.name: page.name}
        labels.update({_norm(alias): alias for alias in page.aliases})
        for key, label in labels.items():
            if not key:
                continue
            other = seen.get(key)
            if other is not None and other.rel != page.rel and frozenset((page.rel, other.rel)) not in named:
                named.add(frozenset((page.rel, other.rel)))
                findings.append({"kind": "possible-duplicate", "page": page.rel, "other": other.rel,
                                 "evidence": f"both are named, titled or aliased \"{label}\""})
            seen.setdefault(key, page)
    shingled = {page.rel: _shingles(page.body) for page in knowledge}
    postings: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for rel, shingles in shingled.items():
        for shingle in shingles:
            postings[shingle].append(rel)
    common_limit = max(3, int(len(knowledge) * COMMON_SHARE))
    distinctive = {rel: {s for s in shingles if len(postings[s]) <= common_limit} for rel, shingles in shingled.items()}
    shared: Counter[tuple[str, str]] = Counter()
    for shingle, rels in postings.items():
        if 1 < len(rels) <= common_limit:
            for i, first in enumerate(rels):
                for second in rels[i + 1:]:
                    shared[(first, second) if first < second else (second, first)] += 1
    for (first, second), count in sorted(shared.items()):
        smaller = min(len(distinctive[first]), len(distinctive[second]))
        if count < MIN_SHARED or smaller < MIN_SHINGLES or frozenset((first, second)) in named:
            continue
        overlap = count / smaller
        if overlap >= DUPLICATE_OVERLAP:
            findings.append({"kind": "possible-duplicate", "page": second, "other": first,
                             "evidence": f"{overlap:.0%} of the shorter page's distinctive text appears in the other"})
    return findings


def _raw_paths(text: str) -> set[str]:
    """The raw/ paths a source page names, as written (NFC), whether or not they still exist."""
    from urllib.parse import unquote

    found: set[str] = set()
    rest = text
    frontmatter = _FRONTMATTER_RE.match(text)
    if frontmatter:
        found.update(m.strip() for m in _FRONTMATTER_VALUE_RE.findall(frontmatter.group(1)))
        rest = _FRONTMATTER_VALUE_RE.sub(" ", frontmatter.group(1)) + text[frontmatter.end():]
    for pattern in _DELIMITED_RAW_RES:
        for match in pattern.finditer(rest):
            path = match.group(1).strip()
            found.add(unquote(path) if pattern is _MARKDOWN_LINK_RAW_RE else path)
        rest = pattern.sub(" ", rest)
    found.update(m.rstrip(".") for m in _RAW_PATH_RE.findall(rest))
    return {_nfc(path) for path in found}


def _raw_backing(target: Path, wiki_dir: Path) -> tuple[dict[str, tuple[float, str]], dict[str, list[str]]]:
    """(source page name -> (newest mtime, raw file) of the raw files it names,
    source page name -> raw files it names that are gone)."""
    from .ingest import raw_source_files, source_matches_by_raw, source_page_index

    records = {name: {**record, "text": _nfc(str(record.get("text") or ""))}
               for name, record in source_page_index(wiki_dir).items()}
    raw_files = raw_source_files(target / "raw")
    raw_rels = [_nfc(path.relative_to(target).as_posix()) for path in raw_files]
    mtimes: dict[str, float] = {}
    for path, rel in zip(raw_files, raw_rels):
        try:
            mtimes[rel] = path.stat().st_mtime
        except OSError:
            continue
    newest: dict[str, tuple[float, str]] = {}
    for rel, names in source_matches_by_raw(records, raw_rels).items():
        for name in names:
            key = _norm(name)
            newest[key] = max(newest.get(key, (0.0, "")), (mtimes.get(rel, 0.0), rel))
    existing = set(raw_rels)
    gone: dict[str, list[str]] = {}
    for name, record in records.items():
        named = sorted(_raw_paths(str(record.get("text") or "")))
        missing = [rel for rel in named if rel not in existing and not (target / rel).exists()]
        if missing:  # also when another raw file it names is still there
            gone[_norm(name)] = missing
    return newest, gone


def wiki_findings(target: Path) -> dict[str, object]:
    """Integrity findings for the compiled wiki at a Link workspace."""
    target = target.expanduser().resolve()
    wiki_dir = target / "wiki"
    wiki = load_pages(wiki_dir)
    pages, targets = wiki.pages, wiki.targets
    raw_mtime, raw_gone = _raw_backing(target, wiki_dir)
    findings: list[dict[str, object]] = []
    for page in pages.values():
        if page.kind == "source":
            newest, raw = raw_mtime.get(page.name, (0.0, ""))
            if newest > page.mtime + 0.001:
                findings.append({"kind": "source-changed", "page": page.rel, "raw": raw,
                                 "evidence": f"{raw}, which it names, has a newer modified time than this page; "
                                             "if its content changed, the page may no longer match it"})
            if page.name in raw_gone:
                findings.append({"kind": "source-raw-missing", "page": page.rel,
                                 "evidence": "names " + ", ".join(raw_gone[page.name])
                                             + ", which is no longer in raw/; what it took from there has "
                                               "nothing under it"})
            continue
        grounded = False
        resolved_any = False
        for cited in page.citations:
            reached = sorted(targets.get(cited, ()))
            if not reached:
                findings.append({"kind": "cites-missing-source", "page": page.rel, "source": cited,
                                 "evidence": f"cites [[{cited}]], which is no page in the wiki"})
                continue
            resolved_any = True
            kinds = {wiki.kind_of(rel) for rel in reached}
            if kinds & {"source", "memory"}:
                grounded = True
            # By file name or by alias: the raw files are the source page's, under its file name.
            for source in (pages[rel] for rel in reached if rel in pages and pages[rel].kind == "source"):
                newest, raw = raw_mtime.get(source.name, (0.0, ""))
                if newest > page.mtime + 0.001 or newest > source.mtime + 0.001:
                    findings.append({"kind": "cites-changed-source", "page": page.rel, "source": cited, "raw": raw,
                                     "evidence": f"cites [[{cited}]], whose raw file {raw} has a newer modified time "
                                                 "than this page or the source page; if its content changed, "
                                                 "these claims may no longer match"})
                    break
                if source.name in raw_gone:
                    findings.append({"kind": "cites-changed-source", "page": page.rel, "source": cited,
                                     "evidence": f"cites [[{cited}]], whose raw file "
                                                 + ", ".join(raw_gone[source.name]) + " is no longer in raw/"})
                    break
        if resolved_any and not grounded:
            findings.append({"kind": "wiki-only-support", "page": page.rel,
                             "evidence": "every citation is another wiki page ("
                                         + ", ".join(f"[[{c}]]" for c in page.citations if c in targets)
                                         + "); none reaches a source in raw/ or a memory"})
    findings += _duplicates(pages.values())
    order = {"cites-changed-source": 0, "source-changed": 1, "source-raw-missing": 2, "cites-missing-source": 3,
             "wiki-only-support": 4, "possible-duplicate": 5}
    findings.sort(key=lambda f: (order.get(str(f["kind"]), 9), str(f["page"])))
    return {"pages_checked": len(pages), "findings": findings}
