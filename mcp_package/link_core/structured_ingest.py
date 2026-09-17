"""Deterministic structured-source ingestion for Link workspaces."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path
from typing import Any

from .files import atomic_write_json, atomic_write_text
from .log import append_log, utc_timestamp
from .validation import validate_wiki
from .wiki import build_backlinks, rebuild_index


CHEZMOI_ADAPTER = "chezmoi-docs-graph-v1"
CHEZMOI_SCHEMA = "chezmoi-documentation-graph-export/v1"
ADAPTER_VERSION = 1


class StructuredIngestError(ValueError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _slugify(value: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")) or "source"


def _group_key(page: dict[str, Any]) -> str:
    navigation_path = page.get("navigation_path")
    if not isinstance(navigation_path, list) or not navigation_path:
        return "Unlisted"
    return " / ".join(str(item) for item in navigation_path[:2])


def _fence(text: str) -> str:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    return "`" * max(4, longest + 1)


def _yaml_strings(values: list[str]) -> str:
    return "[" + ", ".join(json.dumps(value) for value in values) + "]"


def _load_chezmoi_export(source: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    manifest: dict[str, Any] | None = None
    navigation: dict[str, Any] | None = None
    pages: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    try:
        with source.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                record_type = record.get("record_type")
                if record_type == "manifest":
                    manifest = record
                elif record_type == "navigation":
                    navigation = record
                elif record_type == "page":
                    pages.append(record)
                elif record_type == "relationship":
                    relationships.append(record)
                else:
                    raise StructuredIngestError(f"unsupported record_type at line {line_number}: {record_type!r}")
    except json.JSONDecodeError as exc:
        raise StructuredIngestError(f"invalid JSONL at line {exc.lineno}: {exc.msg}") from exc
    if not manifest or manifest.get("schema") != CHEZMOI_SCHEMA:
        actual = manifest.get("schema") if manifest else None
        raise StructuredIngestError(f"adapter {CHEZMOI_ADAPTER} requires schema {CHEZMOI_SCHEMA}; got {actual!r}")
    if not navigation or not pages:
        raise StructuredIngestError("chezmoi export requires one navigation record and at least one page record")
    declared_pages = int(manifest.get("page_count") or 0)
    declared_relationships = int(manifest.get("relationship_count") or 0)
    if declared_pages != len(pages) or declared_relationships != len(relationships):
        raise StructuredIngestError(
            f"manifest counts do not match records: pages {declared_pages}/{len(pages)}, "
            f"relationships {declared_relationships}/{len(relationships)}"
        )
    return manifest, navigation, pages, relationships


def _render_navigation(nodes: list[dict[str, Any]], depth: int = 0) -> list[str]:
    lines: list[str] = []
    for node in nodes:
        title = str(node.get("title") or "Untitled")
        prefix = "  " * depth
        if node.get("type") == "section":
            raw_index = node.get("index_page")
            index_page = raw_index if isinstance(raw_index, dict) else {}
            suffix = f" — index {index_page.get('page_id')}" if index_page.get("page_id") else ""
            lines.append(f"{prefix}- **{title}**{suffix}")
            raw_children = node.get("children")
            children = raw_children if isinstance(raw_children, list) else []
            lines.extend(_render_navigation(children, depth + 1))
        else:
            lines.append(f"{prefix}- {title} — {node.get('page_id', '')}")
    return lines


def _render_chezmoi_pages(
    source_rel: str,
    source_sha256: str,
    manifest: dict[str, Any],
    navigation: dict[str, Any],
    pages: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    excludes: set[str],
) -> tuple[dict[str, str], dict[str, Any]]:
    groups: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for page in sorted(pages, key=lambda item: (item.get("navigation_path") or [], str(item.get("title") or ""))):
        groups.setdefault(_group_key(page), []).append(page)
    unknown_excludes = sorted(excludes.difference(groups))
    if unknown_excludes:
        raise StructuredIngestError("unknown navigation group(s): " + ", ".join(unknown_excludes))
    included_groups = OrderedDict((key, value) for key, value in groups.items() if key not in excludes)
    group_slugs = {key: f"chezmoi-docs-{_slugify(key)}" for key in groups}
    if len(set(group_slugs.values())) != len(group_slugs):
        raise StructuredIngestError("navigation groups produce colliding output names")
    page_groups = {str(page.get("id")): key for key, members in groups.items() for page in members}
    outbound: dict[str, Counter[str]] = defaultdict(Counter)
    inbound: dict[str, Counter[str]] = defaultdict(Counter)
    for relationship in relationships:
        if relationship.get("target_kind") != "internal_page":
            continue
        source_group = page_groups.get(str(relationship.get("source_page_id")))
        target_group = page_groups.get(str(relationship.get("target_page_id")))
        if source_group and target_group and source_group != target_group:
            outbound[source_group][target_group] += 1
            inbound[target_group][source_group] += 1

    outputs: dict[str, str] = {}
    escaped_pages: list[str] = []
    section_rows: list[tuple[str, str, int, int]] = []
    generated_at = str(manifest.get("generated_at") or "")
    ingest_date = generated_at[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", generated_at) else "unknown"
    for group, members in included_groups.items():
        slug = group_slugs[group]
        title = f"chezmoi docs: {group}"
        markdown_bytes = sum(len(str(page.get("markdown") or "")) for page in members)
        urls = sorted(str(page.get("canonical_url") or "") for page in members)
        source_url = min((url for url in urls if url), key=len, default=str(manifest.get("site_origin") or ""))
        tags = list(dict.fromkeys(["chezmoi", "chezmoi-docs", "documentation", *(_slugify(item) for item in group.split(" / "))]))
        lines = [
            "---",
            "type: source",
            f"title: {json.dumps(title)}",
            "source_type: documentation_export",
            f"date_ingested: {ingest_date}",
            f"tags: [{', '.join(tags)}]",
            "confidence: high",
            "project: chezmoi",
            f"raw_path: {source_rel}",
            f"source_url: {json.dumps(source_url)}",
            f"source_repository: {json.dumps(str(manifest.get('source_repository') or ''))}",
            f"source_revision: {json.dumps(str(manifest.get('source_revision') or ''))}",
            f"generated_by: {CHEZMOI_ADAPTER}",
            f"generation_source_sha256: {source_sha256}",
            f"aliases: {_yaml_strings([group.lower(), 'chezmoi ' + group.split(' / ')[-1].lower()])}",
            "---",
            "",
            f"# {title}",
            "",
            f"> **TLDR:** Verbatim chezmoi documentation for the “{group}” navigation section — "
            f"{len(members)} published page{'s' if len(members) != 1 else ''}, {markdown_bytes:,} bytes of Markdown.",
            "",
            "## Summary",
            "",
            f"Section `{group}` of the published chezmoi documentation, deterministically generated from "
            f"`{CHEZMOI_SCHEMA}` at source revision `{str(manifest.get('source_revision') or '')[:12]}`. "
            "Each page body below is upstream Markdown preceded by its canonical URL and source path.",
            "",
            "## Pages",
            "",
        ]
        for page in members:
            body = str(page.get("markdown") or "").rstrip("\n")
            escaped = "[[" in body
            if escaped:
                body = body.replace("[[", "[\\[")
                escaped_pages.append(str(page.get("canonical_url") or ""))
            lines.extend([
                f"### {page.get('title') or 'Untitled'}",
                "",
                f"- Canonical URL: {page.get('canonical_url') or ''}",
                f"- Navigation path: {' → '.join(str(item) for item in page.get('navigation_path') or [])}",
                f"- Source file: `{page.get('source_path') or ''}`",
                f"- Outgoing links: {int(page.get('outgoing_relationship_count') or 0)}",
            ])
            if escaped:
                lines.append("- Note: doubled open brackets are escaped in this rendered page so Link does not treat code samples as wikilinks; the raw export retains exact bytes.")
            fence = _fence(body)
            lines.extend(["", fence + "markdown", body, fence, ""])
        lines.extend(["## Connections", "", "- Part of [[chezmoi-docs-export]]."])
        for target_group, count in outbound[group].most_common(12):
            if target_group in included_groups:
                lines.append(f"- Links out to [[{group_slugs[target_group]}]] ({count} internal link{'s' if count != 1 else ''}).")
        for source_group, count in inbound[group].most_common(8):
            if source_group in included_groups:
                lines.append(f"- Linked to from [[{group_slugs[source_group]}]] ({count} internal link{'s' if count != 1 else ''}).")
        lines.extend(["", "## Raw Source", "", f"`{source_rel}` — records in navigation group `{group}`.", ""])
        path = f"wiki/sources/{slug}.md"
        outputs[path] = "\n".join(lines)
        section_rows.append((group, slug, len(members), markdown_bytes))

    overview = [
        "---",
        "type: source",
        'title: "chezmoi documentation graph export"',
        "source_type: documentation_export",
        f"date_ingested: {ingest_date}",
        "tags: [chezmoi, chezmoi-docs, documentation, graph-export, manifest]",
        "confidence: high",
        "project: chezmoi",
        f"raw_path: {source_rel}",
        f"source_url: {json.dumps(str(manifest.get('site_origin') or ''))}",
        f"source_repository: {json.dumps(str(manifest.get('source_repository') or ''))}",
        f"source_revision: {json.dumps(str(manifest.get('source_revision') or ''))}",
        f"generated_by: {CHEZMOI_ADAPTER}",
        f"generation_source_sha256: {source_sha256}",
        'aliases: ["chezmoi docs export", "chezmoi documentation export", "chezmoi.io export"]',
        "---",
        "",
        "# chezmoi documentation graph export",
        "",
        f"> **TLDR:** Deterministic Link ingest of {len(pages)} chezmoi documentation pages and "
        f"{len(relationships):,} relationships into {len(section_rows)} grouped source pages.",
        "",
        "## Summary",
        "",
        f"{manifest.get('description') or ''} This page records the import policy and provenance. "
        f"The source digest is `{source_sha256}` and adapter version is {ADAPTER_VERSION}.",
        "",
        "## Import policy",
        "",
        f"- Adapter: `{CHEZMOI_ADAPTER}` version {ADAPTER_VERSION}",
        f"- Excluded navigation groups: {', '.join(f'`{item}`' for item in sorted(excludes)) or 'none'}",
        f"- Escaped code-sample pages: {', '.join(f'`{item}`' for item in sorted(set(escaped_pages))) or 'none'}",
        "- Re-ingest is plan-first and refuses unmanaged or manually changed outputs unless explicitly authorized.",
        "",
        "## Section pages",
        "",
        "| Section | Pages | Markdown bytes | Link page |",
        "|---|---:|---:|---|",
    ]
    for group, slug, count, markdown_bytes in sorted(section_rows):
        overview.append(f"| {group} | {count} | {markdown_bytes:,} | [[{slug}]] |")
    overview.extend(["", "## Navigation tree", ""])
    tree = navigation.get("tree")
    overview.extend(_render_navigation(tree if isinstance(tree, list) else []))
    overview.extend(["", "## Connections", ""])
    for group, slug, count, _ in sorted(section_rows):
        overview.append(f"- Contains [[{slug}]] — {group} ({count} page{'s' if count != 1 else ''}).")
    overview.extend(["", "## Raw Source", "", f"`{source_rel}`", ""])
    outputs["wiki/sources/chezmoi-docs-export.md"] = "\n".join(overview)
    return outputs, {
        "manifest": manifest,
        "group_count": len(section_rows),
        "page_count": sum(row[2] for row in section_rows),
        "excluded_groups": sorted(excludes),
        "escaped_pages": sorted(set(escaped_pages)),
    }


def _manifest_path(target: Path, adapter: str, source_rel: str) -> Path:
    source_key = hashlib.sha256(source_rel.encode("utf-8")).hexdigest()[:12]
    return target / ".link-ingest" / f"{adapter}-{source_key}.json"


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StructuredIngestError(f"invalid ingest manifest {path}: {exc}") from exc
    return payload if isinstance(payload, dict) else {}


def plan_structured_ingest(
    target: Path,
    source: Path,
    *,
    adapter: str,
    excludes: list[str] | None = None,
    replace_unmanaged: bool = False,
    prune: bool = False,
) -> dict[str, Any]:
    target = target.expanduser().resolve()
    source = source.expanduser()
    if not source.is_absolute():
        target_candidate = target / source
        source = target_candidate if target_candidate.exists() else source.resolve()
    else:
        source = source.resolve()
    if adapter != CHEZMOI_ADAPTER:
        raise StructuredIngestError(f"unknown adapter: {adapter}; available: {CHEZMOI_ADAPTER}")
    if not source.is_file():
        raise StructuredIngestError(f"source does not exist: {source}")
    try:
        source_rel = source.relative_to(target).as_posix()
    except ValueError as exc:
        raise StructuredIngestError("structured ingest sources must live inside the Link workspace") from exc
    if not source_rel.startswith("raw/"):
        raise StructuredIngestError("structured ingest sources must live under raw/")
    source_bytes = source.read_bytes()
    source_sha256 = _sha256_bytes(source_bytes)
    manifest_record, navigation, pages, relationships = _load_chezmoi_export(source)
    outputs, adapter_summary = _render_chezmoi_pages(
        source_rel,
        source_sha256,
        manifest_record,
        navigation,
        pages,
        relationships,
        set(excludes or []),
    )
    ingest_manifest_path = _manifest_path(target, adapter, source_rel)
    previous = _read_manifest(ingest_manifest_path)
    raw_previous_outputs = previous.get("outputs")
    previous_outputs: dict[str, Any] = raw_previous_outputs if isinstance(raw_previous_outputs, dict) else {}
    changes: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []
    for rel, text in sorted(outputs.items()):
        path = target / rel
        desired_hash = _sha256_text(text)
        if not path.exists():
            changes.append({"path": rel, "action": "create", "desired_sha256": desired_hash})
            continue
        current_hash = _sha256_bytes(path.read_bytes())
        if current_hash == desired_hash:
            changes.append({"path": rel, "action": "unchanged", "desired_sha256": desired_hash})
            continue
        expected_hash = str(previous_outputs.get(rel) or "")
        if expected_hash and current_hash == expected_hash:
            changes.append({"path": rel, "action": "update", "desired_sha256": desired_hash})
        elif replace_unmanaged and not expected_hash:
            changes.append({"path": rel, "action": "replace-unmanaged", "desired_sha256": desired_hash})
        else:
            reason = "modified since the last adapter run" if expected_hash else "existing output is not managed by this adapter"
            conflicts.append({"path": rel, "reason": reason, "current_sha256": current_hash, "expected_sha256": expected_hash})
    stale_paths = sorted(set(str(path) for path in previous_outputs).difference(outputs))
    for rel in stale_paths:
        path = target / rel
        if not path.exists():
            continue
        current_hash = _sha256_bytes(path.read_bytes())
        expected_hash = str(previous_outputs.get(rel) or "")
        if current_hash != expected_hash:
            conflicts.append({"path": rel, "reason": "stale output was manually changed", "current_sha256": current_hash, "expected_sha256": expected_hash})
        elif prune:
            changes.append({"path": rel, "action": "delete", "desired_sha256": ""})
        else:
            changes.append({"path": rel, "action": "retain-stale", "desired_sha256": ""})
    return {
        "adapter": adapter,
        "adapter_version": ADAPTER_VERSION,
        "target": str(target),
        "source": source_rel,
        "source_sha256": source_sha256,
        "manifest_path": ingest_manifest_path.relative_to(target).as_posix(),
        "options": {"exclude": sorted(set(excludes or [])), "prune": prune},
        "summary": adapter_summary,
        "outputs": outputs,
        "output_count": len(outputs),
        "changes": changes,
        "conflicts": conflicts,
        "can_apply": not conflicts,
    }


def apply_structured_ingest(plan: dict[str, Any]) -> dict[str, Any]:
    if plan.get("conflicts"):
        raise StructuredIngestError("ingest plan has conflicts; resolve them or use the explicit replacement option")
    target = Path(str(plan["target"]))
    wiki_dir = target / "wiki"
    if not wiki_dir.exists():
        raise StructuredIngestError(f"missing Link wiki: {wiki_dir}")
    raw_outputs = plan.get("outputs")
    outputs: dict[str, Any] = raw_outputs if isinstance(raw_outputs, dict) else {}
    with tempfile.TemporaryDirectory(prefix="link-structured-ingest-") as temp_dir:
        stage = Path(temp_dir) / "workspace"
        shutil.copytree(target, stage, ignore=shutil.ignore_patterns(".git", ".link-cache", ".link-ingest"))
        stage_wiki = stage / "wiki"
        for change in plan.get("changes") or []:
            rel = str(change.get("path") or "")
            action = str(change.get("action") or "")
            if action == "delete":
                (stage / rel).unlink(missing_ok=True)
            elif action in {"create", "update", "replace-unmanaged", "unchanged"}:
                atomic_write_text(stage / rel, str(outputs[rel]))
        applied_paths = [
            str(change.get("path")) for change in plan.get("changes") or []
            if change.get("action") in {"create", "update", "replace-unmanaged", "delete"}
        ]
        append_log(
            stage_wiki,
            utc_timestamp(),
            "structured-ingest",
            f"{plan['adapter']} | {plan['source']}",
            [
                f"Source sha256: {plan['source_sha256']}",
                f"Adapter version: {plan['adapter_version']}",
                f"Outputs changed: {len(applied_paths)}",
                f"Excluded groups: {', '.join(plan['options']['exclude']) or 'none'}",
            ],
        )
        rebuild_index(stage_wiki)
        atomic_write_json(stage_wiki / "_backlinks.json", build_backlinks(stage_wiki))
        validation = validate_wiki(stage_wiki)
        if not validation.get("passed"):
            raise StructuredIngestError(f"staged wiki failed validation: {validation.get('findings')}")
        commit_paths = set(applied_paths)
        commit_paths.update({"wiki/index.md", "wiki/_backlinks.json", "wiki/log.md"})
        originals: dict[str, bytes | None] = {}
        try:
            for rel in sorted(commit_paths):
                destination = target / rel
                originals[rel] = destination.read_bytes() if destination.exists() else None
                staged = stage / rel
                if staged.exists():
                    atomic_write_text(destination, staged.read_text(encoding="utf-8"))
                else:
                    destination.unlink(missing_ok=True)
            manifest_payload = {
                "schema": "link-structured-ingest/v1",
                "adapter": plan["adapter"],
                "adapter_version": plan["adapter_version"],
                "source": plan["source"],
                "source_sha256": plan["source_sha256"],
                "options": plan["options"],
                "outputs": {rel: _sha256_text(str(text)) for rel, text in sorted(outputs.items())},
                "applied_at": utc_timestamp(),
            }
            atomic_write_json(target / str(plan["manifest_path"]), manifest_payload)
        except Exception:
            for rel, original in originals.items():
                path = target / rel
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(original)
            raise
    return {
        **{key: value for key, value in plan.items() if key != "outputs"},
        "output_count": len(outputs),
        "applied": True,
        "changed_count": len(applied_paths),
        "validation": validation,
    }


def render_structured_ingest_text(result: dict[str, Any]) -> tuple[int, str]:
    lines = [
        f"Link structured ingest: {result['adapter']}",
        "",
        f"Source: {result['source']}",
        f"Source sha256: {result['source_sha256']}",
        # Plans carry the outputs dict; applies drop it and carry the count.
        # Guessing from a summary field here is what crashed text-mode apply.
        f"Outputs: {int(result.get('output_count') or len(result.get('outputs') or {}))}",
    ]
    counts = Counter(str(change.get("action")) for change in result.get("changes") or [])
    if counts:
        lines.append("Plan: " + ", ".join(f"{key}={counts[key]}" for key in sorted(counts)))
    conflicts = result.get("conflicts") or []
    if conflicts:
        lines.extend(["", "Conflicts:"])
        lines.extend(f"- {item['path']}: {item['reason']}" for item in conflicts)
        lines.extend(["", "No files were written."])
        return 1, "\n".join(lines)
    if result.get("applied"):
        lines.extend(["", f"Applied: {result['changed_count']} output changes", "Validation: passed"])
    else:
        lines.extend(["", "Plan only; no files were written.", "Re-run with --apply after reviewing the plan."])
    return 0, "\n".join(lines)
