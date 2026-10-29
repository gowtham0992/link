"""One-time approvals for held tool calls on agents that cannot ask.

An `ask` rule means "this call needs the person's OK". Claude Code, Copilot,
Gemini, Antigravity and Cursor's shell event can show the person a
confirmation themselves. Codex, Windsurf, Kiro, Devin, and Cursor's file
events can only allow or block. On those, Link blocks the call, files a
request here, and tells the agent to ask the person in chat. If the person
agrees, they run `lnk approve <id>` (or approve it in LinkBar) and the agent
repeats the exact same call, which then goes through once.

A grant is for one exact call - every command, read and write the tool
call names, from the same directory, writing the same content - is used up by the call it lets
through, and expires after a few minutes, so an approval never becomes a
standing exception. Kiro can check one call twice, from its global hooks
and from Link's agent profile: the second check, from the other hook,
within a few seconds, is the same call and goes through with it. Agents cannot approve their own requests: `lnk approve`
is a governance command the pre-tool hook holds however it is spelt, and
this file sits under the cache directory the hook protects. A file that is
not well-formed, or that has a second hard link to it, is treated as empty:
a held call then stays held.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shlex
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .files import atomic_write_text_unlocked, file_lock

GRANT_MINUTES = 10
REQUEST_HOURS = 24
# How long a used grant still covers the same call checked again by a different hook (Kiro).
REPEAT_SECONDS = 5
MAX_REQUESTS = 200
# Shorter than the hook's own 10 s timeout, so a stuck lock fails the call
# closed (held) instead of the agent killing the hook mid-write.
LOCK_SECONDS = 2.0


def call_key(calls: Iterable[tuple[str, str]], cwd: str, content: str = "") -> str:
    """One exact call: every command, read and write it names, as sent, from one directory, writing what it writes."""
    exact: dict[str, object] = {"cwd": cwd, "calls": sorted(calls)}
    if content:
        exact["content"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
    payload = json.dumps(exact, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# How much of what a call writes the person sees before approving it.
CONTENT_LINES = 12
CONTENT_CHARS = 800


def call_display(calls: Iterable[tuple[str, str]], cwd: str, content: str = "") -> str:
    """What the person approves: the whole call, line breaks kept, and the start of what it writes."""
    lines = [f"{kind}: {value}" for kind, value in sorted(calls)]
    if content:
        shown = content[:CONTENT_CHARS].splitlines()[:CONTENT_LINES]
        rest = len(content) - len("\n".join(shown))
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
        lines += [f"writing (sha256 {digest}):", *(f"  {line}" for line in shown)]
        lines += [f"  ... and {rest} more characters"] if rest > 0 else []
    return "\n".join(lines + ([f"(in {cwd})"] if cwd else []))


def approvals_path(link_root: Path) -> Path:
    return link_root / ".link-cache" / "approvals.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _save(path: Path, data: dict[str, dict[str, dict[str, object]]]) -> None:
    """Write under the lock the caller holds."""
    atomic_write_text_unlocked(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def _parse(value: object) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _load(path: Path) -> dict[str, dict[str, dict[str, object]]]:
    empty: dict[str, dict[str, dict[str, object]]] = {"requests": {}, "grants": {}}
    try:
        if path.stat().st_nlink > 1:
            return empty  # a second name for this file could have written a grant
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(data, dict):
        return empty
    loaded = empty
    for name in ("requests", "grants"):
        bucket = data.get(name)
        for key, entry in (bucket.items() if isinstance(bucket, dict) else []):
            if isinstance(key, str) and isinstance(entry, dict) and isinstance(entry.get("at"), str) and (
                name == "grants" or isinstance(entry.get("key"), str)
            ):
                loaded[name][key] = entry
    return loaded


def _prune(data: dict[str, dict[str, dict[str, object]]], now: datetime) -> None:
    for name, ttl in (("requests", timedelta(hours=REQUEST_HOURS)), ("grants", timedelta(minutes=GRANT_MINUTES))):
        bucket = data[name]
        for key in list(bucket):
            created = _parse(bucket[key].get("at"))
            if created is None or now - created > ttl or created - now > timedelta(minutes=1):
                del bucket[key]
                continue
            used = bucket[key].get("used")
            if used is not None and ((stamp := _parse(used)) is None or now - stamp > timedelta(seconds=REPEAT_SECONDS)):
                del bucket[key]
    if len(data["requests"]) > MAX_REQUESTS:
        oldest = sorted(data["requests"], key=lambda key: str(data["requests"][key].get("at")))
        for key in oldest[: len(data["requests"]) - MAX_REQUESTS]:
            del data["requests"][key]


def request(link_root: Path, key: str, *, display: str, title: str, rule: str, agent: str, session: str = "",
            now: datetime | None = None) -> str:
    """File (or re-use) a pending request for this exact call; returns its id."""
    moment = now or _now()
    path = approvals_path(link_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path, timeout=LOCK_SECONDS):
        data = _load(path)
        _prune(data, moment)
        for request_id, entry in data["requests"].items():
            if entry.get("key") == key:
                return request_id
        request_id = secrets.token_hex(3)
        while request_id in data["requests"]:
            request_id = secrets.token_hex(3)
        data["requests"][request_id] = {
            "key": key, "display": display, "title": title, "rule": rule, "agent": agent, "session": session,
            "at": _stamp(moment),
        }
        _save(path, data)
    return request_id


def approve(link_root: Path, request_id: str, now: datetime | None = None) -> dict[str, object] | None:
    """Turn a pending request into a one-time grant. None if there is no such request."""
    moment = now or _now()
    path = approvals_path(link_root)
    if not path.exists():
        return None
    with file_lock(path, timeout=LOCK_SECONDS):
        data = _load(path)
        _prune(data, moment)
        entry = data["requests"].pop(request_id.strip().lower(), None)
        if entry is None:
            _save(path, data)
            return None
        data["grants"][str(entry["key"])] = {**entry, "at": _stamp(moment), "request": request_id}
        _save(path, data)
    return entry


def take_grant(link_root: Path, key: str, now: datetime | None = None, *, hook: str = "") -> bool:
    """Use up the grant for this exact call, if the person gave one in the last few minutes.

    `hook` names the hook checking the call; one check of the same call from
    a different hook, right after, is let through with it (see above).
    """
    path = approvals_path(link_root)
    if not path.exists():
        return False
    moment = now or _now()
    with file_lock(path, timeout=LOCK_SECONDS):
        data = _load(path)
        _prune(data, moment)
        entry = data["grants"].get(key)
        if entry is None:
            granted = False
        elif "used" not in entry:
            entry.update(used=_stamp(moment), used_by=hook)
            granted = True
        else:
            granted = bool(hook) and entry.get("used_by") not in {hook, None} and not entry.get("repeated")
            if granted:
                entry["repeated"] = True
            else:
                del data["grants"][key]
        _save(path, data)
    return granted


def pending(link_root: Path, now: datetime | None = None) -> list[dict[str, object]]:
    """Requests waiting for the person, newest first."""
    data = _load(approvals_path(link_root))
    _prune(data, now or _now())
    rows = [{"id": request_id, **entry} for request_id, entry in data["requests"].items()]
    return sorted(rows, key=lambda row: str(row.get("at")), reverse=True)


def quote_argument(text: str, *, windows: bool | None = None) -> str:
    """A path the person can paste into their shell: POSIX quoting, or double quotes for cmd and PowerShell."""
    if os.name == "nt" if windows is None else windows:
        return text if re.fullmatch(r"[\w\\/:.~-]+", text) else f'"{text}"'
    return shlex.quote(text)


def held_reason(decision_reason: str, request_id: str, workspace: Path) -> str:
    """The block message an agent that cannot ask passes on to the person."""
    base = decision_reason.split(" If the person approves")[0]
    return (
        f"{base} This agent cannot ask the person itself, so the call was held, not run. "
        "Do not retry it and do not work around it: tell the person what you want to run and why. "
        f"If they agree, they approve it once with `lnk approve {request_id} {quote_argument(str(workspace))}` "
        "(or in LinkBar); then run exactly the same call again. Never run that command yourself."
    )


def self_only_reason(decision_reason: str) -> str:
    """For a call only the person may make (a rule change, an edit to Link's files)."""
    base = decision_reason.split(" If the person approves")[0]
    return (
        f"{base} Only the person can do this, and this agent cannot ask them itself: do not retry it. "
        "Tell them what you wanted to do and why; they do it themselves, in their own terminal, the viewer "
        "or LinkBar."
    )
