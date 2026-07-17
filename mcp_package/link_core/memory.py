"""Shared memory logic for Link CLI, HTTP, and MCP runtimes."""
from __future__ import annotations

import fnmatch
import re
import urllib.parse
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path

from .consolidate import memory_backlog_summary
from .files import atomic_write_text
from .semantic import semantic_confidence_cap, semantic_match_points
from .security import looks_like_password_note, secret_value_warnings
from .frontmatter import (
    csv_values,
    frontmatter_int,
    frontmatter_string,
    meta_tags,
    parse_frontmatter,
    update_frontmatter_fields,
    yaml_list,
)
from .mcp_verify import display_command
from .log import redact_log_references
from .operations import operation_journal
from .wiki import (
    WIKILINK_RE,
    build_backlinks,
    load_backlinks_index,
)


MEMORY_TYPES = ("preference", "decision", "project", "fact", "note", "procedure")
MEMORY_SCOPES = ("user", "project", "global")
MEMORY_VISIBILITIES = ("private", "project", "team")
MEMORY_REVIEW_STATUSES = ("pending", "reviewed", "needs_update")
MEMORY_PROPOSAL_MIN_SCORE = 70
MEMORY_RECALL_MIN_SCORE = 2
MEMORY_CONFLICT_TYPES = {"preference", "decision", "project"}
MEMORY_STOPWORDS = {
    "about",
    "after",
    "agent",
    "agents",
    "also",
    "and",
    "are",
    "because",
    "before",
    "being",
    "does",
    "done",
    "for",
    "from",
    "has",
    "have",
    "into",
    "link",
    "memory",
    "more",
    "not",
    "now",
    "our",
    "prefer",
    "prefers",
    "project",
    "should",
    "that",
    "the",
    "their",
    "this",
    "use",
    "user",
    "users",
    "want",
    "wants",
    "when",
    "with",
    "work",
}
NEGATION_TERMS = {
    "avoid",
    "disable",
    "disabled",
    "disallow",
    "dont",
    "don't",
    "never",
    "no",
    "not",
    "without",
}
CONFLICT_OPTION_GROUPS = {
    "branch_policy": {"codex", "develop", "development", "direct", "feature", "main", "master", "release"},
    "storage_policy": {"cloud", "hosted", "local", "offline", "remote"},
    "theme": {"dark", "light", "system"},
    "install_method": {"brew", "global", "homebrew", "pipx", "system", "venv", "virtualenv"},
    "release_channel": {"github", "mcp", "pypi"},
}
CONFLICT_GROUP_CONTEXT = {
    "branch_policy": {"branch", "branches", "commit", "commits", "git", "merge", "pr", "pull", "push"},
    "storage_policy": {"agent", "agents", "backend", "data", "memory", "storage", "sync", "wiki"},
    "theme": {"background", "mode", "theme", "ui"},
    "install_method": {"install", "installer", "mcp", "package", "pip", "python", "setup"},
    "release_channel": {"package", "publish", "registry", "release", "version"},
}
MEMORY_QUERY_EQUIVALENTS = (
    {"auth", "authentication", "authorization", "login", "signin", "sign-in", "oauth", "sso"},
    {"setup", "install", "installation", "configure", "configuration", "onboarding", "bootstrap"},
    {"release", "publish", "publishing", "version", "tag", "pypi", "registry"},
    {"branch", "branches", "pr", "pull", "merge", "develop", "main"},
    {"agent", "assistant", "llm", "model", "copilot", "codex", "claude", "cursor"},
    {"memory", "remember", "recall", "preference", "context", "profile"},
    {"ui", "ux", "interface", "web", "viewer", "dashboard"},
    {"fast", "speed", "latency", "performance", "quick", "responsive"},
)
MemoryLogWriter = Callable[[str, str, str, list[str]], None]
BacklinkRebuilder = Callable[[], bool]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def slugify(value: str, fallback: str = "memory", max_len: int = 80) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if len(slug) > max_len:
        # Cap for filesystem limits (255-byte filenames); cut at a word
        # boundary so truncated slugs stay readable.
        head = slug[:max_len]
        slug = head.rsplit("-", 1)[0] if "-" in head else head
    return slug or fallback


def normalize_project(value: str | None) -> str:
    return slugify(value or "", fallback="")


def default_memory_visibility(scope: str) -> str:
    """Return the safest sharing visibility for a memory scope."""
    return "project" if scope == "project" else "private"


def normalize_memory_visibility(scope: str, visibility: object | None = None) -> str:
    value = str(visibility or "").strip().lower()
    if not value:
        return default_memory_visibility(scope)
    if value not in MEMORY_VISIBILITIES:
        raise ValueError(f"visibility must be one of: {', '.join(MEMORY_VISIBILITIES)}")
    return value


def default_project_for_target(target: Path) -> str:
    resolved = target.expanduser().resolve()
    if resolved.name == "wiki" and (resolved / "index.md").exists():
        resolved = resolved.parent
    if (resolved / ".git").exists():
        return normalize_project(resolved.name)
    return ""


def memory_title(text: str, explicit_title: str | None = None) -> str:
    if explicit_title and explicit_title.strip():
        return explicit_title.strip()
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "Memory")
    # Numbered steps ("1. Run the script ...") would otherwise title the
    # memory "1" — the enumeration marker is not the sentence.
    first_line = re.sub(r"^(?:\d+[.)]\s+|step\s+\d+\s*[:.]\s*)", "", first_line, flags=re.IGNORECASE) or first_line
    first_sentence = re.split(r"(?<=[.!?])\s+", first_line, maxsplit=1)[0].strip()
    if len(first_sentence) <= 70:
        return first_sentence.rstrip(".")
    return first_sentence[:67].rstrip() + "..."


def memory_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", value.lower())
        if len(token) >= 3
    }


def compact_memory_text(value: str) -> str:
    return " ".join(
        token
        for token in re.split(r"[^a-z0-9]+", value.lower())
        if token
    )


def significant_memory_tokens(value: str) -> set[str]:
    return {
        token
        for token in memory_tokens(value)
        if token not in MEMORY_STOPWORDS
    }


def stem_memory_token(token: str) -> str:
    """Light deterministic suffix stemming so close paraphrases still match.

    Intentionally tiny: no dictionaries, no language models, no external
    services. Enough to make "committing" match "commit" and "answers"
    match "answer" without changing Link's local-first story.
    """
    for suffix in ("ing", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)]
    return token


def stemmed_memory_tokens(tokens: set[str]) -> set[str]:
    return {stem_memory_token(token) for token in tokens}


def memory_recall_confidence(record: Mapping[str, object], query: str) -> str:
    """Classify how strongly a recalled memory matches the query.

    Lexical recall can surface a memory on one incidental shared word. The
    confidence label lets agents treat weak matches as hints to verify with
    the user instead of facts to act on.

    - strong: the query appears verbatim in the title/TLDR, or every
      significant query token appears in the memory head (title/TLDR/tags).
    - moderate: at least half of the significant query tokens appear
      anywhere in the memory, or a significant query token appears in the
      title (the intent-bearing summary of the memory).
    - weak: everything else that still crossed the recall score floor.
    """
    q = query.lower().strip()
    significant = stemmed_memory_tokens(significant_memory_tokens(q))
    title = str(record.get("title", "")).lower()
    tldr = str(record.get("tldr", "")).lower()
    tags = " ".join(str(tag).lower() for tag in record.get("tags", []))
    trigger = str(record.get("trigger") or "").lower()
    if trigger:
        tldr = f"{tldr} {trigger}".strip()
    body = str(record.get("body", "")).lower()
    if q and (q in title or q in tldr):
        return "strong"
    if not significant:
        return "weak"
    title_tokens = stemmed_memory_tokens(memory_tokens(title))
    head_tokens = title_tokens | stemmed_memory_tokens(
        memory_tokens(tldr) | memory_tokens(tags)
    )
    all_tokens = head_tokens | stemmed_memory_tokens(memory_tokens(body))
    if significant <= head_tokens:
        return "strong"
    coverage = len(significant & all_tokens) / len(significant)
    if coverage >= 0.5:
        return "moderate"
    if significant & title_tokens:
        return "moderate"
    return "weak"


def expanded_memory_query_tokens(value: str) -> set[str]:
    """Return query tokens plus small local synonyms for agent-memory recall.

    This is intentionally tiny and deterministic. It catches common developer
    paraphrases without adding embeddings, model calls, or external services.
    """
    tokens = significant_memory_tokens(value)
    expanded = set(tokens)
    for group in MEMORY_QUERY_EQUIVALENTS:
        if tokens & group:
            expanded.update(group)
    return expanded


def has_negation(value: str) -> bool:
    compact = compact_memory_text(value)
    tokens = set(compact.split())
    if tokens & NEGATION_TERMS:
        return True
    return bool(re.search(r"\b(?:do not|does not|did not|should not|don't|can't|cannot)\b", value, re.IGNORECASE))


def _extract_option_groups(value: str) -> dict[str, set[str]]:
    tokens = memory_tokens(value)
    groups: dict[str, set[str]] = {}
    for group, options in CONFLICT_OPTION_GROUPS.items():
        matches = tokens & options
        if matches:
            groups[group] = matches
    return groups


def _extract_preference_pairs(value: str) -> list[tuple[set[str], set[str]]]:
    pairs: list[tuple[set[str], set[str]]] = []
    patterns = (
        r"\bprefer(?:s|red)?\s+(?P<preferred>.+?)\s+over\s+(?P<rejected>.+?)(?:[.;]|$)",
        r"\buse\s+(?P<preferred>.+?)\s+instead\s+of\s+(?P<rejected>.+?)(?:[.;]|$)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, value, flags=re.IGNORECASE):
            preferred = significant_memory_tokens(match.group("preferred"))
            rejected = significant_memory_tokens(match.group("rejected"))
            if preferred and rejected:
                pairs.append((preferred, rejected))
    return pairs


def slim_memory(record: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in record.items() if key not in {"body", "context"}}


def memory_claim_text(record: Mapping[str, object]) -> str:
    """The memory's core claim: head fields plus the `## Memory` section.

    Similarity checks (duplicates, conflicts, echoes) must compare claims,
    not whole pages: the page template's boilerplate sections dilute token
    overlap and let real duplicates and contradictions slip through.
    """
    return " ".join([
        str(record.get("title") or ""),
        str(record.get("tldr") or ""),
        str(record.get("snippet") or ""),
        procedure_steps_excerpt(str(record.get("body") or ""), max_chars=1200),
    ])


def procedure_steps_excerpt(body: str, max_chars: int = 800) -> str:
    """Bounded steps text for a procedure memory (its Memory section)."""
    text = str(body or "")
    marker = "## Memory"
    start = text.find(marker)
    if start >= 0:
        start += len(marker)
        end = text.find("\n## ", start)
        text = text[start:end] if end > start else text[start:]
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + " …"
    return text


def is_active_memory(record: Mapping[str, object]) -> bool:
    return str(record.get("status") or "active").lower() not in {"archived", "stale"} and not memory_expired(record)


def _parse_date_field(value: object, field: str) -> date | None:
    text = str(value or "").strip().strip('"')
    if not text:
        return None
    if not DATE_RE.match(text):
        raise ValueError(f"{field} must use YYYY-MM-DD")
    return date.fromisoformat(text)


def _parse_review_date(value: object) -> date | None:
    return _parse_date_field(value, "review_after")


def _parse_expires_date(value: object) -> date | None:
    return _parse_date_field(value, "expires_at")


def _today(today: str | None = None) -> date:
    return _parse_review_date(today) if today else date.today()


def memory_active_at(record: Mapping[str, object], as_of: str) -> bool:
    """Whether this memory was active on a given YYYY-MM-DD date.

    Reconstructs history from existing lifecycle fields: capture date,
    archive date (supersession archives the predecessor), and expiry.
    Archived records without an archive date cannot be placed in time and
    are treated as inactive.
    """
    day = _parse_date_field(as_of, "as_of")
    captured = _memory_date(record.get("date_captured"))
    if captured is not None and captured.date() > day:
        return False
    if str(record.get("status") or "active").lower() == "archived":
        archived = _memory_date(record.get("archived_at"))
        if archived is None or archived.date() <= day:
            return False
    if memory_expired(record, today=as_of):
        return False
    return True


def memory_expired(record: Mapping[str, object], today: str | None = None) -> bool:
    """Return true when a memory has passed its optional expiry date."""
    try:
        expires = _parse_expires_date(record.get("expires_at"))
    except ValueError:
        return False
    return expires is not None and expires <= _today(today)


def memory_visible_for_project(record: Mapping[str, object], project: str | None = None) -> bool:
    project_name = normalize_project(project)
    if not project_name:
        return True
    if str(record.get("scope") or "").lower() != "project":
        return True
    record_project = normalize_project(str(record.get("project") or ""))
    return not record_project or record_project == project_name


def extract_tldr(body: str) -> str:
    match = re.search(r">\s*\*\*TLDR:\*\*\s*(.+)", body)
    return match.group(1).strip() if match else ""


def first_body_snippet(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith(">"):
            return stripped[:200]
    return ""


def _heading_title(body: str) -> str:
    match = re.search(r"^#\s+(.+)", body, re.MULTILINE)
    return match.group(1).strip() if match else ""


def memory_record_from_page(wiki_dir: Path, path: Path, include_body: bool = True) -> dict[str, object]:
    wiki_root = wiki_dir.expanduser().resolve()
    path = path.expanduser().resolve()
    text = path.read_text(encoding="utf-8", errors="replace")
    meta, body = parse_frontmatter(text)
    title = meta.get("title") or _heading_title(body) or memory_title(body) or path.stem
    scope = str(meta.get("scope") or "user").lower()
    try:
        visibility = normalize_memory_visibility(scope, meta.get("visibility"))
    except ValueError:
        visibility = str(meta.get("visibility") or "")
    record: dict[str, object] = {
        "name": path.stem,
        "path": f"wiki/{path.relative_to(wiki_root).as_posix()}",
        "title": title,
        "memory_type": meta.get("memory_type") or "note",
        "scope": scope,
        "visibility": visibility,
        "project": normalize_project(str(meta.get("project", ""))),
        "status": meta.get("status") or "active",
        "date_captured": meta.get("date_captured", ""),
        "updated_at": meta.get("updated_at", ""),
        "update_count": meta.get("update_count", "0"),
        "last_update_source": meta.get("last_update_source", ""),
        "archived_at": meta.get("archived_at", ""),
        "archive_reason": meta.get("archive_reason", ""),
        "restored_at": meta.get("restored_at", ""),
        "source": meta.get("source", ""),
        "review_status": meta.get("review_status") or "pending",
        "reviewed_at": meta.get("reviewed_at", ""),
        "review_after": meta.get("review_after", ""),
        "expires_at": meta.get("expires_at", ""),
        "review_note": meta.get("review_note", ""),
        "trigger": str(meta.get("trigger") or ""),
        "context": str(meta.get("context") or ""),
        "applies_when": str(meta.get("applies_when") or ""),
        "supersedes": str(meta.get("supersedes") or ""),
        "superseded_by": str(meta.get("superseded_by") or ""),
        "tags": meta_tags(meta.get("tags", "")),
        "tldr": extract_tldr(body),
        "snippet": first_body_snippet(body),
    }
    if include_body:
        record["body"] = body
    return record


def memory_records(wiki_dir: Path, include_body: bool = True) -> list[dict[str, object]]:
    memories_dir = wiki_dir / "memories"
    if not memories_dir.exists():
        return []
    records: list[dict[str, object]] = []
    for path in sorted(memories_dir.rglob("*.md")):
        if path.name.startswith("."):
            continue
        records.append(memory_record_from_page(wiki_dir, path, include_body=include_body))
    return records


def memory_review_issues(
    record: Mapping[str, object],
    review_command: str = "review-memory",
    today: str | None = None,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    status = str(record.get("status") or "active").lower()
    review_status = str(record.get("review_status") or "pending").lower()
    memory_type = str(record.get("memory_type") or "")
    scope = str(record.get("scope") or "")
    visibility = str(record.get("visibility") or default_memory_visibility(scope))

    if review_status in {"pending", "needs_review"}:
        issues.append({
            "code": "pending_review",
            "severity": "medium",
            "message": "Memory has not been reviewed by the user.",
            "suggested_action": f"Confirm it is still accurate, then run {review_command}.",
        })
    elif review_status == "needs_update":
        issues.append({
            "code": "needs_update",
            "severity": "high",
            "message": "Memory is marked as needing an update.",
            "suggested_action": "Edit the memory page or archive it if it is no longer useful.",
        })
    elif review_status not in MEMORY_REVIEW_STATUSES:
        issues.append({
            "code": "invalid_review_status",
            "severity": "high",
            "message": f"Unknown review_status: {review_status}.",
            "suggested_action": "Use pending, reviewed, or needs_update.",
        })
    review_after = str(record.get("review_after") or "").strip()
    if review_after:
        try:
            due = _parse_review_date(review_after)
        except ValueError as exc:
            issues.append({
                "code": "invalid_review_after",
                "severity": "high",
                "message": str(exc),
                "suggested_action": "Use a YYYY-MM-DD date or remove review_after.",
            })
        else:
            if status == "active" and due is not None and due <= _today(today):
                issues.append({
                    "code": "review_due",
                    "severity": "medium",
                    "message": f"Memory review is due after {review_after}.",
                    "suggested_action": f"Confirm it is still accurate, then run {review_command}.",
                })

    expires_at = str(record.get("expires_at") or "").strip()
    if expires_at:
        try:
            expires = _parse_expires_date(expires_at)
        except ValueError as exc:
            issues.append({
                "code": "invalid_expires_at",
                "severity": "high",
                "message": str(exc),
                "suggested_action": "Use a YYYY-MM-DD date or remove expires_at.",
            })
        else:
            if status == "active" and expires is not None and expires <= _today(today):
                issues.append({
                    "code": "expired",
                    "severity": "high",
                    "message": f"Memory expired at {expires_at} and is excluded from default recall.",
                    "suggested_action": "Update it with a new expiry date, archive it, or delete it after confirmation.",
                })

    applies_when = str(record.get("applies_when") or "").strip()
    if applies_when:
        try:
            parse_applies_when(applies_when)
        except ValueError:
            issues.append({
                "code": "invalid_applies_when",
                "severity": "high",
                "message": (
                    f"applies_when has invalid syntax: {applies_when!r}. The memory is treated "
                    "as out of context everywhere until the condition is fixed."
                ),
                "suggested_action": (
                    "Edit the memory frontmatter to use project:<slug>, path:<glob>, or "
                    "task:<phrase> conditions (comma-separated), or remove applies_when."
                ),
            })

    if status == "stale":
        issues.append({
            "code": "stale_status",
            "severity": "high",
            "message": "Memory is marked stale and is excluded from default recall.",
            "suggested_action": "Archive it, restore it, or update the memory text.",
        })
    if memory_type not in MEMORY_TYPES:
        issues.append({
            "code": "invalid_memory_type",
            "severity": "high",
            "message": f"Unknown memory_type: {memory_type or 'missing'}.",
            "suggested_action": f"Use one of: {', '.join(MEMORY_TYPES)}.",
        })
    if scope not in MEMORY_SCOPES:
        issues.append({
            "code": "invalid_scope",
            "severity": "high",
            "message": f"Unknown scope: {scope or 'missing'}.",
            "suggested_action": f"Use one of: {', '.join(MEMORY_SCOPES)}.",
        })
    if visibility not in MEMORY_VISIBILITIES:
        issues.append({
            "code": "invalid_visibility",
            "severity": "high",
            "message": f"Unknown visibility: {visibility or 'missing'}.",
            "suggested_action": f"Use one of: {', '.join(MEMORY_VISIBILITIES)}.",
        })
    if not str(record.get("source") or "").strip():
        issues.append({
            "code": "missing_source",
            "severity": "medium",
            "message": "Memory has no source metadata.",
            "suggested_action": "Add source metadata so future agents know why this memory exists.",
        })
    if not str(record.get("date_captured") or "").strip():
        issues.append({
            "code": "missing_date_captured",
            "severity": "medium",
            "message": "Memory has no date_captured metadata.",
            "suggested_action": "Add the capture timestamp or recreate the memory.",
        })
    if not (str(record.get("tldr") or "").strip() or str(record.get("snippet") or "").strip()):
        issues.append({
            "code": "missing_summary",
            "severity": "medium",
            "message": "Memory has no usable summary.",
            "suggested_action": "Add a TLDR line or a clear first paragraph.",
        })
    return issues


def _tool_name(command: str) -> str:
    return command.replace("-", "_")


def _cli_command(command: str) -> str:
    return command.replace("_", "-")


def _memory_action(
    *,
    kind: str,
    label: str,
    description: str,
    command: str,
    tool: str,
    arguments: Mapping[str, object],
    priority: str,
) -> dict[str, object]:
    return {
        "kind": kind,
        "label": label,
        "description": description,
        "command": command,
        "tool": tool,
        "arguments": dict(arguments),
        "priority": priority,
    }


def memory_action_hints(
    record: Mapping[str, object],
    issues: Iterable[Mapping[str, str]] | None = None,
    review_command: str = "review-memory",
    command_target: str | Path = ".",
) -> list[dict[str, object]]:
    """Return ordered actions for resolving or auditing one memory."""
    name = str(record.get("name") or "")
    path = str(record.get("path") or f"wiki/memories/{name}.md")
    status = str(record.get("status") or "active").lower()
    issue_list = [dict(issue) for issue in issues] if issues is not None else memory_review_issues(record, review_command)
    issue_codes = {str(issue.get("code") or "") for issue in issue_list}
    review_cli = _cli_command(review_command)
    review_tool = _tool_name(review_command)
    actions: list[dict[str, object]] = []
    seen: set[str] = set()

    def add(action: dict[str, object]) -> None:
        kind = str(action["kind"])
        if kind in seen:
            return
        actions.append(action)
        seen.add(kind)

    if status == "archived":
        add(_memory_action(
            kind="restore",
            label="Restore",
            description="Restore this archived memory to active recall if it is valid again.",
            command=_shell_words("python3", "link.py", "restore-memory", name, command_target),
            tool="restore_memory",
            arguments={"identifier": name},
            priority="high",
        ))
        add(_memory_action(
            kind="explain",
            label="Explain",
            description="Inspect why this memory exists before restoring it.",
            command=_shell_words("python3", "link.py", "explain-memory", name, command_target),
            tool="explain_memory",
            arguments={"identifier": name},
            priority="medium",
        ))
        add(_memory_action(
            kind="forget",
            label="Forget",
            description="Permanently delete only after explicit user confirmation.",
            command=_shell_words("python3", "link.py", "forget-memory", name, command_target, "--confirm"),
            tool="forget_memory",
            arguments={"identifier": name, "confirm": True},
            priority="low",
        ))
        return actions

    if issue_codes & {
        "invalid_review_status",
        "invalid_review_after",
        "invalid_expires_at",
        "invalid_memory_type",
        "invalid_scope",
        "missing_source",
        "missing_date_captured",
    }:
        add(_memory_action(
            kind="edit_metadata",
            label="Edit metadata",
            description="Fix the Markdown frontmatter, then run review again.",
            command=f'$EDITOR "{path}"',
            tool="edit_memory_file",
            arguments={"path": path},
            priority="high",
        ))
    if issue_codes & {"needs_update", "missing_summary"}:
        add(_memory_action(
            kind="update",
            label="Update",
            description="Merge corrected memory text and reset review to pending.",
            command=_shell_words("python3", "link.py", "update-memory", name, "new detail", command_target),
            tool="update_memory",
            arguments={"identifier": name, "memory": "new detail"},
            priority="high",
        ))
    if issue_codes & {"stale_status", "expired"}:
        reason = "expired" if "expired" in issue_codes else "stale"
        add(_memory_action(
            kind="archive",
            label="Archive",
            description="Archive this memory so default recall ignores it.",
            command=_shell_words("python3", "link.py", "archive-memory", name, command_target, "--reason", reason),
            tool="archive_memory",
            arguments={"identifier": name, "reason": reason},
            priority="high",
        ))
    if issue_codes & {"pending_review", "review_due"} and not any(
        issue.get("severity") == "high" for issue in issue_list
    ):
        add(_memory_action(
            kind="review",
            label="Review",
            description="Mark this memory reviewed after the user confirms it is accurate.",
            command=_shell_words("python3", "link.py", review_cli, name, command_target),
            tool=review_tool,
            arguments={"identifier": name},
            priority="high",
        ))

    add(_memory_action(
        kind="explain",
        label="Explain",
        description="Audit provenance, graph links, lifecycle, and review state.",
        command=_shell_words("python3", "link.py", "explain-memory", name, command_target),
        tool="explain_memory",
        arguments={"identifier": name},
        priority="medium",
    ))
    if "update" not in seen:
        add(_memory_action(
            kind="update",
            label="Update",
            description="Merge a corrected detail into this memory.",
            command=_shell_words("python3", "link.py", "update-memory", name, "new detail", command_target),
            tool="update_memory",
            arguments={"identifier": name, "memory": "new detail"},
            priority="medium",
        ))
    if "archive" not in seen:
        add(_memory_action(
            kind="archive",
            label="Archive",
            description="Hide this memory from default recall without deleting the Markdown file.",
            command=_shell_words("python3", "link.py", "archive-memory", name, command_target, "--reason", "why"),
            tool="archive_memory",
            arguments={"identifier": name, "reason": "why"},
            priority="medium",
        ))
    add(_memory_action(
        kind="forget",
        label="Forget",
        description="Permanently delete only after explicit user confirmation.",
        command=_shell_words("python3", "link.py", "forget-memory", name, command_target, "--confirm"),
        tool="forget_memory",
        arguments={"identifier": name, "confirm": True},
        priority="low",
    ))
    return actions


def primary_memory_action(actions: Iterable[Mapping[str, object]]) -> dict[str, object] | None:
    action_list = [dict(action) for action in actions]
    if not action_list:
        return None
    for action in action_list:
        if str(action.get("priority") or "") == "high":
            return action
    return action_list[0]


def memory_log_entries(
    wiki_dir: Path,
    record: Mapping[str, object],
    limit: int = 8,
) -> list[str]:
    try:
        parsed_limit = int(limit)
    except (TypeError, ValueError):
        parsed_limit = 8
    limit = max(1, min(parsed_limit, 50))
    log_path = wiki_dir / "log.md"
    if not log_path.exists():
        return []
    text = log_path.read_text(encoding="utf-8", errors="replace")
    name = str(record.get("name") or "")
    needles = {name, str(record.get("title") or "")}
    if name:
        needles.add(f"memories/{name}.md")
    needles = {needle.lower() for needle in needles if needle}
    blocks = [block.strip() for block in re.split(r"\n---\n", text) if block.strip()]
    matches = [
        block for block in blocks
        if any(needle in block.lower() for needle in needles)
    ]
    return matches[-limit:]


def extract_wikilinks(text: str) -> list[str]:
    links: list[str] = []
    for match in WIKILINK_RE.finditer(text):
        target = match.group(1).strip()
        if target and target not in links:
            links.append(target)
    return links


def recall_state(
    record: Mapping[str, object],
    issues: list[Mapping[str, str]],
) -> dict[str, object]:
    default_enabled = is_active_memory(record)
    high_issues = [issue for issue in issues if str(issue.get("severity") or "") == "high"]
    if not default_enabled:
        state = "disabled"
        if memory_expired(record):
            reason = f"Memory expired at {record.get('expires_at')}; default recall excludes expired memories."
        else:
            reason = f"Memory status is {record.get('status')}; default recall excludes archived and stale memories."
    elif high_issues:
        state = "unsafe"
        reason = "Memory is active but has high-severity quality issues."
    elif issues:
        state = "needs_review"
        reason = "Memory is active but still needs review or stronger metadata."
    else:
        state = "ready"
        reason = "Memory is active, reviewed, and has no detected quality issues."
    return {
        "default_enabled": default_enabled,
        "state": state,
        "reason": reason,
    }


def memory_explanation(
    wiki_dir: Path,
    identifier: str,
    records: Iterable[Mapping[str, object]] | None = None,
    review_command: str = "review-memory",
    backlinks_body_only: bool = True,
    command_target: str | Path = ".",
) -> dict[str, object]:
    record_list = [dict(record) for record in records] if records is not None else memory_records(wiki_dir)
    page_path, resolved_record, error = resolve_memory_page(wiki_dir, identifier, records=record_list)
    if error:
        raise ValueError(error)
    assert page_path is not None and resolved_record is not None

    record = next(
        (
            item for item in record_list
            if str(item.get("name") or "") == str(resolved_record.get("name") or "")
        ),
        dict(resolved_record),
    )
    text = page_path.read_text(encoding="utf-8", errors="replace")
    _, body = parse_frontmatter(text)
    issues = memory_review_issues(record, review_command=review_command)
    actions = memory_action_hints(
        record,
        issues=issues,
        review_command=review_command,
        command_target=command_target,
    )
    backlinks, backlinks_error = load_backlinks_index(wiki_dir / "_backlinks.json")
    if backlinks_error:
        backlinks = build_backlinks(wiki_dir, body_only=backlinks_body_only)
    name = str(record["name"])
    graph = {
        "forward": sorted(backlinks.get("forward", {}).get(name, [])),
        "inbound": sorted(backlinks.get("backlinks", {}).get(name, [])),
        "wikilinks": extract_wikilinks(body),
    }
    lineage: list[dict[str, str]] = []
    by_name = {str(item.get("name") or ""): item for item in record_list}
    seen_chain: set[str] = set()
    cursor = record
    while cursor is not None and str(cursor.get("supersedes") or "") and len(lineage) < 10:
        previous_name = str(cursor.get("supersedes"))
        if previous_name in seen_chain:
            break
        seen_chain.add(previous_name)
        previous = by_name.get(previous_name)
        lineage.insert(0, {
            "name": previous_name,
            "title": str(previous.get("title")) if previous else "",
            "status": str(previous.get("status")) if previous else "missing",
            "relation": "superseded",
        })
        cursor = previous
    lineage.append({
        "name": name,
        "title": str(record.get("title") or ""),
        "status": str(record.get("status") or "active"),
        "relation": "current" if not str(record.get("superseded_by") or "") else "superseded",
    })
    cursor = record
    while cursor is not None and str(cursor.get("superseded_by") or "") and len(lineage) < 12:
        next_name = str(cursor.get("superseded_by"))
        if next_name in seen_chain:
            break
        seen_chain.add(next_name)
        successor = by_name.get(next_name)
        lineage.append({
            "name": next_name,
            "title": str(successor.get("title")) if successor else "",
            "status": str(successor.get("status")) if successor else "missing",
            "relation": "successor",
        })
        cursor = successor

    return {
        "found": True,
        "memory": slim_memory(record),
        "lineage": lineage if len(lineage) > 1 else [],
        "recall": recall_state(record, issues),
        "review": {
            "status": record.get("review_status", "pending"),
            "reviewed_at": record.get("reviewed_at", ""),
            "review_note": record.get("review_note", ""),
            "issues": issues,
            "issue_count": len(issues),
            "actions": actions,
            "primary_action": primary_memory_action(actions),
        },
        "provenance": {
            "source": record.get("source", ""),
            "date_captured": record.get("date_captured", ""),
            "path": record.get("path", ""),
        },
        "lifecycle": {
            "status": record.get("status", "active"),
            "archived_at": record.get("archived_at", ""),
            "archive_reason": record.get("archive_reason", ""),
            "restored_at": record.get("restored_at", ""),
            "expires_at": record.get("expires_at", ""),
        },
        "graph": graph,
        "log_entries": memory_log_entries(wiki_dir, record),
        "body": body,
    }


def resolve_memory_page(
    wiki_dir: Path,
    identifier: str,
    records: Iterable[Mapping[str, object]] | None = None,
    max_identifier_len: int | None = None,
) -> tuple[Path | None, dict[str, object] | None, str | None]:
    needle = str(identifier or "").strip()
    if max_identifier_len is not None:
        needle = needle[:max_identifier_len]
    if not needle:
        return None, None, "memory name or title is required"

    memories_dir = wiki_dir / "memories"
    direct_candidates: list[Path] = []
    raw_path = Path(needle)
    if raw_path.suffix == ".md" or "/" in needle:
        rel = Path(needle.removeprefix("wiki/"))
        direct_candidates.append((wiki_dir / rel).resolve())
        direct_candidates.append((memories_dir / raw_path.name).resolve())
    else:
        direct_candidates.append((memories_dir / f"{needle}.md").resolve())
        direct_candidates.append((memories_dir / f"{slugify(needle)}.md").resolve())

    record_list = [dict(record) for record in records] if records is not None else None
    memories_root = memories_dir.resolve()
    for candidate in direct_candidates:
        try:
            candidate.relative_to(memories_root)
        except ValueError:
            continue
        if candidate.exists() and candidate.is_file():
            if record_list is None:
                return candidate, memory_record_from_page(wiki_dir, candidate), None
            record = next(
                (record for record in record_list if str(record.get("name") or "") == candidate.stem),
                None,
            )
            return candidate, dict(record) if record else None, None

    lowered = needle.lower()
    slug = slugify(needle)
    if record_list is None:
        record_list = memory_records(wiki_dir)
    matches = [
        dict(record) for record in record_list
        if lowered in {str(record.get("name") or "").lower(), str(record.get("title") or "").lower()}
        or slug == str(record.get("name") or "").lower()
    ]
    if len(matches) > 1:
        names = ", ".join(str(record.get("name") or "") for record in matches[:5])
        return None, None, f"memory identifier is ambiguous: {names}"
    if not matches:
        return None, None, f"memory not found: {identifier}"
    record = matches[0]
    return wiki_dir / str(record["path"]).removeprefix("wiki/"), record, None


def unique_page_path(directory: Path, slug: str) -> Path:
    candidate = directory / f"{slug}.md"
    index = 2
    while candidate.exists():
        candidate = directory / f"{slug}-{index}.md"
        index += 1
    return candidate


def write_default_index(index_path: Path) -> None:
    atomic_write_text(
        index_path,
        "# Link Wiki Index\n\n"
        "> Last updated: not yet ingested | 0 pages | 0 sources\n\n"
        "## Categories\n\n"
        "## Recent\n\n"
        "| Date | Operation | Pages Touched |\n"
        "|------|-----------|---------------|\n",
    )


def update_memory_index(
    index_path: Path,
    page_name: str,
    title: str,
    summary: str,
    memory_type: str,
    scope: str,
) -> None:
    if not index_path.exists():
        write_default_index(index_path)
    text = index_path.read_text(encoding="utf-8", errors="replace")
    if f"[[{page_name}]]" in text:
        return
    entry = f"- [[{page_name}]] - {summary} {memory_type} · {scope}\n"
    if "### memories" in text:
        pattern = re.compile(r"(### memories\n)(.*?)(?=\n### |\n## Recent|\Z)", flags=re.DOTALL)
        text = pattern.sub(lambda m: m.group(1) + m.group(2).rstrip() + "\n" + entry, text, count=1)
    elif "\n## Recent" in text:
        text = text.replace("\n## Recent", f"\n### memories\n{entry}\n## Recent", 1)
    else:
        text = text.rstrip() + f"\n\n### memories\n{entry}"
    atomic_write_text(index_path, text)


def remove_memory_from_index(index_path: Path, page_name: str) -> bool:
    if not index_path.exists():
        return False
    text = index_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    filtered = [line for line in lines if f"[[{page_name}]]" not in line]
    if len(filtered) == len(lines):
        return False
    atomic_write_text(index_path, "\n".join(filtered).rstrip() + "\n")
    return True


def replace_markdown_body(text: str, body: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            return text[:end + 4] + "\n\n" + body.strip() + "\n"
    return body.strip() + "\n"


def append_memory_update(body: str, update_text: str, timestamp: str, source: str) -> str:
    source_label = source.strip() or "manual"
    update_block = f"Update ({timestamp}, {source_label}):\n\n{update_text.strip()}"
    pattern = re.compile(r"(## Memory\n)(.*?)(?=\n## |\Z)", flags=re.DOTALL)
    match = pattern.search(body)
    if not match:
        return body.rstrip() + f"\n\n## Memory\n\n{update_block}\n"
    existing = match.group(2).rstrip()
    merged = (existing + "\n\n" if existing else "") + update_block + "\n\n"
    return body[:match.start(2)] + merged + body[match.end(2):]


def set_memory_status(
    wiki_dir: Path,
    identifier: str,
    status: str,
    reason: str | None,
    timestamp: str,
    records: Iterable[Mapping[str, object]] | None = None,
    log_writer: MemoryLogWriter | None = None,
) -> dict[str, object]:
    page_path, record, error = resolve_memory_page(wiki_dir, identifier, records=records)
    if error:
        raise ValueError(error)
    assert page_path is not None and record is not None

    current_status = str(record.get("status") or "active")
    clean_reason = reason.strip() if reason else ""
    if status == "archived":
        updates = {
            "status": "archived",
            "archived_at": f'"{timestamp}"',
        }
        if clean_reason:
            updates["archive_reason"] = f'"{frontmatter_string(clean_reason)}"'
        remove = {"restored_at"}
        operation = "archive-memory"
    elif status == "active":
        updates = {
            "status": "active",
            "restored_at": f'"{timestamp}"',
        }
        remove = {"archived_at", "archive_reason"}
        operation = "restore-memory"
    else:
        raise ValueError("unsupported memory status")

    changed = current_status != status
    if changed:
        with operation_journal(
            wiki_dir,
            operation,
            str(record["title"]),
            timestamp=timestamp,
            paths=[f"wiki/memories/{page_path.name}", "wiki/log.md"],
        ):
            text = page_path.read_text(encoding="utf-8", errors="replace")
            atomic_write_text(page_path, update_frontmatter_fields(text, updates, remove=remove))
            if log_writer:
                log_lines = [
                    f"Updated: memories/{page_path.name}",
                    f"Previous status: {current_status}",
                    f"New status: {status}",
                ]
                if clean_reason:
                    log_lines.append(f"Reason: {clean_reason}")
                log_writer(timestamp, operation, str(record["title"]), log_lines)

    return {
        "updated": changed,
        "name": record["name"],
        "path": record["path"],
        "title": record["title"],
        "previous_status": current_status,
        "status": status,
    }


def set_memory_visibility(
    wiki_dir: Path,
    identifier: str,
    visibility: str,
    timestamp: str,
    records: Iterable[Mapping[str, object]] | None = None,
    log_writer: MemoryLogWriter | None = None,
) -> dict[str, object]:
    page_path, record, error = resolve_memory_page(wiki_dir, identifier, records=records)
    if error:
        raise ValueError(error)
    assert page_path is not None and record is not None

    scope = str(record.get("scope") or "user").lower()
    clean_visibility = normalize_memory_visibility(scope, visibility)
    previous_visibility = str(record.get("visibility") or default_memory_visibility(scope))
    changed = previous_visibility != clean_visibility
    if changed:
        with operation_journal(
            wiki_dir,
            "set-memory-visibility",
            str(record["title"]),
            timestamp=timestamp,
            paths=[f"wiki/memories/{page_path.name}", "wiki/log.md"],
        ):
            text = page_path.read_text(encoding="utf-8", errors="replace")
            atomic_write_text(page_path, update_frontmatter_fields(text, {"visibility": clean_visibility}))
            if log_writer:
                log_writer(
                    timestamp,
                    "set-memory-visibility",
                    str(record["title"]),
                    [
                        f"Updated: memories/{page_path.name}",
                        f"Previous visibility: {previous_visibility}",
                        f"New visibility: {clean_visibility}",
                    ],
                )

    return {
        "updated": changed,
        "name": record["name"],
        "path": record["path"],
        "title": record["title"],
        "scope": scope,
        "previous_visibility": previous_visibility,
        "visibility": clean_visibility,
        "review_status": record.get("review_status", "pending"),
    }


def forget_memory_page(
    wiki_dir: Path,
    identifier: str,
    confirm: bool = False,
    records: Iterable[Mapping[str, object]] | None = None,
    log_writer: MemoryLogWriter | None = None,
    timestamp: str = "",
    rebuild_backlinks: Callable[[], bool] | None = None,
) -> dict[str, object]:
    page_path, record, error = resolve_memory_page(wiki_dir, identifier, records=records)
    if error:
        return {
            "forgotten": False,
            "found": False,
            "error": error,
            "confirmation_required": False,
        }
    assert page_path is not None and record is not None

    payload: dict[str, object] = {
        "forgotten": False,
        "found": True,
        "name": record["name"],
        "path": record["path"],
        "title": record["title"],
        "confirmation_required": not confirm,
    }
    if not confirm:
        return payload

    with operation_journal(
        wiki_dir,
        "forget-memory",
        str(record["title"]),
        timestamp=timestamp,
        paths=[f"wiki/memories/{page_path.name}", "wiki/index.md", "wiki/_backlinks.json", "wiki/log.md"],
    ):
        page_path.unlink()
        index_updated = remove_memory_from_index(wiki_dir / "index.md", page_path.stem)
        backlinks_rebuilt = rebuild_backlinks() if rebuild_backlinks else False
        if log_writer:
            log_writer(
                timestamp,
                "forget-memory",
                f"Forgot memory {payload['path']}",
                [
                    f"Title: {payload['title']}",
                    "Deleted memory page only; memory body was not logged.",
                ],
            )
    redaction = redact_log_references(
        wiki_dir,
        [str(record.get("title") or ""), str(record.get("name") or "")],
        timestamp,
        "Forgot a memory; its title is removed from past log entries.",
    )
    payload.update({
        "forgotten": True,
        "confirmation_required": False,
        "index_updated": index_updated,
        "backlinks_rebuilt": bool(backlinks_rebuilt),
        "log_redaction": redaction,
    })
    return payload


def mark_memory_reviewed(
    wiki_dir: Path,
    identifier: str,
    note: str | None,
    timestamp: str,
    records: Iterable[Mapping[str, object]] | None = None,
    review_command: str = "review-memory",
    log_writer: MemoryLogWriter | None = None,
) -> dict[str, object]:
    page_path, record, error = resolve_memory_page(wiki_dir, identifier, records=records)
    if error:
        raise ValueError(error)
    assert page_path is not None and record is not None

    previous_review_status = str(record.get("review_status") or "pending")
    clean_note = note.strip() if note else ""
    updates = {
        "review_status": "reviewed",
        "reviewed_at": f'"{timestamp}"',
    }
    if clean_note:
        updates["review_note"] = f'"{frontmatter_string(clean_note)}"'
    changed = previous_review_status != "reviewed" or bool(clean_note)
    if changed:
        with operation_journal(
            wiki_dir,
            "review-memory",
            str(record["title"]),
            timestamp=timestamp,
            paths=[f"wiki/memories/{page_path.name}", "wiki/log.md"],
        ):
            text = page_path.read_text(encoding="utf-8", errors="replace")
            atomic_write_text(page_path, update_frontmatter_fields(text, updates))
            if log_writer:
                log_lines = [
                    f"Reviewed: memories/{page_path.name}",
                    f"Previous review status: {previous_review_status}",
                    "New review status: reviewed",
                ]
                if clean_note:
                    log_lines.append(f"Note: {clean_note}")
                log_writer(timestamp, "review-memory", str(record["title"]), log_lines)

    _, updated_record, _ = resolve_memory_page(wiki_dir, str(record["name"]))
    updated_record = updated_record or record
    issues = memory_review_issues(updated_record, review_command=review_command)
    return {
        "updated": changed,
        "name": record["name"],
        "path": record["path"],
        "title": record["title"],
        "previous_review_status": previous_review_status,
        "review_status": "reviewed",
        "remaining_issue_count": len(issues),
        "remaining_issues": issues,
    }


def update_memory_page(
    wiki_dir: Path,
    identifier: str,
    text: str,
    source: str,
    timestamp: str,
    records: Iterable[Mapping[str, object]] | None = None,
    review_command: str = "review-memory",
    allow_conflict: bool = False,
    project: str | None = None,
    log_writer: MemoryLogWriter | None = None,
    rebuild_backlinks: BacklinkRebuilder | None = None,
) -> dict[str, object]:
    clean_text = text.strip()
    if not clean_text:
        raise ValueError("memory update text required")
    clean_source = source.strip() if source else "manual"
    record_list = [dict(item) for item in records] if records is not None else memory_records(wiki_dir)
    page_path, record, error = resolve_memory_page(wiki_dir, identifier, records=record_list)
    if error:
        raise ValueError(error)
    assert page_path is not None and record is not None
    if not is_active_memory(record):
        raise ValueError("cannot update archived or stale memory; restore it first")
    conflict_candidates = memory_conflict_candidates(
        record_list,
        clean_text,
        str(record.get("title") or ""),
        str(record.get("memory_type") or "note"),
        str(record.get("scope") or "user"),
        project=project or str(record.get("project") or ""),
        exclude_names=[str(record.get("name") or "")],
    )
    if conflict_candidates and not allow_conflict:
        return {
            "updated": False,
            "conflict": True,
            "message": "This update may conflict with another active memory. Explain, update, or archive the conflicting memory first, or pass allow_conflict if both should coexist.",
            "name": record["name"],
            "path": record["path"],
            "title": record["title"],
            "project": record.get("project", ""),
            "conflict_candidates": conflict_candidates,
        }

    previous_review_status = str(record.get("review_status") or "pending")
    previous_update_count = frontmatter_int(record.get("update_count"))
    next_update_count = previous_update_count + 1
    original = page_path.read_text(encoding="utf-8", errors="replace")
    _, body = parse_frontmatter(original)
    updated_body = append_memory_update(body, clean_text, timestamp, clean_source)
    updates = {
        "updated_at": f'"{timestamp}"',
        "update_count": str(next_update_count),
        "last_update_source": f'"{frontmatter_string(clean_source)}"',
        "review_status": "pending",
    }
    updated_text = update_frontmatter_fields(original, updates, remove={"reviewed_at", "review_note"})
    with operation_journal(
        wiki_dir,
        "update-memory",
        str(record["title"]),
        timestamp=timestamp,
        paths=[f"wiki/memories/{page_path.name}", "wiki/_backlinks.json", "wiki/log.md"],
    ):
        atomic_write_text(page_path, replace_markdown_body(updated_text, updated_body))
        if log_writer:
            log_writer(
                timestamp,
                "update-memory",
                str(record["title"]),
                [
                    f"Updated: memories/{page_path.name}",
                    f"Previous review status: {previous_review_status}",
                    "New review status: pending",
                    f"Update count: {next_update_count}",
                    f"Source: {clean_source}",
                ],
            )
        backlinks_rebuilt = rebuild_backlinks() if rebuild_backlinks else False

    _, updated_record, _ = resolve_memory_page(wiki_dir, str(record["name"]))
    updated_record = updated_record or record
    issues = memory_review_issues(updated_record, review_command=review_command)
    return {
        "updated": True,
        "name": updated_record["name"],
        "path": updated_record["path"],
        "title": updated_record["title"],
        "project": updated_record.get("project", ""),
        "previous_review_status": previous_review_status,
        "review_status": updated_record.get("review_status", "pending"),
        "updated_at": timestamp,
        "update_count": next_update_count,
        "source": clean_source,
        "remaining_issue_count": len(issues),
        "remaining_issues": issues,
        "backlinks_rebuilt": bool(backlinks_rebuilt),
        "conflict_override": bool(conflict_candidates and allow_conflict),
        "conflict_candidates": conflict_candidates,
    }


def write_memory_page(
    wiki_dir: Path,
    text: str,
    title: str | None,
    memory_type: str,
    scope: str,
    tags: str | None,
    source: str,
    timestamp: str,
    project: str | None = None,
    visibility: str | None = None,
    review_after: str | None = None,
    expires_at: str | None = None,
    trigger: str | None = None,
    applies_when: str | None = None,
    supersedes: str | None = None,
    context: str | None = None,
    records: Iterable[Mapping[str, object]] | None = None,
    allow_duplicate: bool = False,
    allow_conflict: bool = False,
    allow_secret: bool = False,
    log_writer: MemoryLogWriter | None = None,
    rebuild_backlinks: BacklinkRebuilder | None = None,
) -> dict[str, object]:
    if memory_type not in MEMORY_TYPES:
        raise ValueError(f"memory_type must be one of: {', '.join(MEMORY_TYPES)}")
    if scope not in MEMORY_SCOPES:
        raise ValueError(f"scope must be one of: {', '.join(MEMORY_SCOPES)}")
    clean_trigger = " ".join(str(trigger or "").split())
    if clean_trigger and len(clean_trigger) > 200:
        raise ValueError("trigger must be 200 characters or fewer")
    # Retrieval context: surrounding text from the memory's origin. It helps
    # recall find the memory but is never part of the claim, so it needs no
    # review-visible section — frontmatter only, bounded like LoCoMo's
    # measured +/-1-neighbor window.
    clean_context = " ".join(str(context or "").split())
    if len(clean_context) > 600:
        clean_context = clean_context[:600].rsplit(" ", 1)[0].strip()
    clean_applies_when = " ".join(str(applies_when or "").split())
    if clean_applies_when:
        if len(clean_applies_when) > 200:
            raise ValueError("applies_when must be 200 characters or fewer")
        parse_applies_when(clean_applies_when)
    clean_visibility = normalize_memory_visibility(scope, visibility)

    clean_text = text.strip()
    if not clean_text:
        raise ValueError("memory text required")
    if not allow_secret:
        # Memory pages are plain files injected into every connected agent's
        # session; a credential saved here leaks by design. Refuse loudly.
        secret_labels = secret_value_warnings(f"{clean_text}\n{title or ''}")
        password_hint = looks_like_password_note(clean_text)
        if password_hint:
            secret_labels.append(password_hint)
        if secret_labels:
            return {
                "created": False,
                "secret": True,
                "secret_warnings": secret_labels,
                "message": (
                    "This looks like a secret (" + ", ".join(secret_labels) + "). "
                    "Memory is plain Markdown read by every connected agent — keep "
                    "credentials in a password manager. If this is truly not a "
                    "secret, rerun with --allow-secret."
                ),
            }
    clean_source = source.strip() if source is not None else ""
    clean_review_after = str(review_after or "").strip()
    if clean_review_after:
        _parse_review_date(clean_review_after)
    clean_expires_at = str(expires_at or "").strip()
    if clean_expires_at:
        _parse_expires_date(clean_expires_at)
    clean_project = normalize_project(project) if scope == "project" else ""
    derived_title = title
    if not (derived_title and derived_title.strip()) and memory_type == "procedure" and clean_trigger:
        derived_title = clean_trigger
    memory_title_value = memory_title(clean_text, derived_title)
    summary = clean_text.splitlines()[0].strip()
    if len(summary) > 180:
        summary = summary[:177].rstrip() + "..."
    record_list = [dict(record) for record in records] if records is not None else memory_records(wiki_dir)
    superseded_path: Path | None = None
    superseded_record: dict[str, object] | None = None
    if supersedes:
        superseded_path, superseded_record, supersede_error = resolve_memory_page(
            wiki_dir, supersedes, records=record_list
        )
        if supersede_error:
            raise ValueError(f"supersedes: {supersede_error}")
        assert superseded_path is not None and superseded_record is not None
        if not is_active_memory(superseded_record):
            raise ValueError("supersedes target must be an active memory")
    superseded_name = str(superseded_record.get("name")) if superseded_record else ""
    conflict_candidates = memory_conflict_candidates(
        record_list,
        clean_text,
        title,
        memory_type,
        scope,
        project=clean_project,
    )
    if superseded_name:
        conflict_candidates = [
            candidate for candidate in conflict_candidates
            if str(candidate.get("name")) != superseded_name
        ]
    if conflict_candidates and not allow_conflict:
        return {
            "created": False,
            "conflict": True,
            "message": (
                "This memory may conflict with an active memory. If it replaces an outdated "
                "memory, rerun with supersedes=<name> to archive the old one with lineage; "
                "review or update the existing memory, or pass allow_conflict if both should coexist."
            ),
            "title": memory_title_value,
            "memory_type": memory_type,
            "scope": scope,
            "visibility": clean_visibility,
            "project": clean_project,
            "conflict_candidates": conflict_candidates,
        }

    duplicate_candidates = memory_duplicate_candidates(
        record_list,
        clean_text,
        title,
        memory_type,
        scope,
        project=clean_project,
    )
    if superseded_name:
        duplicate_candidates = [
            candidate for candidate in duplicate_candidates
            if str(candidate.get("name")) != superseded_name
        ]
    # A claim cannot be both the same and opposing: records already identified
    # as conflicts are handled by the conflict path (with supersede guidance)
    # and must not also block the write as duplicates.
    conflict_names = {str(candidate.get("name")) for candidate in conflict_candidates}
    duplicate_candidates = [
        candidate for candidate in duplicate_candidates
        if str(candidate.get("name")) not in conflict_names
    ]
    if duplicate_candidates and not allow_duplicate:
        return {
            "created": False,
            "duplicate": True,
            "message": "Similar active memory already exists. Review or update the existing memory, or pass allow_duplicate if this is intentional.",
            "title": memory_title_value,
            "memory_type": memory_type,
            "scope": scope,
            "visibility": clean_visibility,
            "project": clean_project,
            "candidates": duplicate_candidates,
        }
    memories_dir = wiki_dir / "memories"
    memories_dir.mkdir(parents=True, exist_ok=True)
    page_path = unique_page_path(memories_dir, slugify(memory_title_value))
    page_name = page_path.stem
    tag_values = ["memory", memory_type]
    for tag in csv_values(tags):
        slug_tag = slugify(tag, fallback="")
        if slug_tag and slug_tag not in tag_values:
            tag_values.append(slug_tag)
    project_line = f'project: "{frontmatter_string(clean_project)}"\n' if clean_project else ""
    review_after_line = f'review_after: "{frontmatter_string(clean_review_after)}"\n' if clean_review_after else ""
    expires_at_line = f'expires_at: "{frontmatter_string(clean_expires_at)}"\n' if clean_expires_at else ""
    trigger_line = f'trigger: "{frontmatter_string(clean_trigger)}"\n' if clean_trigger else ""
    applies_when_line = (
        f'applies_when: "{frontmatter_string(clean_applies_when)}"\n' if clean_applies_when else ""
    )
    supersedes_line = f'supersedes: "{frontmatter_string(superseded_name)}"\n' if superseded_name else ""
    context_line = f'context: "{frontmatter_string(clean_context)}"\n' if clean_context else ""


    if memory_type == "procedure":
        use_when = (
            f"- {clean_trigger}" if clean_trigger
            else "- An agent starts a task this procedure covers."
        )
        use_when += "\n- Follow the steps in order; confirm with the user before deviating."
    else:
        use_when = (
            f"- An agent needs relevant {scope} context for future work.\n"
            f"- A future answer depends on this {memory_type}."
        )

    page = f"""---
type: memory
title: "{frontmatter_string(memory_title_value)}"
memory_type: {memory_type}
scope: {scope}
visibility: {clean_visibility}
{project_line}status: active
date_captured: "{timestamp}"
source: "{frontmatter_string(clean_source)}"
review_status: pending
{review_after_line}{expires_at_line}{trigger_line}{applies_when_line}{supersedes_line}{context_line}reviewed_at: ""
tags: {yaml_list(tag_values)}
---

# {memory_title_value}

> **TLDR:** {summary}

## Memory

{clean_text}

## Use This When

{use_when}

## Source

{clean_source}
"""
    journal_paths = [f"wiki/memories/{page_path.name}", "wiki/index.md", "wiki/_backlinks.json", "wiki/log.md"]
    if superseded_path is not None:
        journal_paths.insert(1, f"wiki/memories/{superseded_path.name}")
    with operation_journal(
        wiki_dir,
        "remember",
        memory_title_value,
        timestamp=timestamp,
        paths=journal_paths,
    ):
        atomic_write_text(page_path, page)
        if superseded_path is not None and superseded_record is not None:
            # Supersession is one atomic story: the successor records what it
            # replaces, and the predecessor is archived with forward lineage
            # instead of silently coexisting or being deleted.
            old_text = superseded_path.read_text(encoding="utf-8", errors="replace")
            atomic_write_text(superseded_path, update_frontmatter_fields(
                old_text,
                {
                    "status": "archived",
                    "archived_at": f'"{timestamp}"',
                    "archive_reason": f'"{frontmatter_string(f"superseded by {page_name}")}"',
                    "superseded_by": f'"{frontmatter_string(page_name)}"',
                },
                remove={"restored_at"},
            ))
        update_memory_index(wiki_dir / "index.md", page_name, memory_title_value, summary, memory_type, scope)
        if log_writer:
            log_lines = [
                f"Created: memories/{page_path.name}",
                f"Type: {memory_type}",
                f"Scope: {scope}",
                f"Visibility: {clean_visibility}",
            ]
            if superseded_name:
                log_lines.append(f"Supersedes: {superseded_name} (archived)")
            log_writer(
                timestamp,
                "remember",
                memory_title_value,
                log_lines,
            )
        backlinks_rebuilt = rebuild_backlinks() if rebuild_backlinks else False
    return {
        "created": True,
        "supersedes": superseded_name,
        "name": page_name,
        "path": f"wiki/memories/{page_path.name}",
        "title": memory_title_value,
        "memory_type": memory_type,
        "scope": scope,
        "visibility": clean_visibility,
        "project": clean_project,
        "review_after": clean_review_after,
        "expires_at": clean_expires_at,
        "backlinks_rebuilt": bool(backlinks_rebuilt),
        "duplicate_override": bool(duplicate_candidates and allow_duplicate),
        "duplicate_candidates": duplicate_candidates,
        "conflict_override": bool(conflict_candidates and allow_conflict),
        "conflict_candidates": conflict_candidates,
    }


def memory_inbox(
    records: Iterable[Mapping[str, object]],
    limit: int = 20,
    include_archived: bool = False,
    review_command: str = "review-memory",
    project: str | None = None,
    command_target: str | Path = ".",
) -> dict[str, object]:
    limit = max(1, min(limit, 50))
    project_name = normalize_project(project)
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    items: list[dict[str, object]] = []
    for record in records:
        if not memory_visible_for_project(record, project_name):
            continue
        if not include_archived and str(record.get("status") or "").lower() == "archived":
            continue
        issues = memory_review_issues(record, review_command=review_command)
        if not issues:
            continue
        item = slim_memory(record)
        item["issues"] = issues
        item["issue_count"] = len(issues)
        item["actions"] = memory_action_hints(
            record,
            issues=issues,
            review_command=review_command,
            command_target=command_target,
        )
        item["primary_action"] = primary_memory_action(item["actions"])
        item["highest_severity"] = min(
            (issue["severity"] for issue in issues),
            key=lambda severity: severity_rank.get(severity, 9),
        )
        items.append(item)
    items.sort(key=lambda item: (
        severity_rank.get(str(item["highest_severity"]), 9),
        -int(item["issue_count"]),
        str(item.get("date_captured") or ""),
        str(item.get("title") or "").lower(),
    ))
    counts_by_severity: dict[str, int] = {}
    for item in items:
        severity = str(item["highest_severity"])
        counts_by_severity[severity] = counts_by_severity.get(severity, 0) + 1
    return {
        "review_count": len(items),
        "counts_by_severity": counts_by_severity,
        "include_archived": include_archived,
        "project": project_name,
        "next_actions": [
            item["primary_action"]
            for item in items[:limit]
            if item.get("primary_action")
        ],
        "items": items[:limit],
    }


def count_values(records: Iterable[Mapping[str, object]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = str(record.get(field) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def top_tags(records: Iterable[Mapping[str, object]], limit: int = 12) -> list[dict[str, object]]:
    counts: dict[str, int] = {}
    skip = {"memory", *MEMORY_TYPES}
    for record in records:
        for tag in record.get("tags", []):
            tag_text = str(tag).strip()
            if not tag_text or tag_text in skip:
                continue
            counts[tag_text] = counts.get(tag_text, 0) + 1
    return [
        {"tag": tag, "count": count}
        for tag, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def recent_memories(records: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    return sorted(
        (dict(record) for record in records),
        key=lambda record: (
            str(record.get("date_captured") or ""),
            str(record.get("title") or "").lower(),
        ),
        reverse=True,
    )


def memory_profile(
    records: Iterable[Mapping[str, object]],
    limit: int = 10,
    review_command: str = "review-memory",
    project: str | None = None,
) -> dict[str, object]:
    limit = max(1, min(limit, 50))
    project_name = normalize_project(project)
    record_list = [
        dict(record)
        for record in records
        if memory_visible_for_project(record, project_name)
    ]
    active_records = [record for record in record_list if is_active_memory(record)]
    archived_records = [
        record for record in record_list
        if str(record.get("status") or "").lower() == "archived"
    ]
    recent = [slim_memory(record) for record in recent_memories(active_records)]

    def typed(memory_type: str) -> list[dict[str, object]]:
        return [
            slim_memory(record)
            for record in recent_memories(active_records)
            if str(record.get("memory_type") or "") == memory_type
        ][:limit]

    return {
        "memory_count": len(record_list),
        "active_count": len(active_records),
        "review_count": memory_inbox(record_list, limit=limit, review_command=review_command)["review_count"],
        "project": project_name,
        "by_type": count_values(record_list, "memory_type"),
        "by_scope": count_values(record_list, "scope"),
        "by_visibility": count_values(record_list, "visibility"),
        "by_project": count_values(
            [
                record
                for record in record_list
                if str(record.get("scope") or "") == "project"
                and normalize_project(str(record.get("project") or ""))
            ],
            "project",
        ),
        "by_status": count_values(record_list, "status"),
        "top_tags": top_tags(record_list),
        "recent": recent[:limit],
        "preferences": typed("preference"),
        "decisions": typed("decision"),
        "projects": typed("project"),
        "archived": [slim_memory(record) for record in recent_memories(archived_records)][:limit],
    }


def memory_audit_report(
    profile: Mapping[str, object],
    inbox: Mapping[str, object],
    captures: Mapping[str, object],
    next_actions: Iterable[Mapping[str, object]],
    project: str | None = None,
) -> dict[str, object]:
    """Build the shared memory/capture risk report for CLI, HTTP, and MCP."""
    project_name = normalize_project(project)
    review_count = int(inbox.get("review_count") or 0)
    capture_count = int(captures.get("count") or 0)
    capture_warning_count = int(captures.get("warning_count") or 0)
    capture_read_warning_count = int(captures.get("read_warning_count") or 0)
    risk_factors: list[dict[str, object]] = []
    if review_count:
        risk_factors.append({
            "code": "memory_review_backlog",
            "count": review_count,
            "message": f"{review_count} memory item(s) need review or cleanup.",
        })
    if capture_count:
        risk_factors.append({
            "code": "raw_capture_backlog",
            "count": capture_count,
            "message": f"{capture_count} raw capture(s) are waiting for review.",
        })
    if capture_warning_count:
        risk_factors.append({
            "code": "capture_secret_warnings",
            "count": capture_warning_count,
            "message": f"{capture_warning_count} raw capture(s) contain secret-looking values.",
        })
    if capture_read_warning_count:
        risk_factors.append({
            "code": "capture_read_warnings",
            "count": capture_read_warning_count,
            "message": f"{capture_read_warning_count} raw capture(s) could not be read.",
        })
    return {
        "status": "needs_attention" if risk_factors else "healthy",
        "project": project_name,
        "profile": dict(profile),
        "inbox": dict(inbox),
        "captures": dict(captures),
        "risk_factors": risk_factors,
        "next_actions": [dict(action) for action in next_actions],
    }


def memory_audit_next_actions(
    *,
    mode: str,
    inbox: Mapping[str, object],
    captures: Mapping[str, object],
    risk_factors: Iterable[Mapping[str, object]] = (),
    project: str | None = None,
    root: object = ".",
) -> list[dict[str, object]]:
    """Build runtime-specific next actions for a shared memory audit report."""
    project_name = normalize_project(project)
    review_recommended = bool(inbox.get("review_count"))
    capture_recommended = bool(captures.get("count") or captures.get("read_warning_count"))
    risks = list(risk_factors)

    if mode == "cli":
        project_arg = f' --project "{project_name}"' if project_name else ""
        return [
            {
                "label": "Review memory inbox",
                "command": f'python3 link.py memory-inbox "{root}"{project_arg}',
                "recommended": review_recommended,
            },
            {
                "label": "Review raw captures",
                "command": f'python3 link.py capture-inbox "{root}"{project_arg}',
                "recommended": capture_recommended,
            },
            {
                "label": "Run doctor",
                "command": f'python3 link.py doctor "{root}"',
                "recommended": not risks,
            },
        ]

    if mode == "mcp":
        project_arg = f', project="{project_name}"' if project_name else ""
        capture_command = f"capture_inbox({project_arg.lstrip(', ')})" if project_arg else "capture_inbox()"
        return [
            {
                "label": "Review memory inbox",
                "tool": "memory_inbox",
                "command": f"memory_inbox(include_archived=true{project_arg})",
                "recommended": review_recommended,
            },
            {
                "label": "Review raw captures",
                "tool": "capture_inbox",
                "command": capture_command,
                "recommended": capture_recommended,
            },
            {
                "label": "Explain a memory",
                "tool": "explain_memory",
                "command": 'explain_memory(identifier="<memory-name>")',
                "recommended": False,
            },
        ]

    if mode == "web":
        project_query = f"?project={urllib.parse.quote(project_name, safe='')}" if project_name else ""
        project_arg = f' --project "{project_name}"' if project_name else ""
        return [
            {
                "label": "Review memory inbox",
                "detail": "Review pending, stale, invalid, or underspecified memories.",
                "href": f"/inbox{project_query}",
                "command": f'python3 link.py memory-inbox "{root}"{project_arg}',
                "recommended": review_recommended,
            },
            {
                "label": "Review raw captures",
                "detail": "Accept, redact, or delete saved proposal-only raw captures.",
                "href": f"/captures{project_query}",
                "command": f'python3 link.py capture-inbox "{root}"{project_arg}',
                "recommended": capture_recommended,
            },
            {
                "label": "Run doctor",
                "detail": "Check graph, source, memory, raw capture, and secret hygiene.",
                "href": "",
                "command": f'python3 link.py doctor "{root}"',
                "recommended": not risks,
            },
        ]

    raise ValueError(f"Unsupported memory audit action mode: {mode}")


def add_capture_review_to_brief(
    payload: Mapping[str, object],
    captures: Mapping[str, object],
    command_target: str | Path = ".",
) -> dict[str, object]:
    """Attach raw-capture review state, backlog signal, and guidance to a brief."""
    result = dict(payload)
    capture_payload = dict(captures)
    guidance = [str(item) for item in result.get("agent_guidance", [])]
    result["captures"] = capture_payload
    capture_count = int(capture_payload.get("count") or 0)
    warning_count = int(capture_payload.get("warning_count") or 0)
    read_warning_count = int(capture_payload.get("read_warning_count") or 0)
    if capture_count:
        plural = "s" if capture_count != 1 else ""
        guidance.append(
            f"Review {capture_count} saved raw capture{plural} before accepting or deleting capture state."
        )
    if warning_count:
        guidance.append("Redact raw captures with secret warnings before sharing snippets or using their contents.")
    if read_warning_count:
        guidance.append("Fix unreadable raw captures before deciding whether capture memory should be accepted or deleted.")
    review = result.get("review") if isinstance(result.get("review"), Mapping) else {}
    backlog = memory_backlog_summary(
        capture_count=capture_count,
        needs_review_count=int(review.get("count") or 0),
        command_target=command_target,
    )
    result["backlog"] = backlog
    if backlog.get("backlog"):
        guidance.append(
            "The memory backlog is above threshold; offer the user a short consolidation pass "
            f"({backlog.get('command')} prints a read-only plan with approve/discard commands)."
        )
    result["agent_guidance"] = guidance
    return result


def memory_brief(
    records: Iterable[Mapping[str, object]],
    query: str = "",
    limit: int = 6,
    review_command: str = "review-memory",
    project: str | None = None,
    command_target: str | Path = ".",
    semantic_scores: Mapping[str, float] | None = None,
    context_path: str | None = None,
) -> dict[str, object]:
    """Return the compact memory payload an agent should read before work."""
    limit = max(1, min(limit, 20))
    q = query.strip()
    project_name = normalize_project(project)
    record_list = [
        dict(record)
        for record in records
        if memory_visible_for_project(record, project_name)
    ]
    profile = memory_profile(record_list, limit=limit, review_command=review_command, project=project_name)
    inbox = memory_inbox(
        record_list,
        limit=limit,
        review_command=review_command,
        command_target=command_target,
    )

    if q:
        relevant = recall_memories(
            record_list, q, limit=limit, project=project_name,
            semantic_scores=semantic_scores, context_path=context_path,
        )
        selection = "query"
    else:
        relevant = []
        seen: set[str] = set()
        for memory_type in ("preference", "decision", "project"):
            for record in recent_memories(record_list):
                name = str(record.get("name") or "")
                if name in seen:
                    continue
                if not is_active_memory(record):
                    continue
                if str(record.get("memory_type") or "") != memory_type:
                    continue
                if memory_applicability(
                    record, query="", project=project_name, context_path=context_path
                ) == "out_of_context":
                    # Conditional memories stay out of startup briefs unless
                    # their context matches; they surface via task recall.
                    continue
                relevant.append(slim_memory(record))
                seen.add(name)
                if len(relevant) >= limit:
                    break
            if len(relevant) >= limit:
                break
        if len(relevant) < limit:
            for record in recent_memories(record_list):
                name = str(record.get("name") or "")
                if name in seen or not is_active_memory(record):
                    continue
                if memory_applicability(
                    record, query="", project=project_name, context_path=context_path
                ) == "out_of_context":
                    continue
                relevant.append(slim_memory(record))
                seen.add(name)
                if len(relevant) >= limit:
                    break
        selection = "startup"

    guidance = [
        "Use relevant_memories as durable local context before answering or coding.",
        "Call explain_memory before relying on a surprising, stale, or high-impact memory.",
        "Only write memory after explicit user approval; use propose_memories for candidates first.",
        "If a new memory duplicates an existing one, update the existing memory instead of creating another page.",
    ]
    if inbox["review_count"]:
        guidance.insert(
            1,
            "Some memories need review; treat them as provisional when they affect an important decision.",
        )

    return {
        "query": q,
        "project": project_name,
        "selection": selection,
        "profile": profile,
        "relevant_count": len(relevant),
        "relevant_memories": relevant,
        "review": {
            "count": inbox["review_count"],
            "counts_by_severity": inbox["counts_by_severity"],
            "items": inbox["items"],
        },
        "agent_guidance": guidance,
    }


def score_memory(record: Mapping[str, object], query: str) -> int:
    q = query.lower().strip()
    tokens = [token for token in re.split(r"\W+", q) if len(token) >= 3]
    significant_tokens = significant_memory_tokens(q)
    expanded_tokens = expanded_memory_query_tokens(q)
    title = str(record.get("title", "")).lower()
    tldr = str(record.get("tldr", "")).lower()
    body = str(record.get("body", "")).lower()
    tags = " ".join(str(tag).lower() for tag in record.get("tags", []))
    # A procedure's trigger phrase describes when it applies; score it like
    # the intent-bearing head fields so task-shaped queries find recipes.
    trigger = str(record.get("trigger") or "").lower()
    if trigger:
        tldr = f"{tldr} {trigger}".strip()
    # Retrieval context: text from around the memory's origin (neighboring
    # dialogue turns, surrounding notes). It helps recall FIND the memory but
    # is never part of the claim — echoes, duplicates, and conflicts compare
    # claims only (memory_claim_text), and slim output drops it. Measured on
    # LoCoMo: indexing turns with +/-1 neighbors lifts hit@10 0.685 -> 0.749.
    context = str(record.get("context") or "").lower()
    if context:
        body = f"{body} {context}".strip()
    title_tokens = memory_tokens(title)
    tldr_tokens = memory_tokens(tldr)
    body_tokens = memory_tokens(body)
    tags_tokens = memory_tokens(tags)
    score = 0
    if q and q in title:
        score += 20
    if q and (q in tldr or (trigger and q in trigger)):
        score += 12
    if q and q in tags:
        score += 8
    if q and q in body:
        score += 4
    for token in tokens:
        if token in title:
            score += 6
        if token in tldr:
            score += 4
        if token in tags:
            score += 3
        if token in body:
            score += 1
    if significant_tokens:
        searchable = title_tokens | tldr_tokens | tags_tokens | body_tokens
        if significant_tokens <= searchable:
            score += 8
        if significant_tokens <= (title_tokens | tldr_tokens | tags_tokens):
            score += 10
    for token in expanded_tokens - set(tokens):
        if token in title_tokens:
            score += 4
        if token in tldr_tokens:
            score += 3
        if token in tags_tokens:
            score += 2
        if token in body_tokens:
            score += 1
    # Stemmed pass: catch close paraphrases ("committing" vs "commit push")
    # that raw token equality misses, at lower weight than exact hits.
    exact_all = title_tokens | tldr_tokens | tags_tokens | body_tokens
    stemmed_head = stemmed_memory_tokens(title_tokens | tldr_tokens | tags_tokens)
    stemmed_body = stemmed_memory_tokens(body_tokens)
    for token in significant_tokens:
        if token in exact_all:
            continue
        stem = stem_memory_token(token)
        if stem in stemmed_head:
            score += 3
        elif stem in stemmed_body:
            score += 1
    return score


def _memory_date(value: object) -> datetime | None:
    text = str(value or "").strip().strip('"')
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(f"{text}T00:00:00+00:00")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def memory_temporal_boost(record: Mapping[str, object]) -> int:
    """Score current, reviewed memories above old or stale memories."""
    boost = 0
    if str(record.get("review_status") or "").lower() == "reviewed":
        boost += 3
    if str(record.get("review_status") or "").lower() == "needs_update":
        boost -= 6
    if not is_active_memory(record):
        boost -= 12
    parsed = (
        _memory_date(record.get("updated_at"))
        or _memory_date(record.get("reviewed_at"))
        or _memory_date(record.get("date_captured"))
    )
    if parsed is not None:
        age_days = (datetime.now(timezone.utc) - parsed).days
        if age_days <= 30:
            boost += 4
        elif age_days <= 180:
            boost += 2
        elif age_days > 730:
            boost -= 2
    memory_type = str(record.get("memory_type") or "").lower()
    if memory_type in {"preference", "decision", "project", "procedure"}:
        boost += 1
    return boost


def memory_rank_score(record: Mapping[str, object], match_score: int, project: str | None = None) -> int:
    rank_score = match_score
    project_name = normalize_project(project)
    record_scope = str(record.get("scope") or "").lower()
    record_project = normalize_project(str(record.get("project") or ""))
    if project_name and record_scope == "project" and record_project == project_name:
        rank_score += 6
    rank_score += memory_temporal_boost(record)
    return max(1, rank_score)


def list_recipes(
    records: Iterable[Mapping[str, object]],
    project: str | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    """Active procedure memories, newest first, with their triggers."""
    project_name = normalize_project(project)
    recipes = [
        slim_memory(record) | {"steps": procedure_steps_excerpt(str(record.get("body") or ""))}
        for record in records
        if str(record.get("memory_type") or "") == "procedure"
        and is_active_memory(record)
        and memory_visible_for_project(record, project_name)
    ]
    recipes.sort(key=lambda item: str(item.get("updated_at") or item.get("date_captured") or ""), reverse=True)
    return recipes[: max(1, min(limit, 50))]


def render_recipes_text(recipes: Sequence[Mapping[str, object]], target: object = ".") -> tuple[int, str]:
    lines = ["Link recipes (procedural memory)"]
    if not recipes:
        lines.extend([
            "",
            "No recipes yet. Save one after a multi-step task:",
            f"  {display_command(['lnk', 'remember', '<steps>', str(target), '--type', 'procedure', '--trigger', '<when to use>'])}",
        ])
        return 0, "\n".join(lines)
    lines.append(f"{len(recipes)} recipe{'s' if len(recipes) != 1 else ''}")
    for recipe in recipes:
        lines.append("")
        lines.append(f"- {recipe.get('title')}")
        trigger = str(recipe.get("trigger") or "").strip()
        if trigger:
            lines.append(f"  When: {trigger}")
        lines.append(f"  {recipe.get('path')}")
        steps = str(recipe.get("steps") or "").strip()
        if steps:
            preview = steps.splitlines()[0][:100]
            lines.append(f"  First step: {preview}")
    return 0, "\n".join(lines)


def recall_memories(
    records: Iterable[Mapping[str, object]],
    query: str,
    limit: int = 10,
    include_archived: bool = False,
    project: str | None = None,
    semantic_scores: Mapping[str, Mapping[str, float]] | None = None,
    context_path: str | None = None,
    as_of: str | None = None,
    memory_type: str | None = None,
) -> list[dict[str, object]]:
    q = query.strip()
    if not q:
        return []
    if as_of:
        _parse_date_field(as_of, "as_of")
    project_name = normalize_project(project)
    scored: list[tuple[int, int, str, dict[str, object]]] = []
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    for record in records:
        if not memory_visible_for_project(record, project_name):
            continue
        if memory_type and str(record.get("memory_type") or "") != memory_type:
            continue
        if as_of:
            # Temporal recall: reconstruct what was active on that date from
            # lifecycle fields (capture, supersession/archive, expiry).
            if not memory_active_at(record, as_of):
                continue
        elif not include_archived and not is_active_memory(record):
            continue
        lexical_score = score_memory(record, q)
        semantic_match = None
        if semantic_scores:
            semantic_match = semantic_scores.get(str(record.get("name") or ""))
        score = lexical_score + semantic_match_points(semantic_match)
        if score >= MEMORY_RECALL_MIN_SCORE:
            lexical_hit = lexical_score >= MEMORY_RECALL_MIN_SCORE
            rank_score = memory_rank_score(record, score, project=project_name)
            applicability = memory_applicability(
                record, query=q, project=project_name, context_path=context_path
            )
            if applicability == "matched":
                rank_score += 4
            elif applicability == "out_of_context":
                # Conditional memory outside its context: still findable,
                # but demoted and labeled so agents do not apply it blindly.
                rank_score = max(1, rank_score - 10)
            issues = memory_review_issues(record)
            slim = slim_memory(record)
            slim["score"] = score
            slim["rank_score"] = rank_score
            if applicability != "unconditional":
                slim["applicability"] = applicability
            slim["match"] = (
                "hybrid" if (lexical_hit and semantic_match) else ("semantic" if semantic_match else "lexical")
            )
            if semantic_match:
                slim["semantic_similarity"] = float(semantic_match.get("cosine") or 0.0)
            # A match with no lexical evidence is honest about its basis: a
            # close paraphrase is at most moderate confidence, never strong.
            slim["confidence"] = (
                memory_recall_confidence(record, q) if lexical_hit else semantic_confidence_cap(semantic_match)
            )
            if str(record.get("memory_type") or "") == "procedure":
                # The steps are the value of a recipe; carry a bounded excerpt
                # so agents can follow it without another file read.
                slim["steps"] = procedure_steps_excerpt(str(record.get("body") or ""))
            slim["recall"] = recall_state(record, issues)
            slim["review_issue_count"] = len(issues)
            slim["highest_review_severity"] = (
                "none" if not issues else
                min(
                    (str(issue.get("severity") or "low") for issue in issues),
                    key=lambda severity: severity_rank.get(severity, 9),
                )
            )
            recency = str(record.get("updated_at") or record.get("date_captured") or "")
            scored.append((rank_score, score, recency, slim))
    scored.sort(key=lambda item: str(item[3]["title"]).lower())
    scored.sort(key=lambda item: item[2], reverse=True)
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [record for _, _, _, record in scored[:limit]]


APPLICABILITY_CONDITION_KINDS = ("project", "path", "task")


def parse_applies_when(value: object) -> list[tuple[str, str]]:
    """Parse an applies_when string into (kind, argument) conditions.

    Format: comma-separated `kind:argument` conditions with OR semantics,
    e.g. "project:link, task:cutting a release, path:*picochat*".
    Raises ValueError for unknown kinds or empty arguments.
    """
    text = str(value or "").strip()
    if not text:
        return []
    conditions: list[tuple[str, str]] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        kind, _, argument = part.partition(":")
        kind = kind.strip().lower()
        argument = argument.strip()
        if kind not in APPLICABILITY_CONDITION_KINDS or not argument:
            raise ValueError(
                "applies_when conditions must look like project:<slug>, path:<glob>, or task:<phrase>"
            )
        if kind == "project":
            # Store the slug recall actually compares against, so the
            # condition matches what it displays — and reject a value that
            # slugifies to nothing (e.g. "project:!!!"), which would be a
            # silently-dead scope.
            normalized = normalize_project(argument)
            if not normalized:
                raise ValueError(
                    f"applies_when project condition has no usable slug: {argument!r}"
                )
            argument = normalized
        conditions.append((kind, argument))
    return conditions


def memory_applicability(
    record: Mapping[str, object],
    *,
    query: str = "",
    project: str | None = None,
    context_path: str | None = None,
) -> str:
    """Deterministically judge whether a memory applies in this context.

    Returns "unconditional" (no applies_when), "matched" (any condition
    matches: OR semantics), or "out_of_context". Conditions the current
    context cannot evaluate (a path: condition with no known path) simply
    do not match; they never raise.
    """
    try:
        conditions = parse_applies_when(record.get("applies_when"))
    except ValueError:
        # Fail closed: a malformed condition string is still a fence the
        # user wrote. Treating it as unconditional would silently apply the
        # memory everywhere — the exact mis-scoping applies_when prevents.
        # memory_review_issues flags the syntax error for repair.
        return "out_of_context"
    if not conditions:
        return "unconditional"
    query_tokens = stemmed_memory_tokens(significant_memory_tokens(query))
    for kind, argument in conditions:
        if kind == "project" and normalize_project(argument) and (
            normalize_project(argument) == normalize_project(project or "")
        ):
            return "matched"
        if kind == "path" and context_path:
            if fnmatch.fnmatch(str(context_path).lower(), argument.lower()):
                return "matched"
        if kind == "task" and query_tokens:
            condition_tokens = stemmed_memory_tokens(significant_memory_tokens(argument))
            if condition_tokens and condition_tokens <= query_tokens:
                return "matched"
    return "out_of_context"


ECHO_CONTAINMENT = 0.7


def is_existing_memory_echo(
    records: Iterable[Mapping[str, object]],
    text: str,
    threshold: float = ECHO_CONTAINMENT,
) -> bool:
    """True when `text` mostly restates an existing active memory.

    Duplicate detection uses symmetric overlap, which framing words dilute
    ("Per your saved preference, we decided ..."). Echo detection asks the
    asymmetric question instead: are most of an existing memory's significant
    tokens contained in the candidate text? That is the shape of an agent
    repeating stored memory back into the transcript.
    """
    candidate_tokens = stemmed_memory_tokens(significant_memory_tokens(text))
    if not candidate_tokens:
        return False
    for record in records:
        if not is_active_memory(record):
            continue
        # Compare against the memory's core claim (title + TLDR, and the
        # `## Memory` section), not the whole page: template sections would
        # dilute containment and let restatements through.
        views = [
            " ".join([str(record.get("title") or ""), str(record.get("tldr") or "")]),
            procedure_steps_excerpt(str(record.get("body") or ""), max_chars=600),
        ]
        for view in views:
            view_tokens = stemmed_memory_tokens(significant_memory_tokens(view))
            if len(view_tokens) < 4:
                continue
            containment = len(view_tokens & candidate_tokens) / len(view_tokens)
            if containment >= threshold:
                return True
            # Mirrored test: a partial restatement contains little of the
            # full claim, but nearly all of ITS OWN tokens live inside the
            # claim — it adds nothing new, so it is still an echo.
            if len(candidate_tokens) >= 4:
                reverse = len(view_tokens & candidate_tokens) / len(candidate_tokens)
                if reverse >= 0.8:
                    return True
    return False


ABSTENTION_CONFIDENCES = {"", "weak"}


def recall_abstention(results: list[dict[str, object]]) -> dict[str, object]:
    """An explicit don't-know signal for a recall result set.

    LongMemEval-style abstention: when someone asks about something the
    memory never contained, the correct behavior is to say so — not to let
    an agent dress a weak match up as an answer. Link already computes the
    evidence (confidence labels, match kinds); this makes the verdict
    first-class so every surface can pass it to the agent.

    recommended=True means: no memory here is strong enough to assert from.
    """
    if not results:
        return {
            "recommended": True,
            "reason": "no matching memories",
            "guidance": "Say the memory does not contain this rather than guessing.",
        }
    top = results[0]
    confidence = str(top.get("confidence") or "")
    if confidence in ABSTENTION_CONFIDENCES:
        return {
            "recommended": True,
            "reason": f"best match has {confidence or 'no'} confidence",
            "guidance": (
                "Treat matches as hints only; say the memory has nothing "
                "reliable on this rather than asserting from a weak match."
            ),
        }
    return {"recommended": False, "reason": f"best match confidence: {confidence}"}


def memory_duplicate_candidates(
    records: Iterable[Mapping[str, object]],
    text: str,
    title: str | None,
    memory_type: str,
    scope: str,
    project: str | None = None,
    limit: int = 3,
) -> list[dict[str, object]]:
    title_value = memory_title(text, title)
    new_slug = slugify(title_value)
    new_title = compact_memory_text(title_value)
    new_body = compact_memory_text(text)
    new_tokens = memory_tokens(f"{title_value} {text}")
    project_name = normalize_project(project)
    candidates: list[tuple[int, dict[str, object]]] = []

    for record in records:
        if not is_active_memory(record):
            continue
        if scope == "project" and not memory_visible_for_project(record, project_name):
            continue
        reasons: list[str] = []
        score = 0
        record_title = compact_memory_text(str(record.get("title") or ""))
        record_text = compact_memory_text(memory_claim_text(record))
        record_tokens = memory_tokens(record_text)

        if str(record.get("name") or "") == new_slug:
            score = max(score, 100)
            reasons.append("same_slug")
        if new_title and record_title == new_title:
            score = max(score, 96)
            reasons.append("same_title")
        if len(new_body) >= 40 and new_body in record_text:
            score = max(score, 94)
            reasons.append("same_memory_text")

        overlap = sorted(new_tokens & record_tokens)
        union = new_tokens | record_tokens
        overlap_ratio = (len(overlap) / len(union)) if union else 0.0
        same_kind = (
            str(record.get("memory_type") or "") == memory_type
            and str(record.get("scope") or "") == scope
        )
        if same_kind and len(overlap) >= 5 and overlap_ratio >= 0.72:
            score = max(score, min(92, int(70 + overlap_ratio * 25)))
            reasons.append("high_token_overlap")

        if score < 85:
            continue
        candidate = slim_memory(record)
        candidate["duplicate_score"] = min(score, 100)
        candidate["duplicate_reasons"] = reasons
        candidate["matching_terms"] = overlap[:12]
        candidates.append((int(candidate["duplicate_score"]), candidate))

    candidates.sort(key=lambda item: (-item[0], str(item[1]["title"]).lower()))
    return [candidate for _, candidate in candidates[:limit]]


def memory_conflict_candidates(
    records: Iterable[Mapping[str, object]],
    text: str,
    title: str | None,
    memory_type: str,
    scope: str,
    project: str | None = None,
    limit: int = 3,
    exclude_names: Iterable[str] | None = None,
) -> list[dict[str, object]]:
    """Find active memories that may contradict the proposed memory."""
    if memory_type not in MEMORY_CONFLICT_TYPES:
        return []

    title_value = memory_title(text, title)
    new_text = f"{title_value} {text}"
    new_all_tokens = memory_tokens(new_text)
    new_tokens = significant_memory_tokens(new_text)
    new_negated = has_negation(new_text)
    new_groups = _extract_option_groups(new_text)
    new_pairs = _extract_preference_pairs(new_text)
    project_name = normalize_project(project)
    excluded = {name for name in (exclude_names or []) if name}
    candidates: list[tuple[int, dict[str, object]]] = []

    for record in records:
        name = str(record.get("name") or "")
        if name in excluded or not is_active_memory(record):
            continue
        if scope == "project" and not memory_visible_for_project(record, project_name):
            continue
        record_type = str(record.get("memory_type") or "")
        record_scope = str(record.get("scope") or "")
        if record_type != memory_type:
            continue
        if scope != record_scope and "global" not in {scope, record_scope}:
            continue

        record_text = memory_claim_text(record)
        record_all_tokens = memory_tokens(record_text)
        record_tokens = significant_memory_tokens(record_text)
        overlap = sorted(new_tokens & record_tokens)
        union = new_tokens | record_tokens
        overlap_ratio = (len(overlap) / len(union)) if union else 0.0
        reasons: list[str] = []
        score = 0

        if new_negated != has_negation(record_text) and len(overlap) >= 1 and overlap_ratio >= 0.45:
            score = max(score, 92)
            reasons.append("opposite_negation")

        # Revision shape: the new text carries a negation or revision cue
        # ("... does not X anymore; we now Y") and covers most of the
        # record's head claim (title + TLDR). Symmetric ratio misses this —
        # revisions legitimately add replacement content — and negation-XOR
        # misses it when the original claim also contains a negation.
        revision_cue = new_negated or bool(
            re.search(r"\b(?:anymore|no longer|instead of|replace[sd]?|settled on)\b", new_text, re.IGNORECASE)
        )
        if revision_cue:
            # Compare subjects, not phrasing: memory boilerplate tokens
            # ("decision", "project", "prefers", ...) appear in most claims
            # and would connect unrelated memories.
            cue_tokens = {
                "decision", "decid", "project", "team", "user", "prefer",
                "use", "agent", "memory", "through", "now", "anymore",
            }
            head_tokens = stemmed_memory_tokens(significant_memory_tokens(
                " ".join([str(record.get("title") or ""), str(record.get("tldr") or "")])
            )) - cue_tokens
            new_stemmed = stemmed_memory_tokens(new_tokens) - cue_tokens
            head_overlap = head_tokens & new_stemmed
            if len(head_tokens) >= 3 and len(head_overlap) >= 2 and (
                len(head_overlap) / len(head_tokens) >= 0.5
            ):
                score = max(score, 90)
                reasons.append("revises_existing_claim")

        record_groups = _extract_option_groups(record_text)
        for group, new_options in new_groups.items():
            record_options = record_groups.get(group)
            if not record_options:
                continue
            if new_options == record_options:
                continue
            # Ambiguous memories that mention multiple options without a clear
            # preference are left for review instead of automatic conflict.
            if len(new_options) > 1 or len(record_options) > 1:
                continue
            context = CONFLICT_GROUP_CONTEXT.get(group, set())
            context_matches = (
                not context
                or (
                    bool(new_all_tokens & context)
                    and bool(record_all_tokens & context)
                )
            )
            if len(overlap) >= 2 or context_matches:
                score = max(score, 88)
                reasons.append(f"different_{group}")

        record_pairs = _extract_preference_pairs(record_text)
        for new_preferred, new_rejected in new_pairs:
            for record_preferred, record_rejected in record_pairs:
                if (new_preferred & record_rejected) and (new_rejected & record_preferred):
                    score = max(score, 97)
                    reasons.append("reversed_preference")

        if score < 85:
            continue
        candidate = slim_memory(record)
        candidate["conflict_score"] = min(score, 100)
        candidate["conflict_reasons"] = sorted(set(reasons))
        candidate["matching_terms"] = overlap[:12]
        candidates.append((int(candidate["conflict_score"]), candidate))

    candidates.sort(key=lambda item: (-item[0], str(item[1]["title"]).lower()))
    return [candidate for _, candidate in candidates[:limit]]


def memory_proposal_segments(text: str) -> list[str]:
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    segments: list[str] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", line).strip()
        line = re.sub(r"^(?:user|human|me|assistant|codex|agent)\s*:\s*", "", line, flags=re.IGNORECASE)
        if not line:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            sentence = sentence.strip()
            if 18 <= len(sentence) <= 500:
                segments.append(sentence)
    return segments


def normalize_proposed_memory(text: str, memory_type: str) -> str:
    value = text.strip()
    value = re.sub(r"^please remember(?: that)?\s+", "", value, flags=re.IGNORECASE)
    replacements = [
        (r"^i prefer\b", "User prefers"),
        (r"^i like\b", "User likes"),
        (r"^i want\b", "User wants"),
        (r"^i need\b", "User needs"),
        (r"^i do not want\b", "User does not want"),
        (r"^i don't want\b", "User does not want"),
        (r"^i am\b", "User is"),
        (r"^i work\b", "User works"),
        (r"^my\b", "User's"),
        (r"^we decided\b", "Project decided"),
        (r"^we agreed\b", "Project agreed"),
        (r"^we chose\b", "Project chose"),
        (r"^we settled\b", "Project settled"),
    ]
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value, count=1, flags=re.IGNORECASE)
    if memory_type == "decision" and value.lower().startswith("decision:"):
        value = value.split(":", 1)[1].strip()
        value = "Project decided " + value[0].lower() + value[1:] if value else "Project decision"
    if value and value[-1] not in ".!?":
        value += "."
    return value


def proposal_title(memory: str, memory_type: str) -> str:
    title = memory.strip().rstrip(".")
    title = re.sub(r"^(?:User|Project|Team)\s+", "", title, flags=re.IGNORECASE)
    title = re.sub(r"^prefers\b", "Prefer", title, flags=re.IGNORECASE)
    title = re.sub(r"^wants\b", "Want", title, flags=re.IGNORECASE)
    title = re.sub(r"^needs\b", "Need", title, flags=re.IGNORECASE)
    title = re.sub(r"^decided(?: to)?\b", "Decision:", title, flags=re.IGNORECASE)
    title = re.sub(r"^agreed(?: to)?\b", "Decision:", title, flags=re.IGNORECASE)
    title = re.sub(r"^chose\b", "Decision:", title, flags=re.IGNORECASE)
    if memory_type == "project" and not title.lower().startswith("project"):
        title = f"Project {title[0].lower()}{title[1:]}" if title else "Project memory"
    if len(title) <= 70:
        return title or "Memory proposal"
    return title[:67].rstrip() + "..."


def _shell_words(*parts: object) -> str:
    words = [str(part) for part in parts if str(part) != ""]
    if not words:
        return ""
    if len(words) >= 2 and words[0].startswith("python") and words[1] == "link.py":
        return display_command(["link", *words[2:]])
    return display_command(words)


def memory_proposal_action(proposal: Mapping[str, object], *, command_target: str | Path = ".") -> dict[str, object]:
    """Return the safest next action for a memory proposal."""
    memory = str(proposal.get("memory") or "")
    title = str(proposal.get("title") or proposal_title(memory, str(proposal.get("memory_type") or "note")))
    memory_type = str(proposal.get("memory_type") or "note")
    scope = str(proposal.get("scope") or "user")
    visibility = str(proposal.get("visibility") or default_memory_visibility(scope))
    source = str(proposal.get("source") or "proposal")
    project = str(proposal.get("project") or "")
    duplicate_candidates = proposal.get("duplicate_candidates")
    conflict_candidates = proposal.get("conflict_candidates")
    duplicate_list = duplicate_candidates if isinstance(duplicate_candidates, list) else []
    conflict_list = conflict_candidates if isinstance(conflict_candidates, list) else []

    if duplicate_list:
        first = duplicate_list[0] if isinstance(duplicate_list[0], Mapping) else {}
        identifier = str(first.get("name") or first.get("title") or "")
        command_parts: list[object] = [
            "python3",
            "link.py",
            "update-memory",
            identifier,
            memory,
            command_target,
            "--source",
            source,
        ]
        if project:
            command_parts.extend(["--project", project])
        command = _shell_words(*command_parts)
        args: dict[str, object] = {"identifier": identifier, "memory": memory, "source": source}
        if project:
            args["project"] = project
        action = _memory_action(
            kind="update",
            label="Update existing memory",
            description="A strong duplicate exists; update it instead of creating another memory.",
            command=command,
            tool="update_memory",
            arguments=args,
            priority="high",
        )
        action["prompt"] = f'Approve by asking: update memory {identifier} with "{memory}"'
        return action

    if conflict_list:
        first = conflict_list[0] if isinstance(conflict_list[0], Mapping) else {}
        identifier = str(first.get("name") or first.get("title") or "")
        action = _memory_action(
            kind="review_conflict",
            label="Review conflict",
            description="A likely conflicting memory exists; inspect it before saving or archiving anything.",
            command=_shell_words("python3", "link.py", "explain-memory", identifier, command_target),
            tool="explain_memory",
            arguments={"identifier": identifier},
            priority="high",
        )
        action["prompt"] = f"Review possible conflict with {identifier} before saving this proposal."
        return action

    command_parts: list[object] = [
        "python3",
        "link.py",
        "remember",
        memory,
        command_target,
        "--title",
        title,
        "--type",
        memory_type,
        "--scope",
        scope,
        "--visibility",
        visibility,
        "--source",
        source,
    ]
    args: dict[str, object] = {
        "memory": memory,
        "title": title,
        "memory_type": memory_type,
        "scope": scope,
        "visibility": visibility,
        "source": source,
    }
    if project:
        command_parts.extend(["--project", project])
        args["project"] = project
    # Retrieval context rides the structured paths (MCP tool arguments,
    # accept-capture) but stays out of the paste-ready shell command —
    # a 600-char quoted blob would make the command unusable.
    proposal_context = str(proposal.get("context") or "").strip()
    if proposal_context:
        args["context"] = proposal_context
    action = _memory_action(
        kind="remember",
        label="Remember",
        description="Create a new durable memory after the user approves this proposal.",
        command=_shell_words(*command_parts),
        tool="remember_memory",
        arguments=args,
        priority="high",
    )
    action["prompt"] = f"Approve by asking: remember that {memory}"
    return action


_PREAMBLE_INTERJECTIONS = re.compile(
    r"^(?:hey|hi|hello|ok|okay|oh|so|well|also|btw|alright|great|thanks|thank you|yeah|actually|anyway)"
    r"[,!.:\s]+",
    re.IGNORECASE,
)


def _preamble_trim_candidates(text: str) -> list[str]:
    """Trim variants of a segment, most-trimmed first.

    Conversational lead-ins ("hey, before we start — ...") should not become
    part of a durable memory. A trimmed variant is only used when it still
    classifies on its own; otherwise the full text wins.
    """
    stripped = text.strip()
    plain = stripped
    for _ in range(3):
        trimmed = _PREAMBLE_INTERJECTIONS.sub("", plain, count=1).strip()
        if trimmed == plain or not trimmed:
            break
        plain = trimmed
    candidates: list[str] = []
    for dash in ("—", "–"):
        head, sep, tail = plain.partition(dash)
        if sep and tail.strip() and len(head.strip()) <= 60:
            candidates.append(tail.strip())
            break
    if plain != stripped:
        candidates.append(plain)
    candidates.append(stripped)
    return candidates


def classify_memory_segment(segment: str) -> dict[str, object] | None:
    text = segment.strip()
    lower = text.lower()
    if any(cue in lower for cue in ("maybe", "might", "not sure", "wondering", "considering", "could later")):
        return None

    checks: list[tuple[str, str, int, str, tuple[str, ...]]] = [
        (
            "preference",
            "user",
            90,
            "Matched an explicit user preference cue.",
            (
                r"\b(?:i|user|human)\s+(?:prefer|prefers|like|likes|want|wants|need|needs)\b",
                r"\b(?:please\s+)?(?:always|never|avoid|do not|don't)\b",
                r"\bagents?\s+should\s+(?:always|never|prefer|avoid|use)\b",
                r"\b(?:from now on|going forward)\b",
                r"\b(?:i|we)\s+only\s+(?:push|use|deploy|commit|merge|release|write|run|work|ship)\b",
            ),
        ),
        (
            "decision",
            "project",
            88,
            "Matched an explicit decision cue.",
            (
                r"\b(?:we|project|team|user)\s+(?:decided|agreed|chose|settled)\b",
                r"\bdecision\s*:",
            ),
        ),
        (
            "project",
            "project",
            76,
            "Matched a project context cue.",
            (
                r"\b(?:project|repo|repository|link)\s+(?:uses|requires|runs|stores|keeps|ships|releases)\b",
                r"\b(?:this project|this repo)\s+(?:uses|requires|keeps|stores)\b",
            ),
        ),
        (
            "fact",
            "user",
            74,
            "Matched a stable user fact cue.",
            (
                r"\b(?:i am|i work|user is|user works|user has|my role|my timezone)\b",
            ),
        ),
    ]

    for candidate in _preamble_trim_candidates(text):
        candidate_lower = candidate.lower()
        for memory_type, scope, score, reason, patterns in checks:
            if any(re.search(pattern, candidate_lower) for pattern in patterns):
                memory = normalize_proposed_memory(candidate, memory_type)
                return {
                    "memory": memory,
                    "memory_type": memory_type,
                    "scope": scope,
                    "confidence_score": score,
                    "reason": reason,
                }
    return None


def confidence_label(score: int) -> str:
    if score >= 85:
        return "high"
    if score >= 70:
        return "medium"
    return "low"


PROCEDURE_STEP_RE = re.compile(r"^\s*(?:\d+[.)]\s+|step\s+\d+\b)", re.IGNORECASE)


def extract_procedure_candidates(text: str, max_candidates: int = 3) -> list[dict[str, str]]:
    """Find numbered step sequences that look like reusable procedures.

    A candidate is three or more consecutive numbered step lines. The nearest
    preceding non-step line becomes the trigger ("To cut a release:") so the
    recipe is recalled by task shape, not just by its words.
    """
    lines = str(text or "").splitlines()
    candidates: list[dict[str, str]] = []
    index = 0
    while index < len(lines) and len(candidates) < max_candidates:
        if not PROCEDURE_STEP_RE.match(lines[index]):
            index += 1
            continue
        start = index
        while index < len(lines) and (PROCEDURE_STEP_RE.match(lines[index]) or not lines[index].strip()):
            index += 1
        steps = [line.strip() for line in lines[start:index] if PROCEDURE_STEP_RE.match(line)]
        if len(steps) < 3:
            continue
        trigger = ""
        for back in range(start - 1, -1, -1):
            previous = lines[back].strip()
            if previous:
                if 3 <= len(previous) <= 160 and not PROCEDURE_STEP_RE.match(previous):
                    trigger = previous.rstrip(":").strip()
                    trigger = re.sub(r"^(?:user|assistant)\s*:\s*", "", trigger, flags=re.IGNORECASE)
                break
        body = ("\n".join([trigger + ":"] if trigger else []) + "\n" + "\n".join(steps)).strip()
        if len(body) > 1500:
            body = body[:1500].rstrip() + " …"
        candidates.append({"memory": body, "trigger": trigger[:200]})
    return candidates


# A sentence can classify as a preference yet carry no durable substance —
# "I want to set some conventions" is *about* making rules, not itself a
# rule. These rank such meta-preambles below concrete directives so the
# proposal a one-click Accept lands on is the useful one, not the throat-
# clearing that happened to come first in the transcript.
_META_PREAMBLE_RE = re.compile(
    r"(?i)\b(?:want|wanted|like|need|going|trying|hoping|planning)\s+to\s+"
    r"(?:set|establish|define|create|make|figure|think|discuss|talk|"
    r"standardi[sz]e|nail|sort|work)\b"
    r"|\b(?:some|a few|certain|our|the)\s+"
    r"(?:conventions?|guidelines?|standards?|rules?|practices?|norms?|processes?)\b"
    r"|\bhow\s+we\s+(?:work|operate|do things)\b"
)
# Deliberately excludes bare temporal phrases ("from now on", "going
# forward") — they attach just as easily to a vague preamble ("I want to
# set conventions going forward") as to a real rule, so they can't earn the
# concrete bonus on their own. A genuine directive has an action verb or an
# absolute qualifier.
_CONCRETE_DIRECTIVE_RE = re.compile(
    r"(?i)\b(?:only|always|never|by default|whenever)\b"
    r"|\b(?:i|we)\s+(?:prefer|use|deploy|merge|commit|run|ship|release|test|"
    r"avoid|write|require|keep|review|pin|target)\b"
)


def memory_durability_rank(memory: str) -> int:
    """Higher = more durably useful as a standalone memory.

    Used only to order proposals within a capture (not to accept/reject):
    concrete directives outrank vague meta-statements about wanting rules.
    """
    text = str(memory or "").strip()
    rank = 0
    if _CONCRETE_DIRECTIVE_RE.search(text):
        rank += 2
    if _META_PREAMBLE_RE.search(text) and not _CONCRETE_DIRECTIVE_RE.search(text):
        rank -= 2
    return rank


def propose_memories_from_text(
    text: str,
    records: Iterable[Mapping[str, object]],
    source: str = "inline",
    limit: int = 10,
    writes_memory: bool = False,
    project: str | None = None,
    command_target: str | Path = ".",
) -> dict[str, object]:
    record_list = [dict(record) for record in records]
    project_name = normalize_project(project)
    proposals: list[dict[str, object]] = []
    seen: set[str] = set()
    skipped = 0
    for candidate in extract_procedure_candidates(text):
        memory = candidate["memory"]
        dedupe_key = compact_memory_text(memory)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        memory_type = "procedure"
        scope = "project" if project_name else "user"
        title = proposal_title(candidate["trigger"] or memory, memory_type)
        duplicate_candidates = memory_duplicate_candidates(
            record_list, memory, title, memory_type, scope, project=project_name,
        )
        conflict_candidates = memory_conflict_candidates(
            record_list, memory, title, memory_type, scope, project=project_name,
        )
        proposal = {
            "title": title,
            "memory": memory,
            "memory_type": memory_type,
            "scope": scope,
            "project": project_name if scope == "project" else "",
            "trigger": candidate["trigger"],
            "confidence": confidence_label(80),
            "confidence_score": 80,
            "reason": "Matched a numbered step sequence that looks like a reusable procedure.",
            "source": source,
            "duplicate_candidates": duplicate_candidates,
            "conflict_candidates": conflict_candidates,
            "suggested_action": "update-memory" if duplicate_candidates else (
                "review-conflict" if conflict_candidates else "remember"
            ),
        }
        proposal["primary_action"] = memory_proposal_action(proposal, command_target=command_target)
        proposals.append(proposal)
    segments = memory_proposal_segments(text)
    for index, segment in enumerate(segments):
        classified = classify_memory_segment(segment)
        if not classified:
            skipped += 1
            continue
        # Retrieval context: the neighboring sentences around the claim's
        # origin (the LoCoMo-measured +/-1 window). Helps recall find the
        # memory later; never part of the claim itself.
        segment_context = " ".join(
            segments[j] for j in (index - 1, index + 1) if 0 <= j < len(segments)
        ).strip()
        score = int(str(classified["confidence_score"]))
        if score < MEMORY_PROPOSAL_MIN_SCORE:
            skipped += 1
            continue
        memory = str(classified["memory"])
        dedupe_key = compact_memory_text(memory)
        if dedupe_key in seen:
            skipped += 1
            continue
        seen.add(dedupe_key)
        memory_type = str(classified["memory_type"])
        scope = str(classified["scope"])
        title = proposal_title(memory, memory_type)
        duplicate_candidates = memory_duplicate_candidates(
            record_list,
            memory,
            title,
            memory_type,
            scope,
            project=project_name,
        )
        conflict_candidates = memory_conflict_candidates(
            record_list,
            memory,
            title,
            memory_type,
            scope,
            project=project_name,
        )
        if conflict_candidates:
            suggested_action = "review-conflict"
        elif duplicate_candidates:
            suggested_action = "update-memory"
        else:
            suggested_action = "remember"
        proposal = {
            "title": title,
            "memory": memory,
            "memory_type": memory_type,
            "scope": scope,
            "project": project_name if scope == "project" else "",
            "context": segment_context[:600],
            "confidence": confidence_label(score),
            "confidence_score": score,
            "reason": classified["reason"],
            "source": source,
            "duplicate_candidates": duplicate_candidates,
            "conflict_candidates": conflict_candidates,
            "suggested_action": suggested_action,
        }
        proposal["primary_action"] = memory_proposal_action(proposal, command_target=command_target)
        proposals.append(proposal)
    # Rank the most durably useful proposal first so a one-click Accept (and
    # accept-capture --index 1) lands on the substance, not a meta-preamble
    # that happened to come first. Stable: equal ranks keep transcript order.
    proposals.sort(key=lambda p: memory_durability_rank(str(p.get("memory", ""))), reverse=True)
    proposals = proposals[:limit]
    return {
        "proposed": True,
        "source": source,
        "project": project_name,
        "count": len(proposals),
        "skipped_count": skipped,
        "proposals": proposals,
        "writes_memory": writes_memory,
    }
