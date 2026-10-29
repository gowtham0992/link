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

import posixpath
import re
import shlex
from collections.abc import Mapping
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
    # The reader could not see what will run (an encoded PowerShell command, `iex $code`).
    opaque: bool = False


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
    # `cd x && echo y > z` writes x/z: paths after a cd in the same line are
    # read relative to where it went, so a rule on x/** still sees them.
    here = ""

    def at(target: str) -> str:
        if not here or target.startswith(("/", "~")) or target.startswith("$"):
            return target
        return posixpath.join(here, target)

    def finish() -> None:
        nonlocal current, here
        words = _unwrap(current)
        current = []
        if not words:
            return
        name = words[0]
        if name in {"cd", "pushd"}:
            destination = next((word for word in words[1:] if not word.startswith("-")), "")
            if destination:
                here = destination if destination.startswith(("/", "~")) else posixpath.join(here, destination)
            reading.commands.append(words)
            return
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
            reading.reads.extend(at(word) for word in arguments)
        if name in _WRITERS_ALL_ARGS:
            reading.writes.extend(at(word) for word in arguments)
        if name in {"cp", "mv", "install", "ln", "rsync"} and len(arguments) >= 2:
            reading.writes.append(at(arguments[-1]))
            if name in {"cp", "rsync"}:
                reading.reads.extend(at(word) for word in arguments[:-1])
            if name == "mv":  # what is moved away is gone from where it was
                reading.writes.extend(at(word) for word in arguments[:-1])
        if name in {"sed", "perl"} and any(word.startswith("-i") or word.startswith("-pi") for word in words[1:]):
            reading.writes.extend(at(word) for word in arguments[1:])
        if name == "dd":
            reading.writes.extend(at(word[3:]) for word in words[1:] if word.startswith("of="))
        if name == "find" and "-delete" in words and arguments:
            reading.writes.append(at(arguments[0]))
        if name == "git" and "--" in words and any(word in {"checkout", "restore", "rm", "clean"} for word in words):
            where = words[words.index("-C") + 1] if "-C" in words[:-1] else ""
            reading.writes.extend(at(posixpath.join(where, word) if where else word)
                                  for word in words[words.index("--") + 1:])

    for token in _tokens(text):
        if pending_redirect is not None:
            (reading.reads if pending_redirect == "<" else reading.writes).append(at(token))
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
                   "export-csv", "export-clixml", "rename-item", "ren", "rni", "tee-object", "tee"}
_PS_WRITE_ALL = {"remove-item", "rm", "del", "erase", "ri", "rd", "rmdir", "mkdir", "md"}
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
    r"(?i)\[(?:system\.)?io\.(?:file|directory)\]::(?:write|append|delete|move|copy|create|replace|open)\w*"
    r"\s*\(\s*(['\"])(.*?)\1(?:\s*,\s*(['\"])(.*?)\3)?")
# Parameters that take a value; every other -Name is a switch. PowerShell
# accepts any unambiguous prefix (`-Pa` is -Path, `-Dest` is -Destination).
_PS_VALUE_PARAMS = {"path", "literalpath", "lp", "pspath", "filepath", "destination", "value", "encoding", "filter",
                    "include", "exclude", "itemtype", "type", "name", "newname", "pattern", "delimiter", "stream",
                    "credential", "tail", "totalcount", "head", "readcount", "width", "inputobject", "command",
                    "argumentlist", "args", "workingdirectory", "wd", *_PS_WRITE_PARAMS}
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
    """The text inside each `$( ... )`, which runs even inside a double-quoted string."""
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
        start = text.find("$(", start + 2)
    return found


def _ps_is_param(word: str) -> bool:
    return len(word) > 1 and word[0] in _PS_DASHES and not word[1].isdigit() and word[1] not in _PS_DASHES


def _ps_param(word: str, known: set[str] = _PS_VALUE_PARAMS) -> str:
    key = word[1:].partition(":")[0].lower()
    if key in known:
        return key
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
    if path.lower().startswith("$home"):
        path = os.path.expanduser("~") + path[5:]
    elif path.startswith("~"):
        path = os.path.expanduser(path)
    return path


def _ps_absolute(path: str) -> bool:
    return bool(re.match(r"^(?:[A-Za-z]:|\\\\|/|~|\$)", path))


def read_powershell(command: str, *, _depth: int = 0) -> ShellReading:
    """What a PowerShell command line runs, reads and writes.

    Where the reader cannot follow what a command will run (an encoded
    command, `iex` of something it cannot see), the reading is marked
    opaque, and Link's own files are guarded as if it wrote them.
    """
    reading = ShellReading()
    if _depth > 3 or not command.strip():
        return reading
    for inner in _ps_subexpressions(command):
        _merge(reading, read_powershell(inner, _depth=_depth + 1))
    for match in _PS_DOTNET_RE.finditer(command):
        reading.writes.extend(_ps_expand(path) for path in (match.group(2), match.group(4)) if path)
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
        _merge(reading, read_powershell(text, _depth=_depth + 1))

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
        program = name.removesuffix(".exe")
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
                elif key in _PS_VALUE_PARAMS and index + 1 < len(words) and not _ps_is_param(words[index + 1]):
                    named.setdefault(key, []).append(words[index + 1])
                    index += 1
                index += 1
                continue
            positional.append(word)
            index += 1

        def split(values: list[str]) -> list[str]:
            return [item.strip() for value in values for item in value.split(",") if item.strip()]

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
            arguments = named.get("argumentlist", []) + named.get("args", []) + positional[1:]
            run(" ".join(program_words + arguments))
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
            targets = paths + positional + destination + split(named.get("newname", [])) or incoming
            if name in {"new-item", "ni"}:
                targets += [(parent.rstrip("\\/") + "/" if parent not in {"", "."} else "") + child
                            for parent in (paths or positional[:1] or ["."]) for child in named.get("name", [])]
            reading.writes.extend(at(path) for path in targets)
        elif name in _PS_MOVE or name in _PS_COPY:
            sources = paths or positional[:1] or incoming
            targets = destination + (positional[1:] if not paths else positional)
            reading.writes.extend(at(path) for path in targets)
            (reading.writes if name in _PS_MOVE else reading.reads).extend(at(path) for path in sources)
        elif name in _SHELLS or program in _SHELLS:
            # A native program (git, bash -c, cat from Git for Windows) reads its arguments as a POSIX shell would.
            _merge(reading, read_shell(shlex.join(words), _depth=_depth + 1))

    for token in _ps_tokens(command):
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
    return reading
