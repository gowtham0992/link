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

Nothing here rewrites or deletes a memory. Findings are routed to the same
review gate every other change goes through, because a flag that acts on its
own is a flag people learn to fear, and a flag that fires loosely is one they
learn to ignore. Silence is the normal output.
"""
from __future__ import annotations

import json
import re
import subprocess
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


def repo_path_references(text: str) -> list[str]:
    """Repository-looking paths named by a memory, in first-seen order."""
    seen: list[str] = []
    # Memories written on Windows name paths with backslashes. Git and the
    # repository itself use forward slashes, so normalise before matching -
    # otherwise every Windows user's references would silently go unchecked.
    normalised = (text or "").replace("\\", "/")
    for match in _PATH_REFERENCE.finditer(normalised):
        candidate = match.group(1)
        if candidate.startswith(_IGNORED_PREFIXES) or candidate in seen:
            continue
        seen.append(candidate)
    return seen


def _git(repo_root: Path, arguments: list[str], runner: Callable[..., object] | None = None) -> str:
    """Run one read-only git command, returning "" when git cannot answer."""
    if runner is not None:
        return str(runner(repo_root, arguments) or "")
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
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


class StalenessChecker:
    """Check many memories against one repository without repeating git work.

    Each distinct path is resolved against git once, and the rename map is
    read once, no matter how many memories mention them. Fifty memories that
    all cite the same moved file cost one lookup, not fifty.
    """

    def __init__(self, repo_root: Path, *, runner: Callable[..., object] | None = None,
                 limit: int = MAX_PATH_LOOKUPS) -> None:
        self.root = Path(repo_root).expanduser()
        self._runner = runner
        self._limit = limit
        self._known: dict[str, bool] = {}
        self._moves: dict[str, str] | None = None
        self._symbols: SymbolChecker | None = None
        self._sha: str | None = None

    def _was_known(self, path: str) -> bool:
        if path not in self._known:
            self._known[path] = path_was_known(self.root, path, self._runner)
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
        results = self.path_findings(text)
        if self._symbols is None:
            self._symbols = SymbolChecker(self.root, runner=self._runner, limit=self._limit)
        results.extend(self._symbols.findings(text))
        return results

    def anchor_findings(self, anchors: Iterable[str] | None) -> list[dict[str, str]]:
        """Line anchors (see provenance.py) that moved or are gone."""
        if not anchors:
            return []
        from .provenance import verify_anchors  # provenance imports this module

        findings: list[dict[str, str]] = []
        for result in verify_anchors(anchors, self.root):
            state = str(result.get("state"))
            if state == "holds":
                continue
            findings.append({
                "kind": "anchor",
                "path": str(result.get("path") or ""),
                "reference": str(result.get("anchor") or ""),
                "reason": "moved" if state == "moved" else "removed",
                "successor": f"{result.get('path')}:{result.get('line')}" if state == "moved" else "",
                "evidence": str(result.get("evidence") or ""),
            })
        return findings

    def verdict(self, text: str, anchors: Iterable[str] | None = None) -> dict[str, object]:
        """A per-memory verdict for the recall packet.

        `verified` means the memory names things Link could check and every
        one of them holds in the repository at `sha`. `stale` means at least
        one does not. `unverifiable` means there was nothing to check - the
        common case, and not a warning. Pass the memory's `anchors` to have
        its line anchors checked too.
        """
        if self._sha is None:
            self._sha = head_sha(self.root, self._runner)
        anchor_list = [str(a) for a in anchors or [] if str(a).strip()]
        checkable = checkable_references(text) + len(anchor_list)
        if not checkable or not self._sha:
            return {"verdict": "unverifiable", "sha": self._sha or "", "checked": 0, "findings": []}
        found = self.findings(text) + self.anchor_findings(anchor_list)
        return {
            "verdict": "stale" if found else "verified",
            "sha": self._sha,
            "checked": checkable,
            "findings": found,
        }

    def path_findings(self, text: str) -> list[dict[str, str]]:
        """v1: repository paths git once tracked that are gone now."""
        results: list[dict[str, str]] = []
        for candidate in repo_path_references(text)[: self._limit]:
            if (self.root / candidate).exists():
                continue
            if not self._was_known(candidate):
                continue  # never in the repository: prose, not a stale reference
            successor = self._successor(candidate)
            results.append({
                "kind": "path",
                "path": candidate,
                "reference": candidate,
                "reason": "renamed" if successor else "removed",
                "successor": successor,
            })
        return results


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
_URL_RE = re.compile(r"\bhttps?://([a-z0-9.-]+\.[a-z]{2,}|localhost)(:\d{2,5})?(/[^\s)\]>'`\x22]*)?", re.I)
_BACKTICK_RE = re.compile(r"`([^`\n]{2,60})`")
_INSTALL_RE = re.compile(
    r"\b(?:npm\s+(?:install|i|add)|yarn\s+add|pnpm\s+add|bun\s+add|pip\s+install|uv\s+(?:add|pip\s+install)|"
    r"poetry\s+add|cargo\s+add|go\s+get|gem\s+install|bundle\s+add)\s+((?:[@\w./-]+\s*){1,4})"
)
_VERSION_CLAIM_RE = re.compile(
    r"\b(python|node(?:\.js|js)?|go(?:lang)?|ruby|java|rust)\s*v?(\d+(?:\.\d+){0,2})\b", re.I
)
_PM_CLAIM_RE = re.compile(r"\b(?:use|uses|using|prefer|prefers|switched to|stick with|always use)\s+(npm|yarn|pnpm|bun)\b"
                          r"|\b(npm|yarn|pnpm|bun)\s+(?:install|ci|add)\b", re.I)
_LOCKFILES = {"npm": "package-lock.json", "yarn": "yarn.lock", "pnpm": "pnpm-lock.yaml", "bun": "bun.lockb"}
# Environment-shaped words that are really prose or protocol.
_ENV_IGNORE = {"TODO", "FIXME", "README", "API_KEY", "HTTP_GET", "JSON_API", "UTF_8", "CI_CD"}
_DEPENDENCY_MANIFESTS = ("package.json", "pyproject.toml", "requirements.txt", "requirements-dev.txt",
                         "Cargo.toml", "go.mod", "Gemfile")
MAX_SYMBOL_LOOKUPS = 12
# Pickaxe searches are bounded to recent history: a symbol removed years
# ago is not what makes a memory wrong today, and an unbounded -S scan on a
# large repository is slow for every symbol that was never there.
HISTORY_WINDOW = "3 years ago"


def _dedupe(items: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in items:
        if item not in out:
            out.append(item)
    return out


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
        for token in match.group(1).split():
            name = token.strip().rstrip(".,;:")
            name = re.sub(r"(?<=.)[@=<>~^].*$", "", name)  # drop version pins
            if len(name) >= 2 and not name.startswith("-"):
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
        found.append(("url", f"{host.lower()}{port}"))
    return _dedupe(found)


def claim_references(text: str) -> list[tuple[str, str]]:
    """Checkable claims: runtime versions and package managers."""
    found: list[tuple[str, str]] = []
    for tool, version in _VERSION_CLAIM_RE.findall(text or ""):
        name = tool.lower()
        name = "node" if name.startswith("node") else "go" if name.startswith("go") else name
        found.append(("version", f"{name} {version}"))
    for first, second in _PM_CLAIM_RE.findall(text or ""):
        found.append(("package_manager", (first or second).lower()))
    return _dedupe(found)


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value)[:3])


def _satisfies(claimed: str, spec: str) -> bool | None:
    """Does the claimed version satisfy a manifest spec? None when unknown.

    Handles the specs manifests actually use for runtimes: ">=3.12",
    ">=3.10,<3.13", "^20", "~18.4", "20.x", ">=18 <21", "3.12", "1.22".
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
        match = re.fullmatch(r"(>=|<=|==|!=|>|<|~=|\^|~)?\s*v?([\dx*.]+)", part)
        if not match:
            return None
        op, raw = match.group(1) or "", match.group(2)
        bound = _version_tuple(raw.replace("x", "0").replace("*", "0"))
        if not bound:
            return None
        order = compare(claim, bound)
        exact = len(claim) >= len(bound)
        if op in {"", "=="}:
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
        elif op in {"~", "~="}:
            head = 2 if len(bound) > 1 else 1
            if compare(claim, bound[:head]) != 0:
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
        add("go", "go.mod go directive", match.group(1))
    return specs


def package_scripts(repo_root: Path) -> set[str] | None:
    text = _read(repo_root, "package.json")
    if not text:
        return None
    try:
        scripts = json.loads(text).get("scripts") or {}
    except (ValueError, AttributeError):
        return None
    return set(scripts) if isinstance(scripts, dict) else set()


def make_targets(repo_root: Path) -> set[str] | None:
    names: set[str] | None = None
    for rel in ("Makefile", "makefile", "GNUmakefile", "justfile", "Justfile"):
        text = _read(repo_root, rel)
        if not text:
            continue
        names = names or set()
        names.update(re.findall(r"^([A-Za-z0-9][\w.-]*)\s*:(?!=)", text, re.M))
    return names


class SymbolChecker:
    """v2 checks, sharing git answers across many memories like v1."""

    def __init__(self, repo_root: Path, *, runner: Callable[..., object] | None = None,
                 limit: int = MAX_SYMBOL_LOOKUPS) -> None:
        self.root = Path(repo_root).expanduser()
        self._runner = runner
        self._limit = limit
        self._present: dict[str, bool] = {}
        self._past: dict[tuple[str, str], str] = {}
        self._scripts: set[str] | None | bool = False
        self._targets: set[str] | None | bool = False
        self._runtimes: dict[str, list[tuple[str, str]]] | None = None

    def _git(self, arguments: list[str]) -> str:
        return _git(self.root, arguments, self._runner)

    def _tracked_mentions(self, needle: str) -> bool:
        if needle not in self._present:
            self._present[needle] = bool(self._git(["grep", "-I", "-l", "-F", "--", needle]).strip())
        return self._present[needle]

    def _last_seen(self, needle: str, pathspec: tuple[str, ...] = ()) -> str:
        """Short sha + date of the last commit that added or removed `needle`."""
        key = (needle, ",".join(pathspec))
        if key not in self._past:
            output = self._git([
                "log", "--all", "-1", f"--since={HISTORY_WINDOW}", "-S", needle,
                "--format=%h %cs", "--", *pathspec,
            ])
            self._past[key] = output.strip().splitlines()[0] if output.strip() else ""
        return self._past[key]

    def _scripts_now(self) -> set[str] | None:
        if self._scripts is False:
            self._scripts = package_scripts(self.root)
        return self._scripts if self._scripts is not False else None  # type: ignore[return-value]

    def _targets_now(self) -> set[str] | None:
        if self._targets is False:
            self._targets = make_targets(self.root)
        return self._targets if self._targets is not False else None  # type: ignore[return-value]

    def findings(self, text: str) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        lookups = 0
        for kind, reference in symbol_references(text):
            if lookups >= self._limit:
                break
            finding = self._check_symbol(kind, reference)
            lookups += 1
            if finding:
                results.append(finding)
        for kind, reference in claim_references(text):
            finding = self._check_claim(kind, reference)
            if finding:
                results.append(finding)
        return results

    def _finding(self, kind: str, reference: str, reason: str, evidence: str, successor: str = "") -> dict[str, str]:
        # "path" keeps v1 consumers (the recall packet marker) working.
        return {"kind": kind, "path": reference, "reference": reference, "reason": reason,
                "successor": successor, "evidence": evidence}

    def _check_symbol(self, kind: str, reference: str) -> dict[str, str] | None:
        if kind == "script":
            scripts = self._scripts_now()
            if scripts is None or reference in scripts:
                return None
            seen = self._last_seen(f'"{reference}"', ("package.json",))
            if not seen:
                return None
            return self._finding(kind, reference, "removed",
                                 f"package.json no longer defines scripts.{reference} (changed in {seen})")
        if kind == "make_target":
            targets = self._targets_now()
            if targets is None or reference in targets:
                return None
            seen = self._last_seen(f"{reference}:", ("Makefile", "makefile", "GNUmakefile", "justfile", "Justfile"))
            if not seen:
                return None
            return self._finding(kind, reference, "removed", f"no make/just target named {reference} (changed in {seen})")
        if kind == "dependency":
            present = [rel for rel in _DEPENDENCY_MANIFESTS if (self.root / rel).exists()]
            if not present:
                return None
            if any(re.search(rf"(?<![\w@/-]){re.escape(reference)}(?![\w-])", _read(self.root, rel)) for rel in present):
                return None
            seen = self._last_seen(reference, tuple(_DEPENDENCY_MANIFESTS))
            if not seen:
                return None
            return self._finding(kind, reference, "removed",
                                 f"no dependency manifest lists {reference} any more (changed in {seen})")
        if kind in {"env_var", "url"}:
            if self._tracked_mentions(reference):
                return None
            seen = self._last_seen(reference)
            if not seen:
                return None
            what = "environment variable" if kind == "env_var" else "URL"
            return self._finding(kind, reference, "removed",
                                 f"no tracked file mentions the {what} {reference} any more (last changed in {seen})")
        return None

    def _check_claim(self, kind: str, reference: str) -> dict[str, str] | None:
        if kind == "version":
            if self._runtimes is None:
                self._runtimes = runtime_requirements(self.root)
            name, version = reference.split(" ", 1)
            for where, spec in self._runtimes.get(name, []):
                verdict = _satisfies(version, spec)
                if verdict is False:
                    return self._finding(kind, reference, "contradicted",
                                         f"{where} says {spec}, which {name} {version} does not satisfy")
            return None
        if kind == "package_manager":
            claimed = reference
            claimed_lock = _LOCKFILES.get(claimed)
            if not claimed_lock or (self.root / claimed_lock).exists():
                return None
            current = [pm for pm, lock in _LOCKFILES.items() if (self.root / lock).exists()]
            if len(current) != 1:
                return None
            # History gate: the claimed manager's lockfile really was here.
            if not path_was_known(self.root, claimed_lock, self._runner):
                return None
            return self._finding(kind, claimed, "contradicted",
                                 f"the repository now uses {current[0]} ({_LOCKFILES[current[0]]}); "
                                 f"{claimed_lock} was removed", successor=current[0])
        return None


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
