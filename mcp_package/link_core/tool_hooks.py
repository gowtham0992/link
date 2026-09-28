"""Memory that acts when the agent acts: rules, touched code, and delivery.

A memory the agent has read is still only advice. Three things here close
the gap between "the agent was told" and "the agent did the right thing":

- **Enforced rules.** A reviewed memory can carry an `enforce` clause such as
  `ask command: git push --force*` or `deny write: migrations/**`. Before a
  tool call runs, the pre-tool hook matches the call against every active,
  reviewed rule and asks the person (or, when the rule says deny, blocks the
  call), citing the memory. Matching is a glob over the command or path: no
  model, no network, and a rule only takes effect after human review, so a
  bad memory can never become a bad block on its own.
- **Code-triggered recall.** When the agent reads or edits a file, the memories
  anchored to that file (`anchors`, recorded when the memory was written from
  inside the repository) are surfaced once per session. A memory whose anchored symbol is gone from the file is not
  surfaced: it may be stale, and `lnk stale` says so.
- **Delivery tokens.** Everything a hook injects is wrapped in a short
  `(link:<id>)` ... `(link:<id> end)` pair. At session end the transcript is
  searched for both halves, so the receipt can say whether each injection
  arrived whole, arrived cut off, or never arrived.

The hooks run on every tool call, so they read a compiled index
(`.link-cache/hook-index.json`) that is rebuilt only when a memory file
changes, instead of parsing the store each time.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import secrets
import shlex
from collections.abc import Iterable, Mapping
from pathlib import Path

from .enforce_rules import parse_enforce_rules
from .files import atomic_write_json
from .memory import (
    is_active_memory,
    memory_quarantined,
    memory_records,
    memory_visible_for_project,
    normalize_project,
)
from .provenance import MAX_FILE_BYTES, locate, parse_anchor

HOOK_INDEX_VERSION = 1
# At most this many anchored memories per touched file, each on one line:
# a reminder, not a second brief.
MAX_TOUCH_REMINDERS = 3
# Hook output past roughly 10,000 characters is dropped by some hosts without
# a warning; everything Link injects from a hook stays well under it.
HOOK_OUTPUT_BUDGET = 9000

_SHELL_SPLIT_RE = re.compile(r"\s*(?:&&|\|\||;|\||\n)\s*")
_WRITE_TOOLS = {"write", "edit", "multiedit", "notebookedit", "str_replace_based_edit_tool", "create_file"}
_READ_TOOLS = {"read", "view", "notebookread"}
_SHELL_TOOLS = {"bash", "powershell", "shell", "run_shell_command", "terminal"}


def hook_index_path(link_root: Path) -> Path:
    return link_root / ".link-cache" / "hook-index.json"


def _memories_signature(wiki_dir: Path) -> str:
    digest = hashlib.sha256()
    memories = wiki_dir / "memories"
    if memories.is_dir():
        for path in sorted(memories.glob("*.md")):
            try:
                stat = path.stat()
            except OSError:
                continue
            digest.update(f"{path.name}\0{stat.st_mtime_ns}\0{stat.st_size}\n".encode())
    return digest.hexdigest()


def _eligible(record: Mapping[str, object]) -> bool:
    """Only reviewed, active, unquarantined memories may act on tool calls."""
    return (
        is_active_memory(record)
        and not memory_quarantined(record)
        and str(record.get("review_status") or "").lower() == "reviewed"
    )


def build_hook_index(wiki_dir: Path) -> dict[str, object]:
    rules: list[dict[str, object]] = []
    anchors: dict[str, list[dict[str, object]]] = {}
    for record in memory_records(wiki_dir, include_body=False):
        if not _eligible(record):
            continue
        head = {
            "name": str(record.get("name") or ""),
            "title": str(record.get("title") or ""),
            "claim": str(record.get("tldr") or record.get("title") or "")[:240],
            "scope": str(record.get("scope") or "user"),
            "project": str(record.get("project") or ""),
            "visibility": str(record.get("visibility") or ""),
        }
        enforce = record.get("enforce")
        for rule in parse_enforce_rules(enforce if isinstance(enforce, list) else []):
            rules.append({**head, "action": rule.action, "kind": rule.kind, "pattern": rule.pattern})
        anchor_values = record.get("anchors")
        for anchor in anchor_values if isinstance(anchor_values, list) else []:
            parsed = parse_anchor(str(anchor))
            if parsed is None or not parsed[3]:
                continue
            rel, line, symbol, repo = parsed
            anchors.setdefault(rel, []).append({**head, "line": line, "symbol": symbol, "repo": repo})
    return {"version": HOOK_INDEX_VERSION, "rules": rules, "anchors": anchors}


def load_hook_index(wiki_dir: Path, link_root: Path) -> dict[str, object]:
    """The compiled index, rebuilt only when a memory file changed."""
    signature = _memories_signature(wiki_dir)
    path = hook_index_path(link_root)
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("version") == HOOK_INDEX_VERSION and cached.get("signature") == signature:
            return cached
    except (OSError, ValueError, AttributeError):
        pass
    index = build_hook_index(wiki_dir)
    index["signature"] = signature
    try:
        atomic_write_json(path, index)
    except OSError:
        pass  # a read-only cache costs speed, never correctness
    return index


def _applies_to_project(entry: Mapping[str, object], project: str | None) -> bool:
    return memory_visible_for_project(entry, normalize_project(project or ""))


def _shell_segments(command: str) -> list[str]:
    segments = [" ".join(part.split()) for part in _SHELL_SPLIT_RE.split(command) if part.strip()]
    whole = " ".join(command.split())
    return [whole, *[segment for segment in segments if segment != whole]]


def _command_matches(pattern: str, command: str) -> bool:
    wanted = " ".join(pattern.split())
    for segment in _shell_segments(command):
        # `sudo`/`env X=1` prefixes do not hide the command they run.
        candidates = [segment]
        try:
            words = shlex.split(segment)
        except ValueError:
            words = segment.split()
        while words and (words[0] in {"sudo", "env", "command", "exec", "nohup", "time"} or "=" in words[0]):
            words = words[1:]
            candidates.append(" ".join(words))
        if any(fnmatch.fnmatchcase(candidate, wanted) for candidate in candidates):
            return True
    return False


def _path_matches(pattern: str, file_path: str, repo_root: Path | None) -> bool:
    raw = str(file_path or "").strip()
    if not raw:
        return False
    candidates = {raw.replace("\\", "/")}
    if repo_root is not None:
        try:
            candidates.add(Path(raw).resolve().relative_to(repo_root.resolve()).as_posix())
        except (OSError, ValueError):
            pass
    wanted = pattern.replace("\\", "/")
    for candidate in candidates:
        if fnmatch.fnmatch(candidate, wanted) or fnmatch.fnmatch(candidate, f"*/{wanted}"):
            return True
        # "migrations/**" also covers the directory's files at any depth.
        if wanted.endswith("/**") and (f"/{wanted[:-3]}/" in f"/{candidate}"):
            return True
    return False


def tool_call(event: Mapping[str, object]) -> tuple[str, str] | None:
    """(kind, value) for a hook event: a shell command, or a file read or write."""
    tool = str(event.get("tool_name") or "").strip()
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    assert isinstance(tool_input, dict)
    lowered = tool.lower()
    if lowered in _SHELL_TOOLS or (not tool and event.get("command")):
        command = tool_input.get("command") if tool else event.get("command")
        return ("command", str(command or "")) if command else None
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path")
    if not file_path and not tool:
        file_path = event.get("file_path")
    if not file_path:
        return None
    if lowered in _WRITE_TOOLS:
        return "write", str(file_path)
    if lowered in _READ_TOOLS or not tool:
        return "read", str(file_path)
    return None


def evaluate_tool_call(
    index: Mapping[str, object],
    event: Mapping[str, object],
    *,
    project: str | None = None,
    repo_root: Path | None = None,
) -> dict[str, object] | None:
    """The decision for a tool call under the reviewed rules, or None to stay out of the way."""
    call = tool_call(event)
    if call is None:
        return None
    kind, value = call
    matches: list[Mapping[str, object]] = []
    rule_values = index.get("rules")
    for rule in rule_values if isinstance(rule_values, list) else []:
        if not isinstance(rule, dict) or rule.get("kind") != kind or not _applies_to_project(rule, project):
            continue
        pattern = str(rule.get("pattern") or "")
        hit = _command_matches(pattern, value) if kind == "command" else _path_matches(pattern, value, repo_root)
        if hit:
            matches.append(rule)
    if not matches:
        return None
    decision = "deny" if any(rule.get("action") == "deny" for rule in matches) else "ask"
    first = next((rule for rule in matches if rule.get("action") == decision), matches[0])
    names = sorted({str(rule.get("name") or "") for rule in matches})
    verb = "blocked" if decision == "deny" else "needs the person's OK"
    reason = (
        f"Link: this {kind} {verb} under a reviewed memory - \"{first.get('title')}\" ({first.get('name')}), "
        f"rule \"{first.get('action')} {kind}: {first.get('pattern')}\"."
    )
    if decision == "ask":
        reason += " If the person approves, go ahead; otherwise follow the memory."
    else:
        reason += " Do not work around it; tell the person, who can edit the memory if it no longer holds."
    return {"decision": decision, "reason": reason, "memories": names, "kind": kind}


def anchored_reminders(
    index: Mapping[str, object],
    file_path: str,
    *,
    repo_root: Path | None,
    identity: set[str],
    project: str | None = None,
    already_shown: Iterable[str] = (),
) -> list[dict[str, object]]:
    """Memories anchored to the touched file whose symbol is still in it."""
    shown = set(already_shown)
    raw = str(file_path or "").strip()
    if not raw:
        return []
    rel = ""
    if repo_root is not None:
        try:
            rel = Path(raw).resolve().relative_to(repo_root.resolve()).as_posix()
        except (OSError, ValueError):
            rel = ""
    picked: list[dict[str, object]] = []
    anchors = index.get("anchors") if isinstance(index.get("anchors"), dict) else {}
    assert isinstance(anchors, dict)
    lines: list[str] | None = None
    for entry in anchors.get(rel, []) if rel else []:
        name = str(entry.get("name") or "")
        repo = str(entry.get("repo") or "")
        if name in shown or not _applies_to_project(entry, project):
            continue
        if not any(root.startswith(repo) or repo.startswith(root) for root in identity):
            continue  # another repository's anchor
        if lines is None:
            try:
                path = Path(raw)
                lines = [] if path.stat().st_size > MAX_FILE_BYTES else path.read_text(
                    encoding="utf-8", errors="replace").splitlines()
            except OSError:
                lines = []
        symbol = str(entry.get("symbol") or "")
        if not lines or locate(lines, symbol) is None:
            continue  # the anchored symbol is gone: possibly stale, never pushed
        picked.append(dict(entry))
        shown.add(name)
    return picked[:MAX_TOUCH_REMINDERS]


def new_delivery_id() -> str:
    return secrets.token_hex(3)


def delivery_open(delivery_id: str) -> str:
    return f"(link:{delivery_id})"


def delivery_close(delivery_id: str) -> str:
    return f"(link:{delivery_id} end)"


def wrap_for_delivery(text: str, delivery_id: str, *, budget: int = HOOK_OUTPUT_BUDGET) -> tuple[str, bool]:
    """Wrap injected text in its delivery tokens, cut to the hook budget at a line.

    Returns (text, cut). A cut says so in the text itself: silently losing the
    end of a brief is the failure this exists to catch.
    """
    opening = delivery_open(delivery_id)
    closing = delivery_close(delivery_id)
    body = text.rstrip()
    cut = False
    room = budget - len(opening) - len(closing) - 200
    if len(body) > room:
        body = body[:room].rsplit("\n", 1)[0].rstrip()
        body += "\n\n(Link: this was shortened to fit the agent's hook limit; run `lnk brief` for the rest.)"
        cut = True
    # The opening token ends the first line, so what the agent reads first
    # (a waiting handoff, the brief's header) stays exactly as written.
    first, _, rest = body.partition("\n")
    return f"{first} {opening}\n{rest}\n{closing}" if rest else f"{first} {opening}\n{closing}", cut


def render_touch_text(entries: list[Mapping[str, object]], file_label: str, delivery_id: str) -> str:
    lines = [f"Link memory for {file_label} (reviewed; follow unless the person says otherwise):"]
    for entry in entries:
        claim = " ".join(str(entry.get("claim") or entry.get("title") or "").split())
        lines.append(f"- {claim[:220]} ({entry.get('name')})")
    text, _ = wrap_for_delivery("\n".join(lines), delivery_id)
    return text


def verify_deliveries(transcript_text: str, delivery_ids: Iterable[str]) -> dict[str, str]:
    """delivered / truncated / missing for each id, from the session transcript."""
    results: dict[str, str] = {}
    for delivery_id in delivery_ids:
        opened = delivery_open(delivery_id) in transcript_text
        closed = delivery_close(delivery_id) in transcript_text
        results[delivery_id] = "delivered" if opened and closed else ("truncated" if opened else "missing")
    return results


def shown_state_path(link_root: Path) -> Path:
    return link_root / ".link-cache" / "touch-shown.json"


def load_shown(link_root: Path, session_id: str) -> set[str]:
    try:
        payload = json.loads(shown_state_path(link_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    names = payload.get(session_id) if isinstance(payload, dict) else None
    return {str(name) for name in names} if isinstance(names, list) else set()


def remember_shown(link_root: Path, session_id: str, names: Iterable[str], *, keep_sessions: int = 20) -> None:
    path = shown_state_path(link_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            payload = {}
    except (OSError, ValueError):
        payload = {}
    current = [str(name) for name in payload.pop(session_id, [])] if isinstance(payload.get(session_id), list) \
        else []
    for name in names:
        if name not in current:
            current.append(name)
    payload[session_id] = current
    # Newest sessions last; drop the oldest beyond the window.
    while len(payload) > keep_sessions:
        payload.pop(next(iter(payload)))
    try:
        atomic_write_json(path, payload)
    except OSError:
        pass


def find_repo_root(start: Path) -> Path | None:
    """The enclosing git checkout, found by walking up to `.git` (no subprocess)."""
    try:
        current = start.expanduser().resolve()
    except OSError:
        return None
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def cached_repo_identity(link_root: Path, repo_root: Path) -> set[str]:
    """Root commits of a checkout, cached: they never change, and git costs a process."""
    from .staleness import repo_identity

    path = link_root / ".link-cache" / "repo-identity.json"
    key = str(repo_root.resolve())
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, ValueError):
        cache = {}
    known = cache.get(key)
    if isinstance(known, list) and known:
        return {str(item) for item in known}
    roots = repo_identity(repo_root)
    if roots:
        cache[key] = sorted(roots)
        try:
            atomic_write_json(path, cache)
        except OSError:
            pass
    return roots
