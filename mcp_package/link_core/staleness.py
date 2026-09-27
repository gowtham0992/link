"""Notice when a memory has outlived the code it describes.

The most common complaint about agent memory is that nobody can tell when a
memory stopped being true. A note says a thing lives in `a/b.py`, the file is
renamed, and the memory keeps being retrieved and believed. Hosted memory
services cannot fix this: they never see the repository. A local tool sitting
beside the checkout can.

The signal used here is deliberately narrow. A memory is only questioned when
it names a repository path that

1. does not exist now, and
2. did exist at some point in git history.

Both halves matter. Without (2) an unresolvable path is just prose - "put it
in config/settings.py" written before that file was ever created - and
flagging it would be noise. With (2) the path was real and is gone, which is
about as close to proof of staleness as a heuristic gets.

Version 2 applies the same rule to more than file paths. A memory can
name a package script (`npm run build`), a make target, a dependency, an
environment variable or a URL. Each is questioned only when the repository
shows it once had the thing and no longer does: the script was in
package.json and is gone, the variable was referenced in tracked files and
no tracked file mentions it now. Two contradictions are checked directly
against files the repository checks in, because they are deterministic: a
memory naming a runtime version the manifests no longer allow ("we use
Python 3.10" when pyproject requires >=3.12), and a memory naming a package
manager whose lockfile was replaced by another manager's.

A verdict of `verified` needs evidence: at least one thing the memory
names was found holding in this repository. Naming things the repository
never had proves nothing either way, so such a memory is `unverifiable`.
Claims framed as history or as something not to do ("we dropped Python
3.9", "do not use npm here") are not checked as present-tense claims.

Nothing here rewrites or deletes a memory. Findings are routed to the same
review gate every other change goes through, because a flag that acts on its
own is a flag people learn to fear, and a flag that fires loosely is one they
learn to ignore. Silence is the normal output.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from collections.abc import Callable, Iterable
from pathlib import Path

# Scope is source, config, and documentation. Binary assets are left out on
# purpose: documentation names image files constantly, so they are mostly
# false-flag surface, and a moved logo rarely makes a memory wrong.
#
# Two shapes are recognised: anything with a directory separator, and bare
# filenames carrying a source-code extension. Extraction can afford to be
# generous because it is not the precision gate - git history is. A word that
# merely looks like a filename was never tracked, so it is never flagged.
_CODE_SUFFIXES = (
    "py|js|mjs|cjs|ts|tsx|jsx|go|rs|rb|java|kt|swift|c|h|cc|cpp|hpp|cs|php|"
    "sh|bash|zsh|ps1|sql|toml|yml|yaml|json|ini|cfg|md|rst|txt|lock|gradle"
)
_PATH_REFERENCE = re.compile(
    r"(?<![\w./-])("
    r"(?:[\w.-]+/)+[\w-]+(?:\.[\w-]+)*\.[A-Za-z0-9]{1,8}"  # has a directory part (multi-dot names too)
    r"|[\w-]+\.(?:" + _CODE_SUFFIXES + r")"              # bare source filename
    r")(?![\w/])"
)

# Paths inside the memory store itself are not code and move for their own
# reasons; questioning a memory because a wiki page was renamed is noise.
_IGNORED_PREFIXES = ("wiki/", "raw/", ".link-cache/", ".git/")

MAX_PATH_LOOKUPS = 12


def safe_relative_path(path: str) -> bool:
    """A repository-relative path that cannot point outside the checkout."""
    text = str(path or "").replace("\\", "/")
    if not text or text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        return False
    return ".." not in text.split("/")


def repo_path_references(text: str) -> list[str]:
    """Repository-looking paths named by a memory, in first-seen order."""
    seen: list[str] = []
    # Memories written on Windows name paths with backslashes. Git and the
    # repository itself use forward slashes, so normalise before matching -
    # otherwise every Windows user's references would silently go unchecked.
    normalised = (text or "").replace("\\", "/")
    for match in _PATH_REFERENCE.finditer(normalised):
        candidate = match.group(1)
        if candidate.startswith("./"):
            candidate = candidate[2:]
        if candidate.startswith(_IGNORED_PREFIXES) or candidate in seen or not safe_relative_path(candidate):
            continue
        seen.append(candidate)
    return seen


def _git(repo_root: Path, arguments: list[str], runner: Callable[..., object] | None = None,
         timeout: float = 10) -> str:
    """Run one read-only git command, returning "" when git cannot answer."""
    # stdin is closed on purpose. Inside the MCP server, stdin is the stdio
    # transport; a child that inherits it hangs on Windows until its timeout,
    # which made every recall there time out.
    if runner is not None:
        return str(runner(repo_root, arguments) or "")
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=str(repo_root),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout


def path_was_known(repo_root: Path, path: str, runner: Callable[..., object] | None = None) -> bool:
    """True when git has ever tracked this path."""
    output = _git(repo_root, ["log", "--all", "--oneline", "-1", "--", path], runner)
    return bool(output.strip())


def repo_toplevel(start: Path) -> Path | None:
    """The checkout containing `start`, or None outside git."""
    output = _git(Path(start).expanduser(), ["rev-parse", "--show-toplevel"]).strip()
    return Path(output) if output else None


def repo_identity(repo_root: Path, runner: Callable[..., object] | None = None) -> set[str]:
    """Root commits of the repository: the same in every clone, empty before the first commit.

    A checkout path is not an identity (clones move, two clones of one
    project are the same code), and a remote URL is optional. The root
    commit is what makes this history this repository's.
    """
    output = _git(Path(repo_root).expanduser(), ["rev-list", "--max-parents=0", "HEAD"], runner)
    return {line.strip()[:12] for line in output.splitlines() if line.strip()}


# Renames are read in one pass rather than one call per path. Asking git for
# a rename by the *old* path returns nothing - history simplification hides
# the commit - so the rename records are listed once and matched in memory.
RENAME_SCAN_COMMITS = 400


def rename_map(repo_root: Path, runner: Callable[..., object] | None = None) -> dict[str, str]:
    """Old path -> new path, for renames git recorded recently."""
    output = _git(
        repo_root,
        ["log", "--all", "--diff-filter=R", "--name-status", "--format=", "-n", str(RENAME_SCAN_COMMITS)],
        runner,
    )
    moves: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].startswith("R"):
            moves.setdefault(parts[1], parts[2])
    return moves


# Pickaxe searches are bounded to recent history: a symbol removed years
# ago is not what makes a memory wrong today, and an unbounded scan on a
# large repository is slow for every symbol that was never there.
HISTORY_WINDOW = "3 years ago"
# Recall runs these checks while an agent waits. It gets a total budget; a
# memory whose checks did not finish in time is `unverifiable`, never
# `verified`, and never flagged on partial evidence.
RECALL_BUDGET_SECONDS = 1.5
CACHE_SCHEMA = "link-staleness-cache-v1"
# A history lookup that ran out of time on the recall path is remembered as
# such for this HEAD, so the next recall skips it instead of paying the
# budget again. An unbudgeted run (`lnk stale`) recomputes it for real.
_TIMED_OUT = "\x00timed-out"
CACHE_MAX_REPOS = 8
CACHE_MAX_ENTRIES = 2000


class _Repo:
    """One repository's git answers: toplevel, time budget, history cache.

    History answers (was this path ever tracked, when did this token last
    change) depend only on commits, so they are cached per HEAD - in memory
    for one process, and in `cache_path` across processes when given, so a
    repeated `lnk query` does not re-scan history. Present-tense answers read
    the working tree and are never cached.
    """

    def __init__(self, root: Path, *, runner: Callable[..., object] | None = None,
                 budget_seconds: float | None = None, cache_path: Path | None = None) -> None:
        self.runner = runner
        start = Path(root).expanduser()
        top = None if runner is not None else repo_toplevel(start)
        self.is_repo = runner is not None or top is not None
        self.root = top or start
        self._deadline = time.monotonic() + budget_seconds if budget_seconds else None
        # Counts answers that are unknown for lack of time. A verdict that
        # saw one cannot be `verified`: the missing answer might have been "gone".
        self.incomplete = 0
        self._cache_path = cache_path
        self._head: str | None = None
        self._history: dict[str, str] | None = None
        self._dirty = False
        self.timed_out = False

    def git(self, arguments: list[str]) -> str | None:
        """git output, or None once the budget is spent."""
        timeout = 10.0
        if self._deadline is not None:
            remaining = self._deadline - time.monotonic()
            if remaining <= 0.05:
                self.incomplete += 1
                return None
            timeout = max(0.1, min(timeout, remaining))
        started = time.monotonic()
        output = _git(self.root, arguments, self.runner, timeout=timeout)
        if self._deadline is not None and not output and time.monotonic() - started >= timeout - 0.05:
            self.incomplete += 1  # timed out: the answer is unknown, not "no"
            self.timed_out = True
            return None
        return output

    def head(self) -> str:
        if self._head is None:
            self._head = (self.git(["rev-parse", "--short=12", "HEAD"]) or "").strip()
        return self._head

    def _history_cache(self) -> dict[str, str]:
        if self._history is None:
            self._history = {}
            if self._cache_path is not None and self.head():
                try:
                    data = json.loads(self._cache_path.read_text(encoding="utf-8"))
                    repo = (data.get("repos") or {}).get(str(self.root)) or {}
                    if data.get("schema") == CACHE_SCHEMA and repo.get("head") == self.head():
                        entries = repo.get("entries")
                        if isinstance(entries, dict):
                            self._history = {str(k): str(v) for k, v in entries.items()}
                except (OSError, ValueError, AttributeError):
                    pass
        return self._history

    def history(self, key: str, arguments: list[str]) -> str | None:
        """A cached history answer ("" means git found nothing), or None if out of time."""
        cache = self._history_cache()
        if key in cache and not (cache[key] == _TIMED_OUT and self._deadline is None):
            if cache[key] == _TIMED_OUT:
                self.incomplete += 1
                return None
            return cache[key]
        self.timed_out = False
        output = self.git(arguments)
        if output is None:
            if self.timed_out:
                cache[key] = _TIMED_OUT
                self._dirty = True
            return None
        cache[key] = output.strip().splitlines()[0] if output.strip() else ""
        self._dirty = True
        return cache[key]

    def save(self) -> None:
        if not self._dirty or self._cache_path is None or not self.head():
            return
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            repos = data.get("repos") if data.get("schema") == CACHE_SCHEMA else None
        except (OSError, ValueError, AttributeError):
            repos = None
        repos = dict(repos or {})
        repos.pop(str(self.root), None)
        entries = dict(list((self._history or {}).items())[-CACHE_MAX_ENTRIES:])
        repos[str(self.root)] = {"head": self.head(), "entries": entries}
        while len(repos) > CACHE_MAX_REPOS:
            repos.pop(next(iter(repos)))
        try:
            from .files import atomic_write_text

            atomic_write_text(self._cache_path, json.dumps({"schema": CACHE_SCHEMA, "repos": repos}) + "\n")
            self._dirty = False
        except OSError:
            pass


_ERE_SPECIAL = set(".[]{}()*+?^$|\\")


def _ere_escape(text: str) -> str:
    """Escape for POSIX ERE (git -E): only ERE metacharacters, never `-` or `:`."""
    return "".join("\\" + char if char in _ERE_SPECIAL else char for char in text)


def _ere_word(needle: str, *, fold: bool = False) -> str:
    """A POSIX ERE matching `needle` as a whole word, for `git log -E -G`.

    With `fold`, letters match either case and -, _ and . match each other,
    the way package indexes compare distribution names.
    """
    parts: list[str] = []
    for char in needle:
        if fold and char.isalpha():
            parts.append(f"[{char.lower()}{char.upper()}]")
        elif fold and char in "-_.":
            parts.append("[-_.]")
        else:
            parts.append(_ere_escape(char))
    return f"(^|[^[:alnum:]_-]){''.join(parts)}([^[:alnum:]_-]|$)"


class StalenessChecker:
    """Check many memories against one repository without repeating git work.

    Each distinct path is resolved against git once, and the rename map is
    read once, no matter how many memories mention them. Fifty memories that
    all cite the same moved file cost one lookup, not fifty.
    """

    def __init__(self, repo_root: Path, *, runner: Callable[..., object] | None = None,
                 limit: int = MAX_PATH_LOOKUPS, budget_seconds: float | None = None,
                 cache_path: Path | None = None) -> None:
        self._repo = _Repo(repo_root, runner=runner, budget_seconds=budget_seconds, cache_path=cache_path)
        self.root = self._repo.root
        self._runner = runner
        self._limit = limit
        self._known: dict[str, bool] = {}
        self._moves: dict[str, str] | None = None
        self._symbols = SymbolChecker(self.root, runner=runner, limit=limit, repo=self._repo)
        self._identity: set[str] | None = None

    @property
    def is_repo(self) -> bool:
        return self._repo.is_repo

    def save_cache(self) -> None:
        self._repo.save()

    def _was_known(self, path: str) -> bool | None:
        if path not in self._known:
            output = self._repo.history(f"path:{path}", ["log", "--all", "--oneline", "-1", "--", path])
            if output is None:
                return None
            self._known[path] = bool(output)
        return self._known[path]

    def _successor(self, path: str) -> str:
        if self._moves is None:
            self._moves = rename_map(self.root, self._runner)
        return self._moves.get(path, "")

    def findings(self, text: str) -> list[dict[str, str]]:
        """What this text names that the repository once had and no longer does.

        An empty list is the expected result. A finding says only that the
        text refers to something that moved; a person decides what to do.
        Paths first (v1), then scripts, targets, dependencies, variables,
        URLs, and version or package-manager contradictions (v2).
        """
        return self._evaluate(text, None)[0]

    def _evaluate(self, text: str, anchors: list[str] | None) -> tuple[list[dict[str, str]], int]:
        """(findings, how many named things were confirmed to hold)."""
        findings, confirmed = self._paths(text)
        more, held = self._symbols.evaluate(text)
        findings.extend(more)
        confirmed += held
        if anchors:
            more, held = self._anchors(anchors)
            findings.extend(more)
            confirmed += held
        return findings, confirmed

    def _paths(self, text: str) -> tuple[list[dict[str, str]], int]:
        results: list[dict[str, str]] = []
        confirmed = 0
        for candidate in repo_path_references(text)[: self._limit]:
            if (self.root / candidate).exists():
                confirmed += 1
                continue
            if not self._was_known(candidate):
                continue  # never in the repository (or out of time): prose, not a stale reference
            successor = self._successor(candidate)
            results.append({
                "kind": "path",
                "path": candidate,
                "reference": candidate,
                "reason": "renamed" if successor else "removed",
                "successor": successor,
            })
        return results, confirmed

    def path_findings(self, text: str) -> list[dict[str, str]]:
        """v1: repository paths git once tracked that are gone now."""
        return self._paths(text)[0]

    def _anchors(self, anchors: Iterable[str]) -> tuple[list[dict[str, str]], int]:
        from .provenance import verify_anchors  # provenance imports this module

        if self._identity is None:
            self._identity = repo_identity(self.root, self._runner)
        findings: list[dict[str, str]] = []
        confirmed = 0
        for result in verify_anchors(anchors, self.root, identity=self._identity,
                                     was_known=lambda path: bool(self._was_known(path))):
            state = str(result.get("state"))
            if state in {"holds", "moved"}:
                # A symbol that moved within its file is still there: the
                # claim about it holds, only the line number aged.
                confirmed += 1
            elif state == "gone":
                findings.append({
                    "kind": "anchor",
                    "path": str(result.get("path") or ""),
                    "reference": str(result.get("anchor") or ""),
                    "reason": "removed",
                    "successor": "",
                    "evidence": str(result.get("evidence") or ""),
                })
        return findings, confirmed

    def anchor_findings(self, anchors: Iterable[str] | None) -> list[dict[str, str]]:
        """Line anchors (see provenance.py) whose symbol is gone from this repository."""
        return self._anchors(anchors)[0] if anchors else []

    def verdict(self, text: str, anchors: Iterable[str] | None = None) -> dict[str, object]:
        """A per-memory verdict for the recall packet.

        `verified` means at least one thing the memory names was found holding
        in the repository at `sha` and nothing it names is gone. `stale`
        means something it names is gone. `unverifiable` covers the rest:
        nothing checkable, nothing ever present here, or checks that did not
        finish within the time budget. Pass the memory's `anchors` to have
        its line anchors checked too.
        """
        sha = self._repo.head() if self._repo.is_repo else ""
        anchor_list = [str(a) for a in anchors or [] if str(a).strip()]
        if not sha or not (checkable_references(text) or anchor_list):
            return {"verdict": "unverifiable", "sha": sha, "checked": 0, "findings": []}
        incomplete_before = self._repo.incomplete
        found, confirmed = self._evaluate(text, anchor_list)
        if found:
            return {"verdict": "stale", "sha": sha, "checked": confirmed + len(found), "findings": found}
        if confirmed and self._repo.incomplete == incomplete_before:
            return {"verdict": "verified", "sha": sha, "checked": confirmed, "findings": []}
        return {"verdict": "unverifiable", "sha": sha, "checked": 0, "findings": []}


# ── v2: references beyond file paths ─────────────────────────────────────

# `npm run build`, `yarn test`, `pnpm run lint`, `bun run dev`. For yarn,
# pnpm and bun the bare form (`yarn test`) also runs a script.
_SCRIPT_RE = re.compile(
    r"(?<![\w-])(?:(npm|yarn|pnpm|bun)\s+(?:run(?:-script)?\s+)?)([a-z0-9][\w:.-]{1,40})\b"
)
# Built-in package-manager verbs are not scripts.
_PM_BUILTINS = {
    "install", "i", "add", "remove", "rm", "uninstall", "update", "upgrade", "ci", "init",
    "publish", "link", "unlink", "exec", "dlx", "x", "create", "why", "outdated", "audit",
    "login", "logout", "pack", "version", "config", "cache", "help", "run", "test", "start",
    "info", "view", "list", "ls", "prune", "dedupe", "workspace", "workspaces", "set", "global",
}
# `npm test` / `npm start` run the script of that name.
_NPM_SCRIPT_BUILTINS = {"test", "start", "stop", "restart"}
_MAKE_RE = re.compile(r"(?<![\w-])(make|just)\s+([a-z0-9][\w.-]{1,40})\b")
_ENV_VAR_RE = re.compile(r"(?<![\w$])\$?\{?([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\}?(?![\w])")
_URL_RE = re.compile(r"\bhttps?://([a-z0-9.-]+\.[a-z]{2,}|localhost|\d{1,3}(?:\.\d{1,3}){3})(:\d{2,5})?(/[^\s)\]>'`\x22]*)?", re.I)
_BACKTICK_RE = re.compile(r"`([^`\n]{2,60})`")
_INSTALL_RE = re.compile(
    r"\b(npm\s+(?:install|i|add)|yarn\s+(?:global\s+)?add|pnpm\s+add|bun\s+add|pip3?\s+install|"
    r"uv\s+(?:add|pip\s+install)|poetry\s+add|cargo\s+add|go\s+get|gem\s+install|bundle\s+add)\s+([^\n;]*)"
)
# Words that end an install's package list in prose ("pip install httpx then
# restart the worker"). A real package list is short and has no connectives.
_INSTALL_STOP = {
    "then", "and", "to", "for", "in", "with", "the", "a", "an", "before", "after", "so", "if", "from",
    "on", "into", "when", "once", "but", "or", "first", "again", "instead", "which", "that", "it",
    "is", "are", "was", "via", "using", "because", "as", "at", "by", "every", "each", "whenever",
}
_GLOBAL_FLAGS = {"-g", "--global", "--user", "global"}
_VERSION_CLAIM_RE = re.compile(
    r"\b(python|node(?:\.js|js)?|go(?:lang)?|ruby|java|rust)\s*v?(\d+(?:\.\d+){0,2})\b", re.I
)
_PM_CLAIM_RE = re.compile(r"\b(?:use|uses|using|prefer|prefers|switched to|stick with|always use)\s+(npm|yarn|pnpm|bun)\b"
                          r"|\b(npm|yarn|pnpm|bun)\s+(?:install|ci|add)\b", re.I)
_LOCKFILES = {"npm": "package-lock.json", "yarn": "yarn.lock", "pnpm": "pnpm-lock.yaml", "bun": "bun.lockb"}
# Environment-shaped words that are really prose or protocol.
_ENV_IGNORE = {"TODO", "FIXME", "README", "API_KEY", "HTTP_GET", "JSON_API", "UTF_8", "CI_CD"}
# Manifest file names, wherever they sit in the tree: monorepos keep
# dependencies and scripts in workspace packages, not only at the root.
_MANIFEST_NAMES = {"package.json", "pyproject.toml", "Cargo.toml", "go.mod", "Gemfile", "Pipfile",
                   "setup.cfg", "setup.py", "environment.yml"}
_MANIFEST_RE = re.compile(r"(?:^|/)(?:requirements[\w.-]*\.(?:txt|in)|requirements/[\w.-]+\.(?:txt|in))$")
_MAKE_FILES = ("Makefile", "makefile", "GNUmakefile", "justfile", "Justfile", ".justfile")
MAX_MANIFESTS = 300
MAX_SYMBOL_LOOKUPS = 12
# Words that turn a claim into history or a prohibition. "We dropped Python
# 3.9", "do not use npm", "upgraded from Node 16" name the thing without
# claiming it is current, so they are not checked as present-tense claims.
_NOT_CURRENT_BEFORE = re.compile(
    r"\b(?:not|never|don'?t|doesn'?t|didn'?t|won'?t|avoid|instead\s+of|rather\s+than|no\s+longer|stop(?:ped)?|"
    r"drop(?:ped|s|ping)?|remov(?:e|ed|es|ing)|deprecat(?:e|ed|es|ing)|from|off|used\s+to|previously|formerly|"
    r"legacy|old|older|was|were|until|replac(?:e|ed|es|ing)|retir(?:e|ed|es|ing)|migrat(?:e|ed|ing)\s+(?:from|off)|"
    r"upgrad(?:e|ed|ing)\s+from|mov(?:e|ed|ing)\s+(?:from|off)|end[\s-]of[\s-]life|eol)\b", re.I)
_NOT_CURRENT_AFTER = re.compile(
    r"^[^.;!?\n]{0,40}?\b(?:was|were|is|are|has\s+been|got|been)?\s*(?:dropped|removed|deprecated|retired|replaced|"
    r"unsupported|no\s+longer|not\s+supported|end[\s-]of[\s-]life|eol|gone)\b", re.I)


def _clause_before(text: str, start: int, since: int = 0) -> str:
    head = text[since:start]
    cut = max(head.rfind(mark) for mark in (".", ";", "!", "?", "\n", ",", ":"))
    return head[cut + 1:] if cut >= 0 else head


def not_a_current_claim(text: str, start: int, end: int, since: int = 0) -> bool:
    """True when the words around a claim make it history or a prohibition.

    `since` is where the previous claim of the same kind ended: in "from
    Node 16 to Node 20" the "from" belongs to 16, not to 20.
    """
    if _NOT_CURRENT_BEFORE.search(_clause_before(text, start, since)):
        return True
    return bool(_NOT_CURRENT_AFTER.search(text[end:]))


def _dedupe(items: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in items:
        if item not in out:
            out.append(item)
    return out


def _install_packages(arguments: str) -> list[str]:
    """Package names from the words after an install verb, stopping at prose."""
    names: list[str] = []
    for raw in arguments.split():
        token = raw.strip("`'\"()")
        ends_sentence = token.endswith((".", ",", ";", ":")) and not re.search(r"\.\w+$", token)
        token = token.rstrip(".,;:")
        if not token:
            break
        if token.lower() in _INSTALL_STOP:
            break
        if token in _GLOBAL_FLAGS:
            return []  # a global tool, not a project dependency
        if token.startswith("-"):
            if token in {"-r", "--requirement", "-e", "--editable", "-c", "--constraint"}:
                break  # the next word is a file or a path, not a package
            continue
        name = re.sub(r"(?<=.)[@=<>~^!\[].*$", "", token)  # drop version pins and extras
        if not re.fullmatch(r"@?[A-Za-z0-9][\w.-]*(?:/[\w.-]+)?", name) or len(name) < 2:
            break
        names.append(name)
        if ends_sentence or len(names) >= 4:
            break
    return names


def _is_endpoint(host: str, port: str) -> bool:
    """URLs a repository configures (local services, internal hosts, explicit ports).

    A link to public documentation is a fact about the world, not about this
    repository, and a README dropping it does not make the memory wrong.
    """
    host = host.lower()
    return bool(port) or host == "localhost" or bool(re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host)) \
        or host.endswith((".local", ".localhost", ".internal", ".lan", ".test"))


def symbol_references(text: str) -> list[tuple[str, str]]:
    """(kind, reference) pairs beyond file paths, in first-seen order."""
    text = text or ""
    found: list[tuple[str, str]] = []
    for manager, name in _SCRIPT_RE.findall(text):
        if name in _PM_BUILTINS and not (name in _NPM_SCRIPT_BUILTINS and manager == "npm"):
            continue
        if manager == "npm" and name not in _NPM_SCRIPT_BUILTINS and not re.search(
            rf"npm\s+run(?:-script)?\s+{re.escape(name)}\b", text
        ):
            continue  # `npm foo` without `run` is not a script invocation
        found.append(("script", name))
    for _tool, target in _MAKE_RE.findall(text):
        found.append(("make_target", target))
    for match in _INSTALL_RE.finditer(text):
        if not_a_current_claim(text, match.start(), match.end(1)):
            continue
        for name in _install_packages(match.group(2)):
            found.append(("dependency", name))
    for inner in _BACKTICK_RE.findall(text):
        inner = inner.strip()
        # Distribution names (left-pad, @scope/pkg), not module names: an
        # underscore identifier in backticks is usually code, and code that
        # still exists is checked by the path rule, not this one.
        if re.fullmatch(r"@?[a-z0-9][a-z0-9.-]*(?:/[a-z0-9.-]+)?", inner) and (
            "-" in inner or "/" in inner or inner.startswith("@")
        ) and not re.search(r"\.(?:" + _CODE_SUFFIXES + r")$", inner):
            found.append(("dependency", inner))
    for name in _ENV_VAR_RE.findall(text):
        if name not in _ENV_IGNORE and len(name) >= 5:
            found.append(("env_var", name))
    for host, port, _path in _URL_RE.findall(text):
        if _is_endpoint(host, port):
            found.append(("url", f"{host.lower()}{port}"))
    return _dedupe(found)


def claim_references(text: str) -> list[tuple[str, str]]:
    """Checkable present-tense claims: runtime versions and package managers.

    Claims framed as history or prohibition are left out, and so is every
    older version in an upgrade story ("from Node 16 to Node 20"): only the
    newest version named for a runtime is the claim.
    """
    text = text or ""
    found: list[tuple[str, str]] = []
    newest: dict[str, tuple[int, ...]] = {}
    versions: list[tuple[str, str]] = []
    previous_end = 0
    for match in _VERSION_CLAIM_RE.finditer(text):
        tool, version = match.group(1), match.group(2)
        name = tool.lower()
        name = "node" if name.startswith("node") else "go" if name.startswith("go") else name
        since, previous_end = previous_end, match.end()
        if not_a_current_claim(text, match.start(), match.end(), since):
            continue
        versions.append((name, version))
        newest[name] = max(newest.get(name, ()), _version_tuple(version))
    for name, version in versions:
        if _version_tuple(version) == newest[name]:
            found.append(("version", f"{name} {version}"))
    for match in _PM_CLAIM_RE.finditer(text):
        manager = (match.group(1) or match.group(2)).lower()
        tail = text[match.end():match.end() + 40]
        if re.match(r"\s+(?:-g|--global)\b", tail) or re.search(r"\s(?:-g|--global)\b", match.group(0)):
            continue  # a global tool install says nothing about the project's manager
        if not_a_current_claim(text, match.start(), match.end()):
            continue
        found.append(("package_manager", manager))
    return _dedupe(found)


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value)[:3])


def _satisfies(claimed: str, spec: str) -> bool | None:
    """Does the claimed version satisfy a manifest spec? None when unknown.

    Handles the specs manifests actually use for runtimes: ">=3.12",
    ">=3.10,<3.13", "^20", "~18.4" (npm: same minor), "~=3.10" (PEP 440:
    compatible release), "20.x", "==3.12.*", ">=18 <21", "3.12", "1.22".
    """
    claim = _version_tuple(claimed)
    if not claim:
        return None

    def compare(left: tuple[int, ...], right: tuple[int, ...]) -> int:
        # Compare on the common prefix only: "Python 3" is not a claim about
        # the minor version, so it neither satisfies nor violates ">=3.10"
        # on the minor part - it only has to get the major right.
        width = min(len(left), len(right))
        a, b = left[:width], right[:width]
        return (a > b) - (a < b)
    parts = [part.strip() for part in re.split(r"[,\s]+(?=[<>=!~^\d])", spec.strip()) if part.strip()]
    if not parts:
        return None
    for part in parts:
        match = re.fullmatch(r"(>=|<=|===|==|!=|>|<|~=|\^|~)?\s*v?([\dx*X.]+)", part)
        if not match:
            return None
        op, raw = match.group(1) or "", match.group(2)
        # A wildcard ends the version: "3.12.*" and "20.x" constrain only
        # the components before it.
        pieces: list[str] = []
        for piece in raw.split("."):
            if piece in {"*", "x", "X", ""}:
                break
            pieces.append(piece)
        bound = _version_tuple(".".join(pieces))
        if not bound:
            return None
        order = compare(claim, bound)
        exact = len(claim) >= len(bound)
        if op in {"", "==", "==="}:
            if order != 0:
                return False
        elif op == ">=" and order < 0:
            return False
        elif op == ">" and (order < 0 or (order == 0 and exact)):
            return False
        elif op == "<=" and order > 0:
            return False
        elif op == "<" and (order > 0 or (order == 0 and exact)):
            return False
        elif op == "!=" and order == 0 and exact:
            return False
        elif op == "^" and (claim[:1] != bound[:1] or order < 0):
            return False
        elif op == "~=":
            # PEP 440: ~=3.10 means >=3.10, ==3.*; ~=3.10.2 means >=3.10.2, ==3.10.*
            prefix = bound[:-1] if len(bound) > 1 else bound
            if order < 0 or compare(claim, prefix) != 0:
                return False
        elif op == "~":
            # npm: ~18.4 means >=18.4.0 <18.5.0; ~18 means 18.x
            head = 2 if len(bound) > 1 else 1
            if order < 0 or compare(claim, bound[:head]) != 0:
                return False
    return True


def _read(repo_root: Path, relative: str) -> str:
    try:
        return (repo_root / relative).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def runtime_requirements(repo_root: Path) -> dict[str, list[tuple[str, str]]]:
    """Runtime version specs the repository checks in: name -> [(file, spec)]."""
    specs: dict[str, list[tuple[str, str]]] = {}

    def add(name: str, where: str, spec: str) -> None:
        spec = spec.strip().strip("\"'")
        if spec:
            specs.setdefault(name, []).append((where, spec))

    pyproject = _read(repo_root, "pyproject.toml")
    match = re.search(r"^\s*requires-python\s*=\s*[\"']([^\"']+)[\"']", pyproject, re.M)
    if match:
        add("python", "pyproject.toml requires-python", match.group(1))
    for rel, name in ((".python-version", "python"), (".nvmrc", "node"), (".node-version", "node"),
                      (".ruby-version", "ruby")):
        text = _read(repo_root, rel).strip().splitlines()
        if text and re.match(r"v?\d", text[0].strip()):
            add(name, rel, text[0].strip().lstrip("v"))
    package = _read(repo_root, "package.json")
    if package:
        try:
            engines = json.loads(package).get("engines") or {}
        except (ValueError, AttributeError):
            engines = {}
        if isinstance(engines, dict) and isinstance(engines.get("node"), str):
            add("node", "package.json engines.node", engines["node"])
    gomod = _read(repo_root, "go.mod")
    match = re.search(r"^go\s+(\d+(?:\.\d+){0,2})\s*$", gomod, re.M)
    if match:
        # The go directive is a minimum: go 1.22 builds happily on Go 1.23.
        add("go", "go.mod go directive", f">={match.group(1)}")
    return specs


def _json_scripts(text: str) -> set[str]:
    try:
        scripts = json.loads(text).get("scripts") or {}
    except (ValueError, AttributeError):
        return set()
    return set(scripts) if isinstance(scripts, dict) else set()


def package_scripts(repo_root: Path, manifests: Iterable[str] | None = None) -> set[str] | None:
    """Scripts defined by every package.json given (default: the root one)."""
    paths = [rel for rel in (manifests or ["package.json"]) if rel.rsplit("/", 1)[-1] == "package.json"]
    texts = [text for text in (_read(repo_root, rel) for rel in paths) if text]
    if not texts:
        return None
    names: set[str] = set()
    for text in texts:
        names |= _json_scripts(text)
    return names


_MAKE_TARGET_LINE = re.compile(r"^([A-Za-z0-9_./-][^:#=\t]*?)\s*::?(?![=])", re.M)
_JUST_RECIPE_LINE = re.compile(r"^@?([A-Za-z0-9_][\w-]*)(?:\s+[^:=\n]*)?\s*:(?!=)", re.M)
_MAKE_INCLUDE = re.compile(r"^\s*-?s?include\s+(.+)$", re.M)
_JUST_IMPORT = re.compile(r"^\s*(?:import\??|mod\??\s+\w+)\s+['\"]([^'\"]+)['\"]", re.M)


def make_targets(repo_root: Path, extra_files: Iterable[str] = ()) -> set[str] | None:
    """Targets and recipes from Makefiles, justfiles and the files they include."""
    names: set[str] | None = None
    queue: list[tuple[str, bool]] = [(rel, rel.lower().endswith("justfile")) for rel in _MAKE_FILES]
    queue += [(rel, rel.endswith(".just")) for rel in extra_files]
    seen: set[str] = set()
    while queue and len(seen) < 50:
        rel, is_just = queue.pop(0)
        if rel in seen or not safe_relative_path(rel):
            continue
        seen.add(rel)
        text = _read(repo_root, rel)
        if not text:
            continue
        names = names or set()
        if is_just:
            names.update(_JUST_RECIPE_LINE.findall(text))
            for included in _JUST_IMPORT.findall(text):
                queue.append((str(Path(rel).parent / included) if "/" in rel else included, True))
            continue
        for line in _MAKE_TARGET_LINE.findall(text):
            # `lint test: deps` defines two targets; `%.o:` and `$(X):` are patterns.
            names.update(word for word in line.split() if not re.search(r"[%$()]", word))
        for spec in _MAKE_INCLUDE.findall(text):
            for word in spec.split():
                if "$" in word:
                    continue
                if any(ch in word for ch in "*?["):
                    queue.extend((str(p.relative_to(repo_root)), False) for p in sorted(repo_root.glob(word))[:20])
                else:
                    queue.append((word, False))
    return names


class SymbolChecker:
    """v2 checks, sharing git answers across many memories like v1."""

    def __init__(self, repo_root: Path, *, runner: Callable[..., object] | None = None,
                 limit: int = MAX_SYMBOL_LOOKUPS, repo: _Repo | None = None) -> None:
        self._repo = repo or _Repo(repo_root, runner=runner)
        self.root = self._repo.root
        self._runner = runner
        self._limit = limit
        self._present: dict[str, bool] = {}
        self._manifests: list[str] | None = None
        self._make_extra: list[str] = []
        self._scripts: set[str] | None | bool = False
        self._targets: set[str] | None | bool = False
        self._runtimes: dict[str, list[tuple[str, str]]] | None = None

    def _git(self, arguments: list[str]) -> str | None:
        return self._repo.git(arguments)

    def _tracked_files(self) -> list[str]:
        if self._manifests is None:
            output = self._git(["ls-files"]) or ""
            self._manifests = []
            for rel in output.splitlines():
                name = rel.rsplit("/", 1)[-1]
                if name in _MANIFEST_NAMES or _MANIFEST_RE.search(rel):
                    self._manifests.append(rel)
                if rel.endswith((".mk", ".just")):
                    self._make_extra.append(rel)
            self._manifests = self._manifests[:MAX_MANIFESTS]
            self._make_extra = self._make_extra[:50]
        return self._manifests

    def _tracked_mentions(self, needle: str) -> bool | None:
        if needle not in self._present:
            output = self._git(["grep", "-I", "-l", "-w", "-F", "--", needle])
            if output is None:
                return None
            self._present[needle] = bool(output.strip())
        return self._present[needle]

    def _last_seen(self, key: str, regex: str, pathspec: tuple[str, ...] = ()) -> str | None:
        """Short sha + date of the last commit that added or removed a line matching `regex`."""
        return self._repo.history(f"G:{key}:{','.join(pathspec)}", [
            "log", "--all", "-1", f"--since={HISTORY_WINDOW}", "-E", f"-G{regex}",
            "--format=%h %cs", "--", *pathspec,
        ])

    def _scripts_now(self) -> set[str] | None:
        if self._scripts is False:
            self._scripts = package_scripts(self.root, self._tracked_files() or None)
        return self._scripts if self._scripts is not False else None  # type: ignore[return-value]

    def _targets_now(self) -> set[str] | None:
        if self._targets is False:
            self._tracked_files()
            self._targets = make_targets(self.root, self._make_extra)
        return self._targets if self._targets is not False else None  # type: ignore[return-value]

    def findings(self, text: str) -> list[dict[str, str]]:
        return self.evaluate(text)[0]

    def evaluate(self, text: str) -> tuple[list[dict[str, str]], int]:
        """(findings, confirmed count) for everything beyond file paths."""
        results: list[dict[str, str]] = []
        confirmed = 0
        lookups = 0
        for kind, reference in symbol_references(text):
            if lookups >= self._limit:
                break
            state, finding = self._check_symbol(kind, reference)
            lookups += 1
            confirmed += state == "holds"
            if finding:
                results.append(finding)
        for kind, reference in claim_references(text):
            state, finding = self._check_claim(kind, reference, text)
            confirmed += state == "holds"
            if finding:
                results.append(finding)
        return results, confirmed

    def _finding(self, kind: str, reference: str, reason: str, evidence: str, successor: str = "") -> dict[str, str]:
        # "path" keeps v1 consumers (the recall packet marker) working.
        return {"kind": kind, "path": reference, "reference": reference, "reason": reason,
                "successor": successor, "evidence": evidence}

    def _check_symbol(self, kind: str, reference: str) -> tuple[str, dict[str, str] | None]:
        """("holds" | "stale" | "unknown", finding)."""
        unknown: tuple[str, None] = ("unknown", None)
        if kind == "script":
            scripts = self._scripts_now()
            if scripts is None:
                return unknown
            if reference in scripts:
                return ("holds", None)
            seen = self._last_seen(f"script:{reference}", f'"{_ere_escape(reference)}"[[:space:]]*:',
                                   ("package.json", ":(glob)**/package.json"))
            if not seen:
                return unknown
            return ("stale", self._finding(kind, reference, "removed",
                                           f"no package.json defines scripts.{reference} any more (changed in {seen})"))
        if kind == "make_target":
            targets = self._targets_now()
            if targets is None:
                return unknown
            if reference in targets:
                return ("holds", None)
            pathspec = (*_MAKE_FILES, ":(glob)**/*.mk", ":(glob)**/*.just")
            definition = f"^@?([^:#=[:space:]]+[[:space:]]+)*{_ere_escape(reference)}([[:space:]][^:=]*)?:"
            # Belt and braces: a target the parser missed but a tracked file
            # still defines is not gone.
            if (self._git(["grep", "-I", "-l", "-E", definition, "--", *pathspec]) or "").strip():
                return ("holds", None)
            seen = self._last_seen(f"make:{reference}", definition, pathspec)
            if not seen:
                return unknown
            return ("stale", self._finding(kind, reference, "removed",
                                           f"no make/just target named {reference} (changed in {seen})"))
        if kind == "dependency":
            manifests = [rel for rel in self._tracked_files() if (self.root / rel).exists()]
            if not manifests:
                return unknown
            # Package names compare case-insensitively with -, _ and . alike
            # (PEP 503), so "pyyaml" still matches "PyYAML" in requirements.
            flexible = "".join("[-_.]" if char in "-_." else re.escape(char) for char in reference)
            present = re.compile(rf"(?<![\w-]){flexible}(?![\w-])", re.I)
            if any(present.search(_read(self.root, rel)) for rel in manifests):
                return ("holds", None)
            manifest_specs = tuple(sorted({f":(glob)**/{rel.rsplit('/', 1)[-1]}" for rel in manifests}))
            seen = self._last_seen(f"dep:{reference.lower()}", _ere_word(reference, fold=True), manifest_specs)
            if not seen:
                return unknown
            return ("stale", self._finding(kind, reference, "removed",
                                           f"no dependency manifest lists {reference} any more (changed in {seen})"))
        if kind in {"env_var", "url"}:
            mentioned = self._tracked_mentions(reference)
            if mentioned is None:
                return unknown
            if mentioned:
                return ("holds", None)
            seen = self._last_seen(f"{kind}:{reference}", _ere_word(reference))
            if not seen:
                return unknown
            what = "environment variable" if kind == "env_var" else "URL"
            return ("stale", self._finding(kind, reference, "removed",
                                           f"no tracked file mentions the {what} {reference} any more (last changed in {seen})"))
        return unknown

    def _check_claim(self, kind: str, reference: str, text: str = "") -> tuple[str, dict[str, str] | None]:
        unknown: tuple[str, None] = ("unknown", None)
        if kind == "version":
            if self._runtimes is None:
                self._runtimes = runtime_requirements(self.root)
            name, version = reference.split(" ", 1)
            specs = self._runtimes.get(name, [])
            verdicts = [(where, spec, _satisfies(version, spec)) for where, spec in specs]
            for where, spec, verdict in verdicts:
                if verdict is False:
                    return ("stale", self._finding(kind, reference, "contradicted",
                                                   f"{where} says {spec}, which {name} {version} does not satisfy"))
            return ("holds", None) if any(v is True for _w, _s, v in verdicts) else unknown
        if kind == "package_manager":
            claimed = reference
            claimed_lock = _LOCKFILES.get(claimed)
            if not claimed_lock:
                return unknown
            if (self.root / claimed_lock).exists():
                return ("holds", None)
            current = [pm for pm, lock in _LOCKFILES.items() if (self.root / lock).exists()]
            if len(current) != 1:
                return unknown
            # A memory that also names the manager in use is contrasting the
            # two ("we use pnpm, not npm"), not claiming the old one.
            if re.search(rf"\b{current[0]}\b", text, re.I):
                return unknown
            # History gate: the claimed manager's lockfile really was here.
            if not self._repo.history(f"path:{claimed_lock}", ["log", "--all", "--oneline", "-1", "--", claimed_lock]):
                return unknown
            return ("stale", self._finding(kind, claimed, "contradicted",
                                           f"the repository now uses {current[0]} ({_LOCKFILES[current[0]]}); "
                                           f"{claimed_lock} was removed", successor=current[0]))
        return unknown


def head_sha(repo_root: Path, runner: Callable[..., object] | None = None) -> str:
    return _git(Path(repo_root).expanduser(), ["rev-parse", "--short=12", "HEAD"], runner).strip()


def checkable_references(text: str) -> int:
    """How many things in this text Link can check against a repository."""
    return len(repo_path_references(text)) + len(symbol_references(text)) + len(claim_references(text))


def stale_findings(
    text: str,
    repo_root: Path,
    *,
    runner: Callable[..., object] | None = None,
    limit: int = MAX_PATH_LOOKUPS,
) -> list[dict[str, str]]:
    """One-off check of a single text. For many memories use StalenessChecker."""
    return StalenessChecker(repo_root, runner=runner, limit=limit).findings(text)


def describe_findings(findings: Iterable[dict[str, str]]) -> list[str]:
    """One reviewable line per finding."""
    lines: list[str] = []
    for finding in findings:
        kind = finding.get("kind", "path")
        if kind == "anchor":
            lines.append(str(finding.get("evidence") or finding.get("reference")))
            continue
        if kind != "path" and finding.get("evidence"):
            lines.append(str(finding["evidence"]))
        elif finding.get("successor"):
            lines.append(f"{finding['path']} was renamed to {finding['successor']}")
        else:
            lines.append(f"{finding['path']} is no longer in the repository")
    return lines
