"""Session handoff: switch agents mid-task and lose nothing.

The most universal pain of multi-agent work is the switch: a rate limit
hits mid-task, or the next step suits a different tool, and the first
minutes of the new session are spent re-explaining what the old one
already knew. The community's answer is the hand-rolled HANDOFF.md file;
this module is that pattern productized on Link's rails.

A handoff is a small standalone packet - task, decisions made, current
state, explicit next steps - written by one session and pushed loudly
into the next one, whatever agent runs it. Design rules, learned from
the people who hand-roll this today:

- **No return path.** The receiving session cannot ask the old one what
  it meant, so the packet must stand alone.
- **Push, never pull.** Delivery must not depend on the receiving agent
  thinking to ask: handoffs ride at the top of the session-start brief
  and the MCP first-response digest.
- **Ephemeral by design.** A handoff describes a moment, not a truth; it
  expires on its own (default 48h) and never becomes durable memory
  unless the user promotes it through the normal review gate.

Handoffs live under `raw/handoffs/` - beside captures, never inside
`wiki/`, so they are machine-local by default (raw/ never syncs).
Secret-shaped values are redacted at write time, exactly like captures.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .frontmatter import frontmatter_string, parse_frontmatter
from .files import atomic_write_text
from .memory import normalize_project
from .security import redact_secret_values

HANDOFF_DIR = "handoffs"
HANDOFF_TTL_HOURS = 48
# Briefs must stay briefs even when a handoff is verbose.
HANDOFF_BRIEF_MAX_CHARS = 1500


def handoff_dir(root: Path) -> Path:
    return root.expanduser().resolve() / "raw" / HANDOFF_DIR


def _now(now: str | None = None) -> datetime:
    if now:
        return datetime.fromisoformat(now.replace("Z", "+00:00"))
    return datetime.now(timezone.utc)


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "handoff"


def write_handoff(
    root: Path,
    note: str,
    *,
    task: str | None = None,
    next_steps: list[str] | None = None,
    source: str = "cli",
    project: str | None = None,
    now: str | None = None,
    ttl_hours: int = HANDOFF_TTL_HOURS,
) -> dict[str, object]:
    """Write one standalone handoff packet. Returns its record."""
    body = (note or "").strip()
    if not body and not (task or "").strip():
        raise ValueError("a handoff needs a note describing where you left off")
    created = _now(now)
    expires = created + timedelta(hours=max(1, int(ttl_hours)))
    project_name = normalize_project(project)
    safe_body, _, _ = redact_secret_values(body)
    # Title (and the filename slug derived from it) must come from the
    # redacted text - the first line of a note can carry the secret.
    safe_task, _, _ = redact_secret_values((task or "").strip())
    title = (safe_task or safe_body.splitlines()[0]).strip()[:80]
    steps = [str(step).strip() for step in (next_steps or []) if str(step).strip()]
    steps_section = ""
    if steps:
        safe_steps = []
        for step in steps:
            safe, _, _ = redact_secret_values(step)
            safe_steps.append(f"- {safe}")
        steps_section = "\n## Next Steps\n\n" + "\n".join(safe_steps) + "\n"

    # Chain breadcrumb: the newest pending handoff becomes this one's parent,
    # so a long relay of sessions stays walkable.
    previous = pending_handoffs(root, now=now)
    previous_line = ""
    if previous:
        previous_line = f'previous: "{frontmatter_string(str(previous[0]["path"]))}"\n'

    directory = handoff_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = created.strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{stamp}-{_slug(title)}.md"
    counter = 2
    while path.exists():
        path = directory / f"{stamp}-{_slug(title)}-{counter}.md"
        counter += 1

    project_line = f'project: "{frontmatter_string(project_name)}"\n' if project_name else ""
    atomic_write_text(path, f"""---
title: "{frontmatter_string(title)}"
source_type: handoff
source: "{frontmatter_string(source)}"
created_at: "{created.strftime('%Y-%m-%dT%H:%M:%SZ')}"
expires_at: "{expires.strftime('%Y-%m-%dT%H:%M:%SZ')}"
{project_line}{previous_line}---

# {title}

Session handoff. Standalone by design: the next session cannot ask this
one what it meant.

## Where I Left Off

{safe_body}
{steps_section}""")
    return {
        "path": str(path.relative_to(root.expanduser().resolve())),
        "absolute_path": str(path),
        "title": title,
        "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project": project_name,
        "source": source,
    }


def pending_handoffs(
    root: Path,
    project: str | None = None,
    now: str | None = None,
) -> list[dict[str, object]]:
    """Unexpired handoffs, newest first. Expired files are left in place
    (they are the chain's history) but never surfaced."""
    directory = handoff_dir(root)
    if not directory.is_dir():
        return []
    current = _now(now)
    project_name = normalize_project(project)
    records: list[dict[str, object]] = []
    for path in sorted(directory.glob("*.md"), reverse=True):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta, body = parse_frontmatter(text)
        if str(meta.get("source_type") or "") != "handoff":
            continue
        expires_raw = str(meta.get("expires_at") or "")
        try:
            expires = _now(expires_raw) if expires_raw else None
        except ValueError:
            expires = None
        if expires is not None and expires <= current:
            continue
        handoff_project = normalize_project(str(meta.get("project") or ""))
        if project_name and handoff_project and handoff_project != project_name:
            continue
        # Surface only the substance: everything from "Where I Left Off"
        # down, without the title heading and the standalone boilerplate.
        marker = "## Where I Left Off"
        content = body[body.index(marker) + len(marker):].strip() if marker in body else body.strip()
        records.append({
            "path": str(path.relative_to(root.expanduser().resolve())),
            "absolute_path": str(path),
            "title": str(meta.get("title") or path.stem),
            "source": str(meta.get("source") or ""),
            "created_at": str(meta.get("created_at") or ""),
            "expires_at": expires_raw,
            "project": handoff_project,
            "body": content,
        })
    return records


def clear_handoff(root: Path, identifier: str) -> dict[str, object]:
    """Delete a handoff by path or filename. Explicit, like delete-capture."""
    root = root.expanduser().resolve()
    name = Path(identifier).name
    path = handoff_dir(root) / name
    if not path.is_file():
        raise ValueError(f"handoff not found: {name}")
    path.unlink()
    return {"cleared": True, "path": str(path.relative_to(root))}


def _age_label(created_at: str, now: str | None = None) -> str:
    try:
        created = _now(created_at)
    except ValueError:
        return ""
    minutes = int((_now(now) - created).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    return f"{hours}h ago" if hours < 48 else f"{hours // 24}d ago"


def handoff_brief_block(
    handoffs: list[dict[str, object]],
    *,
    clear_command: str = "lnk handoffs --clear <file>",
    now: str | None = None,
) -> str:
    """The loud text block briefs open with when a handoff is waiting.

    Delivery is push by design: it must never depend on the receiving
    agent thinking to ask.
    """
    if not handoffs:
        return ""
    newest = handoffs[0]
    age = _age_label(str(newest.get("created_at") or ""), now)
    source = str(newest.get("source") or "a previous session")
    body = str(newest.get("body") or "")
    if len(body) > HANDOFF_BRIEF_MAX_CHARS:
        body = body[:HANDOFF_BRIEF_MAX_CHARS - 1] + "…"
    lines = [
        f"HANDOFF WAITING ({age} · from {source}): {newest.get('title')}",
        "",
        body,
        "",
        "Resume this task before anything else, then clear it: "
        f"{clear_command.replace('<file>', Path(str(newest.get('path'))).name)}",
    ]
    if len(handoffs) > 1:
        lines.append(f"({len(handoffs) - 1} older handoff(s) also pending — lnk handoffs)")
    return "\n".join(lines)
