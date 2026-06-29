"""Shared Link runtime status helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from .memory import memory_records
from .operations import pending_operations
from .schema import schema_status
from .validation import validate_wiki
from .wiki import build_wiki_cache, close_wiki_cache


def _action(label: str, tool: str, arguments: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "label": label,
        "tool": tool,
        "arguments": arguments or {},
    }


def _warning(code: str, message: str, exc: Exception) -> dict[str, str]:
    detail = str(exc).strip()
    payload = {
        "code": code,
        "message": message,
    }
    if detail:
        payload["detail"] = detail[:200]
    return payload


def link_status(
    wiki_dir: Path,
    *,
    version: str = "",
    cache: Mapping[str, Any] | None = None,
    records: Iterable[Mapping[str, object]] | None = None,
    include_validation: bool = False,
) -> dict[str, object]:
    """Return a compact readiness summary for agents and local clients."""
    wiki_dir = wiki_dir.expanduser().resolve()
    required_paths = {
        "wiki": wiki_dir,
        "index": wiki_dir / "index.md",
        "log": wiki_dir / "log.md",
        "backlinks": wiki_dir / "_backlinks.json",
        "memories": wiki_dir / "memories",
    }
    missing = [name for name, path in required_paths.items() if not path.exists()]
    pages: list[Mapping[str, object]] = []
    record_list: list[Mapping[str, object]] = []
    warnings: list[dict[str, str]] = []
    search_backend = "unavailable"
    persistent_cache: dict[str, object] = {
        "enabled": False,
        "hit": False,
        "partial": False,
        "reused_records": 0,
        "total_records": 0,
    }
    fts_index: dict[str, object] = {
        "available": False,
        "persistent": False,
        "reused": False,
        "path": "",
    }
    if wiki_dir.exists():
        stale_operations: list[Mapping[str, object]] = []
        fresh_operations: list[Mapping[str, object]] = []
        try:
            for operation in pending_operations(wiki_dir):
                if operation.get("stale"):
                    stale_operations.append(operation)
                else:
                    fresh_operations.append(operation)
            if stale_operations:
                warnings.append({
                    "code": "stale_operations",
                    "message": f"{len(stale_operations)} incomplete Link operation(s) need review.",
                    "detail": str([
                        {
                            "operation": item.get("operation"),
                            "description": item.get("description"),
                            "marker": item.get("marker"),
                        }
                        for item in stale_operations[:5]
                    ]),
                })
            elif fresh_operations:
                warnings.append({
                    "code": "pending_operations",
                    "message": f"{len(fresh_operations)} Link operation(s) are currently in progress.",
                    "detail": str([
                        {
                            "operation": item.get("operation"),
                            "description": item.get("description"),
                            "marker": item.get("marker"),
                        }
                        for item in fresh_operations[:5]
                    ]),
                })
        except Exception as exc:
            warnings.append(_warning(
                "operation_journal_unavailable",
                "Could not inspect Link operation markers.",
                exc,
            ))
        wiki_cache: Mapping[str, Any] | None = None
        owns_cache = False
        try:
            if cache is None:
                wiki_cache = build_wiki_cache(wiki_dir)
                owns_cache = True
            else:
                wiki_cache = cache
            pages = list(wiki_cache.get("pages", []))
            search_backend = str(wiki_cache.get("search_backend") or "token-index")
            fts_info = wiki_cache.get("fts_index_info")
            if isinstance(fts_info, Mapping):
                fts_index = {
                    "available": bool(fts_info.get("available")),
                    "persistent": bool(fts_info.get("persistent")),
                    "reused": bool(fts_info.get("reused")),
                    "path": str(fts_info.get("path") or ""),
                }
            cache_info = wiki_cache.get("persistent_cache")
            if isinstance(cache_info, Mapping):
                persistent_cache = {
                    "enabled": bool(cache_info.get("enabled")),
                    "hit": bool(cache_info.get("hit")),
                    "partial": bool(cache_info.get("partial")),
                    "reused_records": int(cache_info.get("reused_records") or 0),
                    "total_records": int(cache_info.get("total_records") or 0),
                }
            read_warning_count = int(wiki_cache.get("read_warning_count") or 0)
            if read_warning_count:
                warnings.append({
                    "code": "cache_read_warnings",
                    "message": f"{read_warning_count} wiki page(s) could not be read; search and page counts may be incomplete.",
                    "detail": str((wiki_cache.get("read_warnings") or [])[:5]),
                })
        except Exception as exc:
            pages = []
            warnings.append(_warning(
                "cache_unavailable",
                "Could not build the wiki page cache; page counts and search backend may be incomplete.",
                exc,
            ))
        finally:
            if owns_cache and isinstance(wiki_cache, dict):
                close_wiki_cache(wiki_cache)
        try:
            record_list = list(records if records is not None else memory_records(wiki_dir))
        except Exception as exc:
            record_list = []
            warnings.append(_warning(
                "memory_records_unavailable",
                "Could not read memory records; memory counts may be incomplete.",
                exc,
            ))

    validation_summary: dict[str, object] = {"checked": False}
    validation_findings: list[Mapping[str, str]] = []
    if include_validation and wiki_dir.exists():
        validation = validate_wiki(wiki_dir)
        validation_findings = list(validation.get("findings") or [])
        validation_error_codes = sorted({
            str(finding.get("code") or "")
            for finding in validation_findings
            if str(finding.get("severity") or "") == "error"
        })
        validation_warning_codes = sorted({
            str(finding.get("code") or "")
            for finding in validation_findings
            if str(finding.get("severity") or "") == "warning"
        })
        validation_summary = {
            "checked": True,
            "passed": validation["passed"],
            "error_count": validation["error_count"],
            "warning_count": validation["warning_count"],
            "finding_count": validation["finding_count"],
            "error_codes": validation_error_codes,
            "warning_codes": validation_warning_codes,
        }

    active_memory_count = sum(1 for record in record_list if str(record.get("status") or "active").lower() == "active")
    needs_review_count = sum(
        1
        for record in record_list
        if str(record.get("review_status") or "pending").lower() != "reviewed"
        and str(record.get("status") or "active").lower() == "active"
    )
    content_page_count = sum(
        1
        for page in pages
        if str(page.get("path") or "") not in {"wiki/index.md", "wiki/log.md"}
    )
    cache_degraded = any(warning.get("code") in {"cache_unavailable", "cache_read_warnings"} for warning in warnings)
    stale_operation_degraded = any(warning.get("code") == "stale_operations" for warning in warnings)
    ready = not missing and bool(pages) and not cache_degraded and (
        not include_validation or bool(validation_summary.get("passed"))
    ) and not stale_operation_degraded
    schema = schema_status(wiki_dir)

    next_actions: list[dict[str, object]] = []
    if missing:
        next_actions.append(_action("repair or scaffold Link structure", "doctor", {"fix": True}))
    if schema.get("status") in {"missing", "old"}:
        next_actions.append(_action("write current Link wiki schema marker", "admin", {"action": "migrate"}))
    elif schema.get("status") == "invalid":
        next_actions.append(_action("inspect invalid Link wiki schema marker", "doctor"))
    elif schema.get("status") == "newer":
        next_actions.append(_action("upgrade Link before writing this wiki", "upgrade_link"))
    if include_validation and validation_summary.get("checked") and not validation_summary.get("passed"):
        error_codes = set(validation_summary.get("error_codes") or [])
        if error_codes & {"stale_backlinks", "invalid_backlinks"}:
            next_actions.append(_action("rebuild graph index", "ingest", {"action": "rebuild"}))
        if error_codes - {"stale_backlinks", "invalid_backlinks"}:
            next_actions.append(_action("repair validation findings", "doctor", {"fix": True}))
        next_actions.append(_action("rerun validation gate", "ingest", {"action": "validate"}))
    if stale_operation_degraded:
        next_actions.append(_action("inspect interrupted Link operation markers", "doctor"))
        next_actions.append(_action("validate wiki after interrupted operation", "ingest", {"action": "validate"}))
    if ready and content_page_count:
        next_actions.append(_action("answer with compact local context", "recall", {"query": "<user task>", "budget": "micro"}))
        next_actions.append(_action("prime agent memory before work", "recall", {"query": "", "mode": "brief"}))
    elif ready:
        next_actions.append(_action("add raw sources or inspect ingest readiness", "ingest", {"action": "status"}))
        next_actions.append(_action("show first-run prompts", "admin", {"action": "prompts"}))
    elif not missing:
        next_actions.append(_action("inspect wiki health", "ingest", {"action": "validate"}))

    return {
        "ready": ready,
        "version": version,
        "wiki": str(wiki_dir),
        "missing": missing,
        "page_count": len(pages),
        "content_page_count": content_page_count,
        "memory_count": len(record_list),
        "active_memory_count": active_memory_count,
        "needs_review_count": needs_review_count,
        "search_backend": search_backend,
        "fts_index": fts_index,
        "persistent_cache": persistent_cache,
        "schema": schema,
        "validation": validation_summary,
        "warnings": warnings,
        "next_actions": next_actions,
    }
