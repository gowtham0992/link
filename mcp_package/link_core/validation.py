"""Wiki validation helpers for Link ingest gates."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from .frontmatter import parse_frontmatter
from .security import secret_value_warnings
from .wiki import WIKILINK_RE, load_backlinks_index


TYPE_DIRECTORIES = {
    "sources": "source",
    "concepts": "concept",
    "entities": "entity",
    "memories": "memory",
    "comparisons": "comparison",
    "explorations": "exploration",
}

REQUIRED_FIELDS = {
    "source": ("type", "title"),
    "concept": ("type", "title"),
    "entity": ("type", "title"),
    "memory": ("type", "title", "memory_type", "scope", "status", "source", "review_status"),
    "comparison": ("type", "title"),
    "exploration": ("type", "title"),
}

REQUIRED_SECTIONS = {
    "source": ("Summary", "Raw Source"),
    "concept": ("Overview", "Sources"),
    "entity": ("Overview", "Sources"),
    "memory": ("Memory", "Source"),
    "comparison": ("Sources",),
    "exploration": ("Answer", "Sources"),
}

SUMMARY_RE = re.compile(r">\s*\*\*(?:TLDR|Query):\*\*", re.IGNORECASE)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _finding(severity: str, code: str, path: str, message: str) -> dict[str, str]:
    return {
        "severity": severity,
        "code": code,
        "path": path,
        "message": message,
    }


def _section_names(body: str) -> set[str]:
    return {
        match.group(1).strip().lower()
        for match in re.finditer(r"^##\s+(.+?)\s*$", body, flags=re.MULTILINE)
    }


def _has_section(body: str, required: str) -> bool:
    names = _section_names(body)
    required_lower = required.lower()
    if required_lower in names:
        return True
    if required_lower == "sources":
        return "sources consulted" in names
    return False


def _markdown_pages(wiki_dir: Path) -> list[Path]:
    if not wiki_dir.exists():
        return []
    return sorted(path for path in wiki_dir.rglob("*.md") if not path.name.startswith("."))


def _normalize_links(index: dict[str, dict[str, list[str]]]) -> dict[str, dict[str, list[str]]]:
    return {
        "backlinks": {
            str(key): sorted(str(item) for item in value)
            for key, value in index.get("backlinks", {}).items()
        },
        "forward": {
            str(key): sorted(str(item) for item in value)
            for key, value in index.get("forward", {}).items()
        },
    }


def _add_links_to_index(
    source: str,
    text: str,
    backlinks: dict[str, list[str]],
    forward_links: dict[str, list[str]],
) -> None:
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


def validate_wiki(wiki_dir: Path, *, strict: bool = False) -> dict[str, Any]:
    """Validate Link wiki structure after agent writes or ingest."""
    wiki_dir = wiki_dir.expanduser().resolve()
    findings: list[dict[str, str]] = []
    required_paths = [
        wiki_dir,
        wiki_dir / "index.md",
        wiki_dir / "log.md",
        wiki_dir / "_backlinks.json",
        *(wiki_dir / dirname for dirname in TYPE_DIRECTORIES),
    ]
    for path in required_paths:
        if not path.exists():
            rel = path.name if path == wiki_dir else path.relative_to(wiki_dir).as_posix()
            findings.append(_finding("error", "missing_required_path", rel, f"Missing required path: {rel}"))

    pages = _markdown_pages(wiki_dir)
    stems = {path.stem.lower() for path in pages}
    unreadable_pages: set[str] = set()
    expected_backlinks: dict[str, dict[str, list[str]]] = {"backlinks": {}, "forward": {}}
    for page in pages:
        rel = page.relative_to(wiki_dir).as_posix()
        try:
            text = page.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            unreadable_pages.add(rel)
            findings.append(_finding("error", "unreadable_page", rel, f"Could not read wiki page: {exc}"))
            continue
        secret_labels = secret_value_warnings(text)
        if secret_labels:
            label = secret_labels[0]
            extra = f" and {len(secret_labels) - 1} more type(s)" if len(secret_labels) > 1 else ""
            findings.append(
                _finding(
                    "error",
                    "secret_value",
                    rel,
                    f"Secret-looking value detected in wiki page ({label}{extra}); redact before serving or querying it.",
                )
            )
        _add_links_to_index(
            page.stem.lower(),
            text,
            expected_backlinks["backlinks"],
            expected_backlinks["forward"],
        )
        if rel in {"index.md", "log.md"}:
            continue
        meta, body = parse_frontmatter(text)
        top_dir = rel.split("/", 1)[0]
        expected_type = TYPE_DIRECTORIES.get(top_dir)
        page_type = str(meta.get("type") or "").strip()

        if not text.startswith("---\n"):
            findings.append(_finding("error", "missing_frontmatter", rel, "Page must start with YAML-style frontmatter."))
        if expected_type is None:
            findings.append(_finding("error", "invalid_directory", rel, "Wiki page is outside a known Link category directory."))
            continue
        if page_type != expected_type:
            findings.append(
                _finding(
                    "error",
                    "type_directory_mismatch",
                    rel,
                    f"Page in {top_dir}/ must declare type: {expected_type}.",
                )
            )

        required_fields = REQUIRED_FIELDS.get(expected_type, ("type", "title"))
        for field in required_fields:
            if not str(meta.get(field) or "").strip():
                findings.append(_finding("error", "missing_frontmatter_field", rel, f"Missing required frontmatter field: {field}"))

        review_after = str(meta.get("review_after") or "").strip().strip('"')
        if expected_type == "memory" and review_after:
            if not DATE_RE.match(review_after):
                findings.append(_finding("error", "invalid_review_after", rel, "review_after must use YYYY-MM-DD."))
            else:
                try:
                    date.fromisoformat(review_after)
                except ValueError:
                    findings.append(_finding("error", "invalid_review_after", rel, "review_after must be a valid calendar date."))

        expires_at = str(meta.get("expires_at") or "").strip().strip('"')
        if expected_type == "memory" and expires_at:
            if not DATE_RE.match(expires_at):
                findings.append(_finding("error", "invalid_expires_at", rel, "expires_at must use YYYY-MM-DD."))
            else:
                try:
                    date.fromisoformat(expires_at)
                except ValueError:
                    findings.append(_finding("error", "invalid_expires_at", rel, "expires_at must be a valid calendar date."))

        if not SUMMARY_RE.search(body):
            findings.append(_finding("warning", "missing_summary", rel, "Page should include a TLDR or Query summary."))

        for section in REQUIRED_SECTIONS.get(expected_type, ()):
            if not _has_section(body, section):
                findings.append(_finding("error", "missing_required_section", rel, f"Missing required section: ## {section}"))

        for match in WIKILINK_RE.finditer(body):
            target = match.group(1).strip().lower()
            if target and target not in stems:
                findings.append(_finding("error", "dead_wikilink", rel, f"Dead wikilink: [[{target}]]"))

    backlinks, backlink_error = load_backlinks_index(
        wiki_dir / "_backlinks.json",
        missing_error="missing wiki/_backlinks.json",
        invalid_prefix="invalid wiki/_backlinks.json",
    )
    if backlink_error:
        findings.append(_finding("error", "invalid_backlinks", "_backlinks.json", backlink_error))
    elif not unreadable_pages:
        if _normalize_links(backlinks) != _normalize_links(expected_backlinks):
            findings.append(_finding("error", "stale_backlinks", "_backlinks.json", "Backlink index is stale; run rebuild-backlinks."))

    error_count = sum(1 for finding in findings if finding["severity"] == "error")
    warning_count = sum(1 for finding in findings if finding["severity"] == "warning")
    passed = error_count == 0 and (warning_count == 0 if strict else True)
    return {
        "wiki": str(wiki_dir),
        "strict": strict,
        "passed": passed,
        "error_count": error_count,
        "warning_count": warning_count,
        "finding_count": len(findings),
        "findings": findings,
    }
