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
# The backticked command must be what is forbidden, right after the negation
# and at most a verb: "Never run `git push --force`", "don't use `npm`".
# "Don't forget to run `make test`" and "never merge without running
# `pnpm lint`" name a command the user wants run, and get no rule.
_SUGGEST_RE = re.compile(
    r"\b(?:never|don't|do not|must not|mustn't|avoid)\s+(?:ever\s+)?"
    r"(?:(?:run|use|call|execute|invoke|type|do)(?:ning)?\s+)?`(?P<command>[^`]{3,120})`",
    re.IGNORECASE,
)
_COMMAND_START_RE = re.compile(r"^(?:[\w.-]+/)*[a-z][\w.-]*(?:\s|$)")


_NEGATION = r"\b(?:never|don't|do not|must not|mustn't|avoid|no)\s+(?:ever\s+)?"
# A constraint that names a file in backticks after a verb that changes or
# reads it: "Never edit `migrations/`", "Don't read `.env`".
_SUGGEST_PATH_RE = re.compile(
    _NEGATION
    + r"(?P<verb>edit|modify|change|touch|write|overwrite|delete|remove|rewrite|read|open|print|cat|log)(?:ing|e?s)?\s+"
    r"(?:(?:to|in|into|anything in|anything under|files? in|files? under|the|the file|the folder)\s+)*"
    r"`(?P<path>[^`\s]{2,120})`",
    re.IGNORECASE,
)
_READ_VERBS = {"read", "open", "print", "cat", "log"}
# Actions people name in words, not commands. Each is forbidden only when
# the sentence forbids it: "never force push", not "force push when asked".
# `git push --force` and `git push --force *`, never `--force*`: that would
# also catch the safer --force-with-lease.
_NAMED_ACTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (r"force[- ]?push(?:ing|es)?|push(?:ing)?\s+(?:with\s+)?(?:--force|-f)\b",
     ("ask command: git push --force", "ask command: git push --force *",
      "ask command: git push -f", "ask command: git push -f *")),
    (r"hard[- ]reset(?:ting)?|reset(?:ting)?\s+--hard",
     ("ask command: git reset --hard", "ask command: git reset --hard *")),
    (r"(?:skip|bypass)(?:ping)?\s+(?:the\s+)?(?:(?:pre-?commit|commit|git)\s+)?hooks?|(?:use\s+|pass\s+)?--no-verify",
     ("ask command: git commit *--no-verify*", "ask command: git push *--no-verify*")),
    (r"(?:run(?:ning)?\s+|use\s+|using\s+)?rm\s+-(?:rf|fr)\b",
     ("ask command: rm -rf *",)),
)
_NAMED_ACTION_RES = tuple(
    (re.compile(_NEGATION + r"(?:" + phrase + r")", re.IGNORECASE), rules) for phrase, rules in _NAMED_ACTIONS
)


def _looks_like_path(value: str) -> bool:
    return bool("/" in value or value.startswith(".") or re.search(r"\.\w{1,8}$", value)) and "*" not in value[:1]


def suggest_enforce_rules(text: str) -> list[str]:
    """Rules a person could approve for a constraint that names a command, a file or a known action.

    Suggestions only: nothing here is saved or enforced until the person
    adds the rule and reviews the memory.
    """
    suggestions: list[str] = []
    source = str(text or "")
    for match in _SUGGEST_PATH_RE.finditer(source):
        path = match.group("path").strip()
        if not _looks_like_path(path):
            continue
        kind = "read" if match.group("verb").lower() in _READ_VERBS else "write"
        pattern = path + "**" if path.endswith("/") else path
        rule = f"ask {kind}: {pattern}"
        if rule not in suggestions:
            suggestions.append(rule)
    # Backticks are code, not prose: "`git push --force`" is read by the
    # command pattern below, so the named actions look outside them.
    prose = re.sub(r"`[^`]*`", " ", source)
    for pattern_re, rules in _NAMED_ACTION_RES:
        if pattern_re.search(prose):
            suggestions += [rule for rule in rules if rule not in suggestions]
    for match in _SUGGEST_RE.finditer(source):
        command = " ".join(match.group("command").split())
        first = command.split(" ")[0]
        # A backticked file name ("never edit `src/app.py`") is not a command.
        looks_like_file = "/" in first or (" " not in command and re.search(r"\.\w{1,5}$", first))
        if not _COMMAND_START_RE.match(command) or looks_like_file:
            continue
        # The command itself and with more arguments, but not a longer word:
        # `git push --force*` would also catch the safer --force-with-lease.
        for rule in (f"ask command: {command}", f"ask command: {command} *"):
            if rule not in suggestions:
                suggestions.append(rule)
    return suggestions[:MAX_ENFORCE_RULES]
