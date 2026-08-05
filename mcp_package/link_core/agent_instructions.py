"""Refresh Link-owned agent instruction files when they go stale.

The integrations installers write a "## Link — Local Agent Memory" section
into each agent's instruction surface (Kiro steering, Claude Code CLAUDE.md,
Codex AGENTS.md, Cursor rules, Gemini/Antigravity GEMINI.md). Those files
are written once and then rot: a real Kiro session was observed falling
back to terminal grep over the wiki because its steering named MCP tools
from an older, full-surface era that the configured slim server does not
expose.

`lnk setup` fixes the MCP config on every run; this module gives it the
same idempotent power over instructions. Refresh-only by design: a file is
touched only when it already carries a Link section marker (meaning Link
wrote it) and that section's content differs from the current template.
Files Link never wrote are never created here — that remains the
installers' and onboard's explicit job. Non-Link content in shared files
(a user's own CLAUDE.md notes, their AGENTS.md) is preserved byte for
byte, mirroring integrations/_shared/instructions.sh.
"""
from __future__ import annotations

import re
from pathlib import Path

# Section markers, oldest first — matching any of them identifies a
# Link-owned section, whatever era wrote it.
INSTRUCTION_MARKERS = (
    "## Link — Local Agent Memory",
    "## Link — Personal Knowledge Wiki",
)

# Home-relative instruction surfaces per agent, matching the destinations
# the integrations installers write (home/global mode).
AGENT_INSTRUCTION_FILES: dict[str, str] = {
    "kiro": ".kiro/steering/link.md",
    "claude-code": ".claude/CLAUDE.md",
    "codex": "AGENTS.md",
    "cursor": ".cursor/rules/link.mdc",
    "antigravity": ".gemini/GEMINI.md",
}

# The current shared template. A test pins this byte-for-byte to
# integrations/_shared/link-instructions.md so the two cannot drift.
INSTRUCTIONS_TEMPLATE = """\
## Link — Local Agent Memory

Local agent memory lives at `~/link/`. It has raw sources in `~/link/raw/`, compiled wiki pages in `~/link/wiki/`, and direct memories in `~/link/wiki/memories/`.

If you are unsure whether Link is ready, use MCP `status` when available, or run `lnk health`.

At the first substantive turn of a session, use MCP `recall` with an empty query when available, or run `lnk brief "session start"` if you only have CLI access. This is cheap and bounded; it prevents asking the user to repeat durable context.

If the user asks what to try after installing Link, use MCP `admin` with action `prompts` when available, or run `lnk next`.

If status reports a missing or old schema marker, use MCP `admin` with action `migrate` when available, or run `lnk migrate`, before other writes.

When the user asks to ingest or drops files into `raw/`, use MCP `ingest` when available, or run `lnk ingest-status`, then follow its guided plan before deciding what to process. If it reports `blocked_secrets` or secret warnings, do not read or ingest flagged raw files until the user redacts them.

When answering a substantive question that may need local memory or wiki context, start with MCP `recall` when available, or run `lnk query "<task or question>" --budget micro`. Read the returned `recall_capsule` first. Do this before broad file reads, grep/search, or asking the user to repeat project context.

If the recall packet has no useful project context and the user is working inside a repo, seed allowlisted source-backed project context before broad searching: run `lnk seed . ~/link` when CLI is available, then retry bounded recall. This does not create durable memory; it only writes source-backed wiki context after secret scanning.

When you only need graph orientation, especially for a large wiki, prefer MCP `admin` with action `graph_summary` or `lnk graph-summary "<topic>"` before requesting the full graph.

Before broad repairs or risky local wiki edits, create a local backup with MCP `admin` action `backup` when available, or run `lnk backup`. Do not include `raw/` unless the user explicitly asks.

After ingesting raw sources or making substantial wiki edits, use MCP `ingest` action `rebuild` and then `ingest` action `validate` when available, or run `lnk rebuild-index`, `lnk rebuild-backlinks`, and `lnk validate`, before saying the wiki is updated.

When the user explicitly asks Link to remember something, use MCP `remember` when available. For uncertain or long-session memory, use MCP `admin` action `propose_memories` or `capture_session` first, then MCP `review` to inspect/approve.

At the end of a meaningful work session, propose memory instead of silently saving it. Use MCP `admin` action `session_end` with concise session notes when available, or run `lnk session-end <notes-or-transcript>`. Show the returned proposals to the user and save durable memory only after approval.

Use MCP `review` for memory inbox, profile, audit, log, explain, archive, restore, and forget workflows. Use MCP `admin` only for less-common maintenance and compatibility actions.
If a memory brief reports a memory backlog (pending captures or reviews above threshold), offer the user a short consolidation pass: use MCP `review` with action `consolidate` when available, or run `lnk consolidate`. The plan is read-only; apply its accept/discard/review commands only after the user approves each action.

If Link session hooks are installed for this agent, the session-start memory brief is injected automatically — do not run a second startup recall; go straight to bounded task recall. Recalled memories carry a `match` field: treat `semantic` matches (paraphrase similarity with capped confidence) as hints to verify with the user, not facts to act on.

When the user says **"remember"**, **"recall"**, **"ingest"**, **"query"**, **"lint"**, or **"research"**, read `~/link/LINK.md` for instructions and follow the protocol. Use terminal commands to access `~/link/` since it's outside the workspace.

One rule for memory fields: `trigger` helps recall find a recipe (task phrase); `applies_when` fences a memory to a context; `scope`/`project`/`visibility` say whose memory it is; `supersedes` replaces an old claim with lineage; `review_after`/`expires_at` age it. When unsure, save with none — fields can be added later through review.

When a new memory contradicts an existing one, do not force both to coexist: with the user's approval, save the new memory with `supersedes: <old-name>` (CLI `--supersedes`). The old memory is archived with lineage in both directions, `explain-memory` shows the full chain, and `lnk recall --as-of YYYY-MM-DD` can reconstruct what was true on a past date.

Recalled memories may carry an `applicability` label: `matched` means the memory's declared conditions fit this context; `out_of_context` means they do not — do not apply that memory here without asking the user. When saving a memory that only applies in specific situations, set scoping conditions (for example `applies_when: "project:acme, task:deploying"`).

After completing a notable multi-step task (a release, a tricky deploy, a recovery), offer to save it as a reusable recipe: propose a `procedure` memory with a short `trigger` phrase describing when it applies, and save it only after the user approves. When starting a recurring task, recall first — approved procedures return with their steps.

Otherwise, keep working normally after the cheap first recall; do not save durable memory unless the user asks or approves it.
"""

_SECTION_PATTERN = re.compile(
    r"(^|\n)(?:" + "|".join(re.escape(m) for m in INSTRUCTION_MARKERS) + r")\n.*?(?=\n## |\Z)",
    re.DOTALL,
)


def find_link_section(text: str) -> str | None:
    """The Link-owned section of an instruction file, or None."""
    match = _SECTION_PATTERN.search(text)
    if match is None:
        return None
    return match.group(0).lstrip("\n")


def upsert_link_section(text: str) -> str:
    """Replace the Link section with the current template, preserving the rest."""
    template = INSTRUCTIONS_TEMPLATE.rstrip()
    match = _SECTION_PATTERN.search(text)
    if match:
        prefix = "\n" if match.group(1) else ""
        return _SECTION_PATTERN.sub(lambda _m: prefix + template, text, count=1).rstrip() + "\n"
    separator = "\n\n" if text.strip() else ""
    return text.rstrip() + separator + template + "\n"


def instruction_file_status(agent: str, home: Path | None = None) -> dict[str, object]:
    """Whether this agent's Link instruction section exists and is current."""
    base = (home or Path.home()).expanduser()
    rel = AGENT_INSTRUCTION_FILES.get(agent)
    if rel is None:
        return {"agent": agent, "present": False, "stale": False, "path": ""}
    path = base / rel
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"agent": agent, "present": False, "stale": False, "path": str(path)}
    section = find_link_section(text)
    if section is None:
        return {"agent": agent, "present": False, "stale": False, "path": str(path)}
    stale = section.rstrip() != INSTRUCTIONS_TEMPLATE.rstrip()
    return {"agent": agent, "present": True, "stale": stale, "path": str(path)}


def refresh_instruction_file(agent: str, home: Path | None = None) -> dict[str, object]:
    """Rewrite a stale Link section in place. No-op unless present and stale."""
    status = instruction_file_status(agent, home)
    if not status["present"] or not status["stale"]:
        return {**status, "refreshed": False}
    path = Path(str(status["path"]))
    text = path.read_text(encoding="utf-8", errors="replace")
    path.write_text(upsert_link_section(text), encoding="utf-8")
    return {**status, "stale": False, "refreshed": True}
