"""Reviewed rules as Zed's own tool permissions (`lnk compile --global`).

Zed runs no hook before a tool call, so Link cannot judge Zed's calls the
way it does for other agents. What Zed has instead is declarative
permission rules in `~/.config/zed/settings.json`:

    "agent": {"tool_permissions": {"tools": {
        "terminal": {"always_deny": [{"pattern": "<regex>"}], "always_confirm": [...]},
        "edit_file": {...}, "write_file": {...}, "delete_path": {...}, "move_path": {...}}}}

Patterns are regular expressions, case-insensitive, matched by Zed against
each command of a chain and against the path the agent names. This module
translates the person's reviewed rules into that shape:

- `deny` becomes `always_deny` and `ask` becomes `always_confirm`;
- a command glob matches the command after `sudo`, `env VAR=1` and similar
  prefixes and by any path to the program, as Link's own matcher does;
- a path glob matches at any depth of the path (`migrations/**`, `.env`);
- read rules are reported, not compiled: Zed has no rule for reading files.

Only personal rules are compiled: reviewed, active memories scoped to the
person and not fenced to a project, path or task, because Zed's settings
file applies in every project. Zed's own decisions are its own; Link does
not see them, count them or hold calls for `lnk approve`.

The settings file is JSON with comments and belongs to the person. Link
writes `agent.tool_permissions` only where there is none, and marks what it
writes with a comment; later runs rewrite or remove only a marked block.
Permissions the person wrote are left alone and reported, with the block
to merge by hand. Every other byte of the file is kept, and the result is
parsed back before it is written.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping

ZED_SETTINGS = ".config/zed/settings.json"
MARKER = "// Link: compiled from your reviewed rules by `lnk compile --global`; change the rules in Link"
_MARKER_PREFIX = "// Link: compiled from your reviewed rules"
# Zed checks copy_path and move_path against their destination as well as their source.
WRITE_TOOLS = ("copy_path", "create_directory", "delete_path", "edit_file", "move_path", "write_file")
_META = set(".+*?()|[]{}^$\\")
# What Link's shell reader looks past before the program: privilege and environment wrappers.
# A wrapper's options may take a value (`sudo -u deploy`, `nice -n 5`, `env -u FOO`).
_PREFIX = (r"^\s*(?:(?:sudo|doas|env|command|exec|nohup|nice|time|xargs)(?:\s+-\S+(?:\s+[^-\s]\S*)?)*\s+"
           r"|\w+=\S*\s+)*(?:\S*/)?\\?")


def _escape(text: str) -> str:
    return "".join("\\" + ch if ch in _META else ch for ch in text)


def _glob(pattern: str) -> str:
    out = []
    for token in re.split(r"(\*\*|\*|\?|\s+)", pattern):
        if token in {"**", "*"}:
            out.append(".*")
        elif token == "?":
            out.append(".")
        elif token and token.isspace():
            out.append(r"\s+")
        else:
            out.append(_escape(token))
    return "".join(out)


def command_regex(pattern: str) -> str:
    """A Link command glob as a regex over one command of a chain."""
    return _PREFIX + _glob(" ".join(pattern.split())) + r"\s*$"


def path_regex(pattern: str) -> str:
    """A Link path glob as a regex over the path an agent names, at any depth."""
    wanted = pattern.replace("\\", "/")
    wanted = wanted[2:] if wanted.startswith("./") else wanted
    if wanted.endswith("/**"):  # the folder itself too: deleting or moving it removes what is inside
        return r"(?:^|/)" + _glob(wanted[:-3]) + r"(?:/|$)"
    return r"(?:^|/)" + _glob(wanted) + r"$"


def compile_permissions(records: Iterable[Mapping[str, object]]) -> tuple[dict[str, object], list[dict[str, str]],
                                                                            list[str]]:
    """(the tool_permissions value, rules left out with the reason, names of memories compiled)."""
    from .enforce_rules import parse_enforce_rules
    from .memory import rules_in_force

    tools: dict[str, dict[str, list[dict[str, str]]]] = {}
    skipped: list[dict[str, str]] = []
    names: list[str] = []

    def add(tool: str, action: str, regex: str) -> None:
        key = "always_deny" if action == "deny" else "always_confirm"
        entries = tools.setdefault(tool, {}).setdefault(key, [])
        if {"pattern": regex} not in entries:
            entries.append({"pattern": regex})

    for record in records:
        name = str(record.get("name") or "")
        compiled = False
        for rule in parse_enforce_rules(rules_in_force(record)):
            if rule.kind == "command":
                add("terminal", rule.action, command_regex(rule.pattern))
                compiled = True
            elif rule.kind == "write":
                for tool in WRITE_TOOLS:
                    add(tool, rule.action, path_regex(rule.pattern))
                compiled = True
            else:
                skipped.append({"name": name, "rule": f"{rule.action} {rule.kind}: {rule.pattern}",
                                "reason": "Zed has no rule for reading files"})
        if compiled:
            names.append(name)
    ordered = {tool: {key: tools[tool][key] for key in sorted(tools[tool])} for tool in sorted(tools)}
    return ({"tools": ordered} if ordered else {}), skipped, names


def _block(permissions: Mapping[str, object], indent: str) -> str:
    body = json.dumps(permissions, indent=2).replace("\n", "\n" + indent)
    return f"{MARKER}\n{indent}\"tool_permissions\": {body}"


def snippet(permissions: Mapping[str, object]) -> str:
    """What to merge by hand into settings.json's "agent" object."""
    return json.dumps({"agent": {"tool_permissions": permissions}}, indent=2)


def splice(text: str | None, permissions: Mapping[str, object]) -> str | None:
    """settings.json with Link's tool_permissions block written, replaced or removed.

    Raises ValueError when the file cannot be edited safely or already holds
    permissions the person wrote.
    """
    from .mcp_connect import _find_key_value, _find_member_start, _jsonc_loads, _jsonc_mask, _object_is_empty

    if text is None or not text.strip():
        if not permissions:
            return text
        return "{\n  \"agent\": {\n    " + _block(permissions, "    ") + "\n  }\n}\n"
    try:
        parsed = _jsonc_loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"is not valid JSON or JSONC ({exc.msg} at line {exc.lineno})") from exc
    if not isinstance(parsed, dict):
        raise ValueError("does not hold a JSON object")
    masked = _jsonc_mask(text)
    first = next(i for i, ch in enumerate(masked) if not ch.isspace())
    agent = _find_key_value(masked, "agent", first)
    if agent is None:
        if not permissions:
            return text
        comma = "" if _object_is_empty(masked, first) else ","
        updated = (text[:first + 1] + "\n  \"agent\": {\n    " + _block(permissions, "    ") + "\n  }" + comma
                   + text[first + 1:])
    elif masked[agent[0]] != "{":
        raise ValueError("has an \"agent\" setting that is not an object")
    else:
        current = _find_key_value(masked, "tool_permissions", agent[0])
        if current is None:
            if not permissions:
                return text
            comma = "" if _object_is_empty(masked, agent[0]) else ","
            updated = text[:agent[0] + 1] + "\n    " + _block(permissions, "    ") + comma + text[agent[0] + 1:]
        else:
            member = _find_member_start(masked, "tool_permissions", agent[0])
            if member is None:
                raise ValueError("could not be read safely")
            before = member - 1
            while masked[before].isspace():
                before -= 1
            marker = text.rfind(_MARKER_PREFIX, before + 1, member)
            if marker < 0:
                raise ValueError("already has agent.tool_permissions of your own; Link leaves them alone. "
                                 "Merge Link's rules by hand (lnk compile --global --dry-run --json shows them)")
            # Link's block starts at the line break before its marker: comments of the person's
            # between the previous member and the marker stay where they are.
            line = text.rfind("\n", before + 1, marker)
            start = line if line >= 0 else marker
            if permissions:
                lead = "\n    " if line >= 0 else ""
                updated = text[:start] + lead + _block(permissions, "    ") + text[current[1]:]
            else:
                end = current[1]
                if masked[before] == ",":
                    updated = text[:before] + text[before + 1:start] + text[end:]
                else:
                    after = end
                    while after < len(masked) and masked[after].isspace():
                        after += 1
                    if after < len(masked) and masked[after] == ",":
                        end = after + 1
                    updated = text[:start] + text[end:]
    check = _jsonc_loads(updated)

    def without_link(settings: object) -> object:
        if not isinstance(settings, dict):
            return settings
        agent_settings = settings.get("agent")
        rest = {k: v for k, v in settings.items() if k != "agent"}
        if isinstance(agent_settings, dict):
            rest["agent"] = {k: v for k, v in agent_settings.items() if k != "tool_permissions"}
            if not rest["agent"]:
                del rest["agent"]
        return rest

    got = check.get("agent", {}).get("tool_permissions") if isinstance(check, dict) else None
    if (got or {}) != dict(permissions) or without_link(check) != without_link(parsed):
        raise ValueError("could not be edited safely")
    return updated


def owns_block(text: str | None) -> bool:
    return bool(text) and _MARKER_PREFIX in str(text)
