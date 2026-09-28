"""Rules a reviewed memory can enforce on the agent's tool calls.

`[ask|deny] command|write|read: <glob>`, stored in a memory's `enforce`
frontmatter. Parsing lives here, apart from the hooks that apply the rules,
so the write path can validate a rule without importing them.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

ENFORCE_ACTIONS = ("ask", "deny")
ENFORCE_KINDS = ("command", "write", "read")
MAX_ENFORCE_RULES = 6

_RULE_RE = re.compile(
    r"^\s*(?:(?P<action>ask|deny)\s+)?(?P<kind>command|write|read)\s*:\s*(?P<pattern>\S.*?)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EnforceRule:
    action: str
    kind: str
    pattern: str

    def text(self) -> str:
        return f"{self.action} {self.kind}: {self.pattern}"


def parse_enforce_rule(value: str) -> EnforceRule:
    """`[ask|deny] command|write|read: <glob>`; the action defaults to ask."""
    match = _RULE_RE.match(str(value or ""))
    if not match:
        raise ValueError(
            "enforce rules look like 'ask command: git push --force*', "
            "'deny write: migrations/**' or 'ask read: .env*'"
        )
    pattern = match.group("pattern").strip().strip("`\"'")
    if not pattern or pattern in {"*", "**"}:
        raise ValueError("an enforce rule needs a specific pattern; '*' would match every tool call")
    return EnforceRule(
        action=(match.group("action") or "ask").lower(),
        kind=match.group("kind").lower(),
        pattern=pattern,
    )


def parse_enforce_rules(values: Iterable[object]) -> list[EnforceRule]:
    rules: list[EnforceRule] = []
    for value in values:
        try:
            rule = parse_enforce_rule(str(value))
        except ValueError:
            continue  # memory_review_issues reports it; a bad rule never blocks anything
        if rule not in rules:
            rules.append(rule)
    return rules


# A constraint that names a command in backticks: "Never run `git push
# --force` on main". Its rule can be suggested without a model.
_SUGGEST_RE = re.compile(
    r"\b(?:never|don't|do not|must not|mustn't|avoid)\b[^.`]*?`(?P<command>[^`]{3,120})`",
    re.IGNORECASE,
)
_COMMAND_START_RE = re.compile(r"^(?:[\w.-]+/)*[a-z][\w.-]*(?:\s|$)")


def suggest_enforce_rules(text: str) -> list[str]:
    """Rules a person could approve for a constraint that names a command."""
    suggestions: list[str] = []
    for match in _SUGGEST_RE.finditer(str(text or "")):
        command = " ".join(match.group("command").split())
        first = command.split(" ")[0]
        # A backticked file name ("never edit `src/app.py`") is not a command.
        looks_like_file = "/" in first or (" " not in command and re.search(r"\.\w{1,5}$", first))
        if not _COMMAND_START_RE.match(command) or looks_like_file:
            continue
        rule = f"ask command: {command}*"
        if rule not in suggestions:
            suggestions.append(rule)
    return suggestions[:3]
