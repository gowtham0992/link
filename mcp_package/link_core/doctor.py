"""Shared doctor report helpers for Link health checks."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .capture import capture_records
from .files import atomic_write_json, atomic_write_text
from .frontmatter import parse_frontmatter
from .ingest import collect_ingest_status, raw_ingest_findings
from .log import verify_log_integrity, write_default_log
from .memory import memory_inbox, memory_records
from .operations import pending_operations
from .schema import migrate_wiki
from .schema import schema_status
from .security import find_sensitive_filenames, find_sensitive_values
from .validation import validate_wiki
from .wiki import WIKILINK_RE, build_backlinks, load_backlinks_index, rebuild_index


DOCTOR_VALIDATION_CODES = {
    "invalid_directory",
    "missing_frontmatter",
    "missing_frontmatter_field",
    "missing_required_section",
    "secret_value",
    "type_directory_mismatch",
    "unreadable_page",
}


@dataclass
class DoctorReport:
    """Structured health-check report used by the CLI and future UI/API surfaces."""

    target: str
    fixes: list[str] = field(default_factory=list)
    ok: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    fix_requested: bool = False

    @property
    def healthy(self) -> bool:
        return not self.errors

    def add_ok(self, message: str) -> None:
        self.ok.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def add_error(self, message: str) -> None:
        self.errors.append(message)


def doctor_validation_errors(validation: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return validation findings that should make doctor fail."""
    findings = validation.get("findings", [])
    if not isinstance(findings, list):
        return []
    return [
        finding
        for finding in findings
        if isinstance(finding, dict)
        and finding.get("severity") == "error"
        and str(finding.get("code") or "") in DOCTOR_VALIDATION_CODES
    ]


def format_validation_error_summary(findings: list[Mapping[str, Any]], limit: int = 8) -> str:
    details = [
        f"{finding.get('path')} [{finding.get('code')}] {finding.get('message')}"
        for finding in findings[:limit]
    ]
    return "validation errors: " + "; ".join(details)


def join_limited(prefix: str, values: list[str], limit: int = 8) -> str:
    return prefix + ", ".join(values[:limit])


def wiki_pages(wiki_dir: Path) -> list[Path]:
    return sorted(
        md for md in wiki_dir.rglob("*.md")
        if not md.name.startswith(".")
    )


def required_paths(target: Path) -> list[Path]:
    """Return the required Link workspace paths for doctor/init repair."""
    wiki_dir = target / "wiki"
    raw_dir = target / "raw"
    return [
        raw_dir,
        wiki_dir,
        wiki_dir / "index.md",
        wiki_dir / "log.md",
        wiki_dir / "_backlinks.json",
        wiki_dir / "sources",
        wiki_dir / "concepts",
        wiki_dir / "entities",
        wiki_dir / "memories",
        wiki_dir / "comparisons",
        wiki_dir / "explorations",
    ]


def page_stems(wiki_dir: Path) -> set[str]:
    return {md.stem.lower() for md in wiki_pages(wiki_dir)}


def wiki_page_records(wiki_dir: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for md in wiki_pages(wiki_dir):
        text = md.read_text(encoding="utf-8", errors="replace")
        meta, body = parse_frontmatter(text)
        records.append({
            "path": md,
            "rel": md.relative_to(wiki_dir).as_posix(),
            "stem": md.stem.lower(),
            "meta": meta,
            "body": body,
        })
    return records


def find_dead_links(wiki_dir: Path) -> list[str]:
    stems = page_stems(wiki_dir)
    dead: list[str] = []
    for md in wiki_pages(wiki_dir):
        source = md.stem.lower()
        text = md.read_text(encoding="utf-8", errors="replace")
        for match in WIKILINK_RE.finditer(text):
            target = match.group(1).strip().lower()
            if target and target not in stems:
                dead.append(f"{source} -> {target}")
    return sorted(set(dead))


def find_unindexed_pages(wiki_dir: Path) -> list[str]:
    index_path = wiki_dir / "index.md"
    if not index_path.exists():
        return []
    index_text = index_path.read_text(encoding="utf-8", errors="replace")
    indexed = {m.group(1).strip().lower() for m in WIKILINK_RE.finditer(index_text)}
    roots = {"index", "log"}
    return sorted(stem for stem in page_stems(wiki_dir) if stem not in indexed and stem not in roots)


def find_pages_missing_summaries(wiki_dir: Path) -> list[str]:
    missing: list[str] = []
    for record in wiki_page_records(wiki_dir):
        stem = str(record["stem"])
        if stem in {"index", "log"}:
            continue
        body = str(record["body"])
        if "> **TLDR:**" not in body and "> **Query:**" not in body:
            missing.append(str(record["rel"]))
    return sorted(missing)


def find_pages_missing_source_sections(wiki_dir: Path) -> list[str]:
    missing: list[str] = []
    source_backed_dirs = {"concepts", "entities", "comparisons", "explorations"}
    for record in wiki_page_records(wiki_dir):
        rel = str(record["rel"])
        top_dir = rel.split("/", 1)[0]
        if top_dir not in source_backed_dirs:
            continue
        body = str(record["body"])
        if not re.search(r"^## Sources\b", body, flags=re.MULTILINE):
            missing.append(rel)
    return sorted(missing)


def source_section_links(body: str) -> set[str]:
    match = re.search(r"^## Sources[^\n]*\n(?P<section>.*?)(?=^## |\Z)", body, flags=re.MULTILINE | re.DOTALL)
    if not match:
        return set()
    return {m.group(1).strip().lower() for m in WIKILINK_RE.finditer(match.group("section"))}


def find_source_count_mismatches(wiki_dir: Path) -> list[str]:
    mismatches: list[str] = []
    for record in wiki_page_records(wiki_dir):
        rel = str(record["rel"])
        if rel.split("/", 1)[0] == "sources":
            continue
        meta = record["meta"]
        if not isinstance(meta, dict) or "source_count" not in meta:
            continue
        try:
            expected = int(str(meta["source_count"]))
        except ValueError:
            mismatches.append(f"{rel} has non-integer source_count")
            continue
        actual = len(source_section_links(str(record["body"])))
        if expected != actual:
            mismatches.append(f"{rel} source_count={expected}, sources section has {actual}")
    return sorted(mismatches)


def find_isolated_pages(wiki_dir: Path) -> list[str]:
    stems = page_stems(wiki_dir)
    records = wiki_page_records(wiki_dir)
    graph = build_backlinks(wiki_dir, body_only=False)
    isolated: list[str] = []
    for record in records:
        stem = str(record["stem"])
        if stem in {"index", "log"}:
            continue
        inbound = [name for name in graph["backlinks"].get(stem, []) if name in stems and name != stem]
        outgoing = [name for name in graph["forward"].get(stem, []) if name in stems and name != stem]
        if not inbound and not outgoing:
            isolated.append(str(record["rel"]))
    return sorted(isolated)


def raw_source_refs(text: str) -> list[str]:
    refs: list[str] = []
    for pattern in (r"`(raw/[^`\n]+)`", r"(?<![\w/])(raw/[^\s`<>()]+)"):
        for match in re.finditer(pattern, text):
            value = match.group(1).strip().rstrip(".,;:]")
            if value and value not in refs:
                refs.append(value)
    return refs


def body_with_tldr(body: str, title: str) -> str:
    if re.search(r">\s*\*\*(?:TLDR|Query):\*\*", body, flags=re.IGNORECASE):
        return body
    summary = f"> **TLDR:** {title} source notes.\n\n"
    heading = re.search(r"^#\s+.+\n", body, flags=re.MULTILINE)
    if heading:
        return body[: heading.end()] + "\n" + summary + body[heading.end():].lstrip("\n")
    return summary + body.lstrip("\n")


def append_section(body: str, title: str, content: str) -> str:
    return body.rstrip() + f"\n\n## {title}\n\n{content.strip()}\n"


def repair_source_page_validation_shape(page: Path, findings: list[dict[str, str]]) -> bool:
    text = page.read_text(encoding="utf-8", errors="replace")
    frontmatter_match = re.match(r"\A---\n.*?\n---\n?", text, flags=re.DOTALL)
    if not frontmatter_match:
        return False
    prefix = frontmatter_match.group(0).rstrip("\n") + "\n\n"
    meta, body = parse_frontmatter(text)
    if not isinstance(meta, dict) or str(meta.get("type") or "").strip() != "source":
        return False
    title = str(meta.get("title") or page.stem).strip() or page.stem
    messages = [str(finding.get("message") or "") for finding in findings]
    codes = {str(finding.get("code") or "") for finding in findings}
    changed = False

    if "missing_summary" in codes:
        updated = body_with_tldr(body, title)
        changed = changed or updated != body
        body = updated

    if any("## Summary" in message for message in messages):
        body = append_section(body, "Summary", f"{title} source notes.")
        changed = True

    if any("## Raw Source" in message for message in messages):
        refs = raw_source_refs(text)
        if refs:
            body = append_section(body, "Raw Source", f"`{refs[0]}`")
            changed = True

    if changed:
        atomic_write_text(page, prefix + body.rstrip() + "\n")
    return changed


def repair_validation_findings(wiki_dir: Path) -> list[str]:
    payload = validate_wiki(wiki_dir)
    findings_by_path: dict[str, list[dict[str, str]]] = {}
    for finding in payload.get("findings", []):
        if not isinstance(finding, dict):
            continue
        path = str(finding.get("path") or "")
        code = str(finding.get("code") or "")
        if not path.startswith("sources/"):
            continue
        if code != "missing_summary" and code != "missing_required_section":
            continue
        findings_by_path.setdefault(path, []).append(finding)

    fixes: list[str] = []
    for rel, findings in sorted(findings_by_path.items()):
        page = wiki_dir / rel
        try:
            repaired = repair_source_page_validation_shape(page, findings)
        except OSError:
            repaired = False
        if repaired:
            fixes.append(f"repaired validation shape for wiki/{rel}")
    return fixes


def _normalize_link_index(data: dict[str, dict[str, list[str]]]) -> dict[str, dict[str, list[str]]]:
    normalized: dict[str, dict[str, list[str]]] = {"backlinks": {}, "forward": {}}
    for section in ("backlinks", "forward"):
        for key, values in data.get(section, {}).items():
            if isinstance(values, list):
                normalized[section][key.lower()] = sorted({str(value).lower() for value in values})
    return normalized


def _backlinks_need_rebuild(wiki_dir: Path, backlinks_path: Path) -> tuple[bool, dict[str, dict[str, list[str]]]]:
    current, load_error = load_backlinks_index(
        backlinks_path,
        missing_error="missing wiki/_backlinks.json",
        invalid_prefix="invalid wiki/_backlinks.json",
    )
    expected = build_backlinks(wiki_dir, body_only=False)
    if load_error or _normalize_link_index(current) != _normalize_link_index(expected):
        return True, expected
    return False, expected


def apply_doctor_fixes(target: Path) -> list[str]:
    """Repair missing generated Link workspace files and return human-readable changes."""
    target = target.expanduser().resolve()
    wiki_dir = target / "wiki"
    fixes: list[str] = []

    for path in required_paths(target):
        if path.suffix:
            continue
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            fixes.append(f"created {path.relative_to(target)}")

    log_path = wiki_dir / "log.md"
    if not log_path.exists():
        write_default_log(log_path)
        fixes.append("created wiki/log.md")

    if not wiki_dir.exists():
        return fixes

    index_path = wiki_dir / "index.md"
    index_missing = not index_path.exists()
    unindexed = [] if index_missing else find_unindexed_pages(wiki_dir)
    if index_missing or unindexed:
        rebuild_index(wiki_dir)
        fixes.append("created wiki/index.md" if index_missing else "rebuilt wiki/index.md")

    backlinks_path = wiki_dir / "_backlinks.json"
    needs_rebuild, expected = _backlinks_need_rebuild(wiki_dir, backlinks_path)
    if needs_rebuild:
        atomic_write_json(backlinks_path, expected)
        fixes.append("rebuilt wiki/_backlinks.json")

    migration = migrate_wiki(wiki_dir)
    if not migration["ok"]:
        fixes.append(f"schema migration skipped: {migration['error']}")
    else:
        fixes.extend(f"schema: {item}" for item in migration["changes"])

    validation_repairs = repair_validation_findings(wiki_dir)
    fixes.extend(validation_repairs)
    if validation_repairs:
        needs_rebuild, expected = _backlinks_need_rebuild(wiki_dir, backlinks_path)
        if needs_rebuild:
            atomic_write_json(backlinks_path, expected)
            fixes.append("rebuilt wiki/_backlinks.json")

    return fixes


def build_doctor_report(
    target: Path,
    *,
    fix: bool = False,
    skip_dirs: set[str] | None = None,
    secret_name_patterns: tuple[str, ...] = (),
    skip_suffixes: set[str] | None = None,
) -> DoctorReport:
    """Build the full Link doctor report without rendering it."""
    target = target.expanduser().resolve()
    wiki_dir = target / "wiki"
    raw_dir = target / "raw"
    skip_dirs = skip_dirs or set()
    skip_suffixes = skip_suffixes or set()
    report = DoctorReport(str(target), fix_requested=fix)
    if fix:
        report.fixes = apply_doctor_fixes(target)

    required = required_paths(target)
    missing = [str(path.relative_to(target)) for path in required if not path.exists()]
    if missing:
        report.add_error("missing required paths: " + ", ".join(missing))
    else:
        report.add_ok("OK required wiki structure")

    if wiki_dir.exists():
        pages = wiki_pages(wiki_dir)
        report.add_ok(f"OK markdown pages: {len(pages)}")

        dead_links = find_dead_links(wiki_dir)
        if dead_links:
            report.add_error(join_limited("dead wikilinks: ", dead_links))
        else:
            report.add_ok("OK no dead wikilinks")

        unindexed = find_unindexed_pages(wiki_dir)
        if unindexed:
            report.add_warning(join_limited("pages missing from index: ", unindexed))
        else:
            report.add_ok("OK index lists wiki pages")

        current, load_error = load_backlinks_index(
            wiki_dir / "_backlinks.json",
            missing_error="missing wiki/_backlinks.json",
            invalid_prefix="invalid wiki/_backlinks.json",
        )
        if load_error:
            report.add_error(load_error)
        else:
            expected = build_backlinks(wiki_dir, body_only=False)
            if _normalize_link_index(current) != _normalize_link_index(expected):
                report.add_error("wiki/_backlinks.json is stale; run: python3 link.py rebuild-backlinks .")
            else:
                report.add_ok("OK backlinks are current")

        schema = schema_status(wiki_dir)
        if schema["status"] == "current":
            report.add_ok(f"OK wiki schema v{schema['version']}")
        elif schema["status"] in {"missing", "old"}:
            report.add_warning("wiki schema marker needs migration; run: link migrate")
        elif schema["status"] == "newer":
            report.add_error(str(schema["error"]))
        else:
            report.add_error(str(schema["error"] or "invalid wiki schema marker"))

        operations = pending_operations(wiki_dir)
        stale_operations = [item for item in operations if item.get("stale")]
        active_operations = [item for item in operations if not item.get("stale")]
        if stale_operations:
            details = [
                f"{item.get('operation')} ({item.get('marker')})"
                for item in stale_operations[:8]
            ]
            report.add_error("incomplete Link operations need review: " + ", ".join(details))
        elif active_operations:
            details = [
                f"{item.get('operation')} ({item.get('marker')})"
                for item in active_operations[:8]
            ]
            report.add_warning("Link operation in progress: " + ", ".join(details))
        else:
            report.add_ok("OK no interrupted Link operations")

        log_integrity = verify_log_integrity(wiki_dir)
        if log_integrity.get("passed"):
            hashed_count = int(log_integrity.get("hashed_entries") or 0)
            if hashed_count:
                report.add_ok(f"OK audit log hash chain ({hashed_count} entries)")
            else:
                report.add_ok("OK audit log readable")
        else:
            findings = [
                str(item)
                for item in log_integrity.get("findings", [])
                if item
            ]
            report.add_error(join_limited("audit log hash chain broken: ", findings))

        missing_summaries = find_pages_missing_summaries(wiki_dir)
        if missing_summaries:
            report.add_warning(join_limited("pages missing TLDR/query summary: ", missing_summaries))
        else:
            report.add_ok("OK wiki pages have summaries")

        missing_sources = find_pages_missing_source_sections(wiki_dir)
        if missing_sources:
            report.add_warning(join_limited("source-backed pages missing Sources section: ", missing_sources))
        else:
            report.add_ok("OK source-backed pages cite sources")

        source_count_mismatches = find_source_count_mismatches(wiki_dir)
        if source_count_mismatches:
            report.add_warning(join_limited("source_count metadata mismatch: ", source_count_mismatches))
        else:
            report.add_ok("OK source_count metadata matches Sources sections")

        validation = validate_wiki(wiki_dir)
        validation_errors = doctor_validation_errors(validation)
        if validation_errors:
            report.add_error(format_validation_error_summary(validation_errors))
        else:
            report.add_ok("OK ingest validation gate")

        isolated = find_isolated_pages(wiki_dir)
        if isolated:
            report.add_warning(join_limited("isolated wiki pages: ", isolated))
        else:
            report.add_ok("OK graph has no isolated wiki pages")

        memory_review = memory_inbox(memory_records(wiki_dir), limit=8, include_archived=True)
        if memory_review["review_count"]:
            names = ", ".join(str(item["name"]) for item in memory_review["items"][:8])
            report.add_warning(f"memories need review: {names}")
        else:
            report.add_ok("OK memories are reviewed")

        captures = capture_records(target, limit=50)
        capture_warning_count = sum(1 for capture in captures if capture["warning_count"])
        if captures:
            report.add_warning(f"raw memory captures pending review: {len(captures)}")
        else:
            report.add_ok("OK no raw memory captures pending review")
        if capture_warning_count:
            report.add_warning(f"raw memory captures with secret warnings: {capture_warning_count}")

    findings = raw_ingest_findings(collect_ingest_status(target, skip_dirs=skip_dirs))
    if findings["blocked"]:
        report.add_warning(join_limited("raw files blocked before ingest: ", findings["blocked"]))
    if findings["stale"]:
        report.add_warning(join_limited("raw files need source refresh: ", findings["stale"]))
    if findings["new"]:
        report.add_warning(join_limited("raw files not referenced by wiki source pages: ", findings["new"]))
    if not any(findings.values()) and raw_dir.exists():
        report.add_ok("OK raw files are represented in wiki sources")

    sensitive_names = find_sensitive_filenames(
        target,
        skip_dirs=skip_dirs,
        patterns=secret_name_patterns,
    )
    if sensitive_names:
        report.add_error(join_limited("sensitive-looking filenames present: ", sensitive_names))
    else:
        report.add_ok("OK no sensitive-looking filenames")

    sensitive_values, sensitive_read_errors = find_sensitive_values(
        target,
        skip_dirs=skip_dirs,
        skip_suffixes=skip_suffixes,
    )
    if sensitive_values:
        report.add_error(join_limited("sensitive-looking file contents present: ", sensitive_values))
    else:
        report.add_ok("OK no sensitive-looking file contents")
    if sensitive_read_errors:
        report.add_error(join_limited("could not scan file contents for secrets: ", sensitive_read_errors))

    return report


def render_doctor_report(report: DoctorReport) -> str:
    """Render a doctor report using the stable CLI text format."""
    lines = [f"Link doctor: {report.target}", ""]
    if report.fix_requested:
        if report.fixes:
            lines.append("Fixes applied:")
            lines.extend(f"- {item}" for item in report.fixes)
            lines.append("")
        else:
            lines.append("Fixes applied: none")
            lines.append("")

    lines.extend(report.ok)

    if report.warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in report.warnings)

    if report.errors:
        lines.append("")
        lines.append("Errors:")
        lines.extend(f"- {error}" for error in report.errors)
        lines.append("")
        lines.append("Result: needs attention")
    else:
        lines.append("")
        lines.append("Result: healthy")

    return "\n".join(lines)
