"""Agent session-hook configuration helpers for Link.

Hooks let supported agents run the Link memory loop automatically:
a session-start hook injects a bounded memory brief into new sessions,
and a session-end hook stores proposal-only session notes for review.

Supported agents differ in mechanism, so each config records its schema:
- Claude Code: nested hook groups inside `~/.claude/settings.json`;
  session-start stdout becomes model context; SessionEnd gets a transcript.
- Codex: the same nested hook schema in `~/.codex/hooks.json`; stdout becomes
  model context; there is no session-end event (Stop fires per turn, which
  would be too noisy for capture), so only session-start is installed.
- Cursor: a flat `~/.cursor/hooks.json` with `version: 1`; session-start must
  print a JSON envelope with `additional_context`; sessionEnd is fire-and-forget
  and only captures when Cursor provides a readable transcript path.

Before-tool hooks (enforced rules) reach every agent with a pre-tool seam;
each answers in its own shape (tool_events.render_reply):
- Claude Code: PreToolUse for shell, file reads, writes and Grep (Devin CLI
  runs these same hooks with its own tool names, which the matcher includes).
- Codex: PreToolUse for Bash and apply_patch; it can only allow or block.
- Cursor: beforeShellExecution, beforeReadFile, and preToolUse for writes
  and deletes.
- Gemini CLI: BeforeTool in `~/.gemini/settings.json` (timeouts in ms).
- Antigravity: PreToolUse in `~/.gemini/config/hooks.json`, under a named key.
- Copilot CLI and VS Code's Copilot harness: `~/.copilot/hooks/link.json`.
- Windsurf (Cascade): pre_run_command, pre_read_code, pre_write_code;
  blocking is by exit code, and there is no session-start event.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .files import atomic_write_json
from .mcp_verify import display_command

SESSION_START_TIMEOUT_SECONDS = 30
SESSION_END_TIMEOUT_SECONDS = 60
# The guard runs on every prompt: it must be fast or absent.
GUARD_TIMEOUT_SECONDS = 10
# Tool hooks run on every tool call and read a compiled index.
TOOL_HOOK_TIMEOUT_SECONDS = 10
# Claude Code's tools, then Devin CLI's: Devin runs the hooks in
# ~/.claude/settings.json by default, with its own tool names.
PRE_TOOL_MATCHER = "Bash|Write|Edit|MultiEdit|NotebookEdit|Read|Grep|exec|read|write|edit|apply_patch"
POST_TOOL_MATCHER = "Read|Edit|Write|MultiEdit"

_HOOK_SCRIPT_MARKERS = ("link.py", "link_hook.py")
# The tool hooks fire around every shell command and file access; they run
# the small link_hook.py next to the CLI when it is there (link_hook.py says why).
_FAST_HOOK_SCRIPT = "link_hook.py"
_FAST_HOOK_EVENTS = ("pre-tool", "post-tool")


@dataclass(frozen=True)
class AgentHookConfig:
    name: str
    display_name: str
    aliases: tuple[str, ...]
    default_settings: str
    # "nested": event -> [{matcher, hooks: [entry]}] (Claude Code, Codex, Gemini CLI);
    # "flat": event -> [entry] (Cursor, Copilot, Windsurf);
    # "named": like nested under a hook-name key, lifecycle events flat (Antigravity).
    schema: str = "nested"
    root_key: str = "hooks"
    version: int | None = None  # flat files that carry {"version": 1}
    timeout_key: str | None = "timeout"
    timeout_scale: int = 1  # Gemini CLI counts milliseconds
    entry_extra: tuple[tuple[str, object], ...] = ()
    start_event: str | None = "SessionStart"
    end_event: str | None = "SessionEnd"
    # Skip "resume": the resumed context already carries the earlier brief.
    start_matcher: str | None = "startup|clear|compact"
    start_emit: str = "text"  # the session-start envelope (link.py _emit_session_start)
    # Per-prompt guard (constraint reminders). Only agents with a
    # prompt-submit hook event support it.
    guard_event: str | None = None
    # Before a tool call: reviewed rules ask or block (tool_hooks), as
    # (event, matcher) pairs - some agents split shell, read and write.
    pre_tool: tuple[tuple[str, str | None], ...] = ()
    pre_tool_emit: str = "text"
    # After a file read or edit: memories anchored to that file.
    post_tool_event: str | None = None
    post_tool_matcher: str | None = None
    # Other hook files the same agent install also writes (Gemini CLI and
    # Antigravity share ~/.gemini; Link connects them as one agent).
    companions: tuple[str, ...] = ()
    restart_hint: str = "Restart the agent; new sessions will start with the Link memory brief."


HOOK_AGENT_CONFIGS: tuple[AgentHookConfig, ...] = (
    AgentHookConfig(
        name="claude-code",
        display_name="Claude Code",
        aliases=("claude-code", "claude", "claude-code-cli"),
        default_settings="~/.claude/settings.json",
        guard_event="UserPromptSubmit",
        pre_tool=(("PreToolUse", PRE_TOOL_MATCHER),),
        post_tool_event="PostToolUse",
        post_tool_matcher=POST_TOOL_MATCHER,
    ),
    AgentHookConfig(
        name="codex",
        display_name="Codex",
        aliases=("codex",),
        default_settings="~/.codex/hooks.json",
        end_event=None,
        pre_tool=(("PreToolUse", "Bash|apply_patch"),),
        pre_tool_emit="codex",
        restart_hint=(
            "Restart Codex and approve the hooks when Codex asks you to trust them (/hooks); "
            "new sessions will then start with the Link memory brief."
        ),
    ),
    AgentHookConfig(
        name="cursor",
        display_name="Cursor",
        aliases=("cursor",),
        default_settings="~/.cursor/hooks.json",
        schema="flat",
        version=1,
        start_event="sessionStart",
        end_event="sessionEnd",
        start_matcher=None,
        start_emit="cursor",
        pre_tool=(("beforeShellExecution", None), ("beforeReadFile", None), ("preToolUse", "Write|Delete")),
        pre_tool_emit="cursor",
    ),
    AgentHookConfig(
        name="antigravity",
        display_name="Antigravity",
        aliases=("antigravity", "antigravity-cli"),
        default_settings="~/.gemini/config/hooks.json",
        schema="named",
        root_key="link",
        end_event=None,
        start_matcher=None,
        start_emit="antigravity",
        pre_tool=(("PreToolUse", "run_command|view_file|write_to_file|replace_file_content|multi_replace_file_content"),),
        pre_tool_emit="antigravity",
        companions=("gemini",),
    ),
    AgentHookConfig(
        name="gemini",
        display_name="Gemini CLI",
        aliases=("gemini", "gemini-cli"),
        default_settings="~/.gemini/settings.json",
        end_event=None,
        start_matcher=None,
        start_emit="gemini",
        timeout_scale=1000,
        pre_tool=(("BeforeTool", "run_shell_command|read_file|read_many_files|write_file|replace"),),
        pre_tool_emit="gemini",
    ),
    AgentHookConfig(
        name="copilot",
        display_name="GitHub Copilot (CLI and VS Code)",
        aliases=("copilot", "github-copilot", "copilot-cli"),
        default_settings="~/.copilot/hooks/link.json",
        schema="flat",
        version=1,
        timeout_key="timeoutSec",
        entry_extra=(("type", "command"),),
        start_event="sessionStart",
        end_event=None,
        start_matcher=None,
        start_emit="copilot",
        pre_tool=(("preToolUse", "bash|view|create|edit"),),
        pre_tool_emit="copilot",
    ),
    AgentHookConfig(
        name="windsurf",
        display_name="Windsurf",
        aliases=("windsurf", "devin-desktop", "cascade"),
        default_settings="~/.codeium/windsurf/hooks.json",
        schema="flat",
        timeout_key=None,
        entry_extra=(("show_output", True),),
        start_event=None,
        end_event=None,
        start_matcher=None,
        pre_tool=(("pre_run_command", None), ("pre_read_code", None), ("pre_write_code", None)),
        pre_tool_emit="windsurf",
        restart_hint=(
            "Windsurf has no session-start hook: memory reaches it through MCP and the instructions "
            "file. The rule checks start with the next tool call."
        ),
    ),
)


def hook_supported_agents() -> tuple[str, ...]:
    """Return canonical agent names that support `lnk connect --hooks`."""
    return tuple(config.name for config in HOOK_AGENT_CONFIGS)


def _find_hook_agent(agent: str) -> AgentHookConfig | None:
    normalized = agent.strip().lower().replace("_", "-")
    for config in HOOK_AGENT_CONFIGS:
        if normalized == config.name or normalized in config.aliases:
            return config
    return None


def supports_agent_hooks(agent: str) -> bool:
    return _find_hook_agent(agent) is not None


def _hook_agent_by_name(agent: str) -> AgentHookConfig:
    config = _find_hook_agent(agent)
    if config is not None:
        return config
    choices = ", ".join(hook_supported_agents())
    raise ValueError(f"session hooks are not supported for agent: {agent}. Try one of: {choices}")


def _settings_path(default_settings: str, override: str | None) -> Path:
    path = Path(override or default_settings).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def _hook_command(
    python_cmd: str,
    runtime_script: Path,
    event: str,
    target: Path,
    emit: str = "text",
) -> str:
    script = runtime_script
    if event in _FAST_HOOK_EVENTS and (runtime_script.parent / _FAST_HOOK_SCRIPT).is_file():
        script = runtime_script.parent / _FAST_HOOK_SCRIPT
    parts = [python_cmd, str(script), "hook", event, str(target)]
    if emit != "text":
        parts.extend(["--emit", emit])
    return display_command(parts)


def _entry(config: AgentHookConfig, command: str, timeout: int, *, grouped: bool,
           matcher: str | None = None) -> dict[str, object]:
    """One hook handler in this agent's shape."""
    entry: dict[str, object] = {"type": "command", "command": command} if grouped else {"command": command}
    entry.update(dict(config.entry_extra))
    if config.timeout_key:
        entry[config.timeout_key] = timeout * config.timeout_scale
    if matcher and not grouped:
        entry["matcher"] = matcher
    return entry


def _grouped(config: AgentHookConfig, matcher: str | None) -> bool:
    """Nested files group handlers under a matcher; Antigravity does that for tool events only."""
    return config.schema == "nested" or (config.schema == "named" and matcher is not None)


def _is_link_hook_command(command: object, event: str) -> bool:
    if not isinstance(command, str):
        return False
    # Hooks run the workspace's link.py (link_hook.py for the tool hooks); an
    # installed `lnk` launcher counts too, so disconnect finds every form.
    launcher = any(marker in command for marker in _HOOK_SCRIPT_MARKERS) or re.search(r"(?:^|[\s/\"'])lnk(?:\s|\"|$)", command)
    return bool(launcher) and f" hook {event}" in command


LINK_HOOK_EVENTS = ("session-start", "session-end", "prompt-check", "pre-tool", "post-tool")


def remove_link_hooks(path: Path, agent: str, *, write: bool) -> dict[str, object]:
    """Find (and with write, remove) Link's hook entries; other hooks stay."""
    config = _find_hook_agent(agent)
    result: dict[str, object] = {"path": str(path), "supported": config is not None,
                                 "found": [], "removed": False}
    if config is None or not path.exists():
        return result
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return result
    settings = json.loads(text)
    hooks = settings.get(config.root_key) if isinstance(settings, dict) else None
    if not isinstance(hooks, dict):
        return result
    found: list[str] = []
    for event_name in list(hooks):
        groups = hooks.get(event_name)
        if not isinstance(groups, list):
            continue
        kept_groups: list[object] = []
        for group in groups:
            if isinstance(group, dict) and isinstance(group.get("hooks"), list):
                inner = [h for h in group["hooks"]
                         if not (isinstance(h, dict) and any(_is_link_hook_command(h.get("command"), e)
                                                             for e in LINK_HOOK_EVENTS))]
                if len(inner) != len(group["hooks"]):
                    found.append(event_name)
                if inner:
                    kept_groups.append({**group, "hooks": inner})
            elif isinstance(group, dict) and any(_is_link_hook_command(group.get("command"), e)
                                                 for e in LINK_HOOK_EVENTS):
                found.append(event_name)
            else:
                kept_groups.append(group)
        if kept_groups:
            hooks[event_name] = kept_groups
        else:
            del hooks[event_name]
    if config.schema == "named" and not hooks:
        del settings[config.root_key]
    result["found"] = sorted(set(found))
    if found and write:
        atomic_write_json(path, settings)
        result["removed"] = True
    return result


def _merge_grouped_event(
    hooks: dict[str, Any],
    event_name: str,
    event: str,
    entry: dict[str, object],
    matcher: str | None = None,
) -> None:
    groups = hooks.get(event_name)
    if not isinstance(groups, list):
        groups = []
    replaced = False
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_hooks = group.get("hooks")
        if not isinstance(group_hooks, list):
            continue
        for index, existing in enumerate(group_hooks):
            if isinstance(existing, dict) and _is_link_hook_command(existing.get("command"), event):
                group_hooks[index] = dict(entry)
                if matcher:
                    group["matcher"] = matcher
                replaced = True
    if not replaced:
        group: dict[str, object] = {"hooks": [dict(entry)]}
        if matcher:
            group["matcher"] = matcher
        groups.append(group)
    hooks[event_name] = groups


def _merge_flat_event(
    hooks: dict[str, Any],
    event_name: str,
    event: str,
    entry: dict[str, object],
) -> None:
    entries = hooks.get(event_name)
    if not isinstance(entries, list):
        entries = []
    replaced = False
    for index, existing in enumerate(entries):
        if isinstance(existing, dict) and _is_link_hook_command(existing.get("command"), event):
            entries[index] = dict(entry)
            replaced = True
    if not replaced:
        entries.append(dict(entry))
    hooks[event_name] = entries


def _event_plan(config: AgentHookConfig, python_cmd: str, runtime_script: Path, target: Path) -> list[dict[str, object]]:
    """Return the ordered event entries this agent should install."""
    plan: list[dict[str, object]] = []

    def add(event_name: str, event: str, matcher: str | None, emit: str, timeout: int) -> None:
        grouped = _grouped(config, matcher)
        command = _hook_command(python_cmd, runtime_script, event, target, emit=emit)
        plan.append({"event_name": event_name, "event": event, "matcher": matcher, "grouped": grouped,
                     "entry": _entry(config, command, timeout, grouped=grouped, matcher=matcher)})

    if config.start_event:
        add(config.start_event, "session-start", config.start_matcher, config.start_emit, SESSION_START_TIMEOUT_SECONDS)
    if config.end_event:
        add(config.end_event, "session-end", None, "text", SESSION_END_TIMEOUT_SECONDS)
    if config.guard_event:
        add(config.guard_event, "prompt-check", None, "text", GUARD_TIMEOUT_SECONDS)
    for event_name, matcher in config.pre_tool:
        add(event_name, "pre-tool", matcher, config.pre_tool_emit, TOOL_HOOK_TIMEOUT_SECONDS)
    if config.post_tool_event:
        add(config.post_tool_event, "post-tool", config.post_tool_matcher, "text", TOOL_HOOK_TIMEOUT_SECONDS)
    return plan


def _hooks_snippet(config: AgentHookConfig, plan: list[dict[str, object]]) -> str:
    hooks: dict[str, Any] = {}
    _merge_plan(hooks, plan)
    payload: dict[str, object] = {config.root_key: hooks}
    if config.version is not None:
        payload = {"version": config.version, **payload}
    return json.dumps(payload, indent=2)


def _merge_plan(hooks: dict[str, Any], plan: list[dict[str, object]]) -> None:
    for item in plan:
        entry = item["entry"]
        assert isinstance(entry, dict)
        if item["grouped"]:
            matcher = item["matcher"] if isinstance(item["matcher"], str) else None
            _merge_grouped_event(hooks, str(item["event_name"]), str(item["event"]), entry, matcher=matcher)
        else:
            _merge_flat_event(hooks, str(item["event_name"]), str(item["event"]), entry)


def _write_hooks(path: Path, config: AgentHookConfig, plan: list[dict[str, object]]) -> None:
    settings: dict[str, Any] = {}
    if path.exists() and path.read_text(encoding="utf-8", errors="replace").strip():
        settings = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(settings, dict):
            raise ValueError(f"{path} must contain a JSON object")
    if config.version is not None:
        settings.setdefault("version", config.version)
    hooks = settings.get(config.root_key)
    if not isinstance(hooks, dict):
        hooks = {}
        settings[config.root_key] = hooks
    _merge_plan(hooks, plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, settings)


def build_agent_hooks_payload(
    *,
    target: Path,
    agent: str,
    runtime_script: Path,
    python_cmd: str,
    settings_path: str | None = None,
    write: bool = False,
) -> dict[str, object]:
    """Build or write session-hook configuration for a supported local agent."""
    config = _hook_agent_by_name(agent)
    path = _settings_path(config.default_settings, settings_path)
    plan = _event_plan(config, python_cmd, runtime_script, target)
    write_status: dict[str, object] = {"requested": write, "ok": False, "message": "preview only"}
    if write:
        try:
            _write_hooks(path, config, plan)
            write_status = {"requested": True, "ok": True, "message": f"updated {path}"}
        except Exception as exc:
            write_status = {"requested": True, "ok": False, "message": str(exc)}

    entry_commands = {
        str(item["event_name"]): str(item["entry"]["command"])  # type: ignore[index]
        for item in plan
    }
    behavior: list[str] = []
    if config.start_event:
        behavior.append(f"{config.start_event}: injects a bounded Link memory brief into new agent sessions.")
    if config.end_event:
        behavior.append(
            f"{config.end_event}: stores proposal-only session notes locally; durable memory still requires review."
        )
    else:
        behavior.append(
            f"{config.display_name} has no session-end hook event; end sessions with `lnk session-end` "
            "or the MCP session_end action to capture memory proposals."
        )
    if config.pre_tool:
        events = ", ".join(event_name for event_name, _ in config.pre_tool)
        behavior.append(
            f"{events}: reviewed memories with enforce rules ask before (or block) the tool calls they "
            "name; nothing is checked until a rule has been reviewed."
        )
        if config.pre_tool_emit not in {"text", "gemini", "copilot", "antigravity"}:
            behavior.append(
                f"{config.display_name} can only allow or block a call, so an ask rule holds the call and "
                "the agent asks you in chat; `lnk approve <id>` lets that exact call through once."
            )
    if config.post_tool_event:
        behavior.append(
            f"{config.post_tool_event}: when a file is read or edited, the reviewed memories anchored to it "
            "are shown once per session."
        )
    if config.name != "claude-code":
        behavior.append(
            f"New: {config.display_name} hook support follows the vendor's documented schema; "
            "if a hook misbehaves, please open an issue."
        )

    companions = [
        build_agent_hooks_payload(target=target, agent=name, runtime_script=runtime_script,
                                  python_cmd=python_cmd, write=write)
        for name in config.companions
    ]
    return {
        "agent": config.name,
        "display_name": config.display_name,
        "target": str(target),
        "settings_path": str(path),
        "events": entry_commands,
        "snippet": _hooks_snippet(config, plan),
        "write": write_status,
        "behavior": behavior,
        "restart_hint": config.restart_hint,
        "companions": companions,
    }


def _content_blocks(content: object) -> list[str]:
    if isinstance(content, str):
        return [content.strip()] if content.strip() else []
    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
    return parts


# Text that Link itself injected into the session (the session-start brief,
# consolidation plans, session-end output). Messages containing these markers
# are Link's own voice: extracting them back into memory proposals would
# create the re-ingestion loop that fills other memory systems with junk
# (a mem0 production audit found 52.7% of stored entries were the system's
# own prompt text). Echoes are dropped at extraction time, by construction.
LINK_ECHO_MARKERS = (
    "Link memory (local, source-backed)",
    "Link memory brief",
    "Link consolidation plan (read-only)",
    "Link session end",
)


# Text that arrives in the transcript with role "user" but that the user
# never typed: subagent reports, slash-command expansions, local command
# output, interruption markers, compaction summaries, peer-session messages.
# Mining these as "the user's own turns" turned a subagent's report ("always
# run migrations with --force") into a high-confidence preference
# attributed to the user. Newer transcripts label the origin; older ones
# only carry the tag, so both are checked.
HARNESS_TEXT_PREFIXES = (
    "<task-notification>",
    "<local-command-caveat>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<bash-input>",
    "<bash-stdout>",
    "<bash-stderr>",
    "<system-reminder>",
    "<cross-session-message",
    "[Request interrupted",
    "This session is being continued from a previous conversation",
)
_SYSTEM_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)


def _harness_reason(entry: dict[str, object], text: str) -> str | None:
    """Why a user-role entry is not the user's own words, or None if it is."""
    if entry.get("isSidechain") is True:
        return "subagent turn"
    if entry.get("isCompactSummary") is True:
        return "compaction summary"
    if entry.get("promptSource") == "system":
        return "system prompt"
    origin = entry.get("origin")
    if isinstance(origin, dict):
        kind = str(origin.get("kind") or "")
        if kind and kind != "human":
            return f"{kind} message"
    stripped = text.lstrip()
    for prefix in HARNESS_TEXT_PREFIXES:
        if stripped.startswith(prefix):
            return f"harness text ({prefix.strip('<>[')})"
    return None


def extract_transcript_text(
    transcript_path: Path,
    *,
    max_chars: int = 6000,
    max_message_chars: int = 800,
    roles: tuple[str, ...] = ("user", "assistant"),
    stats: dict[str, int] | None = None,
    keep_head: bool = False,
) -> str:
    """Extract bounded conversation text from an agent transcript JSONL file.

    Keeps text blocks for the given `roles` (default user + assistant), skips
    tool calls/results, meta entries, and any message carrying Link's own
    injected output (see LINK_ECHO_MARKERS), and returns the most recent
    messages within `max_chars`. Pass roles=("user",) to mine only what the
    user said — memory proposals should come from the user's own words, not the
    assistant's prose, which would otherwise be mis-attributed as user
    preferences.

    With `keep_head`, when the turns exceed the budget Link keeps the opening
    turns as well as the recent ones. Standing rules ("from now on…") are
    stated early in a session; a recency-only window silently drops them.
    """
    role_set = set(roles)
    try:
        raw = transcript_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(entry, dict) or entry.get("isMeta"):
            continue
        if entry.get("type") not in role_set:
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        blocks = _content_blocks(message.get("content"))
        if not blocks:
            continue
        if entry.get("type") == "user":
            # Every text block is checked, not only the first: a real prompt
            # followed by a <task-notification> block used to be mined whole.
            # A block that is only a harness reminder is dropped on its own
            # (the person's text beside it is kept); any other harness block
            # means the message is not the user's own words.
            user_blocks: list[str] = []
            reason = _harness_reason(entry, "")  # entry-level origin markers
            if not reason:
                for block in blocks:
                    cleaned = _SYSTEM_REMINDER_RE.sub("", block).strip()
                    if not cleaned:
                        continue
                    reason = _harness_reason(entry, block)
                    if reason:
                        break
                    user_blocks.append(cleaned)
                if not reason and not user_blocks:
                    # Nothing but harness reminders in the whole message.
                    reason = _harness_reason(entry, blocks[0])
            if reason:
                if stats is not None:
                    stats["dropped_harness_text"] = stats.get("dropped_harness_text", 0) + 1
                continue
            text = "\n".join(user_blocks)
            if not text:
                continue
        else:
            text = "\n".join(blocks)
        if any(marker in text for marker in LINK_ECHO_MARKERS):
            if stats is not None:
                stats["dropped_link_output"] = stats.get("dropped_link_output", 0) + 1
            continue
        if stats is not None:
            stats["kept_messages"] = stats.get("kept_messages", 0) + 1
        if len(text) > max_message_chars:
            text = text[: max_message_chars].rstrip() + " …"
        role = "User" if entry.get("type") == "user" else "Assistant"
        lines.append(f"{role}: {text}")
    if not lines:
        return ""

    def _fits(selected: list[str]) -> bool:
        return sum(len(item) + 2 for item in selected) <= max_chars

    if _fits(lines):
        return "\n\n".join(lines)

    if not keep_head:
        kept: list[str] = []
        total = 0
        for line in reversed(lines):
            cost = len(line) + 2
            if kept and total + cost > max_chars:
                break
            kept.append(line)
            total += cost
        return "\n\n".join(reversed(kept))

    # Head + tail: opening turns carry standing rules, recent turns carry the
    # session's decisions. Spend ~a third of the budget on the head.
    head_budget = max_chars // 3
    head: list[str] = []
    head_total = 0
    consumed = 0
    for index, line in enumerate(lines):
        cost = len(line) + 2
        if head and head_total + cost > head_budget:
            break
        head.append(line)
        head_total += cost
        consumed = index + 1

    tail: list[str] = []
    tail_total = 0
    for line in reversed(lines[consumed:]):
        cost = len(line) + 2
        if tail and head_total + tail_total + cost > max_chars:
            break
        tail.append(line)
        tail_total += cost
    tail.reverse()

    if head and tail:
        return "\n\n".join(head) + "\n\n… (middle of the session omitted) …\n\n" + "\n\n".join(tail)
    return "\n\n".join(head or tail)


# Tools whose output is someone else's text: a web page, a search result, or
# another MCP server. A session that read them can carry instructions the
# user never gave into its proposals, so the capture says so for review.
_WEB_TOOL_NAMES = {"webfetch", "websearch", "web_search", "web_fetch", "fetch", "browser"}


def transcript_untrusted_inputs(transcript_path: Path) -> list[str]:
    """"web" and/or "mcp" when the session's agent read outside content."""
    found: set[str] = set()
    try:
        handle = transcript_path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return []
    with handle:
        for line in handle:
            if '"tool_use"' not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            message = entry.get("message") if isinstance(entry, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = str(block.get("name") or "")
                lowered = name.lower()
                if lowered.startswith("mcp__"):
                    server = lowered.split("__")[1] if lowered.count("__") >= 2 else ""
                    if server != "link":
                        found.add("mcp")
                elif lowered in _WEB_TOOL_NAMES:
                    found.add("web")
    return sorted(found)
