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
  byte for byte, and a file Link cannot read exactly is left alone.
- Within the vendor's limit for the whole file (Windsurf: 6,000
  characters), counting what the person already wrote there; memories that
  do not fit are left out and reported, lowest priority first.

Agents whose hooks deliver the brief at session start (Claude Code, Cursor,
Codex, Gemini CLI, Antigravity, Copilot) are not written: the brief already
reaches them, ranked for the task, and a second copy would only cost tokens.
"""
from __future__ import annotations

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


GLOBAL_TARGETS: tuple[GlobalTarget, ...] = (
    GlobalTarget("windsurf", "Windsurf", ".codeium/windsurf/memories/global_rules.md", budget_chars=6000,
                 budget_note="Windsurf reads at most 6,000 characters of global_rules.md",
                 signs=(".codeium/windsurf",)),
    GlobalTarget("kiro", "Kiro", ".kiro/steering/link-memory.md", signs=(".kiro",)),
    GlobalTarget("zed", "Zed", ".config/zed/AGENTS.md", signs=(".config/zed",)),
)
GLOBAL_TARGET_KEYS = tuple(target.key for target in GLOBAL_TARGETS)


@dataclass
class GlobalPlan:
    home: Path
    files: dict[str, str] = field(default_factory=dict)        # home-relative path -> new content
    unchanged: list[str] = field(default_factory=list)
    included: dict[str, list[str]] = field(default_factory=dict)
    dropped: list[dict[str, str]] = field(default_factory=list)
    excluded: list[dict[str, str]] = field(default_factory=list)
    conflicts: list[dict[str, str]] = field(default_factory=list)


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
        path = home / target.path
        try:
            existing = _read_strict(path)
        except Unreadable as exc:
            plan.conflicts.append({"path": target.path, "reason": str(exc)})
            continue
        if existing is not None and (BLOCK_BEGIN in existing) != (BLOCK_END in existing):
            plan.conflicts.append({"path": target.path, "reason": "has a Link memory marker without its partner"})
            continue
        newline = newline_of(existing)
        others = remove_block(existing, newline) if existing else ""
        budget = target.budget_chars
        if budget is not None:
            budget = max(0, budget - len(others) - 2)
        fit_target = Target(target.key, target.agent, "block", target.path, budget_chars=budget)
        kept, dropped = _fit(fit_target, chosen, _render) if chosen else ([], [])
        for record in dropped:
            plan.dropped.append({"target": target.key, "name": str(record.get("name") or ""),
                                 "reason": target.budget_note or "over the file's limit"})
        if kept:
            content = splice_block(existing, _render(kept), newline)
        elif existing and BLOCK_BEGIN in existing:
            content = remove_block(existing, newline)
        else:
            continue
        plan.included[target.key] = [str(record.get("name") or "") for record in kept]
        if content == existing:
            plan.unchanged.append(target.path)
        else:
            plan.files[target.path] = content
    return plan


def apply_global_plan(plan: GlobalPlan) -> list[str]:
    written: list[str] = []
    for rel, content in plan.files.items():
        path = plan.home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(path, content.encode("utf-8"))
        written.append(str(path))
    return written
