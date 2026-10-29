"""Reviewed personal memory in the global instruction file of agents with no session-start hook.

`lnk compile` writes a repository's memory into that repository's files.
Some agents also read one instruction file of their own in the home
directory at the start of every session, whatever the project. For agents
that have no session-start hook to hand them the Link brief - Windsurf,
Kiro, Zed - that file is the only way personal memory reaches them without
the agent deciding to call a tool. `lnk compile --global` writes it there:

- Only reviewed, active memories scoped to the person (user or global
  scope), never a project's memory and never one fenced to a project,
  path or task. Each is re-checked for secret- and injection-shaped text.
- Into one Link-owned block between markers; the rest of the file is kept
  byte for byte, with its permissions. A file Link cannot read exactly, a
  symlinked file or folder, and a file inside a git work tree (a dotfiles
  repository would publish it) are left alone and reported.
- Within the vendor's limit for the whole file (Windsurf: 6,000
  characters), counting what the person already wrote there; memories that
  do not fit are left out and reported, lowest priority first.
- After a memory changes, only files that already carry Link's block are
  refreshed (`refresh_global_files`); nothing new appears in a home
  directory unless the person runs `lnk compile --global`.

Agents whose hooks deliver the brief at session start (Claude Code, Cursor,
Codex, Gemini CLI, Antigravity, Copilot) are not written: the brief already
reaches them, ranked for the task, and a second copy would only cost tokens.
"""
from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .compile import (
    BLOCK_BEGIN,
    BLOCK_END,
    Target,
    Unreadable,
    _fit,
    _read_strict,
    newline_of,
    remove_block,
    render_block,
    select_memories,
    splice_block,
)
from .files import atomic_write_bytes

PERSONAL_SCOPES = {"user", "global"}


@dataclass(frozen=True)
class GlobalTarget:
    key: str
    agent: str
    path: str  # home-relative
    budget_chars: int | None = None  # for the whole file
    budget_note: str = ""
    signs: tuple[str, ...] = ()  # home-relative paths that show the agent is installed
    owned_file: bool = False  # the whole file is Link's: removed when no memory is left for it


GLOBAL_TARGETS: tuple[GlobalTarget, ...] = (
    GlobalTarget("windsurf", "Windsurf", ".codeium/windsurf/memories/global_rules.md", budget_chars=6000,
                 budget_note="Windsurf reads at most 6,000 characters of global_rules.md",
                 signs=(".codeium/windsurf",)),
    GlobalTarget("kiro", "Kiro", ".kiro/steering/link-memory.md", signs=(".kiro",), owned_file=True),
    GlobalTarget("zed", "Zed", ".config/zed/AGENTS.md", signs=(".config/zed",)),
)
GLOBAL_TARGET_KEYS = tuple(target.key for target in GLOBAL_TARGETS)


@dataclass
class GlobalPlan:
    home: Path
    files: dict[str, str | None] = field(default_factory=dict)  # home-relative path -> new content (None: remove)
    unchanged: list[str] = field(default_factory=list)
    included: dict[str, list[str]] = field(default_factory=dict)
    dropped: list[dict[str, str]] = field(default_factory=list)
    excluded: list[dict[str, str]] = field(default_factory=list)
    conflicts: list[dict[str, str]] = field(default_factory=list)
    # Zed: reviewed rules as its own tool permissions (zed_permissions.py)
    zed_rules_skipped: list[dict[str, str]] = field(default_factory=list)
    zed_snippet: str = ""


def detected_global_targets(home: Path) -> list[str]:
    return [target.key for target in GLOBAL_TARGETS if any((home / sign).exists() for sign in target.signs)]


def _personal(records: Iterable[Mapping[str, object]]) -> tuple[list[Mapping[str, object]], list[dict[str, str]]]:
    kept: list[Mapping[str, object]] = []
    excluded: list[dict[str, str]] = []
    for record in records:
        if str(record.get("scope") or "user") in PERSONAL_SCOPES:
            kept.append(record)
        elif str(record.get("review_status") or "") == "reviewed":
            excluded.append({"name": str(record.get("name") or ""), "title": str(record.get("title") or ""),
                             "reason": "a project's memory: compiled into that repository, not your global files"})
    return kept, excluded


GLOBAL_INTRO = ("The user's reviewed memory, compiled by Link for every project. These are their standing "
                "decisions and preferences; follow them.")


def _render(records: list[Mapping[str, object]]) -> str:
    return render_block(records, intro=GLOBAL_INTRO)


def _refusal(home: Path, rel: str) -> str | None:
    """Why Link must not write ~/rel, or None when it may."""
    path = home / rel
    probe = path
    while probe != home and probe != probe.parent:
        if probe.is_symlink():
            return "is (or is inside) a symlink; Link does not write through links"
        probe = probe.parent
    probe = path.parent
    while True:
        if (probe / ".git").exists():
            return (f"is inside a git work tree ({probe}); personal memory could be committed and pushed. "
                    "Add Link's block by hand if you want it there")
        if probe == home or probe == probe.parent:
            return None
        probe = probe.parent


def owned_global_targets(home: Path) -> list[str]:
    """The targets whose file already carries Link's block."""
    owned = []
    for target in GLOBAL_TARGETS:
        try:
            text = _read_strict(home / target.path)
        except Unreadable:
            continue
        if text is not None and BLOCK_BEGIN in text:
            owned.append(target.key)
    from .zed_permissions import ZED_SETTINGS, owns_block

    try:
        if owns_block(_read_strict(home / ZED_SETTINGS)):
            owned.append("zed-permissions")  # Zed's settings, apart from its AGENTS.md
    except Unreadable:
        pass
    return owned


def plan_global_compile(records: Iterable[Mapping[str, object]], home: Path,
                        targets: list[str] | None = None) -> GlobalPlan:
    """What `lnk compile --global` would write, before anything is written."""
    home = home.expanduser()
    plan = GlobalPlan(home=home)
    personal, plan.excluded = _personal(records)
    chosen, excluded = select_memories(personal, home, "", include_private=True)
    plan.excluded += excluded
    wanted = targets if targets is not None else detected_global_targets(home)
    for target in GLOBAL_TARGETS:
        if target.key not in wanted:
            continue
        refusal = _refusal(home, target.path)
        if refusal:
            plan.conflicts.append({"path": target.path, "reason": refusal})
            continue
        try:
            existing = _read_strict(home / target.path)
        except Unreadable as exc:
            plan.conflicts.append({"path": target.path, "reason": str(exc)})
            continue
        if existing is not None and (existing.count(BLOCK_BEGIN) > 1 or existing.count(BLOCK_END) > 1
                                     or (BLOCK_BEGIN in existing) != (BLOCK_END in existing)
                                     or (BLOCK_BEGIN in existing
                                         and existing.find(BLOCK_END) < existing.find(BLOCK_BEGIN))):
            plan.conflicts.append({"path": target.path,
                                   "reason": "has Link memory markers out of order, unpaired or repeated; "
                                             "fix them by hand"})
            continue
        newline = newline_of(existing)
        fit_target = Target(target.key, target.agent, "block", target.path, budget_chars=target.budget_chars)

        def whole_file(records: list[Mapping[str, object]], existing: str | None = existing,
                       newline: str = newline) -> str:
            return splice_block(existing, _render(records), newline)

        has_block = bool(existing) and BLOCK_BEGIN in str(existing)
        content: str | None = existing
        try:
            kept, dropped = _fit(fit_target, chosen, whole_file) if chosen else ([], [])
            if kept:
                content = whole_file(kept)
            elif has_block:
                content = remove_block(str(existing), newline)
                if target.owned_file and not content.strip():
                    content = None  # Link's own file, and nothing of Link's is left in it
        except ValueError as exc:
            plan.conflicts.append({"path": target.path, "reason": str(exc)})
            continue
        for record in dropped:
            plan.dropped.append({"target": target.key, "name": str(record.get("name") or ""),
                                 "reason": target.budget_note or "over the file's limit"})
        if not kept and not has_block:
            continue
        plan.included[target.key] = [str(record.get("name") or "") for record in kept]
        if content == existing:
            plan.unchanged.append(target.path)
        else:
            plan.files[target.path] = content
    if "zed" in wanted or "zed-permissions" in wanted:
        _plan_zed_permissions(plan, home, chosen)
    return plan


def _plan_zed_permissions(plan: GlobalPlan, home: Path, chosen: list[Mapping[str, object]]) -> None:
    from .zed_permissions import ZED_SETTINGS, compile_permissions, owns_block, snippet, splice

    permissions, plan.zed_rules_skipped, names = compile_permissions(chosen)
    refusal = _refusal(home, ZED_SETTINGS)
    try:
        existing = None if refusal else _read_strict(home / ZED_SETTINGS)
    except Unreadable as exc:
        refusal = str(exc)
    if refusal:
        if permissions:
            plan.zed_snippet = snippet(permissions)
            plan.conflicts.append({"path": ZED_SETTINGS, "reason": refusal + "; merge the rules by hand"})
        return
    if not permissions and not owns_block(existing):
        return
    try:
        content = splice(existing, permissions)
    except ValueError as exc:
        plan.zed_snippet = snippet(permissions)
        plan.conflicts.append({"path": ZED_SETTINGS, "reason": str(exc)})
        return
    plan.included["zed-permissions"] = names
    if content == existing:
        plan.unchanged.append(ZED_SETTINGS)
    else:
        plan.files[ZED_SETTINGS] = content


def apply_global_plan(plan: GlobalPlan) -> list[str]:
    written: list[str] = []
    for rel, content in plan.files.items():
        path = plan.home / rel
        if _refusal(plan.home, rel):  # re-checked: the plan may be old
            continue
        if content is None:
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            written.append(str(path))
            continue
        mode = path.stat().st_mode & 0o777 if path.exists() else None
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(path, content.encode("utf-8"))
        if mode is not None:
            os.chmod(path, mode)
        written.append(str(path))
    return written


def refresh_global_files(records: Iterable[Mapping[str, object]], home: Path | None = None) -> list[str]:
    """Rewrite the global files that already carry Link's block from the current memories.

    Called after a memory joins, changes or leaves the reviewed set, from the
    CLI, the MCP server and the viewer alike, so a forgotten memory leaves
    those files at once rather than at the next `lnk setup`.
    """
    base = (home or Path.home()).expanduser()
    owned = owned_global_targets(base)
    if not owned:
        return []
    return apply_global_plan(plan_global_compile(records, base, targets=owned))


def personal_wiki_dir() -> Path:
    """The personal workspace's wiki: LINK_WORKSPACE, else ~/link."""
    return Path(os.environ.get("LINK_WORKSPACE") or (Path.home() / "link")).expanduser() / "wiki"


def refresh_after_memory_change(wiki_dir: Path, home: Path | None = None) -> list[str]:
    """`refresh_global_files` for a memory change in `wiki_dir`, when it is the personal workspace's.

    A change in any other workspace (a team's, a scratch one) never touches
    the person's global files. Cheap when no global file carries Link's block.
    """
    from .memory import memory_records

    try:
        if wiki_dir.expanduser().resolve() != personal_wiki_dir().resolve():
            return []
    except OSError:
        return []
    if not owned_global_targets((home or Path.home()).expanduser()):
        return []
    return refresh_global_files(memory_records(wiki_dir), home)
