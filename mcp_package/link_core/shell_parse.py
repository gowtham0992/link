"""Read a shell command line the way the shell will run it, for enforced rules.

A rule like `ask command: git push --force*` has to see the command the shell
will actually execute, not the text as typed. Agents chain and wrap
commands (`cd api && sudo -u deploy git push '--force'`, `bash -c "..."`,
`(git push --force)`, `/usr/bin/git ...`), and a text match on the raw line
misses those while firing on quoted text (`git commit -m "fix; rm -rf x"`).

This is a deliberately small reader, not a shell: it splits on control
operators outside quotes, skips heredoc bodies, drops grouping and control
keywords, strips environment assignments and wrapper commands with their
options, reduces a binary path to its name, and looks inside `bash -c`,
`eval`, `$(...)` and backticks. It also collects the files a command reads
and writes (redirections, `tee`, `cp`/`mv` targets, `cat`/`grep`/... arguments)
so path rules apply to shell commands too. What it cannot see (variables
expanded at run time, scripts that do the forbidden thing inside) it does
not pretend to.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field

_OPERATOR_CHARS = ";&|()<>"
_CONTROL_TOKENS = {";", ";;", "&", "&&", "|", "||", "|&", "(", ")", "!"}
_KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "{", "}", "time", "!"}
# Wrapper commands and the options that take a separate value.
_WRAPPERS: dict[str, set[str]] = {
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-U", "-r", "-t", "-T", "--user", "--group"},
    "doas": {"-u", "-C"},
    "env": {"-u", "-C", "-S", "-P", "--unset", "--chdir"},
    "nice": {"-n", "--adjustment"},
    "ionice": {"-c", "-n", "-p"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
    "nohup": set(),
    "time": set(),
    "command": set(),
    "exec": set(),
    "builtin": set(),
    "xargs": {"-n", "-I", "-L", "-P", "-d", "-E", "-s", "-a"},
    "stdbuf": {"-i", "-o", "-e"},
    "caffeinate": set(),
    "chronic": set(),
    "npx": {"-p", "--package"},
    "uvx": {"--from", "--with"},
}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
_READERS = {
    "cat", "less", "more", "head", "tail", "bat", "grep", "egrep", "fgrep", "rg", "ag", "sed", "awk",
    "source", ".", "strings", "xxd", "od", "base64", "jq", "yq", "vi", "vim", "nano", "code", "open",
    "diff", "wc", "sort", "uniq", "cut", "nl", "tac",
}
_WRITERS_ALL_ARGS = {"tee", "touch", "truncate", "rm", "rmdir", "shred", "unlink", "chmod", "chown"}
_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")
_SUBSTITUTION_RE = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


@dataclass
class ShellReading:
    commands: list[list[str]] = field(default_factory=list)
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)


def _drop_heredoc_bodies(text: str) -> str:
    lines = text.split("\n")
    kept: list[str] = []
    delimiter: str | None = None
    for line in lines:
        if delimiter is not None:
            if line.strip() == delimiter:
                delimiter = None
            continue
        kept.append(line)
        match = _HEREDOC_RE.search(line)
        if match:
            delimiter = match.group(2)
    return "\n".join(kept)


def _newlines_outside_quotes_to_semicolons(text: str) -> str:
    out: list[str] = []
    quote: str | None = None
    escaped = False
    for character in text:
        if escaped:
            out.append(character)
            escaped = False
            continue
        if character == "\\" and quote != "'":
            out.append(character)
            escaped = True
            continue
        if quote:
            if character == quote:
                quote = None
            out.append(character)
            continue
        if character in "'\"":
            quote = character
        out.append(";" if character == "\n" else character)
    return "".join(out)


def _tokens(text: str) -> list[str]:
    lexer = shlex.shlex(text, posix=True, punctuation_chars=_OPERATOR_CHARS)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:  # an unbalanced quote: fall back to plain words
        return text.split()


def _unwrap(words: list[str]) -> list[str]:
    """Strip keywords, assignments and wrapper commands down to the real command."""
    changed = True
    while words and changed:
        changed = False
        while words and (words[0] in _KEYWORDS or _ASSIGNMENT_RE.match(words[0])):
            words = words[1:]
            changed = True
        if not words:
            break
        name = words[0].rsplit("/", 1)[-1]
        if name in _WRAPPERS:
            takes_value = _WRAPPERS[name]
            words = words[1:]
            while words and words[0].startswith("-"):
                option = words.pop(0)
                if option == "--":
                    break
                if option in takes_value and words:
                    words.pop(0)
            if name == "timeout" and words:
                words = words[1:]  # the duration
            if name == "env":
                while words and _ASSIGNMENT_RE.match(words[0]):
                    words = words[1:]
            changed = True
    if words and "/" in words[0]:
        words = [words[0].rsplit("/", 1)[-1], *words[1:]]
    return words


def read_shell(command: str, *, _depth: int = 0) -> ShellReading:
    reading = ShellReading()
    if _depth > 3 or not command.strip():
        return reading
    for match in _SUBSTITUTION_RE.finditer(command):
        inner = match.group(1) if match.group(1) is not None else match.group(2)
        _merge(reading, read_shell(inner, _depth=_depth + 1))
    text = _newlines_outside_quotes_to_semicolons(_drop_heredoc_bodies(command))
    current: list[str] = []
    pending_redirect: str | None = None

    def finish() -> None:
        nonlocal current
        words = _unwrap(current)
        current = []
        if not words:
            return
        name = words[0]
        if name in _SHELLS:
            for index, word in enumerate(words[1:], start=1):
                if word.startswith("-") and "c" in word.lstrip("-") and index + 1 < len(words):
                    _merge(reading, read_shell(words[index + 1], _depth=_depth + 1))
                    return
        if name == "eval" and len(words) > 1:
            _merge(reading, read_shell(" ".join(words[1:]), _depth=_depth + 1))
            return
        reading.commands.append(words)
        arguments = [word for word in words[1:] if not word.startswith("-")]
        if name in _READERS:
            reading.reads.extend(arguments)
        if name in _WRITERS_ALL_ARGS:
            reading.writes.extend(arguments)
        if name in {"cp", "mv", "install", "ln", "rsync"} and len(arguments) >= 2:
            reading.writes.append(arguments[-1])
            if name in {"cp", "rsync"}:
                reading.reads.extend(arguments[:-1])
        if name == "sed" and any(word.startswith("-i") for word in words[1:]):
            reading.writes.extend(arguments[1:])

    for token in _tokens(text):
        if pending_redirect is not None:
            (reading.reads if pending_redirect == "<" else reading.writes).append(token)
            pending_redirect = None
            continue
        if token and set(token) <= set("<>&"):
            if token.startswith(("<", ">")) or token in {">&", "&>"}:
                pending_redirect = "<" if token.startswith("<") else ">"
                continue
        if token in _CONTROL_TOKENS or (token and set(token) <= set(_OPERATOR_CHARS)):
            finish()
            continue
        current.append(token)
    finish()
    return reading


def _merge(into: ShellReading, other: ShellReading) -> None:
    into.commands.extend(other.commands)
    into.reads.extend(other.reads)
    into.writes.extend(other.writes)
