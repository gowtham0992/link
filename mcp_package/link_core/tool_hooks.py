"""Memory that acts when the agent acts: rules, touched code, and delivery.

A memory the agent has read is still only advice. Three things here close
the gap between "the agent was told" and "the agent did the right thing":

- **Enforced rules.** A reviewed memory can carry an `enforce` clause such as
  `ask command: git push --force*` or `deny write: migrations/**`. Before a
  tool call runs, the pre-tool hook matches the call against every active,
  reviewed rule and asks the person (or, when the rule says deny, blocks the
  call), citing the memory. Matching is a glob over the command or path: no
  model, no network, and a rule only takes effect after human review, so a
  bad memory can never become a bad block on its own.
- **Code-triggered recall.** When the agent reads or edits a file, the memories
  anchored to that file (`anchors`, recorded when the memory was written from
  inside the repository) are surfaced once per session. A memory whose anchored symbol is gone from the file is not
  surfaced: it may be stale, and `lnk stale` says so.
- **Delivery tokens.** Everything a hook injects is wrapped in a short
  `(link:<id>)` ... `(link:<id> end)` pair. At session end the transcript is
  searched for both halves, so the receipt can say whether each injection
  arrived whole, arrived cut off, or never arrived.

The hooks run on every tool call, so they read a compiled index
(`.link-cache/hook-index.json`) that is rebuilt only when a memory file
changes, instead of parsing the store each time.
"""
from __future__ import annotations

import fnmatch
import functools
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from datetime import date
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from stat import S_ISREG

from .project_scope import (
    default_project_for_target,
    memory_visible_for_project,
    normalize_project,
    parse_applies_when,
)
from .shell_parse import READ_SECONDS, command_forms, looks_like_powershell, read_powershell, read_shell
from .tool_events import EMITS, HookReply, call_binding, call_content, can_ask, native_emit, render_reply, tool_calls

# Everything else is imported where it is used: the pre-tool hook runs before
# every shell command and file access, and deciding against the compiled
# index needs none of memory.py, provenance.py, the rule parser or the file
# writers. (link_hook.py says why that matters.)

HOOK_INDEX_VERSION = 2
# At most this many anchored memories per touched file, each on one line:
# a reminder, not a second brief.
MAX_TOUCH_REMINDERS = 3
# Hook output past roughly 10,000 characters is dropped by some hosts without
# a warning; everything Link injects from a hook stays well under it.
HOOK_OUTPUT_BUDGET = 9000



def hook_index_path(link_root: Path) -> Path:
    return link_root / ".link-cache" / "hook-index.json"


def _memories_signature(wiki_dir: Path) -> str:
    # Every memory file, nested ones too (memory_records reads them), and
    # today's date: an expires_at passing must retire its rules.
    digest = hashlib.sha256(date.today().isoformat().encode())
    memories = wiki_dir / "memories"
    if memories.is_dir():
        for path in sorted(memories.rglob("*.md")):
            try:
                stat = path.stat()
            except OSError:
                continue
            digest.update(f"{path.relative_to(memories)}\0{stat.st_mtime_ns}\0{stat.st_size}\n".encode())
    return digest.hexdigest()


def _eligible(record: Mapping[str, object]) -> bool:
    """Reviewed, active, unquarantined memories act on tool calls (anchors and reviewed rules)."""
    from .memory import is_active_memory, memory_quarantined

    return (
        is_active_memory(record)
        and not memory_quarantined(record)
        and str(record.get("review_status") or "").lower() == "reviewed"
    )


def build_hook_index(wiki_dir: Path) -> dict[str, object]:
    from .enforce_rules import parse_enforce_rules
    from .memory import memory_records, rules_in_force
    from .provenance import parse_anchor

    rules: list[dict[str, object]] = []
    anchors: dict[str, list[dict[str, object]]] = {}
    for record in memory_records(wiki_dir, include_body=False):
        if not _eligible(record) and not rules_in_force(record):
            continue
        head = {
            "name": str(record.get("name") or ""),
            "title": str(record.get("title") or ""),
            "claim": str(record.get("tldr") or record.get("title") or "")[:240],
            "scope": str(record.get("scope") or "user"),
            "project": str(record.get("project") or ""),
            "visibility": str(record.get("visibility") or ""),
            "applies_when": str(record.get("applies_when") or ""),
        }
        # Rules the person approved keep acting while a change to the memory
        # waits for review (memory.rules_in_force); new ones wait with it.
        for rule in parse_enforce_rules(rules_in_force(record)):
            rules.append({**head, "action": rule.action, "kind": rule.kind, "pattern": rule.pattern})
        anchor_values = record.get("anchors") if _eligible(record) else []
        for anchor in anchor_values if isinstance(anchor_values, list) else []:
            parsed = parse_anchor(str(anchor))
            if parsed is None or not parsed[3]:
                continue
            rel, line, symbol, repo = parsed
            anchors.setdefault(rel, []).append({**head, "line": line, "symbol": symbol, "repo": repo})
    return {"version": HOOK_INDEX_VERSION, "rules": rules, "anchors": anchors}


def load_hook_index(wiki_dir: Path, link_root: Path) -> dict[str, object]:
    """The compiled index, rebuilt only when a memory file changed."""
    signature = _memories_signature(wiki_dir)
    path = hook_index_path(link_root)
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("version") == HOOK_INDEX_VERSION and cached.get("signature") == signature:
            return cached
    except (OSError, ValueError, AttributeError):
        pass
    index = build_hook_index(wiki_dir)
    index["signature"] = signature
    try:
        from .files import atomic_write_json

        atomic_write_json(path, index)
    except OSError:
        pass  # a read-only cache costs speed, never correctness
    return index


def _applies_to_project(entry: Mapping[str, object], project: str | None) -> bool:
    return memory_visible_for_project(entry, normalize_project(project or ""))


def _rule_applies(rule: Mapping[str, object], project: str | None, context_path: str | None) -> bool:
    """A project's rule applies only inside that project; a fenced memory only where it matches.

    Outside any known project a project rule stays quiet: firing it in
    every other repository is how a guard gets switched off.
    """
    if str(rule.get("scope") or "") == "project" and str(rule.get("project") or ""):
        if normalize_project(project or "") != normalize_project(str(rule.get("project"))):
            return False
    if str(rule.get("applies_when") or "").strip():
        return _fence_matches(str(rule.get("applies_when")), project, context_path)
    return True


def _fence_matches(applies_when: str, project: str | None, context_path: str | None) -> bool:
    """An applies_when fence, judged the way memory_applicability judges it with no query.

    A tool call carries no task text, so task: conditions never match here;
    project: and path: conditions do. A malformed fence fails closed.
    """
    try:
        conditions = parse_applies_when(applies_when)
    except ValueError:
        return False
    if not conditions:
        return True  # "," parses to nothing: unconditional, as recall reads it
    current = normalize_project(project or "")
    for kind, argument in conditions:
        if kind == "project" and argument and argument == current:
            return True
        if kind == "path" and context_path and fnmatch.fnmatch(str(context_path).lower(), argument.lower()):
            return True
    return False


@functools.lru_cache(maxsize=4096)
def _path_candidates(raw: str, repo_root: Path | None, base: Path | None) -> tuple[str, ...]:
    """Every name a rule may know the path by, resolved once however many rules ask: as resolved
    (firmlink and Unicode spellings folded), as the repository names it, and by identity."""
    path = Path(os.path.expanduser(raw))  # never raises, unlike Path.expanduser on `~x/y`
    if not path.is_absolute() and base is not None:
        path = base / path
    try:
        resolved = path.resolve()
    except (OSError, ValueError):
        return ()
    names = [_spelled(str(resolved)).replace("\\", "/")]
    if repo_root is not None:
        root = _resolved(repo_root)
        try:
            names.append(resolved.relative_to(root).as_posix())
        except ValueError:
            pass
        # The same checkout under another spelling (the macOS firmlink, a decomposed é): by identity.
        try:
            inside = _relative_to(resolved, root)
        except (OSError, ValueError):
            inside = None
        if inside:
            names.append(inside)
    return tuple(names)


@functools.lru_cache(maxsize=64)
def _resolved(path: Path) -> Path:
    return path.resolve()


def _path_matches(pattern: str, file_path: str, repo_root: Path | None, base: Path | None = None, *,
                  tree: bool = False) -> bool:
    """Does a path rule cover this file? With `tree` (a delete, a move away, a folder copied over), the folder
    a `dir/**` rule names counts too, and so does a named folder above it: `rm -r secrets`, `mv config x`.

    The working folder itself does not: `find . -delete`, `git clean`, `tar x` there act on what they
    select, every day, and a rule on one folder must not stop them all.
    """
    raw = str(file_path or "").strip()
    if not raw:
        return False
    candidates = {raw.replace("\\", "/")}
    candidates.update(_path_candidates(raw, repo_root, base))
    # Case-insensitive: `.ENV` is `.env` on the default macOS and Windows disks.
    wanted = unicodedata.normalize("NFC", pattern.replace("\\", "/")).lower()
    for candidate in (unicodedata.normalize("NFC", item).lower() for item in candidates):
        if candidate.startswith("./"):
            candidate = candidate[2:]
        if fnmatch.fnmatchcase(candidate, wanted) or fnmatch.fnmatchcase(candidate, f"*/{wanted}"):
            return True
        # "migrations/**" also covers the directory's files at any depth.
        if wanted.endswith("/**") and (f"/{wanted[:-3]}/" in f"/{candidate}"):
            return True
        folder, candidate = wanted[:-3], candidate.rstrip("/")
        if tree and wanted.endswith("/**") and candidate not in {"", "."} and (
                fnmatch.fnmatchcase(candidate, folder) or fnmatch.fnmatchcase(candidate, f"*/{folder}")
                or folder.startswith(f"{candidate}/")):
            return True
    return False


# Link's own commands that approve, clear, retire or rewrite a memory: with a
# rule active, an agent running them from the shell is asking the person.
# Link's commands that turn rules on or off, or let a held call through.
GOVERNANCE_COMMANDS = {
    "review-memory", "enforce", "archive-memory", "forget-memory", "update-memory", "restore-backup", "approve",
}
# Every way Link's CLI is started: the launcher, the script (checkout or
# workspace copy), the pip module, the package name pipx and uv know.
_LINK_PROGRAMS = {"lnk", "lnk.exe", "link", "link.py", "link_cli", "link_cli.py", "link_hook.py", "link-mcp"}
_LINK_MODULES = {"link_cli", "link_mcp", "link_core"}
# The viewer's endpoints for the same changes: `curl localhost:3000/api/archive-memory`
# is the governance command by another road. (The viewer refuses them for a
# memory that carries rules; this asks before the request is even sent.)
_VIEWER_GOVERNANCE = re.compile(r"/api/(?:review|archive|restore|update|forget)-memory(?![\w-])", re.IGNORECASE)


def _link_program_at(words: list[str]) -> int | None:
    """Where Link's CLI is named in a command (`lnk`, `python3 link.py`, `python3 -m link_cli`), if it is."""
    for index, word in enumerate(words):
        if word.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].lower() in _LINK_PROGRAMS:
            return index
        if word == "-m" and index + 1 < len(words) and words[index + 1].split(".")[0] in _LINK_MODULES:
            return index + 1
    return None


def is_link_governance(words: list[str]) -> bool:
    """Does this command run one of Link's governance commands, however it is spelt?

    Read from the parsed words, not the text: `python3 -u link.py approve`,
    `python3 -m link_cli approve`, `uv run link.py approve`, a quoted path
    with spaces, and a program named by a variable (`$L approve`) all count.
    So does Link's CLI given a subcommand only known at run time (`lnk $A`,
    `lnk $(echo approve)`): it could be any of them.
    Code passed to an interpreter (`python -c`) is only caught when it names
    Link's modules or the viewer's endpoints; anything subtler is out of a
    pre-tool hook's sight. Any word naming one of the viewer's governance
    endpoints counts, whatever sends it (curl, wget, httpie, `python -c`).
    """
    if any(_VIEWER_GOVERNANCE.search(word) for word in words):
        return True
    link_at = _link_program_at(words)
    if link_at is not None:
        for word in words[link_at + 1:]:
            if "$" in word or "`" in word:
                return True
            if not word.startswith("-"):
                break  # the subcommand, as typed
        if _only_reads_governance(words[link_at + 1:]):
            return False
    if not any(word in GOVERNANCE_COMMANDS for word in words) and not any(
        module in word for word in words[1:] for module in _LINK_MODULES
    ):
        return False
    if words and words[0] in GOVERNANCE_COMMANDS:
        return True  # `$(echo lnk) approve`: the program was substituted away, the subcommand is left
    if link_at is not None:
        return True
    for index, word in enumerate(words):
        if word in {"-c", "-e"} and index + 1 < len(words) and any(m in words[index + 1] for m in _LINK_MODULES):
            return True
        if index == 0 and ("$" in word or "`" in word):
            return True  # the program is decided at run time
    return False


def _only_reads_governance(arguments: list[str]) -> bool:
    """`lnk approve` with no id lists the held calls; `lnk enforce x --suggest` only shows rules."""
    options = [word for word in arguments if word.startswith("-")]
    operands = [word for word in arguments if not word.startswith("-")]
    if "--" in arguments:
        operands += arguments[arguments.index("--") + 1:]
    if operands[:1] == ["approve"]:
        return len(operands) == 1
    if operands[:1] == ["enforce"]:
        named = [option.partition("=")[0] for option in options]
        suggest = any(len(option) > 3 and "--suggest".startswith(option) for option in named)
        changes = any(len(option) > 2 and ("--rule".startswith(option) or "--clear".startswith(option))
                      for option in named)
        return suggest and not changes
    return False


_CASE_FOLDING_FS = sys.platform in {"darwin", "win32"}


def _tail(root: Path) -> str:
    """How a protected folder is named relative to Link's root: `wiki/memories`, `.link-cache`."""
    return root.name if root.name.startswith(".") else f"{root.parent.name}/{root.name}"


def _fold(text: str) -> str:
    text = text.replace("\\", "/")
    return text.lower() if _CASE_FOLDING_FS else text


def _names_root(text: str, roots: Iterable[Path], *, tree: bool = False) -> bool:
    """Text Link cannot resolve (`$X/wiki/memories`, `cd "$LR" && rm -rf wiki`) that names a protected folder.

    With `tree`, a path ending in the folder above one (`$X/wiki`) counts too.
    """
    folded = _fold(text)
    for root in roots:
        tail = _fold(_tail(root))
        if tail in folded or (tree and re.search(rf"(?:^|/){re.escape(tail.split('/')[0])}/?$", folded)):
            return True
    return False


def _code_names_link(code: str, roots: Sequence[Path]) -> bool:
    """Code for an interpreter that names Link's files: a protected folder, or Link's root by its path."""
    if _names_root(code, roots):
        return True
    folded = _fold(code)
    home = Path.home()
    for root in roots:
        if root.name != ".link-cache":
            continue
        forms = {root.parent.as_posix(), root.parent.resolve().as_posix()}
        for place in list(forms):
            try:
                relative = Path(place).relative_to(home).as_posix()
            except ValueError:
                continue
            forms |= {f"~/{relative}", f"$HOME/{relative}", f"${{HOME}}/{relative}"}
        if any(re.search(re.escape(_fold(form)) + r"(?![\w.-])", folded) for form in forms):
            return True
    return False


# macOS shows the data volume at / and again at /System/Volumes/Data: a
# firmlink, not a symlink, so resolve() keeps whichever spelling it is given.
_DATA_VOLUME = "/System/Volumes/Data"


def _spelled(path_text: str) -> str:
    """A resolved path in one spelling: Unicode NFC (APFS accepts NFD too), without the macOS firmlink."""
    text = unicodedata.normalize("NFC", path_text)
    if sys.platform == "darwin" and (text == _DATA_VOLUME or text.startswith(_DATA_VOLUME + "/")):
        text = text[len(_DATA_VOLUME):] or "/"
    return text


def _identity(path: Path) -> tuple[int, int] | None:
    """What a file is, whatever path names it: (device, inode). None if it does not exist or has no inode."""
    try:
        info = os.stat(path)
    except (OSError, ValueError):
        return None
    return (info.st_dev, info.st_ino) if info.st_ino else None


def _relative_to(path: Path, root: Path) -> str | None:
    """Where a resolved path lies inside root, judged by file identity: "" for root itself, None if outside.

    Strings miss the same folder named another way (the firmlink, NFD, a
    case the disk ignores). Walking up from the path, or the part of it that
    exists, and comparing each folder's device and inode with root's does not.
    """
    wanted = _identity(root)
    if wanted is None:
        return None
    parts: list[str] = []
    current = path
    while True:
        if _identity(current) == wanted:
            return "/".join(reversed(parts))
        if current.parent == current:
            return None
        parts.append(current.name)
        current = current.parent


def _hard_link_into(path: Path, roots: Iterable[Path]) -> bool:
    """Is an existing file a hard link to one of the protected files? (Writing it writes theirs.)"""
    try:
        info = os.stat(path)
    except (OSError, ValueError):
        return False
    if info.st_nlink < 2 or not info.st_ino or not S_ISREG(info.st_mode):
        return False
    for root in roots:
        try:
            for child in root.rglob("*"):
                if _identity(child) == (info.st_dev, info.st_ino):
                    return True
        except OSError:
            continue
    return False


def _under(path_text: str, roots: Iterable[Path], base: Path | None, *, tree: bool = False) -> bool:
    """Is the path inside one of the roots, or (for `tree`) a folder that contains one?

    Deleting or moving `wiki/` removes `wiki/memories` too, so for a write
    that acts on everything beneath its target an ancestor counts; copying a
    file into `~` or a plain `chmod 700 ~` does not touch Link's files. A path
    Link cannot resolve (a variable it does not know) counts when it names a
    protected folder. macOS and Windows file systems ignore case, so
    `.LINK-CACHE` is `.link-cache` there. Paths are compared as text and by
    file identity, so another spelling of the same folder (the macOS
    /System/Volumes/Data firmlink, a decomposed é) or a hard link to a
    protected file is inside too.
    """
    if "$" in str(path_text) or "`" in str(path_text):
        return _names_root(str(path_text), roots, tree=tree)
    path = Path(os.path.expanduser(str(path_text or "")))
    if not path.is_absolute() and base is not None:
        path = base / path
    try:
        resolved_path = path.resolve()
        resolved = _spelled(str(resolved_path))
    except (OSError, ValueError):  # a NUL in the path, an unreadable link
        return False
    roots = list(roots)
    for root in roots:
        try:
            root_path = root.resolve()
            root_text = _spelled(str(root_path))
        except (OSError, ValueError):
            continue
        if _relative_to(resolved_path, root_path) is not None \
                or (tree and _relative_to(root_path, resolved_path) is not None):
            return True
        mine, theirs = (resolved.lower(), root_text.lower()) if _CASE_FOLDING_FS else (resolved, root_text)
        # Windows paths use "\\" (and accept "/"): compare in the platform's own separator.
        mine, theirs = mine.replace("/", os.sep), theirs.replace("/", os.sep)
        if mine == theirs or mine.startswith(theirs.rstrip(os.sep) + os.sep) \
                or (tree and theirs.startswith(mine.rstrip(os.sep) + os.sep)):
            return True
        if any(ch in mine for ch in "*?["):
            # A wildcard (`Remove-Item .link-cach?`, `rm wiki/mem*`): the root, or a folder above it,
            # matches the pattern, or the part before the first wildcard lies inside the root.
            literal = mine[:min(mine.index(ch) for ch in "*?[" if ch in mine)].rsplit(os.sep, 1)[0]
            ancestors = [theirs, *(str(parent) for parent in Path(theirs).parents)] if tree else [theirs]
            if any(fnmatch.fnmatchcase(candidate, mine) for candidate in ancestors) \
                    or literal == theirs or literal.startswith(theirs.rstrip(os.sep) + os.sep):
                return True
    return _hard_link_into(resolved_path, roots)


def evaluate_tool_call(
    index: Mapping[str, object],
    event: Mapping[str, object],
    *,
    project: str | None = None,
    repo_root: Path | None = None,
    context_path: str | None = None,
    protected: Iterable[Path] = (),
) -> dict[str, object] | None:
    """The decision for a tool call under the reviewed rules, or None to stay out of the way.

    Shell commands are read as the shell will run them (shell_parse): every
    command in a chain, past wrappers and quoting, plus the files they read
    and write, so path rules hold for `cat .env` and `> migrations/x.sql` too.
    While any rule is active, writing Link's own memory files from a tool
    asks first: editing a rule out by hand would skip the review it needs.
    """
    calls = tool_calls(event)
    if not calls:
        return None
    _path_candidates.cache_clear()  # resolved once per call, never carried over to the next
    _resolved.cache_clear()
    # A line built to be slow to read (thousands of paths, `$(` nested hundreds deep) is cut off and
    # reported unreadable well inside the agent's hook timeout, never read past it.
    deadline = time.monotonic() + READ_SECONDS
    commands: list[list[str]] = []
    reads: list[str] = []
    writes: list[str] = []
    trees: set[str] = set()
    code: list[str] = []
    opaque = False
    for kind, value in calls:
        if kind in {"command", "powershell"}:
            reading = read_powershell(value, deadline=deadline) if kind == "powershell" \
                else read_shell(value, deadline=deadline)
            if kind == "command" and looks_like_powershell(value):
                # A shell tool on Windows may run PowerShell: read it that way too.
                other = read_powershell(value, deadline=deadline)
                reading.commands += [words for words in other.commands if words not in reading.commands]
                reading.reads += other.reads
                reading.writes += other.writes
                reading.trees += other.trees
                reading.code += other.code
                reading.opaque = reading.opaque or other.opaque
            commands += reading.commands
            reads += reading.reads
            writes += reading.writes
            trees.update(reading.trees)
            code += reading.code
            opaque = opaque or reading.opaque
        elif kind == "read":
            reads.append(value)
        else:
            writes.append(value)
    base = Path(context_path) if context_path else None
    rule_values = index.get("rules")
    rules = [rule for rule in (rule_values if isinstance(rule_values, list) else []) if isinstance(rule, dict)]
    # Each command's forms and each path once, however many rules there are or times a line repeats them.
    forms = list(dict.fromkeys(" ".join(form) for words in commands for form in command_forms(words)))
    reads, writes = list(dict.fromkeys(reads)), list(dict.fromkeys(writes))

    def in_time() -> bool:
        nonlocal opaque
        if time.monotonic() <= deadline:
            return True
        opaque = True  # not finished in time: what was left unchecked waits for the person
        return False

    matches: list[Mapping[str, object]] = []
    for rule in rules:
        if not _rule_applies(rule, project, context_path):
            continue
        rule_kind = str(rule.get("kind") or "")
        pattern = str(rule.get("pattern") or "")
        hit = False
        if rule_kind == "command":
            wanted = " ".join(pattern.split())
            hit = any(fnmatch.fnmatchcase(form, wanted) for form in forms)
        elif rule_kind in {"write", "read"}:
            targets = writes if rule_kind == "write" else reads
            hit = any(in_time() and _path_matches(pattern, target, repo_root, base, tree=target in trees)
                      for target in targets)
        if hit:
            matches.append(rule)
    # Changing Link's own rules or files is checked whatever else the call
    # does, and wins: an approval for one part of a call must never carry a
    # rule change or a memory edit through with it.
    roots = list(protected)
    guards: list[Mapping[str, object]] = []
    if rules and any(is_link_governance(words) for words in commands):
        guards.append({
            "name": "link-governance", "title": "Only the person approves, clears or retires rules",
            "action": "ask", "kind": "command", "pattern": "lnk review-memory|enforce|archive-memory|approve|...",
        })
    # A path Link resolved, under its files, is a definite write; a path through a variable it cannot
    # know that names them (`cp x "$PROJ/wiki/memories/"`), or code that names them (`python3 -c "...
    # open('~/link/.link-cache/hook-index.json')"`), may be nothing of the kind, so the person can let
    # that through once.
    resolved = [target for target in writes if "$" not in target and "`" not in target]
    unresolved = [target for target in writes if "$" in target or "`" in target]
    if rules and roots and any(in_time() and _under(target, roots, base, tree=target in trees) for target in resolved):
        guards.append({
            "name": "link-memory-files", "title": "Link memory and approval files change only through Link",
            "action": "ask", "kind": "write", "pattern": "<Link memories and .link-cache>/**",
        })
    # A command Link cannot read (`eval "$c"`, an encoded PowerShell command)
    # might touch anything, so it waits for the person - but it is everyday
    # shell too (`eval "$(ssh-agent -s)"`), so the person can let it through
    # once, having seen exactly what it is.
    unreadable: list[Mapping[str, object]] = []
    if rules and roots and not guards and (
            any(_under(target, roots, base, tree=target in trees) for target in unresolved)
            or any(_code_names_link(text, roots) for text in code)):
        unreadable.append({
            "name": "link-unclear-write", "title": "A call that may change Link's files waits for the person",
            "action": "ask", "kind": "write", "pattern": "<a variable or code naming Link's files>",
        })
    if rules and roots and opaque and not guards and not unreadable:
        unreadable.append({
            "name": "link-unreadable-command", "title": "A command Link cannot read waits for the person",
            "action": "ask", "kind": "command", "pattern": "<eval or an encoded command>",
        })
    if not matches and not guards and not unreadable:
        return None
    every = [*guards, *unreadable, *matches]
    decision = "deny" if any(rule.get("action") == "deny" for rule in every) else "ask"
    # The reason cites what decided: a guard, else a user's deny rule over an unreadable call's ask.
    cited = unreadable if decision == "ask" or not matches else []
    first = (guards or cited or [next((rule for rule in matches if rule.get("action") == decision), matches[0])])[0]
    names = sorted({str(rule.get("name") or "") for rule in matches})
    rule_kind = str(first.get("kind") or calls[0][0])
    verb = "blocked" if decision == "deny" else "needs the person's OK"
    reason = (
        f"Link: this {rule_kind} {verb} under a reviewed memory - \"{first.get('title')}\" ({first.get('name')}), "
        f"rule \"{first.get('action')} {rule_kind}: {first.get('pattern')}\"."
    )
    if decision == "ask":
        reason += " If the person approves, go ahead; otherwise follow the memory."
    else:
        reason += " Do not work around it; tell the person, who can edit the memory if it no longer holds."
    return {
        "decision": decision, "reason": reason, "memories": names, "kind": rule_kind,
        "calls": sorted(calls), "content": call_content(event), "binding": call_binding(event),
        "title": str(first.get("title") or ""),
        "rule": f"{first.get('action')} {rule_kind}: {first.get('pattern')}",
        # Only a user's ask rule can be let through once; a governance or
        # Link-file guard is for the person to do themselves.
        "approvable": decision == "ask" and not guards,
        "governance": bool(guards),
    }


def anchored_reminders(
    index: Mapping[str, object],
    file_path: str,
    *,
    repo_root: Path | None,
    identity: set[str],
    project: str | None = None,
    already_shown: Iterable[str] = (),
) -> list[dict[str, object]]:
    """Memories anchored to the touched file whose symbol is still in it."""
    from .provenance import MAX_FILE_BYTES, locate

    shown = set(already_shown)
    raw = str(file_path or "").strip()
    if not raw:
        return []
    rel = ""
    if repo_root is not None:
        try:
            rel = Path(raw).resolve().relative_to(repo_root.resolve()).as_posix()
        except (OSError, ValueError):
            rel = ""
    picked: list[dict[str, object]] = []
    anchors = index.get("anchors") if isinstance(index.get("anchors"), dict) else {}
    assert isinstance(anchors, dict)
    lines: list[str] | None = None
    for entry in anchors.get(rel, []) if rel else []:
        name = str(entry.get("name") or "")
        repo = str(entry.get("repo") or "")
        if name in shown or not _applies_to_project(entry, project):
            continue
        if not any(root.startswith(repo) or repo.startswith(root) for root in identity):
            continue  # another repository's anchor
        if lines is None:
            try:
                path = Path(raw)
                lines = [] if path.stat().st_size > MAX_FILE_BYTES else path.read_text(
                    encoding="utf-8", errors="replace").splitlines()
            except OSError:
                lines = []
        symbol = str(entry.get("symbol") or "")
        if not lines or locate(lines, symbol) is None:
            continue  # the anchored symbol is gone: possibly stale, never pushed
        picked.append(dict(entry))
        shown.add(name)
    return picked[:MAX_TOUCH_REMINDERS]


def new_delivery_id() -> str:
    import secrets

    return secrets.token_hex(3)


def delivery_open(delivery_id: str) -> str:
    return f"(link:{delivery_id})"


def delivery_close(delivery_id: str) -> str:
    return f"(link:{delivery_id} end)"


def wrap_for_delivery(text: str, delivery_id: str, *, budget: int = HOOK_OUTPUT_BUDGET) -> tuple[str, bool]:
    """Wrap injected text in its delivery tokens, cut to the hook budget at a line.

    Returns (text, cut). A cut says so in the text itself: silently losing the
    end of a brief is the failure this exists to catch.
    """
    opening = delivery_open(delivery_id)
    closing = delivery_close(delivery_id)
    body = text.rstrip()
    cut = False
    room = budget - len(opening) - len(closing) - 200
    if len(body) > room:
        body = body[:room].rsplit("\n", 1)[0].rstrip()
        body += "\n\n(Link: this was shortened to fit the agent's hook limit; run `lnk brief` for the rest.)"
        cut = True
    # The opening token ends the first line, so what the agent reads first
    # (a waiting handoff, the brief's header) stays exactly as written.
    first, _, rest = body.partition("\n")
    return f"{first} {opening}\n{rest}\n{closing}" if rest else f"{first} {opening}\n{closing}", cut


def render_touch_text(entries: Sequence[Mapping[str, object]], file_label: str, delivery_id: str) -> str:
    lines = [f"Link memory for {file_label} (reviewed; follow unless the person says otherwise):"]
    for entry in entries:
        claim = " ".join(str(entry.get("claim") or entry.get("title") or "").split())
        lines.append(f"- {claim[:220]} ({entry.get('name')})")
    text, _ = wrap_for_delivery("\n".join(lines), delivery_id)
    return text


def verify_deliveries(transcript_text: str, delivery_ids: Iterable[str]) -> dict[str, str]:
    """delivered / truncated / missing for each id, from the session transcript."""
    results: dict[str, str] = {}
    for delivery_id in delivery_ids:
        opened = delivery_open(delivery_id) in transcript_text
        closed = delivery_close(delivery_id) in transcript_text
        results[delivery_id] = "delivered" if opened and closed else ("truncated" if opened else "missing")
    return results


def shown_state_path(link_root: Path) -> Path:
    return link_root / ".link-cache" / "touch-shown.json"


def load_shown(link_root: Path, session_id: str) -> set[str]:
    try:
        payload = json.loads(shown_state_path(link_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    names = payload.get(session_id) if isinstance(payload, dict) else None
    return {str(name) for name in names} if isinstance(names, list) else set()


def remember_shown(link_root: Path, session_id: str, names: Iterable[str], *, keep_sessions: int = 20) -> None:
    path = shown_state_path(link_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            payload = {}
    except (OSError, ValueError):
        payload = {}
    current = [str(name) for name in payload.pop(session_id, [])] if isinstance(payload.get(session_id), list) \
        else []
    for name in names:
        if name not in current:
            current.append(name)
    payload[session_id] = current
    # Newest sessions last; drop the oldest beyond the window.
    while len(payload) > keep_sessions:
        payload.pop(next(iter(payload)))
    try:
        from .files import atomic_write_json

        atomic_write_json(path, payload)
    except OSError:
        pass


def find_repo_root(start: Path) -> Path | None:
    """The enclosing git checkout, found by walking up to `.git` (no subprocess)."""
    try:
        current = start.expanduser().resolve()
    except OSError:
        return None
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def cached_repo_identity(link_root: Path, repo_root: Path) -> set[str]:
    """Root commits of a checkout, cached: they never change, and git costs a process."""
    from .staleness import repo_identity

    path = link_root / ".link-cache" / "repo-identity.json"
    key = str(repo_root.resolve())
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, ValueError):
        cache = {}
    known = cache.get(key)
    if isinstance(known, list) and known:
        return {str(item) for item in known}
    roots = repo_identity(repo_root)
    if roots:
        cache[key] = sorted(roots)
        try:
            from .files import atomic_write_json

            atomic_write_json(path, cache)
        except OSError:
            pass
    return roots


# --- The pre-tool and post-tool hooks -------------------------------------
# Both fire around every shell command and file access, so they run from
# here: link.py hands `hook pre-tool|post-tool` to fast_tool_hook before the
# rest of the CLI loads, which is most of what a hook call used to cost.

TOOL_HOOK_EVENTS = ("pre-tool", "post-tool")


def read_hook_event(stream: object) -> dict[str, object]:
    """The agent's hook event JSON from stdin, or {} when none was piped in."""
    if stream is None or getattr(stream, "isatty", lambda: True)():
        return {}
    try:
        raw = stream.read()  # type: ignore[attr-defined]
    except OSError:
        return {}
    if not str(raw).strip():
        return {}
    try:
        payload = json.loads(raw)
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def hook_project_dir(event: Mapping[str, object], environ: Mapping[str, str] | None = None) -> str:
    """The project directory the hook fired in, across agent schemas.

    Claude Code, Codex, Gemini and Copilot send `cwd`; Cursor sends
    `workspace_roots`; Windsurf puts `cwd` in `tool_info`; Antigravity sends
    `workspacePaths` and a command's `Cwd`; Devin sets DEVIN_PROJECT_DIR.
    Without it, project rules and path fences cannot apply.
    """
    env = os.environ if environ is None else environ
    info = event.get("tool_info") if isinstance(event.get("tool_info"), dict) else {}
    call = event.get("toolCall") if isinstance(event.get("toolCall"), dict) else {}
    args = call.get("args") if isinstance(call, dict) and isinstance(call.get("args"), dict) else {}
    candidates: list[object] = [event.get("cwd"), info.get("cwd") if isinstance(info, dict) else None,
                                args.get("Cwd") if isinstance(args, dict) else None]
    for key in ("workspace_roots", "workspacePaths"):
        roots = event.get(key)
        if isinstance(roots, list) and roots:
            candidates.append(roots[0])
    candidates += [env.get("DEVIN_PROJECT_DIR"), env.get("CLAUDE_PROJECT_DIR")]
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def hook_project(event: Mapping[str, object], project: str | None) -> str:
    """The project the agent is working in: its repository's, wherever in it the cwd is.

    Tool hooks fire with the agent's current directory, which follows every
    `cd`; naming the project from that directory alone left project rules
    unscoped in any subdirectory.
    """
    if project:
        return project
    project_dir = hook_project_dir(event)
    if not project_dir:
        return ""
    repo_root = find_repo_root(Path(project_dir))
    return default_project_for_target(repo_root) if repo_root else ""


def _target_dir(event: Mapping[str, object]) -> str:
    """With no directory in the payload, the folder of the first absolute file the call names."""
    for kind, value in tool_calls(event):
        if kind in {"read", "write"} and Path(os.path.expanduser(value)).is_absolute():
            return str(Path(os.path.expanduser(value)).parent)
    return ""


def _workspace(target: Path) -> tuple[Path, Path]:
    """(wiki directory, Link root) for a hook target that names either."""
    target = target.expanduser().resolve()
    if target.name == "wiki" and (target / "index.md").exists():
        return target, target.parent
    return target / "wiki", target


def _event_session(event: Mapping[str, object]) -> str:
    """The session or conversation id, whichever key this agent uses."""
    for key in ("session_id", "conversation_id", "sessionId", "trajectory_id", "conversationId"):
        value = event.get(key)
        if value:
            return str(value)
    return ""


def _cursor_runs_link_itself(home: Path | None = None) -> bool:
    """Has Link installed its own Cursor hooks (so Cursor's copy of Claude's can stand down)?"""
    try:
        text = ((home or Path.home()) / ".cursor" / "hooks.json").read_text(encoding="utf-8")
    except OSError:
        return False
    return " hook pre-tool " in text and ("link.py" in text or "link_hook.py" in text or "lnk" in text)


def pre_tool_reply(target: Path, event: Mapping[str, object], *, project: str | None, emit: str,
                   environ: Mapping[str, str] | None = None) -> HookReply:
    """The pre-tool hook's answer to its agent under the reviewed rules.

    An `ask` on an agent that cannot ask (tool_events.can_ask) is held:
    blocked with a request the person can approve once (approvals.py); the
    same call repeated after that goes through.
    """
    actual = native_emit(emit, event, os.environ if environ is None else environ)
    if actual == "cursor" and emit == "text" and _cursor_runs_link_itself():
        # Cursor also runs Claude Code's hooks; Link's own Cursor hook answers this call.
        return render_reply(None, actual, event)
    emit = actual
    wiki_dir, root = _workspace(target)
    if not wiki_dir.exists():
        return render_reply(None, emit, event)
    index = load_hook_index(wiki_dir, root)
    if not index.get("rules"):
        return render_reply(None, emit, event)
    project_dir, project_name = hook_project_dir(event), project or ""
    try:
        project_dir = project_dir or _target_dir(event)
        repo_root = find_repo_root(Path(project_dir)) if project_dir else None
        project_name = project or (default_project_for_target(repo_root) if repo_root else "")
        decision = evaluate_tool_call(
            index, event, project=project_name, repo_root=repo_root, context_path=project_dir or None,
            protected=[wiki_dir / "memories", root / ".link-cache"],
        )
    except Exception as exc:  # with rules in force, a call Link failed to read is not let through unseen
        print(f"Link pre-tool hook could not read this call: {exc}", file=sys.stderr)
        decision = _unreadable_call(event)
    if decision is None:
        return render_reply(None, emit, event)
    session = _event_session(event)
    verdict = str(decision["decision"])
    memories = decision.get("memories")
    if verdict == "ask" and not can_ask(emit, event):
        decision, verdict = _hold(decision, root, project_dir, emit, session)
    try:
        from .usage import record_retrieval

        record_retrieval(
            root, "enforce", [str(name) for name in memories] if isinstance(memories, list) else [],
            project=project_name, surface="hook", session=session, decision=verdict,
        )
    except Exception as exc:  # a receipt that cannot be written must not undo the decision
        print(f"Link could not record this decision: {exc}", file=sys.stderr)
    return render_reply(None if verdict == "approved" else decision, emit, event)


def _unreadable_call(event: Mapping[str, object]) -> dict[str, object]:
    """The decision for a call whose reading failed while rules are in force.

    It waits for the person, who can let it through once having seen it; if
    Link cannot even say what the call is, it is blocked.
    """
    title = "Link could not read this call"
    try:
        calls = sorted(tool_calls(event))
        content = call_content(event)
    except Exception:
        calls, content = [], ""
    reason = f"Link: this call needs the person's OK - \"{title}\" (link-unreadable-call), so no rule was checked."
    if not calls:
        return {
            "decision": "deny", "memories": [], "kind": "command", "calls": [], "content": "", "title": title,
            "reason": reason.replace("needs the person's OK", "is blocked") + " Tell the person what you meant to run.",
            "rule": "deny command: <a call Link could not read>", "approvable": False, "governance": False,
        }
    return {
        "decision": "ask", "reason": reason + " If the person approves, go ahead; otherwise do not run it.",
        "memories": [], "kind": calls[0][0], "calls": calls, "content": content, "title": title,
        "rule": "ask command: <a call Link could not read>", "approvable": True, "governance": False,
    }


def _hold(decision: Mapping[str, object], root: Path, cwd: str, emit: str,
          session: str) -> tuple[dict[str, object], str]:
    """An ask on an agent that cannot ask: let a call the person approved through once, else hold it.

    Fails closed: if the approvals file cannot be read or written, the call
    is held without a way through rather than let past the rule.
    """
    from . import approvals

    held = dict(decision)
    reason = str(decision["reason"])
    if not decision.get("approvable"):
        held.update(decision="deny", reason=approvals.self_only_reason(reason))
        return held, "deny"
    raw_calls = decision.get("calls")
    calls = [(str(call[0]), str(call[1])) for call in raw_calls if isinstance(call, (list, tuple)) and len(call) == 2] \
        if isinstance(raw_calls, list) else []
    content = str(decision.get("content") or "")
    try:
        key = approvals.call_key(calls, cwd, str(decision.get("binding") or ""))
        if approvals.take_grant(root, key, hook=emit):
            return held, "approved"
        request_id = approvals.request(
            root, key, display=approvals.call_display(calls, cwd, content), title=str(decision.get("title") or ""),
            rule=str(decision.get("rule") or ""), agent=emit, session=session,
        )
        held.update(decision="deny", reason=approvals.held_reason(reason, request_id, root))
    except Exception:  # a broken approvals file must not open the rule
        held.update(decision="deny", reason=approvals.self_only_reason(reason)
                    + " (Link could not record a request for the person to approve.)")
    return held, "held"


def pre_tool_output(target: Path, event: Mapping[str, object], *, project: str | None, emit: str) -> str:
    """What the pre-tool hook prints for agents that read stdout (kept for the CLI path)."""
    return pre_tool_reply(target, event, project=project, emit=emit).stdout


def post_tool_output(target: Path, event: Mapping[str, object], *, project: str | None) -> str:
    """What the post-tool hook prints: reviewed memories anchored to the file just read or edited."""
    files = [value for kind, value in tool_calls(event) if kind in {"read", "write"}]
    if not files:
        return ""
    file_path = Path(files[0]).expanduser()
    if not file_path.is_absolute():
        file_path = Path(hook_project_dir(event) or ".") / file_path
    wiki_dir, root = _workspace(target)
    if not wiki_dir.exists():
        return ""
    index = load_hook_index(wiki_dir, root)
    anchors = index.get("anchors") if isinstance(index.get("anchors"), dict) else {}
    if not anchors:
        return ""
    repo_root = find_repo_root(file_path)
    if repo_root is None:
        return ""
    try:
        rel = file_path.resolve().relative_to(repo_root.resolve()).as_posix()
    except (OSError, ValueError):
        return ""
    if rel not in anchors:  # type: ignore[operator]
        return ""  # the common case, decided before any git call
    session = str(event.get("session_id") or "")
    project_name = hook_project(event, project)
    entries = anchored_reminders(
        index, str(file_path), repo_root=repo_root, identity=cached_repo_identity(root, repo_root),
        project=project_name, already_shown=load_shown(root, session) if session else (),
    )
    if not entries:
        return ""
    names = [str(entry.get("name") or "") for entry in entries]
    delivery_id = new_delivery_id()
    if session:
        remember_shown(root, session, names)
    from .usage import record_retrieval

    record_retrieval(root, "touch", names, project=project_name, surface="hook", session=session, delivery=delivery_id)
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": render_touch_text(entries, rel, delivery_id),
    }})


def fast_tool_hook(argv: list[str]) -> int | None:
    """Run `hook pre-tool|post-tool [target] [--emit E] [--project P]` without the CLI.

    Returns None, before reading stdin, for anything it does not recognise,
    so the full CLI handles it. Like every hook, it never breaks the agent's
    tool call: an error is reported on stderr and the call goes ahead -
    except that a call Link fails to read while rules are in force waits for
    the person (pre_tool_reply).
    """
    if not argv or argv[0] not in TOOL_HOOK_EVENTS:
        return None
    event_name, rest = argv[0], argv[1:]
    target = "."
    seen_target = False
    emit = "text"
    project: str | None = None
    index = 0
    while index < len(rest):
        arg = rest[index]
        if arg in {"--emit", "--project"} and index + 1 < len(rest):
            if arg == "--emit":
                emit = rest[index + 1]
            else:
                project = rest[index + 1]
            index += 2
            continue
        if arg.startswith("-") or seen_target:
            return None
        target, seen_target = arg, True
        index += 1
    if emit not in EMITS:
        return None
    event = read_hook_event(sys.stdin)
    try:
        if event_name == "pre-tool":
            reply = pre_tool_reply(Path(target), event, project=project, emit=emit)
        else:
            reply = HookReply(post_tool_output(Path(target), event, project=project))
    except Exception as exc:  # a hook must never break the agent's tool call
        print(f"Link {event_name} hook failed: {exc}", file=sys.stderr)
        reply = render_reply(None, emit, event) if event_name == "pre-tool" else HookReply()
        if reply.stdout:
            print(reply.stdout)
        return 0
    return emit_reply(reply)


def emit_reply(reply: HookReply) -> int:
    """Print a hook reply the way its agent reads it; returns the exit code."""
    if reply.stdout:
        print(reply.stdout)
    if reply.stderr:
        print(reply.stderr, file=sys.stderr)
    return reply.exit_code
