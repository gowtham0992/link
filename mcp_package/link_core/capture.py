"""Shared raw capture helpers for Link CLI and MCP runtimes."""
from __future__ import annotations

import re
from pathlib import Path
from collections.abc import Callable, Collection, Mapping

from .files import atomic_write_text
from .frontmatter import frontmatter_string, parse_frontmatter
from .log import utc_timestamp
from .mcp_verify import display_command
from .memory import (
    normalize_project,
    proposal_fingerprint,
    propose_memories_from_text,
    slugify,
)
from .security import (
    injected_instruction_warnings,
    redact_secret_values,
    secret_value_warnings,
)


CaptureCommands = Callable[[str], dict[str, str]]
CaptureProposalBuilder = Callable[[str, str, int, str, bool], dict[str, object]]


def _shell_words(*parts: object) -> str:
    words = [str(part) for part in parts if str(part) != ""]
    if not words:
        return ""
    if len(words) >= 2 and words[0].startswith("python") and words[1] == "link.py":
        return display_command(["link", *words[2:]])
    return display_command(words)


def capture_title(
    text: str,
    source: str = "",
    title: str | None = None,
    *,
    default_source: str = "inline",
    path_source: bool = False,
    max_source_len: int = 120,
) -> str:
    """Build a stable human-readable title for saved raw memory captures."""
    if title and title.strip():
        return " ".join(title.split())

    source_value = " ".join(str(source or "").split())
    if source_value and source_value != default_source:
        if path_source:
            stem = Path(source_value).stem.replace("-", " ").replace("_", " ").strip()
            if stem:
                return f"Memory capture: {stem.title()}"
        else:
            return f"Memory capture: {source_value[:max_source_len]}"

    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "Session notes")
    short = " ".join(first_line.split()[:10]).strip(" .")
    return f"Memory capture: {short or 'Session notes'}"


def capture_filename(timestamp: str, title: str, raw_dir: Path) -> Path:
    """Atomically reserve a unique capture path under raw_dir.

    Concurrent session-end hooks (several agents/terminals closing at once)
    share the same second-timestamp and default title, so a check-then-write
    counter loop races: two hooks pick the same name and one clobbers the
    other. Claim each name with O_CREAT|O_EXCL so only one hook can own it;
    the caller overwrites the reserved placeholder with the real content.
    """
    import errno
    import os

    safe_stamp = str(timestamp).replace("-", "").replace(":", "")
    title_slug = slugify(title.replace("Memory capture:", ""), fallback="session-notes")
    base = f"{safe_stamp}-{title_slug}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    counter = 1
    while True:
        name = f"{base}.md" if counter == 1 else f"{base}-{counter}.md"
        candidate = raw_dir / name
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.close(fd)
            return candidate
        except FileExistsError:
            counter += 1
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                counter += 1
                continue
            raise
        if counter > 10000:  # pathological; give up rather than spin
            return raw_dir / f"{base}-{os.getpid()}.md"


DISMISSED_LEDGER_LIMIT = 500


def dismissed_ledger_path(root: Path) -> Path:
    """The dismissed-proposals ledger (dotfile: invisible to the inbox scan)."""
    return root.expanduser().resolve() / "raw" / "memory-captures" / ".dismissed-proposals.json"


def load_dismissed_fingerprints(root: Path) -> dict[str, dict[str, str]]:
    """Fingerprints of proposals the user already dismissed.

    Dismissal is a decision Link remembers: without it, deleting a junk
    capture just schedules the same proposal to reappear at the next
    session-end of the same conversation.
    """
    import json

    path = dismissed_ledger_path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = payload.get("fingerprints") if isinstance(payload, dict) else None
    if not isinstance(entries, dict):
        return {}
    return {
        str(fp): {
            "memory": str(entry.get("memory") or "") if isinstance(entry, dict) else "",
            "dismissed_at": str(entry.get("dismissed_at") or "") if isinstance(entry, dict) else "",
        }
        for fp, entry in entries.items()
    }


def record_dismissed_proposals(root: Path, memories: list[str]) -> int:
    """Add proposal fingerprints to the dismissed ledger; returns count added.

    Bounded FIFO (oldest dismissals fall off past DISMISSED_LEDGER_LIMIT) so
    the ledger can't grow without limit over years of sessions.
    """
    import json

    texts = [str(memory or "").strip() for memory in memories]
    texts = [text for text in texts if text]
    if not texts:
        return 0
    entries = load_dismissed_fingerprints(root)
    added = 0
    stamp = utc_timestamp()
    for text in texts:
        fingerprint = proposal_fingerprint(text)
        if fingerprint in entries:
            continue
        entries[fingerprint] = {"memory": text[:160], "dismissed_at": stamp}
        added += 1
    if not added:
        return 0
    # dicts preserve insertion order: trimming from the front drops oldest.
    if len(entries) > DISMISSED_LEDGER_LIMIT:
        for stale in list(entries.keys())[: len(entries) - DISMISSED_LEDGER_LIMIT]:
            del entries[stale]
    path = dismissed_ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps({"fingerprints": entries}, indent=2) + "\n")
    return added


def capture_proposal_fingerprints(text: str, project: str | None = None) -> set[str]:
    """Fingerprints of everything a saved capture would propose on re-mining."""
    mining_text = capture_proposal_source(text)
    if mining_text is None:
        _, mining_text = capture_notes_from_markdown(text)
    if not mining_text:
        return set()
    mined = propose_memories_from_text(mining_text, [], limit=10, project=project)
    proposals = mined.get("proposals")
    items: list[object] = proposals if isinstance(proposals, list) else []
    return {
        proposal_fingerprint(str(item.get("memory") or ""))
        for item in items
        if isinstance(item, dict) and str(item.get("memory") or "").strip()
    }


def pending_proposal_fingerprints(
    root: Path,
    *,
    exclude_conversation: str | None = None,
) -> dict[str, str]:
    """Map of proposal fingerprint -> capture rel-path across pending captures.

    Lets a session-end hook see what other conversations already put in the
    review inbox, so the same claim is never waiting in two places.
    """
    root = root.expanduser().resolve()
    capture_dir = root / "raw" / "memory-captures"
    if not capture_dir.exists():
        return {}
    fingerprints: dict[str, str] = {}
    for path in sorted(capture_dir.rglob("*.md")):
        if path.name.startswith("."):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta, _ = parse_frontmatter(text)
        if exclude_conversation and str(meta.get("conversation") or "") == exclude_conversation:
            continue
        rel = path.relative_to(root).as_posix()
        project_name = normalize_project(str(meta.get("project") or ""))
        for fingerprint in capture_proposal_fingerprints(text, project=project_name):
            fingerprints.setdefault(fingerprint, rel)
    return fingerprints


def find_conversation_capture(root: Path, conversation_id: str) -> Path | None:
    """The pending capture already holding this conversation, if any."""
    conversation = str(conversation_id or "").strip()
    if not conversation:
        return None
    root = root.expanduser().resolve()
    capture_dir = root / "raw" / "memory-captures"
    if not capture_dir.exists():
        return None
    for path in sorted(capture_dir.rglob("*.md")):
        if path.name.startswith("."):
            continue
        try:
            meta, _ = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if str(meta.get("conversation") or "") == conversation:
            return path
    return None


def write_session_capture(
    root: Path,
    *,
    text: str,
    source: str,
    title: str | None = None,
    project: str | None = None,
    timestamp: str | None = None,
    default_source: str = "inline",
    path_source: bool = False,
    proposal_text: str | None = None,
    decision_trail: list[str] | None = None,
    conversation_id: str | None = None,
    source_type: str = "conversation",
) -> dict[str, object]:
    """Persist proposal-only session notes under raw/memory-captures.

    `proposal_text` records exactly which turns memory is mined from (the
    user's own turns), so accept-time re-mining reads the same words the
    hook did — never the assistant's prose. `decision_trail` records why
    proposals were kept or dropped, so the pipeline is reviewable.
    """
    root = root.expanduser().resolve()
    notes = text.strip()
    if not notes:
        raise ValueError("session capture input is required")
    source_value = str(source or default_source).strip() or default_source
    captured_at = timestamp or utc_timestamp()
    project_name = normalize_project(project)
    capture_name = capture_title(
        notes,
        source_value,
        title,
        default_source=default_source,
        path_source=path_source,
    )
    secret_warnings = secret_value_warnings(notes)
    capture_dir = root / "raw" / "memory-captures"
    capture_dir.mkdir(parents=True, exist_ok=True)
    conversation = str(conversation_id or "").strip()
    # One capture per conversation: a session-end for a conversation that is
    # already waiting in the inbox refreshes that file (newer transcript,
    # newer proposals) instead of stacking a near-duplicate next to it.
    refreshed_capture = find_conversation_capture(root, conversation) if conversation else None
    capture_path = refreshed_capture or capture_filename(captured_at, capture_name, capture_dir)
    project_line = f'project: "{frontmatter_string(project_name)}"\n' if project_name else ""
    conversation_line = f'conversation: "{frontmatter_string(conversation)}"\n' if conversation else ""

    # Proposal source: the user's own turns, redacted, so accept-time mining
    # reads exactly what the hook mined — not the assistant's prose beneath.
    mined = (proposal_text or "").strip()
    mined_section = ""
    if mined and mined != notes:
        safe_mined, _, _ = redact_secret_values(mined)
        mined_section = f"\n## Proposal Source\n\nMemory is mined only from these (the user's own turns):\n\n{safe_mined}\n"

    trail_section = ""
    if decision_trail:
        safe_lines = []
        for line in decision_trail:
            safe, _, _ = redact_secret_values(str(line))
            safe_lines.append(f"- {safe}")
        trail_section = "\n## How Link Read This Session\n\n" + "\n".join(safe_lines) + "\n"

    atomic_write_text(
        capture_path,
        f"""---
title: "{frontmatter_string(capture_name)}"
source_type: {source_type}
date_captured: "{captured_at}"
{project_line}{conversation_line}---

# {capture_name}

Captured locally for Link memory review. This raw note is proposal-only until the user approves durable memories.

## Source Input

{source_value}
{trail_section}{mined_section}
## Notes

{notes}
""",
    )
    return {
        "path": capture_path.relative_to(root).as_posix(),
        "absolute_path": str(capture_path),
        "source": source_value,
        "title": capture_name,
        "project": project_name,
        "timestamp": captured_at,
        "secret_warnings": secret_warnings,
        "conversation": conversation,
        "refreshed": refreshed_capture is not None,
    }


def resolve_capture_file(root: Path, capture: str, *, max_len: int | None = None) -> Path | None:
    """Resolve a user-provided raw capture path without escaping the Link root."""
    raw = str(capture or "").strip()
    if max_len is not None:
        raw = raw[:max_len]
    if not raw:
        return None

    root = root.expanduser().resolve()
    raw_path = Path(raw).expanduser()
    candidates = [raw_path]
    if not raw_path.is_absolute():
        candidates.extend([
            root / raw,
            root / "raw" / "memory-captures" / raw,
            root / "raw" / "memory-captures" / f"{raw}.md",
        ])

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not resolved.is_file():
            continue
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        return resolved
    return None


def capture_notes_from_markdown(text: str) -> tuple[dict[str, object], str]:
    """Return capture frontmatter and the `## Notes` body when present."""
    meta, body = parse_frontmatter(text)
    match = re.search(r"^## Notes\s*(.*?)(?=^## |\Z)", body, flags=re.MULTILINE | re.DOTALL)
    notes = match.group(1).strip() if match else body.strip()
    return meta, notes


def capture_proposal_source(text: str) -> str | None:
    """Return the `## Proposal Source` body (user turns) when present.

    Accept-time mining reads this instead of the full notes so the
    assistant's prose is never re-attributed as the user's preference.
    """
    _, body = parse_frontmatter(text)
    match = re.search(r"^## Proposal Source\s*(.*?)(?=^## |\Z)", body, flags=re.MULTILINE | re.DOTALL)
    if not match:
        return None
    section = match.group(1).strip()
    # Drop the leading explanatory sentence Link writes above the turns.
    section = re.sub(
        r"^Memory is mined only from these \(the user's own turns\):\s*",
        "", section,
    ).strip()
    return section or None


def capture_decision_trail(text: str) -> list[str]:
    """Return the `## How Link Read This Session` bullet lines when present."""
    _, body = parse_frontmatter(text)
    match = re.search(r"^## How Link Read This Session\s*(.*?)(?=^## |\Z)", body, flags=re.MULTILINE | re.DOTALL)
    if not match:
        return []
    return [
        line.lstrip("- ").strip()
        for line in match.group(1).strip().splitlines()
        if line.strip().startswith("-")
    ]


def capture_proposal_selection(
    root: Path,
    capture: str,
    *,
    index: int = 1,
    project: str | None = None,
    default_project: str = "",
    propose_memories: CaptureProposalBuilder,
    max_capture_len: int | None = None,
) -> dict[str, object]:
    """Resolve a raw capture and return the selected proposal plus context."""
    try:
        proposal_index = int(index)
    except (TypeError, ValueError):
        raise ValueError("proposal index must be an integer")
    if proposal_index < 1:
        raise ValueError("proposal index must be 1 or greater")

    root = root.expanduser().resolve()
    capture_path = resolve_capture_file(root, capture, max_len=max_capture_len)
    if capture_path is None:
        raise ValueError(f"capture not found: {str(capture or '').strip()[:max_capture_len] if max_capture_len else capture}")

    raw_text = capture_path.read_text(encoding="utf-8", errors="replace")
    meta, notes = capture_notes_from_markdown(raw_text)
    if not notes:
        raise ValueError("capture has no notes")

    rel_path = capture_path.relative_to(root).as_posix()
    project_name = normalize_project(project or str(meta.get("project") or "") or default_project)
    # Mine from the user's own turns when the capture recorded them, so accept
    # never re-attributes the assistant's prose. Fall back to full notes for
    # older captures written before proposal-source provenance existed.
    mining_text = capture_proposal_source(raw_text) or notes
    # Imported captures mine in curated mode: the source was a deliberate
    # instruction file, so chat-junk heuristics do not apply to it.
    curated = str(meta.get("source_type") or "").strip().lower() == "import"
    proposals = propose_memories(
        mining_text,
        rel_path,
        max(1, min(max(proposal_index, 10), 50)),
        project_name,
        curated,
    )
    proposal_items = proposals.get("proposals")
    if not isinstance(proposal_items, list):
        proposal_items = []
    if proposal_index > len(proposal_items):
        raise ValueError(f"capture has {len(proposal_items)} proposal(s); index {proposal_index} is unavailable")
    proposal = proposal_items[proposal_index - 1]
    if not isinstance(proposal, dict):
        raise ValueError(f"capture proposal {proposal_index} is invalid")
    return {
        "capture_path": capture_path,
        "capture": rel_path,
        "proposal_index": proposal_index,
        "project": project_name,
        "meta": meta,
        "notes": notes,
        "proposals": proposals,
        "proposal": proposal,
    }


def capture_accept_memory_args(
    selection: Mapping[str, object],
    *,
    title: str | None = None,
    memory_type: str | None = None,
    scope: str | None = None,
    visibility: str | None = None,
    tags: str | None = None,
) -> dict[str, object]:
    """Build write_memory_page arguments for an accepted capture proposal."""
    proposal = selection.get("proposal")
    if not isinstance(proposal, Mapping):
        raise ValueError("capture proposal is invalid")
    project_name = str(selection.get("project") or "")
    chosen_scope = str(scope or proposal.get("scope") or "user")
    return {
        "text": str(proposal.get("memory") or ""),
        "title": title or str(proposal.get("title") or "Memory"),
        "memory_type": memory_type or str(proposal.get("memory_type") or "note"),
        "scope": chosen_scope,
        "visibility": visibility or str(proposal.get("visibility") or ""),
        "tags": tags,
        "source": str(selection.get("capture") or ""),
        "project": project_name if chosen_scope == "project" else "",
        "trigger": str(proposal.get("trigger") or "") or None,
        "context": str(proposal.get("context") or "") or None,
    }


def capture_accept_payload(selection: Mapping[str, object], result: Mapping[str, object]) -> dict[str, object]:
    """Build the public accept-capture payload from selection and write result."""
    proposal = selection.get("proposal")
    if not isinstance(proposal, Mapping):
        raise ValueError("capture proposal is invalid")
    return {
        "accepted": bool(result.get("created")),
        "capture": str(selection.get("capture") or ""),
        "proposal_index": selection.get("proposal_index"),
        "project": str(result.get("project") or proposal.get("project") or ""),
        "proposal": proposal,
        "result": dict(result),
    }


def redact_capture_file(
    root: Path,
    capture: str,
    *,
    replacement: str = "[redacted-secret]",
    max_capture_len: int | None = None,
) -> dict[str, object]:
    """Redact secret-looking values from a saved raw capture."""
    root = root.expanduser().resolve()
    capture_path = resolve_capture_file(root, capture, max_len=max_capture_len)
    if capture_path is None:
        label = str(capture or "").strip()
        if max_capture_len is not None:
            label = label[:max_capture_len]
        raise ValueError(f"capture not found: {label}")

    original = capture_path.read_text(encoding="utf-8", errors="replace")
    redacted, labels, replacement_count = redact_secret_values(original, replacement=replacement)
    rel_path = capture_path.relative_to(root).as_posix()
    if replacement_count:
        atomic_write_text(capture_path, redacted)
    return {
        "redacted": bool(replacement_count),
        "path": rel_path,
        "labels": labels,
        "replacement_count": replacement_count,
    }


def delete_capture_file(
    root: Path,
    capture: str,
    *,
    confirm: bool = False,
    max_capture_len: int | None = None,
    record_dismissals: bool = True,
) -> dict[str, object]:
    """Delete a saved raw capture only after explicit confirmation.

    A confirmed delete is the user declining the capture's proposals, so the
    proposal fingerprints are recorded as dismissed — the same claims won't
    re-enter the inbox from the next session of the same conversation.
    (`record_dismissals=False` is for dedup cleanup, where the surviving
    duplicate must stay proposable.)
    """
    root = root.expanduser().resolve()
    capture_path = resolve_capture_file(root, capture, max_len=max_capture_len)
    if capture_path is None:
        label = str(capture or "").strip()
        if max_capture_len is not None:
            label = label[:max_capture_len]
        raise ValueError(f"capture not found: {label}")

    rel_path = capture_path.relative_to(root).as_posix()
    payload = {
        "deleted": False,
        "path": rel_path,
        "confirmation_required": not confirm,
        "dismissed_count": 0,
    }
    if not confirm:
        return payload

    if record_dismissals:
        try:
            text = capture_path.read_text(encoding="utf-8", errors="replace")
            meta, _ = parse_frontmatter(text)
            mining_text = capture_proposal_source(text)
            if mining_text is None:
                _, mining_text = capture_notes_from_markdown(text)
            mined = propose_memories_from_text(
                mining_text or "", [], limit=10,
                project=normalize_project(str(meta.get("project") or "")),
            )
            proposals = mined.get("proposals")
            items: list[object] = proposals if isinstance(proposals, list) else []
            memories = [
                str(item.get("memory") or "")
                for item in items
                if isinstance(item, dict)
            ]
            payload["dismissed_count"] = record_dismissed_proposals(root, memories)
        except OSError:
            pass

    capture_path.unlink()
    payload["deleted"] = True
    payload["confirmation_required"] = False
    return payload


def dedup_pending_captures(
    root: Path,
    *,
    accepted_fingerprints: Collection[str] = (),
    apply: bool = False,
) -> dict[str, object]:
    """Collapse the review inbox: drop captures that offer nothing new.

    Walks pending captures newest-first (the newest copy of a conversation
    carries the longest transcript, so it survives). A capture is removable
    when everything it would propose is already covered — by a newer pending
    capture, an accepted memory, or the dismissed ledger — or when it
    proposes nothing at all. Dry-run by default; removed duplicates are NOT
    added to the dismissed ledger, because the surviving copy must stay
    proposable.
    """
    root = root.expanduser().resolve()
    capture_dir = root / "raw" / "memory-captures"
    covered: set[str] = set(accepted_fingerprints)
    covered.update(load_dismissed_fingerprints(root))
    kept: list[dict[str, object]] = []
    removable: list[dict[str, object]] = []
    entries: list[tuple[str, Path, str, str]] = []
    if capture_dir.exists():
        for path in capture_dir.rglob("*.md"):
            if path.name.startswith("."):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            meta, _ = parse_frontmatter(text)
            entries.append((str(meta.get("date_captured") or ""), path, text,
                            normalize_project(str(meta.get("project") or ""))))
    entries.sort(key=lambda item: (item[0], item[1].as_posix()), reverse=True)
    for _, path, text, project_name in entries:
        rel = path.relative_to(root).as_posix()
        fingerprints = capture_proposal_fingerprints(text, project=project_name)
        if not fingerprints:
            removable.append({"path": rel, "reason": "no_proposals"})
            continue
        fresh = fingerprints - covered
        if not fresh:
            removable.append({"path": rel, "reason": "all_duplicates"})
            continue
        covered.update(fingerprints)
        kept.append({"path": rel, "fresh_proposals": len(fresh)})
    removed: list[str] = []
    if apply:
        for item in removable:
            target = root / str(item["path"])
            try:
                target.unlink()
                removed.append(str(item["path"]))
            except OSError:
                continue
    return {
        "applied": apply,
        "kept": kept,
        "removable": removable,
        "removed": removed,
        "kept_count": len(kept),
        "removable_count": len(removable),
    }


def cli_capture_commands(rel_path: str, command_target: str | Path = ".") -> dict[str, str]:
    return {
        "accept": _shell_words("python3", "link.py", "accept-capture", rel_path, command_target, "--index", "1"),
        "redact": _shell_words("python3", "link.py", "redact-capture", rel_path, command_target),
        "delete": _shell_words("python3", "link.py", "delete-capture", rel_path, command_target, "--confirm"),
    }


def mcp_capture_commands(rel_path: str) -> dict[str, str]:
    return {
        "accept": f'accept_capture(capture="{rel_path}", index=1)',
        "redact": f'redact_capture(capture="{rel_path}")',
        "delete": f'delete_capture(capture="{rel_path}", confirm=true)',
    }


def capture_records(
    root: Path,
    limit: int = 20,
    project: str | None = None,
    commands_for: CaptureCommands | None = None,
    *,
    read_warnings: list[dict[str, str]] | None = None,
    proposal_limit: int = 3,
) -> list[dict[str, object]]:
    root = root.expanduser().resolve()
    capture_dir = root / "raw" / "memory-captures"
    if not capture_dir.exists():
        return []
    project_name = normalize_project(project)
    command_builder = commands_for or cli_capture_commands
    dismissed = set(load_dismissed_fingerprints(root))
    records: list[dict[str, object]] = []
    for path in sorted(capture_dir.rglob("*.md")):
        if path.name.startswith("."):
            continue
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            stat = path.stat()
        except OSError as exc:
            if read_warnings is not None:
                read_warnings.append({
                    "capture": rel,
                    "error": str(exc) or exc.__class__.__name__,
                })
            continue
        meta, notes = capture_notes_from_markdown(text)
        capture_project = normalize_project(str(meta.get("project") or ""))
        if project_name and capture_project and capture_project != project_name:
            continue
        warnings = secret_value_warnings(text)
        injection_warnings = injected_instruction_warnings(text)
        safe_notes, _, _ = redact_secret_values(notes)
        # What Accept will actually save: mine from the user's own turns
        # (proposal source) the same way accept-capture does, so the preview
        # matches the outcome and never surfaces the assistant's prose.
        # Dismissed proposals stay hidden here for the same reason: accept
        # excludes them, so showing them would desync preview from outcome.
        mining_text = capture_proposal_source(text) or notes
        # Imported captures preview in curated mode, mirroring accept — a
        # chat-mode preview of a curated file would hide most of what
        # accept can actually save.
        curated = str(meta.get("source_type") or "").strip().lower() == "import"
        preview_cap = max(1, min(int(proposal_limit or 3), 50))
        mined = propose_memories_from_text(
            mining_text, [], source=rel, limit=preview_cap,
            exclude_fingerprints=dismissed, curated=curated,
        )
        proposals_obj = mined.get("proposals")
        proposal_items: list[object] = proposals_obj if isinstance(proposals_obj, list) else []
        proposal_previews: list[dict[str, object]] = []
        for proposal in proposal_items[:preview_cap]:
            if not isinstance(proposal, dict):
                continue
            preview_text, _, _ = redact_secret_values(str(proposal.get("memory") or ""))
            proposal_previews.append({
                "title": str(proposal.get("title") or ""),
                "memory": preview_text[:240],
                "memory_type": str(proposal.get("memory_type") or ""),
                "confidence": str(proposal.get("confidence") or ""),
            })
        records.append({
            "path": rel,
            "title": str(meta.get("title") or path.stem),
            "project": capture_project,
            "date_captured": str(meta.get("date_captured") or ""),
            "size_bytes": stat.st_size,
            "secret_warnings": warnings,
            "warning_count": len(warnings),
            "injection_warnings": injection_warnings,
            "snippet": re.sub(r"\s+", " ", safe_notes).strip()[:180],
            "proposal_count": len(proposal_items),
            "proposals": proposal_previews,
            "decision_trail": capture_decision_trail(text),
            "mined_from_user_turns": capture_proposal_source(text) is not None,
            "commands": command_builder(rel),
        })
    records.sort(key=lambda item: (str(item["date_captured"]), str(item["path"])), reverse=True)
    return records[:max(1, min(limit, 50))]


def capture_inbox(
    root: Path,
    limit: int = 20,
    project: str | None = None,
    commands_for: CaptureCommands | None = None,
    *,
    proposal_limit: int = 3,
) -> dict[str, object]:
    project_name = normalize_project(project)
    read_warnings: list[dict[str, str]] = []
    captures = capture_records(
        root,
        limit=limit,
        project=project_name,
        commands_for=commands_for,
        read_warnings=read_warnings,
        proposal_limit=proposal_limit,
    )
    return {
        "count": len(captures),
        "warning_count": sum(1 for capture in captures if capture["warning_count"]),
        "read_warning_count": len(read_warnings),
        "read_warnings": read_warnings,
        "project": project_name,
        "captures": captures,
    }


def render_capture_inbox_text(payload: dict[str, object]) -> str:
    """Render human-readable raw capture inbox output."""
    project_name = str(payload.get("project") or "")
    captures_obj = payload.get("captures")
    captures: list[object] = captures_obj if isinstance(captures_obj, list) else []
    warning_count_obj = payload.get("warning_count")
    warning_count = warning_count_obj if isinstance(warning_count_obj, int) else 0
    read_warning_count_obj = payload.get("read_warning_count")
    read_warning_count = read_warning_count_obj if isinstance(read_warning_count_obj, int) else 0
    read_warnings_obj = payload.get("read_warnings")
    read_warnings: list[object] = read_warnings_obj if isinstance(read_warnings_obj, list) else []

    lines = ["Raw capture inbox"]
    if project_name:
        lines.append(f"Project: {project_name}")
    lines.append(
        f"{len(captures)} readable capture{'s' if len(captures) != 1 else ''} · "
        f"{warning_count} with secret-looking warnings · {read_warning_count} read warnings"
    )
    if read_warnings:
        lines.extend(["", "Capture read warnings:"])
        for warning in read_warnings[:20]:
            if isinstance(warning, dict):
                lines.append(f"   {warning.get('capture')}: {warning.get('error')}")
    if not captures:
        lines.extend(["", "No readable saved raw captures."])
        return "\n".join(lines)
    for index, capture in enumerate(captures, start=1):
        if not isinstance(capture, dict):
            continue
        commands_obj = capture.get("commands")
        commands: dict[object, object] = commands_obj if isinstance(commands_obj, dict) else {}
        secret_warnings_obj = capture.get("secret_warnings")
        secret_warnings: list[object] = secret_warnings_obj if isinstance(secret_warnings_obj, list) else []
        lines.extend(["", f"{index}. {capture.get('title')}"])
        lines.append(f"   Path: {capture.get('path')}")
        if capture.get("project"):
            lines.append(f"   Project: {capture.get('project')}")
        if secret_warnings:
            lines.append("   Secret-looking values: " + ", ".join(str(label) for label in secret_warnings))
        injection_obj = capture.get("injection_warnings")
        injection_list: list[object] = injection_obj if isinstance(injection_obj, list) else []
        if injection_list:
            lines.append(
                "   Injection-shaped instructions: "
                + ", ".join(str(label) for label in injection_list)
                + " — verify you actually said this before accepting."
            )
        lines.append(f"   Accept: {commands.get('accept')}")
        if secret_warnings:
            lines.append(f"   Redact: {commands.get('redact')}")
        lines.append(f"   Delete: {commands.get('delete')}")
    return "\n".join(lines)


def render_accept_capture_text(payload: dict[str, object], *, target: object = ".") -> tuple[int, str]:
    """Render accept-capture text and return the corresponding exit code."""
    if not payload.get("accepted"):
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        duplicate_candidates = result.get("duplicate_candidates") or result.get("candidates")
        if isinstance(duplicate_candidates, list) and duplicate_candidates:
            first = duplicate_candidates[0]
            if isinstance(first, dict):
                return 1, f"Duplicate candidate: {first.get('title')} ({first.get('path')})"
        conflict_candidates = result.get("conflict_candidates")
        if isinstance(conflict_candidates, list) and conflict_candidates:
            first = conflict_candidates[0]
            if isinstance(first, dict):
                return 1, f"Conflict candidate: {first.get('title')} ({first.get('path')})"
        return 1, "Capture proposal was not accepted."

    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    lines = [
        "Capture proposal accepted",
        f"Capture: {payload.get('capture')}",
        f"Proposal: {payload.get('proposal_index')}",
        f"Memory: {result.get('path')}",
    ]
    if result.get("project"):
        lines.append(f"Project: {result.get('project')}")
    if payload.get("capture_cleared"):
        lines.append("Capture cleared from the inbox — nothing left to review in it.")
    lines.extend(["", "Next:", f"  {_shell_words('python3', 'link.py', 'review-memory', result.get('name'), target)}"])
    return 0, "\n".join(lines)


def render_redact_capture_text(payload: dict[str, object]) -> str:
    """Render redact-capture CLI output."""
    if payload.get("redacted"):
        labels_obj = payload.get("labels")
        labels: list[object] = labels_obj if isinstance(labels_obj, list) else []
        return "\n".join([
            "Capture redacted",
            f"Path: {payload.get('path')}",
            "Labels: " + ", ".join(str(label) for label in labels),
            f"Replacement count: {payload.get('replacement_count', 0)}",
        ])
    return "\n".join([
        "No secret-looking values found.",
        f"Path: {payload.get('path')}",
    ])


def render_delete_capture_text(payload: dict[str, object], *, target: object = ".") -> tuple[int, str]:
    """Render delete-capture CLI output and return the corresponding exit code."""
    path = str(payload.get("path") or "")
    if payload.get("confirmation_required"):
        return 1, "\n".join([
            "Confirmation required.",
            f"Run: {_shell_words('python3', 'link.py', 'delete-capture', path, target, '--confirm')}",
        ])
    if payload.get("deleted"):
        return 0, "\n".join([
            "Capture deleted",
            f"Path: {path}",
        ])
    return 1, "\n".join([
        "Capture was not deleted.",
        f"Path: {path}",
    ])


def render_capture_session_text(payload: dict[str, object]) -> str:
    """Render capture-session CLI output."""
    proposals = payload.get("proposals") if isinstance(payload.get("proposals"), dict) else {}
    proposal_items = proposals.get("proposals") if isinstance(proposals.get("proposals"), list) else []
    lines = [
        "Session captured",
        f"Path: {payload.get('path')}",
    ]
    if payload.get("project"):
        lines.append(f"Project: {payload.get('project')}")
    secret_warnings = payload.get("secret_warnings") if isinstance(payload.get("secret_warnings"), list) else []
    if secret_warnings:
        lines.append("Secret-looking content: " + ", ".join(str(label) for label in secret_warnings))
    lines.append(f"Proposals: {proposals.get('count', 0)}")
    if not proposal_items:
        lines.append("No durable memory candidates found.")
        return "\n".join(lines)
    for index, proposal in enumerate(proposal_items, start=1):
        if not isinstance(proposal, dict):
            continue
        lines.extend([
            "",
            f"{index}. {proposal.get('title')} [{proposal.get('confidence')}]",
            f"   Type: {proposal.get('memory_type')} | Scope: {proposal.get('scope')}",
        ])
        if proposal.get("project"):
            lines.append(f"   Project: {proposal.get('project')}")
        lines.append(f"   Action: {proposal.get('suggested_action')}")
        lines.append(f"   Memory: {proposal.get('memory')}")
    lines.extend(["", "Next:", "  Ask the user which proposals to remember, update, or discard."])
    return "\n".join(lines)


def render_session_end_text(payload: dict[str, object]) -> str:
    """Render the agent-friendly session-end proposal output."""
    proposals = payload.get("proposals") if isinstance(payload.get("proposals"), dict) else {}
    proposal_items = proposals.get("proposals") if isinstance(proposals.get("proposals"), list) else []
    lines = [
        "Link session end",
        "Captured proposal-only session notes for review.",
        f"Path: {payload.get('path')}",
    ]
    if payload.get("project"):
        lines.append(f"Project: {payload.get('project')}")
    secret_warnings = payload.get("secret_warnings") if isinstance(payload.get("secret_warnings"), list) else []
    if secret_warnings:
        lines.append("Secret-looking content: " + ", ".join(str(label) for label in secret_warnings))
    lines.append(f"Memory proposals: {proposals.get('count', 0)}")
    if not proposal_items:
        lines.extend([
            "No durable memory candidates found.",
            "",
            "Next:",
            "  Continue without saving memory.",
        ])
        return "\n".join(lines)
    for index, proposal in enumerate(proposal_items, start=1):
        if not isinstance(proposal, dict):
            continue
        lines.extend([
            "",
            f"{index}. {proposal.get('title')} [{proposal.get('confidence')}]",
            f"   Type: {proposal.get('memory_type')} | Scope: {proposal.get('scope')}",
        ])
        if proposal.get("project"):
            lines.append(f"   Project: {proposal.get('project')}")
        lines.append(f"   Action: {proposal.get('suggested_action')}")
        lines.append(f"   Memory: {proposal.get('memory')}")
    lines.extend([
        "",
        "Next:",
        "  Ask the user which proposals to remember, update, archive, or discard.",
        "  Do not save durable memory without approval.",
    ])
    return "\n".join(lines)


def capture_review_summary(
    root: Path,
    limit: int = 3,
    project: str | None = None,
    commands_for: CaptureCommands | None = None,
) -> dict[str, object]:
    """Return compact capture backlog context for briefs, audits, and dashboards."""
    payload = capture_inbox(
        root,
        limit=50,
        project=project,
        commands_for=commands_for,
    )
    captures = payload["captures"] if isinstance(payload.get("captures"), list) else []
    return {
        "count": len(captures),
        "warning_count": int(payload.get("warning_count") or 0),
        "read_warning_count": int(payload.get("read_warning_count") or 0),
        "read_warnings": payload.get("read_warnings") if isinstance(payload.get("read_warnings"), list) else [],
        "project": str(payload.get("project") or ""),
        "items": captures[:max(1, min(limit, 10))],
    }
