"""Reviewed personal memory in the global instruction file of agents with no session-start hook.

`lnk compile` writes a repository's memory into that repository's files.
Some agents also read one instruction file of their own in the home
directory at the start of every session, whatever the project. For agents
that have no session-start hook to hand them the Link brief - Windsurf,
Zed, and the Kiro IDE (it reads hooks per workspace only) - that file is the only
way personal memory reaches them without the agent deciding to call a tool.
`lnk compile --global` writes it there:

- Only reviewed, active memories scoped to the person (user or global
  scope), never a project's memory and never one fenced to a project,
  path or task. Each is re-checked for secret- and injection-shaped text.
- Into one Link-owned block between markers; the rest of the file is kept
  byte for byte, with its permissions. A file Link cannot read exactly, a
  symlinked file or folder, and a file inside a git work tree (a dotfiles
  repository would publish it) are left alone and reported.
- Within the vendor's limit for the whole file (Windsurf: 6,000
  characters), counting what the person already wrote there; memories that
  do not fit are left out and reported, lowest priority first. When the
  person's own text leaves no room even for an empty block, a block already
  there shrinks to Link's two markers (never deleted) and that is reported.
- After a memory changes, only files that already carry Link's block are
  refreshed (`refresh_global_files`); nothing new appears in a home
  directory unless the person runs `lnk compile --global`.
- When no memory is left for a file, its block stays, empty: the block is
  how Link knows the file is its to refresh, so the next reviewed memory
  arrives without another `lnk compile --global`. Deleting the block by
  hand is how the person takes a file back (and so the only way a block
  leaves a file). Zed's settings.json has no room
  for an empty block, so while it holds no rule of Link's, a marker in
  Zed's AGENTS.md block records that its permissions are still Link's.
- Global files follow the personal workspace only (LINK_WORKSPACE, else
  ~/link), whether written by `lnk compile --global` or by a refresh.

Agents whose hooks deliver the brief at session start (Claude Code, Cursor,
Codex, Gemini CLI, Antigravity, Copilot) are not written: the brief already
reaches them, ranked for the task, and a second copy would only cost tokens.
Kiro keeps its steering file even with Link's Kiro hooks: Kiro CLI then
gets the brief twice, which costs tokens, but the Kiro IDE would otherwise
get none. `lnk setup` says which of the two the hooks reach.
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
    _within,
    newline_of,
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
    owned_file: bool = False  # the whole file is Link's: removed when Link stops writing it


GLOBAL_TARGETS: tuple[GlobalTarget, ...] = (
    GlobalTarget("windsurf", "Windsurf", ".codeium/windsurf/memories/global_rules.md", budget_chars=6000,
                 budget_note="Windsurf reads at most 6,000 characters of global_rules.md",
                 signs=(".codeium/windsurf",)),
    GlobalTarget("kiro", "Kiro", ".kiro/steering/link-memory.md", signs=(".kiro",), owned_file=True),
    GlobalTarget("zed", "Zed", ".config/zed/AGENTS.md", signs=(".config/zed",)),
)
GLOBAL_TARGET_KEYS = tuple(target.key for target in GLOBAL_TARGETS)
# Zed's settings.json, apart from its AGENTS.md: written only when asked for (`--targets zed` asks
# for both) or when the file already carries Link's block, never by a refresh of AGENTS.md alone.
ZED_PERMISSIONS = "zed-permissions"


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
    # Files whose limit the person's own text fills: no room even for an empty block.
    no_room: list[dict[str, str]] = field(default_factory=list)
    # Targets left out on purpose.
    skipped: list[dict[str, str]] = field(default_factory=list)


# Kiro's hook files and the event in each that hands it the brief at session start (agent_hooks.py).
_KIRO_START_HOOKS = (("kiro", ".kiro/hooks/link.json", "SessionStart"),
                     ("kiro-agent", ".kiro/agents/link.json", "agentSpawn"))


def kiro_start_hook(home: Path) -> str:
    """The home-relative Kiro hook file through which Link's brief reaches Kiro at session start, or ''."""
    from .agent_hooks import remove_link_hooks

    for agent, rel, event in _KIRO_START_HOOKS:
        found = remove_link_hooks(home / rel, agent, write=False).get("found")
        if isinstance(found, list) and event in found:
            return rel
    return ""


def detected_global_targets(home: Path) -> list[str]:
    """Installed agents that can take a global file.

    Kiro keeps its steering copy even with Link's Kiro hooks: Kiro CLI runs
    global hooks, but the Kiro IDE reads hooks per workspace only, so the
    steering file is the one channel that reaches both.
    """
    found = [target.key for target in GLOBAL_TARGETS if any((home / sign).exists() for sign in target.signs)]
    return found + [ZED_PERMISSIONS] if "zed" in found else found


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


GLOBAL_EMPTY = ("No reviewed personal memory right now. Link fills this block again when one is reviewed; "
                "delete the block to stop Link writing to this file.")
# What is left of Link's block when the person's own text fills the file's limit: the file stays Link's.
MARKERS_ONLY = f"{BLOCK_BEGIN}\n{BLOCK_END}\n"
# Inside Zed's AGENTS.md block, on a line of its own: Link's block in Zed's settings.json is empty
# for now (so gone from the file) but the permissions are still Link's to refresh.
ZED_PERMISSIONS_KEPT = "<!-- Link keeps Zed's tool permissions in settings.json; no rule at the moment -->"


def _render(records: list[Mapping[str, object]], zed_permissions_kept: bool = False) -> str:
    if records:
        block = render_block(records, intro=GLOBAL_INTRO)
    else:
        block = f"{BLOCK_BEGIN}\n## Link memory\n\n{GLOBAL_EMPTY}\n{BLOCK_END}\n"
    if zed_permissions_kept:
        block = block.replace(BLOCK_END, ZED_PERMISSIONS_KEPT + "\n" + BLOCK_END)
    return block


def _keeps_zed_permissions(text: str | None) -> bool:
    """Whether Zed's AGENTS.md says Link's (now empty) permissions in settings.json are still Link's."""
    if not text or BLOCK_BEGIN not in text or BLOCK_END not in text:
        return False
    block = text[text.find(BLOCK_BEGIN):text.find(BLOCK_END)]
    return any(line.strip() == ZED_PERMISSIONS_KEPT for line in block.splitlines())


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


def _zed_agents_text(home: Path) -> str | None:
    try:
        return _read_strict(home / ".config/zed/AGENTS.md")
    except Unreadable:
        return None


def owned_global_targets(home: Path) -> list[str]:
    """The targets whose file already carries Link's block (an empty one included)."""
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
        settings_owned = owns_block(_read_strict(home / ZED_SETTINGS))
    except Unreadable:
        settings_owned = False
    if settings_owned or _keeps_zed_permissions(_zed_agents_text(home)):
        owned.append(ZED_PERMISSIONS)
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
    # Zed's settings first: whether its permissions stay Link's while empty is recorded in AGENTS.md.
    zed_kept = _keeps_zed_permissions(_zed_agents_text(home))
    if ZED_PERMISSIONS in wanted:
        zed_kept = _plan_zed_permissions(plan, home, chosen, zed_kept)
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
                       newline: str = newline, zed: bool = target.key == "zed" and zed_kept) -> str:
            return splice_block(existing, _render(records, zed), newline)

        has_block = bool(existing) and BLOCK_BEGIN in str(existing)
        # A file already Link's keeps its block, empty if need be, so it stays Link's to refresh;
        # one named in `targets` (asked for, or owned) gets one; one merely detected waits for a memory.
        keep_block = has_block or targets is not None
        content: str | None = existing
        try:
            kept, dropped = _fit(fit_target, chosen, whole_file) if chosen else ([], [])
            if kept or (keep_block and _within(fit_target, whole_file([]))):
                content = whole_file(kept)
            elif keep_block:
                # The person's own text fills the limit. A block already there shrinks to its markers,
                # never smaller than that, so the file stays Link's and fills again once there is room.
                if has_block:
                    content = splice_block(existing, MARKERS_ONLY, newline)
                plan.no_room.append({"path": target.path, "reason": (
                    f"your own text leaves no room for Link's block ({target.budget_note or 'the file limit'}); "
                    + ("Link keeps only its markers there and fills the block again once you shorten the file"
                       if has_block else "shorten the file and run `lnk compile --global` again"))})
        except ValueError as exc:
            plan.conflicts.append({"path": target.path, "reason": str(exc)})
            continue
        for record in dropped:
            plan.dropped.append({"target": target.key, "name": str(record.get("name") or ""),
                                 "reason": target.budget_note or "over the file's limit"})
        if content == existing and not has_block:
            continue
        plan.included[target.key] = [str(record.get("name") or "") for record in kept]
        if content == existing:
            plan.unchanged.append(target.path)
        else:
            plan.files[target.path] = content
    return plan


def _plan_zed_permissions(plan: GlobalPlan, home: Path, chosen: list[Mapping[str, object]], kept: bool) -> bool:
    """Plan Zed's settings.json; return whether Zed's AGENTS.md should record the permissions as Link's.

    They stay Link's while Link has no rule to write (the settings file then
    carries nothing of Link's), and stop being recorded once its block is back
    in settings.json. A file Link may not edit keeps the record as it was.
    """
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
        return kept
    if not permissions and not owns_block(existing):
        return True  # asked for, or still Link's: the first reviewed rule is written without another compile
    try:
        content = splice(existing, permissions)
    except ValueError as exc:
        plan.zed_snippet = snippet(permissions)
        plan.conflicts.append({"path": ZED_SETTINGS, "reason": str(exc)})
        return kept
    plan.included[ZED_PERMISSIONS] = names
    if content == existing:
        plan.unchanged.append(ZED_SETTINGS)
    else:
        plan.files[ZED_SETTINGS] = content
    return not permissions


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


def refresh_global_files(records: Iterable[Mapping[str, object]], home: Path | None = None,
                         warnings: list[dict[str, str]] | None = None) -> list[str]:
    """Rewrite the global files that already carry Link's block from the current memories.

    Called after a memory joins, changes or leaves the reviewed set, from the
    CLI, the MCP server and the viewer alike, so a forgotten memory leaves
    those files at once rather than at the next `lnk setup`. Files with no
    room for Link's block are added to `warnings`, when given.
    """
    base = (home or Path.home()).expanduser()
    owned = owned_global_targets(base)
    if not owned:
        return []
    plan = plan_global_compile(records, base, targets=owned)
    if warnings is not None:
        warnings += plan.no_room
    return apply_global_plan(plan)


def personal_wiki_dir() -> Path:
    """The personal workspace's wiki: LINK_WORKSPACE, else ~/link."""
    return Path(os.environ.get("LINK_WORKSPACE") or (Path.home() / "link")).expanduser() / "wiki"


def refresh_after_memory_change(wiki_dir: Path, home: Path | None = None,
                                warnings: list[dict[str, str]] | None = None) -> list[str]:
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
    return refresh_global_files(memory_records(wiki_dir), home, warnings)
