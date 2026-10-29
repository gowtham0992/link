"""Every agent's tool-hook payload, read one way; every agent's answer, written its way.

Coding agents announce a tool call to their hooks in a dozen shapes:
Claude Code, Codex, Devin CLI, Kiro CLI and Copilot's PascalCase alias send
`tool_name` + `tool_input`; Gemini CLI does too, with its own tool names;
Copilot's camelCase events send `toolName` + `toolArgs` (sometimes a JSON
string); Cursor's dedicated events put `command` or `file_path` at the top
level; Windsurf (Cascade) nests a `tool_info` under `agent_action_name`;
Antigravity sends `toolCall: {name, args}` with capitalised argument names;
Codex's `apply_patch` carries a whole patch whose `*** Update File:` lines
are the only record of which files it writes.

`tool_calls` turns any of them into the same list of (kind, value) pairs -
a shell command, a file read, a file write - so one rule matcher serves
every agent. `render_reply` turns Link's decision back into what each agent
reads: Claude's `hookSpecificOutput`, Cursor's `permission`, Gemini's and
Antigravity's top-level `decision`, Copilot's top-level
`permissionDecision`, or exit code 2 with the reason on stderr for agents
that only understand that (Windsurf, Kiro).

Agents differ in what they can do with an answer. Claude Code, Cursor's
shell event, Copilot, Gemini and Antigravity can put the call in front of
the person ("ask"). The rest can only allow or block. For those, an `ask`
rule becomes a block whose reason tells the agent to ask the person in
chat, and gives the person a one-time approval (approvals.py) that lets
the same call through once.
"""
from __future__ import annotations

import json
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass

# Every agent Link knows how to answer, by its --emit name.
# "kiro-agent" answers as "kiro" does; the name tells Link's agent-profile hook from its global one.
EMITS = ("text", "cursor", "codex", "gemini", "copilot", "windsurf", "kiro", "kiro-agent", "antigravity", "devin")
# Agents (or events) that can show the person a confirmation; the rest can only allow or block.
ASK_CAPABLE = {"text", "gemini", "copilot", "antigravity"}
_CURSOR_ASK_EVENTS = {"beforeShellExecution", "beforeMCPExecution"}

SHELL_TOOLS = {
    "bash", "powershell", "pwsh", "shell", "run_shell_command", "terminal", "exec", "execute_bash", "run_command",
}
_POWERSHELL_TOOLS = {"powershell", "pwsh"}
# Devin CLI's tool names: it runs the hooks in ~/.claude/settings.json with these.
_DEVIN_TOOLS = {"exec", "read", "write", "edit", "apply_patch", "notebook_read", "notebook_edit", "grep", "glob"}
READ_TOOLS = {
    "read", "view", "notebookread", "notebook_read", "grep", "read_file", "read_many_files", "view_file", "fs_read",
}
WRITE_TOOLS = {
    "write", "edit", "multiedit", "notebookedit", "notebook_edit", "str_replace_based_edit_tool", "create_file",
    "create", "write_file", "replace", "fs_write", "write_to_file", "replace_file_content",
    "multi_replace_file_content", "apply_patch", "delete",
}
_PATH_KEYS = ("file_path", "notebook_path", "path", "AbsolutePath", "TargetFile", "absolute_path", "target_file")
_COMMAND_KEYS = ("command", "command_line", "CommandLine", "cmd")
_PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$|^\*\*\* Move to: (.+?)\s*$", re.MULTILINE)
_WINDSURF_EVENTS = {"pre_run_command": "command", "pre_read_code": "read", "pre_write_code": "write",
                    "post_read_code": "read", "post_write_code": "write", "post_run_command": "command"}


@dataclass(frozen=True)
class HookReply:
    """What a tool hook hands back to its agent."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


def _as_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _command_text(value: object) -> str:
    if isinstance(value, list):  # older Codex: ["bash", "-lc", "..."]; shell_parse reads inside -c
        return shlex.join(str(part) for part in value)
    return str(value or "")


def patch_paths(patch: str) -> list[str]:
    """The files a Codex-style patch adds, updates, deletes or moves to."""
    return [match.group(1) or match.group(2) for match in _PATCH_FILE_RE.finditer(patch)]


def _from_tool(name: str, args: Mapping[str, object]) -> list[tuple[str, str]]:
    lowered = name.strip().lower()
    if lowered in SHELL_TOOLS:
        command = next((args.get(key) for key in _COMMAND_KEYS if args.get(key)), None)
        if not command:
            return []
        text = _command_text(command)
        # PowerShell keeps backslashes and reads files through cmdlets: shell_parse reads it its own way.
        found: list[tuple[str, str]] = [("powershell" if lowered in _POWERSHELL_TOOLS else "command", text)]
        # Codex can also apply a patch through the shell (`apply_patch <<'EOF'`,
        # or the older ["apply_patch", "<patch>"] form): its headers name the files it writes.
        patch = "\n".join(str(part) for part in command) if isinstance(command, list) else text
        if "*** Begin Patch" in patch:
            found += [("write", path) for path in patch_paths(patch)]
        return found
    if lowered == "apply_patch":
        patch = str(args.get("command") or args.get("patch") or args.get("input") or "")
        return [("write", path) for path in patch_paths(patch)]
    if lowered == "read_many_files":
        includes = args.get("include")
        return [("read", str(item)) for item in includes] if isinstance(includes, list) else []
    if lowered == "fs_read":
        operations = args.get("operations")
        return [("read", str(op.get("path"))) for op in operations
                if isinstance(op, dict) and op.get("path")] if isinstance(operations, list) else []
    kind = "write" if lowered in WRITE_TOOLS else "read" if lowered in READ_TOOLS else ""
    if not kind:
        return []
    path = next((args.get(key) for key in _PATH_KEYS if args.get(key)), None)
    if path:
        return [(kind, str(path))]
    return [(kind, value) for value in _named_paths(args)]


def _named_paths(args: Mapping[str, object]) -> list[str]:
    """Paths from arguments whose name says they hold one ("filePath", "target_path", "files").

    For file tools whose argument names are not documented (Devin CLI's), so
    a rule on a path still sees the call whatever the field is called.
    """
    found: list[str] = []
    for key, value in args.items():
        name = str(key).lower()
        if ("path" not in name and "file" not in name) or any(w in name for w in ("text", "content", "data")):
            continue  # "file_text" and "file_content" carry what is written, not where
        values = value if isinstance(value, list) else [value]
        found += [item for item in values if isinstance(item, str) and item.strip() and "\n" not in item]
    return found


def _tool(event: Mapping[str, object]) -> tuple[str, dict[str, object]] | None:
    """(tool name, arguments) for the payloads that name a tool."""
    call = event.get("toolCall")
    if isinstance(call, dict):  # Antigravity
        return str(call.get("name") or ""), _as_dict(call.get("args"))
    if str(event.get("agent_action_name") or "") in _WINDSURF_EVENTS:
        return None
    if "toolName" in event:  # Copilot, camelCase events
        return str(event.get("toolName") or ""), _as_dict(event.get("toolArgs"))
    tool = str(event.get("tool_name") or "")
    if tool:  # Claude Code, Codex, Devin, Kiro, Gemini, Copilot's PascalCase alias, Cursor preToolUse
        return tool, _as_dict(event.get("tool_input"))
    return None


def tool_calls(event: Mapping[str, object]) -> list[tuple[str, str]]:
    """Every (kind, value) a hook event names: shell commands, files read, files written."""
    action = str(event.get("agent_action_name") or "")
    if action in _WINDSURF_EVENTS:  # Windsurf / Devin Desktop (Cascade)
        info = _as_dict(event.get("tool_info"))
        kind = _WINDSURF_EVENTS[action]
        value = info.get("command_line") if kind == "command" else info.get("file_path")
        return [(kind, str(value))] if value else []
    named = _tool(event)
    if named:
        return _from_tool(*named)
    if event.get("command"):  # Cursor beforeShellExecution
        return [("command", _command_text(event.get("command")))]
    if event.get("file_path"):  # Cursor beforeReadFile
        return [("read", str(event.get("file_path")))]
    return []


# Arguments that carry what a file tool writes, and (the first set) what an edit replaces.
_OLD_CONTENT_KEYS = {"old_str", "old_string", "oldtext", "old", "targetcontent"}
_NEW_CONTENT_KEYS = {"content", "contents", "file_text", "text", "new_str", "new_string", "newtext", "new",
                     "codecontent", "replacementcontent", "new_source", "insert_text", "patch", "input"}


def call_content(event: Mapping[str, object]) -> str:
    """What a file tool call writes, as one text: a patch, a file's content, what an edit replaces and with what.

    The same whatever the agent calls its arguments, so Kiro's two hooks,
    which name them differently, see one call. Empty for a shell command,
    whose text is the call itself.
    """
    named = _tool(event)
    if not named or named[0].strip().lower() in SHELL_TOOLS:
        return ""
    name, args = named
    old: list[str] = []
    new: list[str] = []
    if name.strip().lower() == "apply_patch":
        new += [str(args.get(key)) for key in ("command", "patch", "input") if args.get(key)][:1]

    def walk(value: object, role: list[str] | None) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                lowered = str(key).lower()
                walk(item, old if lowered in _OLD_CONTENT_KEYS else new if lowered in _NEW_CONTENT_KEYS else role)
        elif isinstance(value, list):
            for item in value:
                walk(item, role)
        elif role is not None and isinstance(value, str) and value:
            role.append(value)

    if not new:
        walk(args, None)
    if not old:
        return "\n".join(sorted(new))
    return "\n".join([f"replace: {text}" for text in sorted(old)] + [f"with: {text}" for text in sorted(new)])


def native_emit(emit: str, event: Mapping[str, object], environ: Mapping[str, str]) -> str:
    """The agent actually running a hook that was installed for Claude Code.

    Cursor and Devin CLI both run the hooks in ~/.claude/settings.json by
    default. Cursor marks its payloads with `cursor_version`; Devin sets
    DEVIN_PROJECT_DIR where Claude Code sets CLAUDE_PROJECT_DIR. Each gets
    an answer in its own shape rather than Claude's.
    """
    if emit != "text":
        return emit
    if "cursor_version" in event:
        return "cursor"
    if environ.get("DEVIN_PROJECT_DIR") and not environ.get("CLAUDE_PROJECT_DIR"):
        return "devin"
    if str(event.get("tool_name") or "") in _DEVIN_TOOLS:
        return "devin"  # Claude Code's own tools are capitalised; these lowercase names are Devin's
    return emit


def can_ask(emit: str, event: Mapping[str, object]) -> bool:
    """Can this agent, for this event, put the call in front of the person?"""
    if emit == "cursor":
        return str(event.get("hook_event_name") or "beforeShellExecution") in _CURSOR_ASK_EVENTS
    return emit in ASK_CAPABLE


def render_reply(decision: Mapping[str, object] | None, emit: str, event: Mapping[str, object]) -> HookReply:
    """Link's decision (None: stay out of the way) in the shape this agent reads."""
    if decision is None:
        return HookReply(json.dumps({"permission": "allow"})) if emit == "cursor" else HookReply()
    verdict = str(decision["decision"])
    reason = str(decision["reason"])
    if emit == "cursor":
        payload: dict[str, object] = {"permission": verdict, "user_message": reason}
        if str(event.get("hook_event_name") or "") != "beforeReadFile":
            payload["agent_message"] = reason
        return HookReply(json.dumps(payload))
    if emit in {"gemini", "antigravity"}:
        return HookReply(json.dumps({"decision": verdict, "reason": reason}))
    if emit == "copilot":
        return HookReply(json.dumps({"permissionDecision": verdict, "permissionDecisionReason": reason}))
    if emit == "devin":
        return HookReply(json.dumps({"decision": "block", "reason": reason}))
    if emit in {"windsurf", "kiro", "kiro-agent"}:
        return HookReply(stderr=reason, exit_code=2)
    event_name = str(event.get("hook_event_name") or "PreToolUse")
    return HookReply(json.dumps({"hookSpecificOutput": {
        "hookEventName": event_name if emit == "codex" else "PreToolUse",
        "permissionDecision": verdict,
        "permissionDecisionReason": reason,
    }}))
