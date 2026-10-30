"""Read a shell command line the way the shell will run it, for enforced rules.

A rule like `ask command: git push --force*` has to see the command the shell
will actually execute, not the text as typed. Agents chain and wrap
commands (`cd api && sudo -u deploy git push '--force'`, `bash -c "..."`,
`(git push --force)`, `/usr/bin/git ...`), and a text match on the raw line
misses those while firing on quoted text (`git commit -m "fix; rm -rf x"`).

This is a deliberately small reader, not a shell: it splits on control
operators outside quotes, skips comments and heredoc bodies, drops grouping
and control keywords, strips environment assignments and wrapper commands
with their options, reduces a binary path to its name, and looks inside
`bash -c`, `eval`, `$(...)`, backticks, `<(...)` and the commands git runs
for an alias or a setting. It expands `~`, braces, `$'...'` and the
variables it can know (assigned earlier in the line, or in the hook's own
environment). It also collects the files a command reads and writes
(redirections, `tee`, `cp`/`mv` targets, `find -delete`, `cat`/`grep`/...
arguments) so path rules apply to shell commands too. What it cannot see
(a variable it cannot know, code handed to an interpreter, a script that
does the forbidden thing inside) it does not pretend to: the reading says
so (`opaque`, `code`, a `$` left in a path), and the caller decides.
"""
from __future__ import annotations

import os
import posixpath
import re
import shlex
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import permutations

_OPERATOR_CHARS = ";&|()<>"
_CONTROL_TOKENS = {";", ";;", "&", "&&", "|", "||", "|&", "(", ")", "!"}
_KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "{", "}", "time", "!", "coproc"}
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
    "watch": {"-n", "--interval"},
}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
_READERS = {
    "cat", "less", "more", "head", "tail", "bat", "grep", "egrep", "fgrep", "rg", "ag", "sed", "awk",
    "source", ".", "strings", "xxd", "od", "base64", "jq", "yq", "vi", "vim", "nano", "code", "open",
    "diff", "wc", "sort", "uniq", "cut", "nl", "tac",
}
_WRITERS_ALL_ARGS = {"tee", "touch", "truncate", "mkdir"}
# Removing a file or folder removes everything beneath it.
_REMOVERS = {"rm", "rmdir", "shred", "unlink"}
# Interpreters whose code arrives on the command line (`python3 -c`, `node -e`) or on stdin.
_INTERPRETER_RE = re.compile(
    r"^(?:python[\d.]*|py|pypy\d*|node|nodejs|bun|deno|perl|ruby|php|osascript|rscript|lua)(?:\.exe)?$",
    re.IGNORECASE)
_CODE_OPTION_RE = re.compile(r"-[A-Za-z]*[ceEr]|--eval|--print|eval")
# What a `$(...)`, backtick or `<(...)` leaves in the line: a value only known when it runs.
SUBSTITUTED = "$_LINK_SUBST_"
_HEREDOC_RE = re.compile(r"<<(-?)[ \t]*(\\?)(['\"]?)([^\s'\";&|<>()]+)\3")
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_VARIABLE_RE = re.compile(r"\$(?:\{([A-Za-z_]\w*)(?::?[-=]([^}]*))?\}|([A-Za-z_]\w*))")
_BRACE_RE = re.compile(r"(?<!\$)\{([^{}\s]*,[^{}\s]*)\}")
_ANSI_C_RE = re.compile(r"\\(x[0-9A-Fa-f]{1,2}|[0-7]{1,3}|.)", re.DOTALL)
_ANSI_C_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f",
                   "v": "\v"}
_GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix",
                      "--config-env", "--attr-source"}
# git settings whose value git runs as a command (and an alias, which runs git or, after "!", the shell).
_GIT_EXEC_KEY_RE = re.compile(
    r"^(?:core\.(?:pager|editor|sshcommand|fsmonitor|askpass)|sequence\.editor|diff\.external"
    r"|credential\.(?:.+\.)?helper|pager\..+|.+\.textconv|gpg\.(?:.+\.)?program|filter\..+\.(?:clean|smudge|process)"
    r"|merge\..+\.driver|diff\..+\.command|(?:diff|merge)tool\..+\.cmd)$")
# Environment variables whose value a program runs as a command.
_EXEC_VARIABLES = {"GIT_PAGER", "PAGER", "GIT_EDITOR", "EDITOR", "VISUAL", "GIT_SEQUENCE_EDITOR", "GIT_SSH_COMMAND",
                   "GIT_SSH", "GIT_EXTERNAL_DIFF", "GIT_ASKPASS", "SSH_ASKPASS"}
# `git.exe`, `npm.cmd`: Windows finds a program by its name with or without the extension.
_WINDOWS_PROGRAM_RE = re.compile(r"(?i)\.(?:exe|cmd|bat|ps1)$")
# A reading must finish well inside an agent's hook timeout (often 10 s). Past this much text,
# or this many seconds, the line is reported unreadable instead of read to the end.
MAX_COMMAND_CHARS = 100_000
READ_SECONDS = 2.5
# Nested shells, `$(...)` and `-exec` runs are followed this deep; deeper is unreadable, not empty.
MAX_DEPTH = 4


class _Unreadable(Exception):
    """The line is too long, too slow or too tangled to read: the reading says opaque."""


def _check(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise _Unreadable


@dataclass
class ShellReading:
    commands: list[list[str]] = field(default_factory=list)
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    # Writes that act on everything beneath their target (a delete, a move away, a recursive chmod, a
    # folder copied over another): for these alone, a folder above Link's files counts. Each is in writes too.
    trees: list[str] = field(default_factory=list)
    # Code handed to an interpreter (`python3 -c`, `node -e`, a heredoc on stdin): text, not read.
    code: list[str] = field(default_factory=list)
    # The reader could not see what will run (an encoded PowerShell command, `iex $code`, `eval "$c"`).
    opaque: bool = False


def _ansi_c(body: str) -> str:
    def decode(match: re.Match[str]) -> str:
        code = match.group(1)
        if code[0] == "x" and len(code) > 1:
            return chr(int(code[1:], 16))
        if code[0] in "01234567":
            return chr(int(code, 8))
        return _ANSI_C_ESCAPES.get(code, code)

    return _ANSI_C_RE.sub(decode, body)


def _prepare(text: str) -> tuple[str, list[tuple[str, str, bool]]]:
    """Comments dropped, `$'...'` decoded, heredoc bodies taken out: (text, [(body, its line, quoted)]).

    One pass with the shell's own quoting, across lines: a `<<` in quotes,
    in a `<<<` here-string or in arithmetic (`$((1<<2))`) starts no heredoc,
    so the lines after it are still read as commands.
    """
    out: list[str] = []
    bodies: list[tuple[str, str, bool]] = []
    pending: list[tuple[str, bool]] = []
    quote = ""
    arithmetic = 0
    line_from = 0
    index, size = 0, len(text)
    while index < size:
        ch = text[index]
        if quote == "'":
            quote = "" if ch == "'" else quote
            out.append(ch)
            index += 1
            continue
        if ch == "\\":
            out.append(text[index:index + 2])
            index += 2
            continue
        if quote:
            quote = "" if ch == '"' else quote
            out.append(ch)
            index += 1
            continue
        if text.startswith("$'", index):
            end = index + 2
            while end < size and text[end] != "'":
                end += 2 if text[end] == "\\" else 1
            out.append(shlex.quote(_ansi_c(text[index + 2:end])))
            index = end + 1
            continue
        if ch in "'\"":
            quote = ch
        elif text.startswith("((", index):
            arithmetic += 1
            out.append("((")
            index += 2
            continue
        elif arithmetic and text.startswith("))", index):
            arithmetic -= 1
            out.append("))")
            index += 2
            continue
        elif ch == "#" and (index == 0 or text[index - 1] in " \t\n;&|()"):
            while index < size and text[index] != "\n":
                index += 1
            continue
        elif text.startswith("<<<", index):
            out.append("<<<")
            index += 3
            continue
        elif ch == "<" and not arithmetic and (match := _HEREDOC_RE.match(text, index)):
            pending.append((match.group(4), bool(match.group(2) or match.group(3))))
            out.append(match.group(0))
            index = match.end()
            continue
        elif ch == "\n":
            line = "".join(out[line_from:])
            out.append(ch)
            line_from = len(out)
            index += 1
            for delimiter, quoted in pending:
                body: list[str] = []
                while index < size:
                    end = text.find("\n", index)
                    end = size if end < 0 else end
                    row, index = text[index:end], end + 1
                    if row.strip() == delimiter:
                        break
                    body.append(row)
                bodies.append(("\n".join(body), line, quoted))
            pending = []
            continue
        out.append(ch)
        index += 1
    return "".join(out), bodies


def _substitutions(text: str) -> tuple[str, list[str]]:
    """The text with each `$(...)`, backtick and `<(...)` replaced by SUBSTITUTED, and what each runs."""
    out: list[str] = []
    found: list[str] = []
    quote = ""
    index, size = 0, len(text)
    while index < size:
        ch = text[index]
        if quote == "'":
            quote = "" if ch == "'" else quote
            out.append(ch)
            index += 1
            continue
        if ch == "\\":
            out.append(text[index:index + 2])
            index += 2
            continue
        if text.startswith("$(", index) or (not quote and text[index:index + 2] in {"<(", ">("}):
            depth, end, inner = 1, index + 2, ""
            while end < size and depth:
                c = text[end]
                if c == "\\":
                    end += 1
                elif inner:
                    inner = "" if c == inner else inner
                elif c in "'\"":
                    inner = c
                elif c in "()":
                    depth += 1 if c == "(" else -1
                end += 1
            found.append(text[index + 2:end - 1 if depth == 0 else end])
            out.append(SUBSTITUTED)
            index = end
            continue
        if ch == "`":
            end = index + 1
            while end < size and text[end] != "`":
                end += 2 if text[end] == "\\" else 1
            found.append(text[index + 1:end])
            out.append(SUBSTITUTED)
            index = end + 1
            continue
        if quote:
            quote = "" if ch == '"' else quote
        elif ch in "'\"":
            quote = ch
        out.append(ch)
        index += 1
    return "".join(out), found


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


def _braces(word: str, limit: int = 64) -> list[str]:
    """`wiki/{memories,x}` as the shell expands it: wiki/memories wiki/x."""
    match = _BRACE_RE.search(word)
    if not match:
        return [word]
    if len(_BRACE_RE.findall(word)) > 16:  # thousands of `{a,b}`: no path, and too deep to expand
        raise _Unreadable
    found: list[str] = []
    for part in match.group(1).split(","):
        found += _braces(word[:match.start()] + part + word[match.end():], limit)
        if len(found) >= limit:
            break
    return found[:limit]


def _option_values(words: list[str], short: str = "", long: tuple[str, ...] = ()) -> list[str]:
    """What an option is given: `-o x`, `-sSo x`, `-ox`, `--output x`, `--output=x`."""
    found: list[str] = []
    for index, word in enumerate(words):
        following = words[index + 1:index + 2]
        if word.startswith("--"):
            key, equals, value = word.partition("=")
            if key in long:
                found += [value] if equals else following
        elif short and word.startswith("-") and short in word[1:]:
            rest = word[word.index(short, 1) + 1:]
            found += [rest] if rest else following
    return found


def program_name(word: str) -> str:
    """The program a word runs: `/usr/bin/git` and `git.exe` are `git`."""
    name = word.rsplit("/", 1)[-1]
    plain = _WINDOWS_PROGRAM_RE.sub("", name)
    return plain.lower() if plain != name else name


def _unwrap(words: list[str], seen: set[str] | None = None) -> list[str]:
    """Strip keywords, assignments and wrapper commands down to the real command."""
    changed = True
    while words and changed:
        changed = False
        while words and (words[0] in _KEYWORDS or words[0] == "function" or _ASSIGNMENT_RE.match(words[0])):
            # `function gp { git push -f; }`: the name goes too, and the body is read as commands.
            words = words[2:] if words[0] == "function" else words[1:]
            changed = True
        if not words:
            break
        name = program_name(words[0])
        if name in _WRAPPERS:
            if seen is not None:
                seen.add(name)
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
    if words and program_name(words[0]) != words[0]:
        words = [program_name(words[0]), *words[1:]]
    return words


def git_parts(words: list[str]) -> tuple[str, list[tuple[str, str]], list[str]]:
    """git's own options before the subcommand: (the -C directory, the -c settings, the subcommand onward)."""
    where = ""
    settings: list[tuple[str, str]] = []
    index = 1
    while index < len(words) and words[index].startswith("-"):
        key, _, value = words[index].partition("=")
        if words[index] in _GIT_VALUE_OPTIONS and index + 1 < len(words):
            key, value = words[index], words[index + 1]
            index += 1
        if key in {"-C", "--work-tree"}:
            where = posixpath.join(where, value) if where and key == "-C" else value
        elif key == "-c":
            name, _, setting = value.partition("=")
            settings.append((name, setting))
        index += 1
    return where, settings, words[index:]


_GIT_PUSH_VALUE_OPTIONS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
_NPM_VALUE_OPTIONS = {"-w", "--workspace", "--prefix", "--registry", "-C", "--userconfig", "--cache", "--otp"}
# rm's other spellings of its options: `-R` and `--recursive` are `-r`, `--force` is `-f`.
_RM_ALIASES = {"-R": "-r", "--recursive": "-r", "--force": "-f", "--dir": "-d", "--verbose": "-v"}
# Options moved to the front one at a time, at most this many (each is one more form to match).
_MAX_MOVED_OPTIONS = 8


def _option_groups(args: list[str], takes_value: set[str],
                   aliases: Mapping[str, str] | None = None) -> tuple[list[list[str]], list[str]]:
    """([each option with its value], [operands]): `-uf` is `-u -f`, and `--` ends the options."""
    groups: list[list[str]] = []
    operands: list[str] = []
    index = 0
    while index < len(args):
        word = args[index]
        if word == "--":
            operands += args[index + 1:]
            break
        if len(word) > 1 and word.startswith("-"):
            word = (aliases or {}).get(word, word)
            if not word.startswith("--") and len(word) > 2 and word[1:].isalpha() \
                    and not any(f"-{letter}" in takes_value for letter in word[1:]):
                groups += [[(aliases or {}).get(f"-{letter}", f"-{letter}")] for letter in word[1:]]
            elif word in takes_value and index + 1 < len(args):
                groups.append([word, args[index + 1]])
                index += 1
            else:
                groups.append([word])
        else:
            operands.append(word)
        index += 1
    return groups, operands


def _reordered(head: list[str], groups: list[list[str]], operands: list[str], *, merge: bool = False) -> list[list[str]]:
    """The orders a rule may be written in: options first or last, each option first, short flags merged.

    `git push --force*` holds for `git push -u --force origin x`, `git push origin
    main*` for `git push -u origin main`, and (merged) `rm -rf*` for `rm -r -f x`
    and `rm -fr x`.
    """
    flat = [word for group in groups for word in group]
    forms = [head + flat + operands, head + operands + flat]
    for index, group in enumerate(groups[:_MAX_MOVED_OPTIONS]):
        forms.append(head + group + [word for other in groups[:index] + groups[index + 1:] for word in other] + operands)
    if merge:
        letters = list(dict.fromkeys(group[0][1] for group in groups if len(group) == 1 and len(group[0]) == 2
                                     and group[0][1].isalpha()))
        rest = [word for group in groups if not (len(group) == 1 and len(group[0]) == 2) for word in group]
        if 2 <= len(letters) <= 4:
            forms += [head + ["-" + "".join(order)] + rest + operands for order in permutations(letters)]
    return forms


def command_forms(words: list[str]) -> list[list[str]]:
    """The command as read, and the plain forms a rule is written against.

    `git -C . push -f`, `git push origin main --force` and `git push origin
    +main` (a leading + forces that ref) are `git push -f`, `git push
    --force origin main` and `git push --force origin main`; `npm pub` is
    `npm publish` (npm takes any unambiguous abbreviation). Options may come
    in any order and short ones bundled (`git push -u --force`, `git push -uf`,
    `rm -fr`, `rm -r -f`, `rm -Rf`), and `git.exe` is `git`.
    """
    forms = [words]
    if words and program_name(words[0]) != words[0]:
        words = [program_name(words[0]), *words[1:]]
        forms.append(words)
    if words and words[0] == "git":
        _, _, rest = git_parts(words)
        plain = ["git", *rest]
        if rest and rest[0] == "push":
            groups, positional = _option_groups(rest[1:], _GIT_PUSH_VALUE_OPTIONS)
            if any(len(ref) > 1 and ref.startswith("+") for ref in positional):
                groups.insert(0, ["--force"])
                positional = [ref.removeprefix("+") for ref in positional]
            reordered = _reordered(["git", "push"], groups, positional)
            plain = reordered[0]
            forms += [form for form in reordered[1:] if form != words]
        if plain != words:
            forms.append(plain)
    elif words and words[0] == "rm":
        groups, operands = _option_groups(words[1:], set(), _RM_ALIASES)
        forms += [form for form in _reordered(["rm"], groups, operands, merge=True) if form != words]
    elif words and words[0] == "npm":
        index = 1
        while index < len(words) and words[index].startswith("-"):
            index += 2 if words[index] in _NPM_VALUE_OPTIONS else 1
        if index < len(words):
            command = words[index]
            command = "publish" if len(command) >= 2 and "publish".startswith(command) else command
            plain = ["npm", command, *words[index + 1:]]
            if plain != words:
                forms.append(plain)
    return forms


def read_shell(command: str, *, environ: Mapping[str, str] | None = None, deadline: float | None = None,
               _depth: int = 0, _variables: Mapping[str, str] | None = None) -> ShellReading:
    """What a shell command line runs, reads and writes; `opaque` where it cannot be read in time."""
    reading = ShellReading()
    if not command.strip():
        return reading
    if _depth > MAX_DEPTH:  # `bash -c` inside `bash -c` ... five deep: what runs at the bottom is not read
        reading.opaque = True
        return reading
    if deadline is None:
        deadline = time.monotonic() + READ_SECONDS
    try:
        _read_shell(reading, command, environ, deadline, _depth, _variables)
    except _Unreadable:
        reading.opaque = True
    return reading


def _read_shell(reading: ShellReading, command: str, environ: Mapping[str, str] | None, deadline: float,
                _depth: int, _variables: Mapping[str, str] | None) -> None:
    env = os.environ if environ is None else environ
    variables: dict[str, str] = dict(_variables or {})
    loops: dict[str, list[str]] = {}  # `for d in a b; do rm -rf $d; done`

    def nested(text: str, into: ShellReading = reading) -> None:
        _merge(into, read_shell(text, environ=env, deadline=deadline, _depth=_depth + 1, _variables=variables))

    text, bodies = _prepare(command)
    if len(text) > MAX_COMMAND_CHARS:  # heredoc bodies aside, too long to read in time
        reading.opaque = True
        return
    for body, line, quoted in bodies:
        programs = {word.rsplit("/", 1)[-1] for word in re.findall(r"[\w./+-]+", line)}
        if programs & _SHELLS:  # `bash <<EOF`, `cat <<EOF | sh`: the body runs
            nested(body)
        elif any(_INTERPRETER_RE.match(name) for name in programs):
            reading.code.append(body)
        elif not quoted:  # an unquoted heredoc still runs its $(...)
            for inner in _substitutions(body)[1]:
                nested(inner)
    text, inners = _substitutions(text)
    for inner in inners:
        nested(inner)
    text = _newlines_outside_quotes_to_semicolons(text)
    current: list[str] = []
    pending_redirect: str | None = None
    # `cd x && echo y > z` writes x/z: paths after a cd in the same line are
    # read relative to where it went, so a rule on x/** still sees them.
    here = ""
    upstream: list[str] = []  # what the previous command of a pipeline names, for xargs

    def expand(word: str) -> str:
        def value(match: re.Match[str]) -> str:
            name = match.group(1) or match.group(3)
            known = variables.get(name, env.get(name))
            return known if known is not None else match.group(2) if match.group(2) is not None else match.group(0)

        if (word == "~" or word.startswith("~/")) and env.get("HOME"):
            word = env["HOME"] + word[1:]
        return _VARIABLE_RE.sub(value, word) if "$" in word else word

    def at(target: str) -> str:
        if not here or target.startswith(("/", "~", "$")) or re.match(r"^[A-Za-z]:[\\/]", target):
            return target
        return posixpath.join(here, target)

    def paths(word: str) -> list[str]:
        loop = re.fullmatch(r"\$\{?([A-Za-z_]\w*)\}?(.*)", word, re.DOTALL)
        items = [item + loop.group(2) for item in loops[loop.group(1)]] \
            if loop and loop.group(1) in loops else [word]
        return [at(expand(each)) for item in items for each in _braces(item)]

    def write(into: ShellReading, words: list[str], *, tree: bool = False) -> None:
        found = [path for word in words for path in paths(word)]
        into.writes.extend(found)
        if tree:
            into.trees.extend(found)

    def git_setting(key: str, value: str) -> None:
        key = key.strip().lower()
        if key.startswith("alias."):  # `!cmd` runs in the shell; anything else is a git command
            nested(value[1:] if value.startswith("!") else f"git {value}")
        elif _GIT_EXEC_KEY_RE.match(key):
            nested(value.removeprefix("!"))

    def assigned(pairs: list[tuple[str, str]]) -> None:
        values = dict(pairs)
        for name, value in pairs:
            if name in _EXEC_VARIABLES and value:
                nested(value)
            elif name == "GIT_CONFIG_PARAMETERS":
                for key, setting in re.findall(r"'([^'=]+)=([^']*)'", value):
                    git_setting(key, setting)
            elif name.startswith("GIT_CONFIG_KEY_"):
                git_setting(value, values.get("GIT_CONFIG_VALUE_" + name.removeprefix("GIT_CONFIG_KEY_"), ""))

    def analyse(words: list[str], into: ShellReading, finds: int = 0) -> None:
        nonlocal here
        _check(deadline)
        name = words[0]
        if name in {"cd", "pushd"}:
            destination = next((word for word in words[1:] if not word.startswith("-")), "")
            destination = "$OLDPWD" if "-" in words[1:] else destination or "~"
            here = paths(destination)[0]
            into.commands.append(words)
            return
        if name in _SHELLS:
            for index, word in enumerate(words[1:], start=1):
                if word.startswith("-") and "c" in word.lstrip("-") and index + 1 < len(words):
                    script = words[index + 1]
                    if script.startswith(("$", "`")):
                        into.opaque = True  # `bash -c "$c"`: what runs is not on the line
                    else:
                        nested(script, into)
                    return
        if name == "eval" and len(words) > 1:
            script = " ".join(words[1:])
            if script.startswith(("$", "`")):
                into.opaque = True
            else:
                nested(script, into)
            return
        into.commands.append(words)
        if _INTERPRETER_RE.match(name):
            into.code.extend(words[index + 1] for index, word in enumerate(words[1:-1], start=1)
                             if _CODE_OPTION_RE.fullmatch(word))
        arguments = [word for word in words[1:] if not word.startswith("-")]
        if name in _READERS:
            into.reads.extend(path for word in arguments for path in paths(word))
        if name in _WRITERS_ALL_ARGS:
            write(into, arguments)
        if name in _REMOVERS:
            write(into, arguments, tree=True)
        if name in {"chmod", "chown", "chgrp"}:
            recursive = any(word == "--recursive" or (word.startswith("-") and not word.startswith("--")
                                                      and "R" in word) for word in words[1:])
            reference = any(word.startswith("--reference") for word in words)  # else the first is the mode or owner
            write(into, arguments if reference else arguments[1:], tree=recursive)
        if name in {"cp", "mv", "install", "ln", "rsync"}:
            folders = _option_values(words[1:], "t", ("--target-directory",))
            positional = [word for word in arguments if word not in folders]
            if folders or len(positional) >= 2:
                destination, sources = (folders[0], positional) if folders else (positional[-1], positional[:-1])
                # A folder's contents copied over another (`rsync -a x/ ~/link/`, `cp -r x/ ~/link`, which
                # macOS's cp reads as the contents) can replace anything beneath the destination.
                contents = name in {"cp", "rsync"} and any(source.endswith(("/", "/.")) for source in sources)
                write(into, [destination], tree=contents or (name == "rsync" and any(w.startswith("--delete")
                                                                                      for w in words)))
                # A folder copied or moved onto another merges into it: `cp -r x/link ~/` writes ~/link.
                write(into, [posixpath.join(destination, posixpath.basename(source))
                             for source in sources if not source.endswith("/")], tree=True)
                if name in {"cp", "rsync"}:
                    into.reads.extend(path for word in sources for path in paths(word))
                if name == "mv":  # what is moved away is gone from where it was
                    write(into, sources, tree=True)
        if (name == "sed" and any(_sed_in_place(word) for word in words[1:])) \
                or (name == "perl" and any(_perl_in_place(word) for word in words[1:])):
            # The first operand is the script, unless `-e`/`-f` gave it: then every one is a file.
            given = any(word in {"-e", "-f", "--expression", "--file"} or word.startswith(("--expression=", "--file="))
                        for word in words[1:])
            write(into, arguments if given and name == "sed" else arguments[1:])
        if name in {"awk", "gawk"} and ("inplace" in {value.removesuffix(".awk") for value in
                                                      _option_values(words[1:], "i", ("--include",))}):
            write(into, [word for word in arguments if word not in {"inplace", "inplace.awk"}][1:])  # gawk -i inplace
        if name == "patch":
            operands, index = [], 1
            while index < len(words):
                if words[index] in _PATCH_VALUE_OPTIONS:
                    index += 1
                elif not words[index].startswith("-"):
                    operands.append(words[index])
                index += 1
            outputs = _option_values(words[1:], "o", ("--output",))
            # `patch file < fix.diff` changes the file; `patch -p1 < fix.diff`, whatever files the diff names.
            write(into, outputs or operands[:1] or _option_values(words[1:], "d", ("--directory",)) or ["."],
                  tree=not outputs and not operands)
        if name == "sort":
            write(into, _option_values(words[1:], "o", ("--output",)))
        if name == "dd":
            write(into, [word[3:] for word in words[1:] if word.startswith("of=")])
        if name == "find":
            index = 1
            while index < len(words) and words[index] in {"-H", "-L", "-P"}:
                index += 1
            starts = []
            while index < len(words) and not words[index].startswith(("-", "(", "!")):
                starts.append(words[index])
                index += 1
            starts = starts or ["."]
            if "-delete" in words:
                write(into, starts, tree=True)
            while index < len(words):
                if words[index] in {"-exec", "-execdir", "-ok", "-okdir"}:
                    end = index + 1
                    while end < len(words) and words[end] not in {";", "+"}:
                        end += 1
                    run = words[index + 1:end]
                    index = end  # each run is read once: a find inside it reads its own
                    if finds >= 2:  # `find -exec find -exec find -exec ...`
                        into.opaque = True
                        continue
                    for start in starts:  # what find runs, on what it finds
                        found = _unwrap([part.replace("{}", start) for part in run] + ([] if "{}" in run else [start]))
                        if found:
                            analyse(found, into, finds + 1)
                index += 1
        if name in {"tar", "bsdtar", "gtar"}:
            options = words[1:]
            if options and not options[0].startswith("-"):
                options = ["-" + options[0], *options[1:]]  # `tar xzf x.tar`, the old bundled form
            letters = "".join(word[1:] for word in options if word.startswith("-") and not word.startswith("--"))
            longs = {word.partition("=")[0] for word in options if word.startswith("--")}
            if "x" in letters or longs & {"--extract", "--get"}:  # what an archive holds is not on the line
                write(into, _option_values(options, "C", ("--directory",)) or ["."], tree=True)
            if any(letter in letters for letter in "cruA") or longs & {"--create", "--append", "--update"}:
                write(into, _option_values(options, "f", ("--file",)))
        if name == "unzip" and not any(letter in "ltpzZ" for word in words[1:]
                                       if word.startswith("-") and not word.startswith("--") for letter in word[1:]):
            write(into, _option_values(words[1:], "d", ()) or ["."], tree=True)
        if name == "ditto" and len(arguments) >= 2:  # ditto merges a folder's contents into the last
            write(into, arguments[-1:], tree=True)
            into.reads.extend(path for word in arguments[:-1] for path in paths(word))
        if name == "cpio":
            letters = "".join(word[1:] for word in words[1:] if word.startswith("-") and not word.startswith("--"))
            if "i" in letters or "--extract" in words:
                write(into, _option_values(words[1:], "D", ("--directory",)) or ["."], tree=True)
            elif ("p" in letters or "--pass-through" in words) and arguments:
                write(into, arguments[-1:], tree=True)
        if name == "pax":
            letters = "".join(word[1:] for word in words[1:] if word.startswith("-") and not word.startswith("--"))
            if "r" in letters:  # -r extracts here; -rw copies into the last operand
                write(into, arguments[-1:] if "w" in letters and arguments else ["."], tree=True)
        if name == "curl":
            write(into, _option_values(words[1:], "o", ("--output", "--output-dir")))
        if name == "wget":
            write(into, _option_values(words[1:], "O", ("--output-document",))
                  + _option_values(words[1:], "P", ("--directory-prefix",)))
        if name == "git":
            where, settings, rest = git_parts(words)
            for key, value in settings:
                git_setting(key, value)
            sub, args = (rest[0], rest[1:]) if rest else ("", [])

            def located(items: list[str]) -> list[str]:
                return [posixpath.join(where, item) if where and not item.startswith(("/", "~", "$")) else item
                        for item in items]

            if sub == "config":
                positional, index = [], 0
                while index < len(args):
                    if args[index] in {"--file", "-f", "--blob", "--type", "--default", "--comment"}:
                        index += 1
                    elif not args[index].startswith("-"):
                        positional.append(args[index])
                    index += 1
                if positional and positional[0] in {"set", "add"}:  # `git config set alias.x ...` (git 2.46)
                    positional = positional[1:]
                if len(positional) >= 2:
                    git_setting(positional[0], positional[1])
            elif sub in {"rm", "restore"} or (sub == "checkout" and "--" in args):
                targets = args[args.index("--") + 1:] if "--" in args else [a for a in args if not a.startswith("-")]
                write(into, located(targets), tree=True)
            elif sub == "clean" or _git_rewrites_work_tree(sub, args):
                # `git -C ~/link stash`, `cd ~/link && git reset --hard`: every file of the work tree may change.
                write(into, [where or "."], tree=True)

    def finish(separator: str) -> None:
        nonlocal current, upstream
        raw, current = current, []
        incoming, upstream = upstream, []
        if raw and raw[0] in {"export", "declare", "typeset", "local", "readonly"}:
            raw = [word for word in raw[1:] if not word.startswith("-")]
            if not all(_ASSIGNMENT_RE.match(word) for word in raw):
                return
        prefix: list[tuple[str, str]] = []
        for word in raw:
            if not _ASSIGNMENT_RE.match(word):
                break
            name, _, value = word.partition("=")
            prefix.append((name, expand(value)))
        if raw and len(prefix) == len(raw):  # `L=~/link`: remembered for the rest of the line
            variables.update(prefix)
        assigned(prefix)
        if len(raw) >= 3 and raw[0] == "for" and raw[2] == "in":
            loops[raw[1]] = [path for word in raw[3:] for path in _braces(expand(word))]
            return
        seen: set[str] = set()
        words = _unwrap([expand(word) for word in raw], seen)
        if not words:
            return
        if separator == "|":
            upstream = [word for word in words[1:] if not word.startswith("-")]
        if "xargs" in seen:  # xargs adds arguments only known when it runs: `xargs lnk approve`
            reading.commands.append([*words, SUBSTITUTED])
        if "xargs" not in seen or not incoming:
            analyse(words, reading)
            return
        # `... | xargs rm`: what the writer gets comes down the pipe.
        alone = ShellReading()
        analyse(words, alone)
        if not alone.writes or any("{}" in word for word in words):
            fed = ShellReading()
            for item in incoming if any("{}" in word for word in words) else [""]:
                analyse([word.replace("{}", item) for word in words] if item else words + incoming, fed)
            alone.writes += fed.writes
            alone.trees += fed.trees
        _merge(reading, alone)

    for token in _tokens(text):
        _check(deadline)
        if pending_redirect is not None:
            (reading.reads if pending_redirect == "<" else reading.writes).extend(paths(token))
            pending_redirect = None
            continue
        if token in {">|", ">>|"} or (token and set(token) <= set("<>&") and (
                token.startswith(("<", ">")) or token in {">&", "&>"})):
            pending_redirect = "<" if token.startswith("<") else ">"
            continue
        if token in _CONTROL_TOKENS or (token and set(token) <= set(_OPERATOR_CHARS)):
            finish(token)
            continue
        current.append(token)
    finish("")


_PATCH_VALUE_OPTIONS = {"-d", "-i", "-o", "-r", "-B", "-D", "-F", "-V", "-Y", "-z", "-g", "-p", "--directory", "--input",
                        "--output", "--reject-file", "--prefix", "--ifdef", "--fuzz", "--suffix"}


def _sed_in_place(word: str) -> bool:
    """`sed -i`, `-i.bak`, `-Ei`, `--in-place`, `--in-place=.bak`."""
    if word == "--in-place" or word.startswith("--in-place="):
        return True
    letters = re.match(r"-([A-Za-z]*)", word) if not word.startswith("--") else None
    return bool(letters and "i" in letters.group(1))


def _perl_in_place(word: str) -> bool:
    """`perl -i`, `-pi`, `-0pi`, `-i.bak`, `-0777pi`: an -i before an option that takes the rest of the word."""
    if not word.startswith("-") or word.startswith("--"):
        return False
    rest = word[1:]
    index = 0
    while index < len(rest):
        letter = rest[index]
        index += 1
        if letter in "0l":  # -0777, -l015: the digits belong to the option
            while index < len(rest) and (rest[index].isdigit() or rest[index] in "xX"):
                index += 1
        elif letter == "i":
            return True
        elif letter in "IMmFCdDxeEV" or not letter.isalpha():
            return False
    return False


def _git_rewrites_work_tree(sub: str, args: list[str]) -> bool:
    """git commands that rewrite the work tree's files: `stash`, `reset --hard`, `pull`, `checkout <branch>`..."""
    operands = [arg for arg in args if not arg.startswith("-")]
    if sub == "stash":
        return not operands or operands[0] not in {"list", "show", "create", "drop", "clear", "store"}
    if sub in {"pull", "merge", "rebase", "cherry-pick", "revert", "am"}:
        return True
    if sub == "apply":
        return not any(arg in {"--check", "--stat", "--numstat", "--summary", "--cached"} for arg in args)
    if sub == "reset":
        return any(arg in {"--hard", "--keep", "--merge"} for arg in args)
    if sub in {"checkout", "switch"}:  # `git checkout -b new` starts a branch where it is and changes no file
        creates = any(arg in {"-b", "-B", "-c", "-C", "--orphan", "--create", "--force-create"} for arg in args)
        return "-" in args or len(operands) >= (2 if creates else 1)  # `git checkout -`: the branch before
    return False


def _merge(into: ShellReading, other: ShellReading) -> None:
    into.commands.extend(other.commands)
    into.reads.extend(other.reads)
    into.writes.extend(other.writes)
    into.trees.extend(other.trees)
    into.code.extend(other.code)
    into.opaque = into.opaque or other.opaque


# ── PowerShell ───────────────────────────────────────────────────────────
# Read with POSIX rules, `Get-Content C:\repo\.env` loses its backslashes
# and names no file at all, so path rules and the guard on Link's own files
# never saw a PowerShell call. PowerShell keeps backslashes, quotes with
# '...' (literal) and "..." (backtick escapes), and reads and writes files
# through cmdlets and their aliases rather than through redirection alone.

_PS_READ = {"get-content", "gc", "cat", "type", "import-csv", "import-clixml", "get-filehash",
            "format-hex", "import-powershelldatafile", "select-string", "sls"}
_PS_WRITE_FIRST = {"set-content", "sc", "add-content", "ac", "clear-content", "clc", "out-file", "new-item", "ni",
                   "export-csv", "export-clixml", "rename-item", "ren", "rni", "tee-object", "tee", "mkdir", "md",
                   "clear-item", "cli"}
# Cmdlets that remove (or, renaming, move away) the item and everything beneath it.
_PS_WRITE_ALL = {"remove-item", "rm", "del", "erase", "ri", "rd", "rmdir"}
_PS_RENAME = {"rename-item", "ren", "rni"}
_PS_FOREACH = {"foreach-object", "%", "foreach"}
_PS_MOVE = {"move-item", "mv", "move", "mi"}
_PS_COPY = {"copy-item", "cp", "copy", "cpi"}
_PS_CD = {"set-location", "cd", "sl", "chdir", "push-location", "pushd"}
_PS_SHELLS = {"powershell", "pwsh"}
_PS_EVAL = {"invoke-expression", "iex"}
_PS_START = {"start-process", "saps", "start"}
_PS_PATH_PARAMS = ("path", "literalpath", "lp", "pspath", "filepath")
# Parameters that name a file written, whatever the cmdlet (Invoke-WebRequest, Expand-Archive).
_PS_WRITE_PARAMS = ("outfile", "destinationpath", "literaldestinationpath")
# .NET file calls: [IO.File]::WriteAllText('path', ...), [System.IO.Directory]::Delete('path').
_PS_DOTNET_RE = re.compile(
    r"(?i)\[(?:system\.)?io\.(file|directory)\]::(write|append|delete|move|copy|create|replace|open)\w*"
    r"\s*\(\s*(?:(['\"])([^'\"]*)\3|\$(\w+))(?:\s*,\s*(['\"])([^'\"]*)\6)?")
# `$name = 'literal'`, anywhere in the line: what a later `$name` stands for.
_PS_ASSIGN_RE = re.compile(r"\$(\w+)\s*=\s*(['\"])([^'\"`$]*)\2")
_PS_PART = r"(?:'[^']*'|\"[^\"`$]*\"|\$(?:env:)?\w+)"
_PS_JOIN_RE = re.compile(
    rf"(?i)\(\s*Join-Path\s+(?:-Path\s+)?({_PS_PART}|[^\s()'\"]+)\s+(?:-ChildPath\s+)?({_PS_PART}|[^\s()'\"]+)\s*\)")
_PS_CONCAT_RE = re.compile(rf"\(\s*({_PS_PART}(?:\s*\+\s*{_PS_PART})+)\s*\)")
# `$m = Join-Path $HOME 'link'`: the same Join-Path, without its parentheses.
_PS_ASSIGN_JOIN_RE = re.compile(r"(?i)(\$\w+\s*=\s*)(Join-Path\s[^;|\n(){}]*)")
# `@('push', '-f')`: an array of literals, as the comma list it is.
_PS_ARRAY_RE = re.compile(rf"@\(\s*({_PS_PART}(?:\s*,\s*{_PS_PART})*)\s*\)")
# Parameters that take a value; every other -Name is a switch. PowerShell
# accepts any unambiguous prefix (`-Pa` is -Path, `-Dest` is -Destination).
_PS_VALUE_PARAMS = {"path", "literalpath", "lp", "pspath", "filepath", "destination", "value", "encoding", "filter",
                    "include", "exclude", "itemtype", "type", "name", "newname", "pattern", "delimiter", "stream",
                    "credential", "tail", "totalcount", "head", "readcount", "width", "inputobject", "command",
                    "argumentlist", "args", "workingdirectory", "wd", "erroraction", "ea", *_PS_WRITE_PARAMS}
# Common switches: a short prefix that could be one of them (`-r` for -Recurse, `-h` for -Hidden, `-v` for
# -Verbose) is read as a switch, so it never swallows the path after it.
_PS_SWITCH_PARAMS = {"recurse", "force", "confirm", "whatif", "verbose", "debug", "passthru", "append", "noclobber",
                     "nonewline", "raw", "wait", "nonewwindow", "asbytestream", "container", "directory", "file",
                     "hidden", "readonly", "system", "followsymlink", "useshellexecute", "asjob"}
# powershell.exe / pwsh options that take a value, before the command itself.
_PS_SHELL_VALUE_PARAMS = {"executionpolicy", "ex", "ep", "workingdirectory", "wd", "outputformat", "of",
                          "inputformat", "if", "configurationname", "settingsfile", "windowstyle", "w",
                          "psconsolefile", "version", "v", "custompipename"}
_PS_ENV_RE = re.compile(r"\$env:([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
_PS_VAR_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
_PS_SINGLE_QUOTES = "'\u2018\u2019\u201a\u201b"
_PS_DOUBLE_QUOTES = '"\u201c\u201d\u201e'
_PS_DASHES = "-\u2013\u2014\u2015"
_PS_REDIRECT_RE = re.compile(r"([1-6*]?)(>>?)(&[12])?")
# Text a shell tool runs that is PowerShell rather than POSIX shell: a Verb-Noun cmdlet, a
# PowerShell or cmd.exe launch, or $env: - read both ways, since either reading may be the true one.
_PS_HINT_RE = re.compile(
    r"(?i)(?:^|[\s;|&({])(?:[a-z]+-[a-z]+|pwsh|powershell|iex|cmd)(?:\.exe)?(?=[\s;|&)}]|$)|\$env:")


def looks_like_powershell(command: str) -> bool:
    return bool(_PS_HINT_RE.search(command))


def _ps_tokens(text: str) -> list[str]:
    """Words and operators, with PowerShell's quoting; backslashes are ordinary characters.

    A block or subexpression (`{ }`, `( )`) ends the statement before it, so
    the commands inside it are read as statements of their own.
    """
    tokens: list[str] = []
    word: list[str] = []
    started = False
    index = 0

    def flush() -> None:
        nonlocal word, started
        if started:
            tokens.append("".join(word))
        word, started = [], False

    while index < len(text):
        ch = text[index]
        if ch == "@" and text[index + 1:index + 2] in {"'", '"'} and text[index + 2:index + 3] in {"\n", "\r"}:
            quote = text[index + 1]  # a here-string runs to a line that starts with its closing quote
            end = text.find("\n" + quote + "@", index + 2)
            end = len(text) if end < 0 else end
            word.append(text[index + 2:end].lstrip("\r\n"))
            started, index = True, end + 3
            continue
        if ch in _PS_SINGLE_QUOTES:
            end = index + 1
            while end < len(text):
                if text[end] in _PS_SINGLE_QUOTES and text[end + 1:end + 2] in _PS_SINGLE_QUOTES \
                        and text[end + 1:end + 2]:
                    word.append("'")
                    end += 2
                    continue
                if text[end] in _PS_SINGLE_QUOTES:
                    break
                word.append(text[end])
                end += 1
            started, index = True, end + 1
            continue
        if ch in _PS_DOUBLE_QUOTES:
            end = index + 1
            while end < len(text) and text[end] not in _PS_DOUBLE_QUOTES:
                if text[end] == "`" and end + 1 < len(text):
                    end += 1
                word.append(text[end])
                end += 1
            started, index = True, end + 1
            continue
        if ch == "`" and index + 1 < len(text):
            if text[index + 1] in {"\n", "\r"}:  # line continuation
                flush()
                index += 3 if text.startswith("\r\n", index + 1) else 2
                continue
            word.append(text[index + 1])
            started, index = True, index + 2
            continue
        if text.startswith("<#", index):
            flush()
            end = text.find("#>", index + 2)
            index = len(text) if end < 0 else end + 2
            continue
        if ch == "#" and not started:
            while index < len(text) and text[index] != "\n":
                index += 1
            continue
        if ch.isspace() and ch != "\n":
            flush()
            index += 1
            continue
        if text.startswith("${", index) and (close := text.find("}", index + 2)) > 0:
            word.append(text[index:close + 1])  # `${HOME}` is a variable, not a block
            started, index = True, close + 1
            continue
        if ch in "{}()":
            flush()
            tokens.append(";")
            index += 1
            continue
        if ch == ">" or (ch in "123456*" and not started and text[index + 1:index + 2] == ">"):
            match = _PS_REDIRECT_RE.match(text, index)
            assert match is not None
            flush()
            if not match.group(3):  # `2>&1` merges streams and names no file
                tokens.append(">")
            index = match.end()
            continue
        operator = next((op for op in ("&&", "||", "|", ";", "\n", "&") if text.startswith(op, index)), None)
        if operator and not started or operator in {"&&", "||", "|", ";", "\n"}:
            flush()
            tokens.append(operator)
            index += len(operator)
            continue
        word.append(ch)
        started = True
        index += 1
    flush()
    return tokens


def _ps_subexpressions(text: str) -> list[str]:
    """The text inside each outermost `$( ... )`, which runs even inside a double-quoted string.

    Only the outermost: reading one reads those inside it, and finding every
    `$(` again at each depth took minutes on a line of a few hundred.
    """
    found: list[str] = []
    start = text.find("$(")
    while start >= 0:
        depth, end = 0, start + 1
        while end < len(text):
            if text[end] == "(":
                depth += 1
            elif text[end] == ")":
                depth -= 1
                if depth == 0:
                    break
            end += 1
        found.append(text[start + 2:end])
        start = text.find("$(", end)
    return found


def _ps_is_param(word: str) -> bool:
    return len(word) > 1 and word[0] in _PS_DASHES and not word[1].isdigit() and word[1] not in _PS_DASHES


def _ps_param(word: str, known: set[str] = _PS_VALUE_PARAMS) -> str:
    key = word[1:].partition(":")[0].lower()
    if key in known:
        return key
    if any(name.startswith(key) for name in _PS_SWITCH_PARAMS):
        return key  # `-r` may be -Recurse: a switch, which takes no value
    candidates = sorted((name for name in known if name.startswith(key)), key=len)
    # One cmdlet rarely has both -Destination and -DestinationPath: the shorter is meant.
    return candidates[0] if candidates and all(name.startswith(candidates[0]) for name in candidates) else key


def _ps_expand(path: str, variables: Mapping[str, str] | None = None) -> str:
    import os

    for prefix in ("microsoft.powershell.core\\filesystem::", "filesystem::"):
        if path.lower().startswith(prefix):
            path = path[len(prefix):]
            break
    if path.startswith(("\\\\?\\", "\\\\.\\")):
        path = path[4:]
    if variables:
        path = _PS_VAR_RE.sub(lambda m: variables.get(m.group(1).lower(), m.group(0)), path)
    path = _PS_ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), path)
    if path.lower().startswith("${home}"):
        path = os.path.expanduser("~") + path[7:]
    elif path.lower().startswith("$home"):
        path = os.path.expanduser("~") + path[5:]
    elif path.startswith("~"):
        path = os.path.expanduser(path)
    return path


def _ps_absolute(path: str) -> bool:
    return bool(re.match(r"^(?:[A-Za-z]:|\\\\|/|~|\$)", path))


def _ps_literals(command: str) -> tuple[str, dict[str, str]]:
    """`(Join-Path 'C:\\ws' 'wiki')` and `($root + '\\wiki')`, made of literals and known variables, as one literal."""
    command = _PS_ASSIGN_JOIN_RE.sub(lambda match: f"{match.group(1)}({match.group(2).strip()})", command)
    command = _PS_ARRAY_RE.sub(lambda match: match.group(1), command)
    variables = {name.lower(): value for name, _, value in _PS_ASSIGN_RE.findall(command)}

    def part(text: str) -> str | None:
        if text.startswith("$"):
            if text[1:].lower() in variables:
                return variables[text[1:].lower()]
            expanded = _ps_expand(text)  # $HOME, $env:USERPROFILE
            return None if "$" in expanded else expanded
        return text[1:-1] if text[:1] in {"'", '"'} else text

    def literal(parts: list[str | None], original: str) -> str:
        if any(item is None for item in parts):
            return original
        return "'" + "".join(item or "" for item in parts).replace("'", "''") + "'"

    def join(match: re.Match[str]) -> str:
        parent, child = part(match.group(1)), part(match.group(2))
        separator = "\\" if parent and "\\" in parent else "/"
        return literal([parent and parent.rstrip("\\/"), separator, child and child.lstrip("\\/")], match.group(0))

    command = _PS_JOIN_RE.sub(join, command)
    command = _PS_CONCAT_RE.sub(lambda match: literal(
        [part(item) for item in re.findall(_PS_PART, match.group(1))], match.group(0)), command)
    # `$m = (Join-Path ...)` is a literal now: what a later `$m` stands for.
    variables.update({name.lower(): value for name, _, value in _PS_ASSIGN_RE.findall(command)})
    return command, variables


def read_powershell(command: str, *, deadline: float | None = None, _depth: int = 0) -> ShellReading:
    """What a PowerShell command line runs, reads and writes.

    Where the reader cannot follow what a command will run (an encoded
    command, `iex` of something it cannot see, a line too long or too deeply
    nested to read in time), the reading is marked opaque.
    """
    reading = ShellReading()
    if not command.strip():
        return reading
    if _depth > MAX_DEPTH or len(command) > MAX_COMMAND_CHARS:
        reading.opaque = True
        return reading
    if deadline is None:
        deadline = time.monotonic() + READ_SECONDS
    try:
        _read_powershell(reading, command, deadline, _depth)
    except _Unreadable:
        reading.opaque = True
    return reading


def _read_powershell(reading: ShellReading, command: str, deadline: float, _depth: int) -> None:
    command, literals = _ps_literals(command)
    for inner in _ps_subexpressions(command):
        _merge(reading, read_powershell(inner, deadline=deadline, _depth=_depth + 1))
    for match in _PS_DOTNET_RE.finditer(command):
        first = match.group(4) or literals.get((match.group(5) or "").lower(), "")
        found = [_ps_expand(path) for path in (first, match.group(7)) if path]
        reading.writes.extend(found)
        if match.group(1).lower() == "directory" and match.group(2).lower() in {"delete", "move"}:
            reading.trees.extend(found[:1])  # [IO.Directory]::Delete('~/link', $true): everything beneath
    here = ""
    variables: dict[str, str] = {}
    statement: list[str] = []
    pending_redirect = False
    upstream: list[str] = []  # what the previous command of a pipeline handed on

    def at(target: str) -> str:
        target = _ps_expand(target, variables)
        if not here or _ps_absolute(target):
            return target
        while target.startswith((".\\", "./")):
            target = target[2:]
        separator = "\\" if "\\" in here else "/"
        return here if target in {".", ""} else here.rstrip("\\/") + separator + target

    def run(text: str) -> None:
        _merge(reading, read_powershell(text, deadline=deadline, _depth=_depth + 1))

    def finish(separator: str) -> None:
        nonlocal statement, here, upstream
        words, statement = statement, []
        incoming, upstream = upstream, []
        if words and words[0] in {"&", "."}:
            words = words[1:]  # the call and dot-source operators
        if not words:
            return
        if separator == "|":
            upstream = [word for word in words if not _ps_is_param(word)]
        if words[0].startswith("$"):  # `$p = 'C:\x'` or, quoted, `$p='C:\x'`
            if len(words) >= 3 and words[1] == "=":
                if len(words) == 3:
                    variables[words[0].lstrip("$").strip("{}").lower()] = _ps_expand(words[2], variables)
                    return
                words = words[2:]
            elif "=" in words[0] and len(words) == 1:
                name, _, value = words[0].partition("=")
                variables[name.lstrip("$").strip("{}").lower()] = _ps_expand(value, variables)
                return
        name = words[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
        reading.commands.append([words[0].replace("\\", "/").rsplit("/", 1)[-1], *words[1:]])
        program = _WINDOWS_PROGRAM_RE.sub("", name)
        if name in _PS_FOREACH:
            upstream = incoming  # `'C:\\x' | ForEach-Object { Remove-Item $_ }`: the block gets what came down
            return
        if program in _PS_SHELLS:
            index = 1
            while index < len(words):
                word = words[index]
                if not _ps_is_param(word):
                    run(" ".join(words[index:]))  # Windows PowerShell runs what follows as a command
                    return
                key = word[1:].partition(":")[0].lower()
                if key in {"e", "ec"} or (len(key) > 1 and "encodedcommand".startswith(key)):
                    reading.opaque = True
                    return
                if key == "c" or (len(key) > 1 and "command".startswith(key)):
                    if index + 1 < len(words):
                        run(" ".join(words[index + 1:]))
                    return
                if key == "f" or (len(key) > 1 and "file".startswith(key)):
                    return
                index += 2 if key in _PS_SHELL_VALUE_PARAMS else 1
            return
        if program == "cmd":
            flag = next((i for i, w in enumerate(words) if w.lower() in {"/c", "/k", "/r"}), None)
            if flag is not None and flag + 1 < len(words):
                run(" ".join(words[flag + 1:]))  # del, rd, copy, move and type are PowerShell aliases too
            return
        named: dict[str, list[str]] = {}
        positional: list[str] = []
        index = 1
        while index < len(words):
            word = words[index]
            if _ps_is_param(word):
                key = _ps_param(word)
                inline = word.partition(":")[2]
                if inline:
                    named.setdefault(key, []).append(inline)
                elif key in _PS_VALUE_PARAMS and index + 1 < len(words) and (
                        not _ps_is_param(words[index + 1]) or key in {"argumentlist", "args"}):
                    # `-ArgumentList '-c','...'`: what is handed on may itself start with a dash.
                    named.setdefault(key, []).append(words[index + 1])
                    index += 1
                index += 1
                continue
            positional.append(word)
            index += 1

        def split(values: list[str]) -> list[str]:
            return [item.strip() for value in values for item in value.split(",") if item.strip()]

        def piped(values: list[str]) -> list[str]:
            """`$_`, `$PSItem` and their properties (`$_.FullName`) stand for what came down the pipe."""
            return [item for value in values
                    for item in (incoming if value.lower().split(".")[0] in {"$_", "$psitem"} else [value])]

        paths = split([value for key in _PS_PATH_PARAMS for value in named.get(key, [])])
        positional = split(positional)
        destination = split(named.get("destination", []))
        reading.writes.extend(at(path) for path in split([v for key in _PS_WRITE_PARAMS for v in named.get(key, [])]))
        if name in _PS_EVAL:
            text = [_ps_expand(value, variables) for value in named.get("command", []) + positional]
            if not text or any(value.startswith("$") for value in text):
                reading.opaque = True  # `iex $code`, `... | iex`: what runs is not on the line
            else:
                run(" ".join(text))
            return
        if name in _PS_START:
            program_words = split(paths) or positional[:1]
            arguments = split(named.get("argumentlist", []) + named.get("args", [])) + positional[1:]
            run(" ".join(program_words + arguments))
            return
        if name == "expand-archive":  # what the archive holds lands beneath the destination
            found = [at(path) for path in split(named.get("destinationpath", []) + named.get("destination", [])
                                                + named.get("literaldestinationpath", [])) or positional[1:2] or ["."]]
            reading.writes.extend(found)
            reading.trees.extend(found)
            return
        if name in _PS_CD:
            target = (paths or positional or [""])[0]
            if target:
                here = at(target)
            return
        if name in _PS_READ:
            sources = paths or (positional[1:] if name in {"select-string", "sls"} else positional)
            reading.reads.extend(at(path) for path in sources)
        elif name in _PS_WRITE_FIRST or name in _PS_WRITE_ALL:
            # Every word could be the path: a parameter Link does not know (`-Enc utf8`) shifts
            # the positions, so for a cmdlet that writes, all of them count.
            targets = piped(paths + positional + destination + split(named.get("newname", [])) or incoming)
            if name in {"new-item", "ni"}:
                targets += [(parent.rstrip("\\/") + "/" if parent not in {"", "."} else "") + child
                            for parent in (paths or positional[:1] or ["."]) for child in named.get("name", [])]
            found = [at(path) for path in targets]
            reading.writes.extend(found)
            if name in _PS_WRITE_ALL:
                reading.trees.extend(found)
            elif name in _PS_RENAME:
                reading.trees.extend(at(path) for path in (paths or positional[:1]))
        elif name in _PS_MOVE or name in _PS_COPY:
            sources = piped(paths or positional[:1]) or incoming
            targets = destination + (positional[1:] if not paths else positional)
            reading.writes.extend(at(path) for path in targets)
            (reading.writes if name in _PS_MOVE else reading.reads).extend(at(path) for path in sources)
            if name in _PS_MOVE:
                reading.trees.extend(at(path) for path in sources)
        elif name in _SHELLS or program in _SHELLS or program == "git" or _INTERPRETER_RE.match(program):
            # A native program (git, bash -c, python -c, cat from Git for Windows) reads its arguments as a
            # POSIX shell would.
            native = read_shell(shlex.join([program, *words[1:]]), deadline=deadline, _depth=_depth + 1)
            native.commands = [found for found in native.commands if found not in reading.commands]
            _merge(reading, native)

    for token in _ps_tokens(command):
        _check(deadline)
        if pending_redirect:
            if token not in {";", "|", "&&", "||", "\n", ">"}:
                reading.writes.append(at(token))
                pending_redirect = False
                continue
            pending_redirect = False
        if token == ">":
            pending_redirect = True
            continue
        if token in {"&&", "||", "|", ";", "\n"} or (token == "&" and statement):
            finish(token)
            continue
        statement.append(token)
    finish("")
