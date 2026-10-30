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

import os
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
    # Codex reads $CODEX_HOME/AGENTS.md (~/.codex by default). Link used to
    # write ~/AGENTS.md, which Codex never reads (it walks from the project
    # root down) and Claude Code does, as a parent folder of every project
    # under the home directory; migrate_codex_instructions moves it.
    "codex": ".codex/AGENTS.md",
    "cursor": ".cursor/rules/link.mdc",
    "antigravity": ".gemini/GEMINI.md",
}

# The current shared template. A test pins this byte-for-byte to
# integrations/_shared/link-instructions.md so the two cannot drift.
INSTRUCTIONS_TEMPLATE = """\
## Link — Local Agent Memory

Local agent memory lives at `~/link/`. It has raw sources in `~/link/raw/`, wiki pages built from them in `~/link/wiki/`, and direct memories in `~/link/wiki/memories/`.

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

If a session brief opens with **HANDOFF WAITING**, that is the user's previous session (possibly on a different agent) handing you the task: read it first, resume that work before anything else, and after the user confirms the task is picked up, clear it with `lnk handoffs --clear <file>`. When the user says they are stopping, switching agents, or hitting a rate limit, offer to write a handoff for the next session: `lnk handoff "<where we left off>" --task "<short title>" --next "<step>"` (or describe it and let the user run it). Keep it standalone - the next session cannot ask this one what it meant.

At the end of a meaningful work session, propose memory instead of silently saving it. Use MCP `admin` action `session_end` with concise session notes when available, or run `lnk session-end <notes-or-transcript>`. Show the returned proposals to the user and save durable memory only after approval.

Use MCP `review` for memory inbox, profile, audit, log, explain, archive, restore, and forget workflows. Use MCP `admin` only for less-common maintenance and compatibility actions.
If a memory brief reports a memory backlog (pending captures or reviews above threshold), offer the user a short consolidation pass: use MCP `review` with action `consolidate` when available, or run `lnk consolidate`. The plan is read-only; apply its accept/discard/review commands only after the user approves each action.

If Link session hooks are installed for this agent, the session-start memory brief is injected automatically — do not run a second startup recall; go straight to bounded task recall. Recalled memories carry a `match` field: treat `semantic` matches (paraphrase similarity with capped confidence) as hints to verify with the user, not facts to act on.

When the user says **"remember"**, **"recall"**, **"ingest"**, **"query"**, **"lint"**, or **"research"**, read `~/link/LINK.md` for instructions and follow the protocol. Use terminal commands to access `~/link/` since it's outside the workspace.

One rule for memory fields: `trigger` helps recall find a recipe (task phrase); `applies_when` fences a memory to a context; `scope`/`project`/`visibility` say whose memory it is; `supersedes` replaces an old claim with lineage; `review_after`/`expires_at` age it. When unsure, save with none — fields can be added later through review.

When a new memory contradicts an existing one, do not force both to coexist: with the user's approval, save the new memory with `supersedes: <old-name>` (CLI `--supersedes`). The old memory is archived with lineage in both directions, `explain-memory` shows the full chain, and `lnk recall --as-of YYYY-MM-DD` can reconstruct what was true on a past date.

Recalled memories may carry an `applicability` label: `matched` means the memory's declared conditions fit this context; `out_of_context` means they do not — do not apply that memory here without asking the user. When saving a memory that only applies in specific situations, set scoping conditions (for example `applies_when: "project:acme, task:deploying"`).

After completing a notable multi-step task (a release, a tricky deploy, a recovery), offer to save it as a reusable recipe: propose a `procedure` memory with a short `trigger` phrase describing when it applies, and save it only after the user approves. When starting a recurring task, recall first — approved procedures return with their steps.

Some reviewed memories carry **enforce rules**. With Link's tool hooks installed, a tool call that matches one waits for the user's OK or is blocked, and the decision names the memory: follow it, never work around it. On an agent that cannot ask the user itself, the call is held instead: tell the user what you wanted to run and why, give them the `lnk approve <id>` line from the message, and run the exact same call again only after they say they approved it. Never run `lnk approve` yourself. Never review, clear, archive, forget or update a memory that carries rules - only the user does that, in `lnk`, the viewer or LinkBar. Add a rule only when the user asks (`lnk enforce <memory> --rule "ask command: ..."`, or MCP `remember(enforce=...)`); it acts after the user reviews the memory. A session brief may end with **Waiting for the user's OK**: show those items at a natural pause and run a listed command only after the user says yes to that item in chat. Recalled memories may carry `verified` or `stale_paths` (checked against the repository): treat a stale one as possibly wrong and say so. `lnk receipt` shows what memory reached each session and whether it arrived whole; `lnk compile` writes reviewed memory into the files agents read; `lnk stale --instructions` checks those files.

Otherwise, keep working normally after the cheap first recall; do not save durable memory unless the user asks or approves it.
"""

# The start of `lnk compile`'s block (compile.BLOCK_BEGIN; a test pins the two).
BLOCK_BEGIN_PREFIX = "<!-- BEGIN LINK MEMORY"

# A Link section runs from its marker to the earliest of: the end of its
# last line (every template since 2026-05 ends with one starting
# "Otherwise, "), the line before `lnk compile`'s block, the next heading
# (ATX of any level, or setext), the end of the file. Whatever the person
# writes after it - a plain line, their own `### Shell`, the compiled
# block - is theirs, not Link's. A UTF-8 BOM before a heading on the first
# line is the file's, kept as it was. integrations/_shared/instructions.sh
# and instructions.ps1 use this same pattern.
_SECTION_PATTERN = re.compile(
    r"(^\ufeff?|\n)(?:" + "|".join(re.escape(m) for m in INSTRUCTION_MARKERS) + r")\r?\n.*?"
    r"(?:(?<=\n)Otherwise, [^\r\n]*"
    r"|(?=(?:\r?\n)+(?:" + re.escape(BLOCK_BEGIN_PREFIX) + r"|#{1,6}[ \t]|[^\r\n]+\r?\n(?:=+|-+)[ \t]*(?:\r?\n|\Z)))"
    r"|(?=(?:\r?\n)*\Z))",
    re.DOTALL,
)


def find_link_section(text: str) -> str | None:
    """The Link-owned section of an instruction file, or None."""
    match = _SECTION_PATTERN.search(text)
    if match is None:
        return None
    return match.group(0).lstrip("\ufeff\r\n")


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _template(newline: str) -> str:
    return INSTRUCTIONS_TEMPLATE.rstrip().replace("\n", newline)


def upsert_link_section(text: str) -> str:
    """Replace the Link section with the current template, preserving the rest."""
    newline = _newline(text)
    template = _template(newline)
    match = _SECTION_PATTERN.search(text)
    if match:
        prefix = match.group(1)  # the line break before the section, exactly as it was
        tail = text[match.end():]
        return text[:match.start()] + prefix + template + (tail if tail.strip() else newline)
    separator = newline * 2 if text.strip() else ""
    return text.rstrip("\r\n") + separator + template + newline


def remove_link_section(text: str) -> str:
    """The file without its Link section; everything else byte for byte."""
    match = _SECTION_PATTERN.search(text)
    if match is None:
        return text
    newline = _newline(text)
    bom = match.group(1).rstrip("\n")
    head, tail = text[:match.start()], text[match.end():]
    if not head.strip():
        rest = tail.lstrip("\r\n")
        return bom + rest if rest.strip() else rest
    if not tail.strip():
        return head.rstrip("\r\n") + newline
    return head.rstrip("\r\n") + newline * 2 + tail.lstrip("\r\n")


def _read_exact(path: Path) -> str | None:
    """The file's text exactly, None when absent; ValueError when it is not UTF-8 (never guessed at)."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    return data.decode("utf-8")


def _write_exact(path: Path, text: str) -> None:
    """Through a symlink to its target, keeping the mode; a read-only file is refused (PermissionError)."""
    from .files import write_config_bytes

    path.parent.mkdir(parents=True, exist_ok=True)
    write_config_bytes(path, text.encode("utf-8"))


def codex_home(home: Path) -> Path:
    """Where Codex keeps its global files: $CODEX_HOME, else ~/.codex."""
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else home / ".codex"


def copilot_home(home: Path) -> Path:
    """Where Copilot CLI keeps its user hooks folder: $COPILOT_HOME, else ~/.copilot."""
    configured = os.environ.get("COPILOT_HOME")
    return Path(configured).expanduser() if configured else home / ".copilot"


# Agents whose home folder moves with an environment variable.
_MOVABLE_HOMES = (("~/.codex", codex_home), ("~/.copilot", copilot_home))


def agent_home_path(spec: str, home: Path | None = None) -> Path:
    """An agent's home-relative file ("~/.cursor/mcp.json") as a path.

    Codex keeps its config.toml and hooks.json in $CODEX_HOME as well as its
    AGENTS.md, and Copilot CLI its hooks in $COPILOT_HOME/hooks; connect,
    disconnect, doctor and setup all resolve those folders here so none of
    them edits ~/.codex or ~/.copilot while the agent reads another folder.
    """
    for prefix, resolve in _MOVABLE_HOMES:
        if spec == prefix or spec.startswith(prefix + "/"):
            return resolve((home or Path.home()).expanduser()) / spec[len(prefix) + 1:]
    if home is not None and spec.startswith("~/"):
        return home.expanduser() / spec[2:]
    return Path(spec).expanduser()


def _instruction_path(agent: str, base: Path) -> Path | None:
    if agent == "codex":
        return codex_home(base) / "AGENTS.md"
    rel = AGENT_INSTRUCTION_FILES.get(agent)
    return base / rel if rel is not None else None


def migrate_codex_instructions(home: Path | None = None, *, write: bool = True) -> dict[str, object]:
    """Give Codex Link's section where it reads it ($CODEX_HOME/AGENTS.md, default ~/.codex).

    Link used to write it to ~/AGENTS.md, which Codex never reads. Claude
    Code does read that file (as a parent folder of projects under the home
    directory), and may have no other copy of Link's instructions: the
    section is moved out of ~/AGENTS.md only when ~/.claude/CLAUDE.md
    carries it too, and copied otherwise. Only Link's own section is ever
    touched; files that are not UTF-8 are left alone, and line endings and
    permissions are kept.
    """
    base = (home or Path.home()).expanduser()
    old = base / "AGENTS.md"
    new = codex_home(base) / "AGENTS.md"
    result: dict[str, object] = {"from": str(old), "to": str(new), "moved": False}
    override = new.with_name("AGENTS.override.md")
    try:
        old_text = _read_exact(old)
        new_text = _read_exact(new)
        claude_text = _read_exact(base / AGENT_INSTRUCTION_FILES["claude-code"])
        if override.exists() and override.read_text(encoding="utf-8", errors="replace").strip():
            result["override"] = str(override)  # Codex reads that one instead of AGENTS.md
    except (OSError, ValueError) as exc:
        result["error"] = f"left alone: {exc}"
        return result
    if old_text is None or find_link_section(old_text) is None:
        return result
    result["needed"] = True
    if new_text is not None and find_link_section(new_text) is not None:
        result["needed"] = False  # Codex already has it; leave ~/AGENTS.md to Claude Code
        return result
    keep_old = claude_text is None or find_link_section(claude_text) is None
    result["kept_for_claude_code"] = keep_old
    if not write:
        return result
    try:
        _write_exact(new, upsert_link_section(new_text or ""))
        if not keep_old:
            rest = remove_link_section(old_text)
            if rest.strip() or old.is_symlink():  # a symlink stays the person's link to their file
                _write_exact(old, rest)
            else:
                old.unlink()
    except OSError as exc:
        result["error"] = f"left alone: {exc}"
        return result
    result["moved"] = True
    return result


def instruction_file_status(agent: str, home: Path | None = None) -> dict[str, object]:
    """Whether this agent's Link instruction section exists and is current."""
    base = (home or Path.home()).expanduser()
    path = _instruction_path(agent, base)
    if path is None:
        return {"agent": agent, "present": False, "stale": False, "path": ""}
    try:
        text = _read_exact(path)
    except (OSError, ValueError):
        text = None
    section = find_link_section(text) if text is not None else None
    if section is None:
        return {"agent": agent, "present": False, "stale": False, "path": str(path)}
    stale = section.replace("\r\n", "\n").rstrip() != INSTRUCTIONS_TEMPLATE.rstrip()
    return {"agent": agent, "present": True, "stale": stale, "path": str(path)}


def refresh_instruction_file(agent: str, home: Path | None = None) -> dict[str, object]:
    """Rewrite a stale Link section in place. No-op unless present and stale."""
    status = instruction_file_status(agent, home)
    if not status["present"] or not status["stale"]:
        return {**status, "refreshed": False}
    path = Path(str(status["path"]))
    text = _read_exact(path) or ""
    try:
        _write_exact(path, upsert_link_section(text))
    except OSError as exc:
        return {**status, "refreshed": False, "error": str(exc)}
    return {**status, "stale": False, "refreshed": True}
