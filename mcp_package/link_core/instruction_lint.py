"""Check a repository's agent instruction files the way `lnk stale` checks memories.

AGENTS.md, CLAUDE.md, GEMINI.md, Copilot, Cursor, Windsurf and Kiro rules are
memory too: hand-written, loaded into every session, and just as able to go
out of date. Three kinds of finding, all reported and none acted on:

- stale: the file names a path, script, make target, dependency, variable,
  endpoint, runtime version or package manager the repository once had and
  no longer does. Same engine and same precision rule as memory staleness:
  git history has to show the thing existed.
- budget: the file is larger than the agent reads. Hard limits (Codex stops
  at 32 KiB of AGENTS.md, Windsurf at 12,000 characters per rule file,
  Claude Code skips a CLAUDE.md over 4 MiB) mean text past the limit never
  reaches the agent, silently. Guidance limits (Claude Code's 200 lines,
  Cursor's 500) are reported separately and do not fail the check.
- contradiction: two instruction files, or an instruction file and a
  reviewed memory, say opposite things. Word rules decide, as they do for
  memories; the optional local contradiction model adds pairs they miss.

Link's own compiled block and Link-owned files are skipped: their content
comes from memories, which `lnk stale` already checks.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath

from .agent_instructions import INSTRUCTION_MARKERS
from .compile import BLOCK_BEGIN, BLOCK_END, OWNED_MARKER
from .memory import (
    MEMORY_CONFLICT_TYPES,
    claim_values,
    has_negation,
    is_active_memory,
    memory_conflict_candidates,
    memory_quarantined,
    nli_contradiction_flags,
    significant_memory_tokens,
)
from .staleness import StalenessChecker, _git, describe_findings

CODEX_MAX_BYTES = 32 * 1024
CLAUDE_MAX_BYTES = 4 * 1024 * 1024
CLAUDE_GUIDANCE_LINES = 200
CURSOR_GUIDANCE_LINES = 500
WINDSURF_MAX_CHARS = 12_000
MAX_CLAIM_LINES = 600

_NAMES = {"AGENTS.md", "AGENTS.override.md", "CLAUDE.md", "CLAUDE.local.md", "GEMINI.md"}


def instruction_kind(rel: str) -> str | None:
    """Which agent family reads this repository file as instructions, if any."""
    path = PurePosixPath(rel)
    parts = path.parts
    if any(part in {"node_modules", ".git", "vendor", "third_party"} for part in parts):
        return None
    name = path.name
    if name in {"AGENTS.md", "AGENTS.override.md"}:
        return "agents-md"
    if name in {"CLAUDE.md", "CLAUDE.local.md"}:
        return "claude-md"
    if name == "GEMINI.md":
        return "gemini-md"
    head = "/".join(parts[:2])
    if head == ".claude/rules" and name.endswith(".md"):
        return "claude-rules"
    if head == ".cursor/rules" and name.endswith(".mdc"):
        return "cursor-rules"
    if rel == ".cursorrules":
        return "cursor-legacy"
    if head == ".windsurf/rules" and name.endswith(".md"):
        return "windsurf-rules"
    if rel == ".windsurfrules":
        return "windsurf-legacy"
    if head == ".kiro/steering" and name.endswith(".md"):
        return "kiro-steering"
    if rel == ".github/copilot-instructions.md":
        return "copilot"
    if head == ".github/instructions" and name.endswith(".instructions.md"):
        return "copilot-rules"
    return None


def discover_instruction_files(repo: Path) -> list[tuple[str, str]]:
    """(relative path, kind) for every instruction file git tracks or would track."""
    output = _git(repo, ["ls-files", "--cached", "--others", "--exclude-standard"])
    found: list[tuple[str, str]] = []
    for rel in sorted(set(output.splitlines())):
        kind = instruction_kind(rel)
        if kind and (repo / rel).is_file() and not (repo / rel).is_symlink():
            found.append((rel, kind))
    return found


def _read(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return ""


def user_owned_lines(text: str) -> list[tuple[int, str]]:
    """(1-based line number, line) for the parts a person wrote.

    Link's compiled block and Link's own instruction section are left out:
    the first comes from memories, the second is Link's own template.
    """
    if OWNED_MARKER in text:
        return []
    lines = text.splitlines()
    kept: list[tuple[int, str]] = []
    in_block = in_section = False
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith(BLOCK_BEGIN[:24]):
            in_block = True
        if in_block:
            if stripped.startswith(BLOCK_END):
                in_block = False
            continue
        if stripped in INSTRUCTION_MARKERS:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            in_section = False
        if in_section:
            continue
        kept.append((number, line))
    return kept


_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


def claim_lines(lines: Sequence[tuple[int, str]]) -> list[tuple[int, str]]:
    """Prose rules worth comparing, one per bullet or paragraph (wrapped lines joined).

    Not code, headings, tables or frontmatter, and not tiny. A rule wrapped
    over three lines is one rule: comparing its fragments paired "never use
    that tool name elsewhere" with a copy of itself.
    """
    claims: list[tuple[int, str]] = []
    current: list[str] = []
    start = 0

    def flush() -> None:
        text = " ".join(current).strip()
        if len(text.split()) >= 4 and len(text) <= 600:
            claims.append((start, text))
        current.clear()

    in_code = False
    in_front = bool(lines) and lines[0][1].strip() == "---"
    for index, (number, line) in enumerate(lines):
        stripped = line.strip()
        if in_front:
            if index > 0 and stripped == "---":
                in_front = False
            continue
        if stripped.startswith(("```", "~~~")):
            flush()
            in_code = not in_code
            continue
        if in_code or not stripped or stripped.startswith(("#", ">", "|", "<!--")):
            flush()
            continue
        if _BULLET.match(stripped) or not current:
            flush()
            start = number
        current.append(_BULLET.sub("", stripped))
    flush()
    return claims


# ── checks ───────────────────────────────────────────────────────────────

def _finding(kind: str, rel: str, line: int | None, reason: str, **extra: object) -> dict[str, object]:
    item: dict[str, object] = {"kind": kind, "file": rel, "line": line, "reason": reason}
    item.update(extra)
    return item


def stale_findings_for(rel: str, lines: Sequence[tuple[int, str]], checker: StalenessChecker) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    here = PurePosixPath(rel).parent
    for number, line in lines:
        if not line.strip():
            continue
        for finding in checker.findings(line):
            # A nested file's links are relative to its own directory.
            if finding.get("kind") == "path" and str(here) != "." and \
                    (checker.root / str(here) / str(finding.get("path") or "")).exists():
                continue
            results.append(_finding(
                "stale", rel, number, describe_findings([finding])[0],
                check=finding.get("kind", "path"), reference=finding.get("reference", ""),
                successor=finding.get("successor", ""), severity="stale",
            ))
    return results


def budget_findings(files: Sequence[tuple[str, str]], repo: Path) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    sizes: dict[str, bytes] = {}
    for rel, _kind in files:
        try:
            sizes[rel] = (repo / rel).read_bytes()
        except OSError:
            sizes[rel] = b""
    for rel, kind in files:
        raw = sizes[rel]
        text = raw.decode("utf-8", errors="replace")
        lines = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
        if kind in {"claude-md", "claude-rules"}:
            if kind == "claude-md" and len(raw) > CLAUDE_MAX_BYTES:
                results.append(_finding("budget", rel, None,
                                        f"{len(raw)} bytes; Claude Code skips a CLAUDE.md over 4 MiB entirely",
                                        severity="truncated", limit=CLAUDE_MAX_BYTES, size=len(raw),
                                        over=len(raw) - CLAUDE_MAX_BYTES, unit="bytes"))
            elif lines > CLAUDE_GUIDANCE_LINES:
                results.append(_finding("budget", rel, None,
                                        f"{lines} lines, {lines - CLAUDE_GUIDANCE_LINES} over Claude Code's guidance of "
                                        f"{CLAUDE_GUIDANCE_LINES}; longer files are followed less reliably",
                                        severity="guidance", limit=CLAUDE_GUIDANCE_LINES, size=lines,
                                        over=lines - CLAUDE_GUIDANCE_LINES, unit="lines"))
        elif kind == "cursor-rules" and lines > CURSOR_GUIDANCE_LINES:
            results.append(_finding("budget", rel, None,
                                    f"{lines} lines, {lines - CURSOR_GUIDANCE_LINES} over Cursor's guidance of "
                                    f"{CURSOR_GUIDANCE_LINES} per rule; split it",
                                    severity="guidance", limit=CURSOR_GUIDANCE_LINES, size=lines,
                                    over=lines - CURSOR_GUIDANCE_LINES, unit="lines"))
        elif kind == "windsurf-rules" and len(text) > WINDSURF_MAX_CHARS:
            results.append(_finding("budget", rel, None,
                                    f"{len(text)} characters, {len(text) - WINDSURF_MAX_CHARS} over Windsurf's limit of "
                                    f"{WINDSURF_MAX_CHARS:,} per rule file; the rest is not read",
                                    severity="truncated", limit=WINDSURF_MAX_CHARS, size=len(text),
                                    over=len(text) - WINDSURF_MAX_CHARS, unit="characters"))
    # Codex concatenates AGENTS.md from the repository root down to the working
    # directory and stops at 32 KiB, so the budget is per chain, not per file.
    agents = sorted(rel for rel, kind in files if kind == "agents-md" and PurePosixPath(rel).name == "AGENTS.md")
    for rel in agents:
        directory = PurePosixPath(rel).parent
        chain = [a for a in agents if directory == PurePosixPath(a).parent
                 or PurePosixPath(a).parent in directory.parents]
        total = sum(len(sizes[a]) for a in chain)
        if total > CODEX_MAX_BYTES:
            where = "this file" if len(chain) == 1 else f"the chain {' + '.join(chain)}"
            results.append(_finding("budget", rel, None,
                                    f"{total:,} bytes in {where}, {total - CODEX_MAX_BYTES:,} over Codex's "
                                    f"32 KiB limit; Codex silently drops everything past it",
                                    severity="truncated", limit=CODEX_MAX_BYTES, size=total,
                                    over=total - CODEX_MAX_BYTES, unit="bytes", chain=chain))
    return results


# Rules that say two statements cannot both hold. The memory store's
# "revision" rules (a new memory replacing an old one on the same subject)
# do not apply to two files that are both meant to be current.
OPPOSITION_REASONS = {"opposite_negation", "negates_existing_claim", "reversed_preference", "changed_value"}
_CODE_SPAN = re.compile(r"`[^`]*`|\[([^\]]*)\]\([^)]*\)|https?://\S+|\S*[/\\]\S*|\b\w+(?:[-.]\w+)+\b")
DUPLICATE_OVERLAP = 0.6


def prose(text: str) -> str:
    """The words of a rule without code spans, links, paths or hyphenated names.

    Option words live inside identifiers constantly ("feature-development",
    "`master`" in a branch name); only prose can contradict prose.
    """
    return re.sub(r"\s+", " ", _CODE_SPAN.sub(lambda m: m.group(1) or " ", text)).strip()


def _same_rule(a: str, b: str) -> bool:
    """Two copies of one rule (AGENTS.md and CLAUDE.md often carry both)."""
    if a.strip().lower() == b.strip().lower():
        return True
    if claim_values(a) != claim_values(b):
        return False  # "2 spaces" and "4 spaces" share every word but the one that matters
    ta, tb = significant_memory_tokens(a), significant_memory_tokens(b)
    union = ta | tb
    return bool(union) and len(ta & tb) / len(union) >= DUPLICATE_OVERLAP and has_negation(a) == has_negation(b)


def _opposed(candidate: Mapping[str, object]) -> bool:
    raw = candidate.get("conflict_reasons")
    reasons = {str(r) for r in raw} if isinstance(raw, (list, tuple, set)) else set()
    return bool(reasons & OPPOSITION_REASONS) or any(r.startswith("different_") for r in reasons)


def _pseudo_record(rel: str, number: int, text: str) -> dict[str, object]:
    # Instruction lines are standing rules: compared as decisions, visible
    # everywhere, active and reviewed by definition.
    return {"name": f"{rel}:{number}", "title": text, "tldr": text, "snippet": text, "body": "",
            "memory_type": "decision", "scope": "global", "project": "", "status": "active",
            "review_status": "reviewed", "visibility": "team"}


def _no_embedder(_texts: list[str]) -> list[list[float]]:
    return []  # word rules only: deterministic, and the model tier is separate


def contradiction_findings(
    claims: Mapping[str, Sequence[tuple[int, str]]],
    memories: Iterable[Mapping[str, object]],
    *,
    scorer: Callable | None = None,
) -> list[dict[str, object]]:
    records = {rel: [_pseudo_record(rel, n, prose(t)) for n, t in lines[:MAX_CLAIM_LINES] if len(prose(t).split()) >= 4]
               for rel, lines in claims.items()}
    original = {f"{rel}:{n}": t for rel, lines in claims.items() for n, t in lines}
    results: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()

    def add(a: str, b: str, text_a: str, text_b: str, how: str, **extra: object) -> None:
        key = tuple(sorted((a, b)))
        if key in seen or _same_rule(text_a, text_b):
            return
        seen.add(key)  # type: ignore[arg-type]
        text_a, text_b = original.get(a, text_a), original.get(b, text_b)
        rel, _, line = a.rpartition(":")
        results.append(_finding("contradiction", rel, int(line) if line.isdigit() else None,
                                f"may contradict {b}", other=b, text=text_a, other_text=text_b,
                                method=how, severity="contradiction", **extra))

    files = sorted(records)
    for rel in files:
        others = [r for other in files if other != rel for r in records[other]]
        if not others:
            continue
        for record in records[rel]:
            name, text = str(record["name"]), str(record["title"])
            for candidate in memory_conflict_candidates(others, text, None, "decision", "global",
                                                        limit=3, embedder=_no_embedder):
                if _opposed(candidate):
                    add(name, str(candidate["name"]), text, str(candidate.get("title") or ""), "word rules",
                        reasons=candidate.get("conflict_reasons", []))
            if scorer is not None:
                for flag in nli_contradiction_flags(others, text, None, "decision", "global", None, scorer):
                    add(name, str(flag["name"]), text, str(flag.get("title") or ""), "contradiction model",
                        probability=flag.get("probability"))

    everything = [r for rel in files for r in records[rel]]
    if everything:
        for memory in memories:
            if memory_quarantined(memory) or not is_active_memory(memory):
                continue
            if str(memory.get("review_status") or "") != "reviewed":
                continue
            memory_type = str(memory.get("memory_type") or "")
            if memory_type not in MEMORY_CONFLICT_TYPES:
                continue
            title = str(memory.get("title") or "")
            claim = prose(f"{title}. {memory.get('tldr') or memory.get('snippet') or ''}")
            label = f"memory {memory.get('name')}"
            for candidate in memory_conflict_candidates(everything, claim, None, "decision", "global",
                                                        limit=3, embedder=_no_embedder):
                if _opposed(candidate):
                    add(str(candidate["name"]), label, str(candidate.get("title") or ""),
                        str(memory.get("tldr") or title), "word rules",
                        reasons=candidate.get("conflict_reasons", []))
            if scorer is not None:
                for flag in nli_contradiction_flags(everything, claim, None, "decision", "global", None, scorer):
                    add(str(flag["name"]), label, str(flag.get("title") or ""),
                        str(memory.get("tldr") or title), "contradiction model",
                        probability=flag.get("probability"))
    return results


def lint_instructions(
    repo: Path,
    memories: Iterable[Mapping[str, object]] = (),
    *,
    cache_path: Path | None = None,
    scorer: Callable | None = None,
    checker: StalenessChecker | None = None,
) -> dict[str, object]:
    """Every finding for the instruction files in `repo`. Reads only."""
    checker = checker or StalenessChecker(repo, cache_path=cache_path)
    root = checker.root
    files = discover_instruction_files(root)
    checker.exclude_from_mentions = [rel for rel, _kind in files]
    # A bare filename in an instruction file is usually an example ("run
    # main.ts") or a file to create ("add a PLAN.md"); only a linked one
    # ([CLAUDE.md](CLAUDE.md)) or one with a directory is a reference.
    checker.bare_filenames = "linked"
    findings: list[dict[str, object]] = []
    claims: dict[str, list[tuple[int, str]]] = {}
    for rel, _kind in files:
        lines = user_owned_lines(_read(root / rel))
        findings.extend(stale_findings_for(rel, lines, checker))
        claims[rel] = claim_lines(lines)
    findings.extend(budget_findings(files, root))
    findings.extend(contradiction_findings(claims, list(memories), scorer=scorer))
    checker.save_cache()
    order = {"stale": 0, "contradiction": 1, "budget": 2}
    findings.sort(key=lambda f: (order.get(str(f["kind"]), 9), str(f["file"]),
                                 f["line"] if isinstance(f["line"], int) else 0))
    failing = [f for f in findings if f.get("severity") != "guidance"]
    return {
        "repo": str(root),
        "files": [{"path": rel, "kind": kind} for rel, kind in files],
        "checked": len(files),
        "findings": findings,
        "flagged": len(failing),
        "contradiction_model": scorer is not None,
    }
