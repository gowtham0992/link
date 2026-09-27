"""Serverless memory sync for Link: your own git remote, no service.

`lnk sync` moves reviewed memory between machines through a git remote the
user controls (a private GitHub repo, a homelab bare repo, anything git can
push to). Three promises distinguish it from plain git:

- **Secrets never leave.** Staged changes are scanned before they are
  committed, and every object an outgoing push would carry — every
  unpushed commit, not only the current tree — is scanned before the
  push, with the same detector that guards memory writes. A
  credential-shaped value stops the sync with the file named. Private
  material (raw captures, ingest staging, operation snapshots, backups) is
  ignored and never staged, even if an older setup tracked it.
- **Conflicts become review items, never markers.** When two machines edit
  the same memory, the remote version keeps the original path and the
  local version is preserved as a sibling memory file — both real, both
  recallable — and Link's own consolidate/duplicate machinery surfaces the
  pair for the human to merge. Git conflict markers never touch wiki files.
- **The log stays tamper-evident.** Diverged logs union entry-by-entry
  into a freshly rebuilt hash chain, and a sync-merge entry declares the
  re-anchor — the same discipline log redaction uses.

What syncs: `wiki/` (and the .gitignore itself). What never syncs: `raw/`
captures (private by design), runtime files (each machine's installed Link
provides its own), caches and backups.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Callable

from .frontmatter import parse_frontmatter, update_frontmatter_fields
from .log import append_log, merge_log_texts, refresh_log_anchor, utc_timestamp
from .security import injected_instruction_warnings, secret_value_warnings

# Appended to the workspace .gitignore at init: the runtime is derived from
# the installed package (syncing it would fight the stale-runtime guard and
# version-skew between machines), and generated wiki artifacts rebuild.
SYNC_IGNORE_LINES = (
    "",
    "# Link runtime (machine-local; provided by the installed Link)",
    "/link.py",
    "/serve.py",
    "/link_core/",
    "/LINK.md",
    "/logo.svg",
    "/logo.png",
    "/.link-team.json",
    "/.link-team-imports.json",
    "/.link-usage.json",
    "# Private local material: never leaves this machine",
    "/raw/",
    "/.link-ingest/",
    "/.link-backups/",
    "/.link-cache/",
    "/wiki/.link-operations/",
    # Obsidian's per-machine UI state: changes on every open, and syncing it
    # between machines produces pointless conflicts. Themes/plugins in the
    # rest of .obsidian/ still sync so the vault feels the same everywhere.
    "/wiki/.obsidian/workspace.json",
)

TEAM_CONFIG_FILE = ".link-team.json"
# Machine-local record of what team-sync imported, so a memory the user
# forgot or archived is not resurrected by the next sync.
TEAM_IMPORT_LEDGER = ".link-team-imports.json"

# Paths that must never be staged in a sync repo, even if an older
# .gitignore let them in and they are still tracked. Link never untracks
# them itself: a commit that removes tracked files deletes them from disk
# on every machine that pulls it (including machines on older Link).
PRIVATE_TRACKED_PATHS = ("raw", ".link-ingest", ".link-backups", ".link-cache", "wiki/.link-operations")

# Outgoing files larger than this are not text a person wrote; skip the scan.
SECRET_SCAN_MAX_BYTES = 2_000_000

# Regenerated after every merge instead of being merged.
GENERATED_WIKI_FILES = ("wiki/index.md", "wiki/_backlinks.json", "wiki/_link_schema.json")

_OBJECT_LINE_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?(?: |$)")


class SyncError(RuntimeError):
    """A sync step failed in a way the user must resolve."""


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    # core.quotepath=off and -z (wherever names are parsed) keep non-ASCII
    # names verbatim: a quoted "wiki/caf\303\251.md" matched no file, so it
    # skipped the secret scan and its conflict was never resolved.
    result = subprocess.run(
        ["git", "-c", "core.quotepath=off", *args], cwd=root, stdin=subprocess.DEVNULL,
        # Git writes paths as UTF-8 on every platform; decoding with the
        # Windows locale turned café.md into cafÃ©.md, which matched no file.
        capture_output=True, text=True, encoding="utf-8", errors="surrogateescape", timeout=120,
    )
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise SyncError(f"git {' '.join(args[:2])} failed: {message[:400]}")
    return result


def _git_bytes(root: Path, *args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args], cwd=root, input=stdin if stdin is not None else b"",
        capture_output=True, timeout=120,
    )


def _z_names(output: str) -> list[str]:
    return [name for name in output.split("\0") if name]


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], stdin=subprocess.DEVNULL, capture_output=True, timeout=10)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def _is_repo(root: Path) -> bool:
    return (root / ".git").exists()


def _current_branch(root: Path) -> str:
    result = _git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False)
    branch = result.stdout.strip()
    if result.returncode == 0 and branch:
        return branch
    # Unborn branch (a clone of an empty remote, or a remote whose HEAD
    # pointed at a branch nobody pushed): rev-parse has no commit to name,
    # but the symbolic ref still says which branch we are on.
    symbolic = _git(root, "symbolic-ref", "--short", "HEAD", check=False).stdout.strip()
    return symbolic or "main"


def _remote_url(root: Path) -> str | None:
    result = _git(root, "remote", "get-url", "origin", check=False)
    url = result.stdout.strip()
    return url or None


def _has_commit(root: Path, ref: str = "HEAD") -> bool:
    return _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False).returncode == 0


def ensure_sync_gitignore(root: Path) -> bool:
    """Append the sync ignore lines missing from the workspace .gitignore."""
    path = root / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    missing = [line for line in SYNC_IGNORE_LINES if line and line not in existing.splitlines()]
    if not missing:
        return False
    block = "\n".join(SYNC_IGNORE_LINES).strip("\n")
    text = existing.rstrip("\n") + ("\n\n" if existing.strip() else "") + block + "\n"
    path.write_text(text, encoding="utf-8")
    return True


def _ensure_commit_identity(root: Path) -> None:
    """Give the sync repo a local identity when the machine has none.

    A fresh machine (or a CI runner) often has no global user.name/email,
    and git refuses to commit without one — which would make lnk sync
    crash on first run. The fallback is repo-local only: the user's global
    config is never touched, and a configured identity always wins.
    """
    email = _git(root, "config", "user.email", check=False).stdout.strip()
    if not email:
        _git(root, "config", "user.name", "Link Sync", check=False)
        _git(root, "config", "user.email", "link-sync@localhost", check=False)


def _is_private(rel: str) -> bool:
    return any(rel == private or rel.startswith(private + "/") for private in PRIVATE_TRACKED_PATHS)


def _stage_all(root: Path) -> None:
    """Stage every change except private material, tracked or not.

    Equivalent to `git add -A` minus the private roots. (Exclude pathspecs
    would say the same, but git exits non-zero when one names an ignored
    directory.) A local edit or deletion under a still-tracked raw/ is
    never staged, so it can never reach the remote or another machine.
    """
    listing = _git(root, "ls-files", "-z", "--modified", "--deleted", "--others", "--exclude-standard").stdout
    paths = sorted({rel for rel in _z_names(listing) if not _is_private(rel)})
    for start in range(0, len(paths), 200):
        _git(root, "--literal-pathspecs", "add", "-A", "--", *paths[start:start + 200])


def _has_staged_changes(root: Path) -> bool:
    return _git(root, "diff", "--cached", "--quiet", check=False).returncode == 1


def tracked_private_paths(root: Path) -> list[str]:
    """Private roots an older setup left tracked (reported, never untracked)."""
    tracked: list[str] = []
    for rel in PRIVATE_TRACKED_PATHS:
        if _git(root, "ls-files", "-z", "--", rel, check=False).stdout.strip("\0"):
            tracked.append(rel)
    return tracked


def _private_tracked_warning(root: Path, tracked: list[str]) -> str:
    paths = " ".join(tracked)
    return (
        f"Private material is still tracked by this sync repo from an older setup: {', '.join(tracked)}. "
        "Link no longer stages changes under it, and it does not untrack it for you: a commit that "
        "untracks files deletes them from disk on every machine that pulls it. To stop tracking it, "
        "first back it up on every machine (lnk backup --include-raw), then run "
        f"`git -C {root} rm -r --cached -- {paths}` and "
        f"`git -C {root} commit -m \"stop tracking private material\"`. "
        "Earlier commits on the remote still contain these files."
    )


def _symlinks_under(root: Path) -> list[str]:
    """Every symlink in a worktree (outside .git), as root-relative paths."""
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        if current == root:
            dirnames[:] = [name for name in dirnames if name != ".git"]
        for name in [*dirnames, *filenames]:
            path = current / name
            if path.is_symlink():
                found.append(path.relative_to(root).as_posix())
    return sorted(found)


def _tracked_symlinks(root: Path, ref: str) -> list[str]:
    """Paths committed as symlinks (mode 120000) in `ref`."""
    listing = _git(root, "ls-tree", "-r", "-z", "--full-tree", ref, check=False).stdout
    links: list[str] = []
    for record in _z_names(listing):
        meta, _, path = record.partition("\t")
        if meta.split(" ", 1)[0] == "120000":
            links.append(path)
    return sorted(links)


def _refuse_symlinks(links: list[str], where: str) -> None:
    if links:
        shown = ", ".join(links[:5]) + (f" (+{len(links) - 5} more)" if len(links) > 5 else "")
        raise SyncError(
            f"refusing to sync: {where} contains symlinks ({shown}). A symlink in a shared repo can "
            "point at any file on your disk, so Link never reads, writes or merges through one. "
            "Remove them (and the commits that added them) and sync again."
        )


def _symlinked_component(root: Path, rel: str) -> str | None:
    """The first component of root/rel that is a symlink, if any."""
    current = root
    for part in Path(rel).parts:
        current = current / part
        if current.is_symlink():
            return current.relative_to(root).as_posix()
    return None


def _scan_blobs(root: Path, items: list[tuple[str, str]]) -> dict[str, list[str]]:
    """Secret labels per blob sha, for (sha, path) pairs. Non-blobs are skipped."""
    shas = sorted({sha for sha, _ in items})
    if not shas:
        return {}
    check = _git_bytes(root, "cat-file", "--batch-check", stdin="".join(f"{sha}\n" for sha in shas).encode())
    if check.returncode != 0:
        raise SyncError(f"could not read the objects to scan: {check.stderr.decode(errors='replace')[:300]}")
    wanted: list[str] = []
    for line in check.stdout.decode(errors="replace").splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[1] == "blob" and int(fields[2]) <= SECRET_SCAN_MAX_BYTES:
            wanted.append(fields[0])
    if not wanted:
        return {}
    batch = _git_bytes(root, "cat-file", "--batch", stdin="".join(f"{sha}\n" for sha in wanted).encode())
    if batch.returncode != 0:
        raise SyncError(f"could not read the objects to scan: {batch.stderr.decode(errors='replace')[:300]}")
    labels: dict[str, list[str]] = {}
    data = batch.stdout
    offset = 0
    while offset < len(data):
        header_end = data.index(b"\n", offset)
        header = data[offset:header_end].decode(errors="replace").split()
        offset = header_end + 1
        if len(header) != 3:
            continue
        size = int(header[2])
        content = data[offset:offset + size]
        offset += size + 1
        found = secret_value_warnings(content.decode("utf-8", errors="replace"))
        if found:
            labels[header[0]] = found
    return labels


def _staged_secret_findings(root: Path) -> list[dict[str, object]]:
    """Scan exactly what the next commit would record, before committing it."""
    raw = _git(root, "diff", "--cached", "--raw", "-z", "--no-abbrev", "--no-renames",
               "--diff-filter=ACMRT").stdout
    fields = raw.split("\0")
    items: list[tuple[str, str]] = []
    index = 0
    while index + 1 < len(fields):
        meta, path = fields[index], fields[index + 1]
        index += 2
        parts = meta.split()
        if len(parts) >= 4 and path:
            items.append((parts[3], path))
    labels = _scan_blobs(root, items)
    return [{"path": path, "label": label} for sha, path in items for label in labels.get(sha, [])]


def _outgoing_secret_findings(root: Path, branch: str) -> list[dict[str, object]]:
    """Scan every object a push would carry: all unpushed commits, not the tree.

    A secret committed earlier and redacted since still travels inside the
    old commit; scanning only the current files let it through.
    """
    if not _has_commit(root):
        return []
    upstream = f"origin/{branch}"
    has_upstream = _has_commit(root, upstream)
    range_args = ["HEAD", "--not", upstream] if has_upstream else ["HEAD"]
    listing = _git(root, "rev-list", "--objects", *range_args).stdout
    items: list[tuple[str, str]] = []
    for line in listing.split("\n"):
        if _OBJECT_LINE_RE.match(line):
            sha, _, path = line.partition(" ")
            items.append((sha, path))
        elif items and line:
            # A path containing a newline continues the previous record.
            sha, path = items[-1]
            items[-1] = (sha, f"{path}\n{line}")
    items = [(sha, path) for sha, path in items if path]
    labels = _scan_blobs(root, items)
    findings: list[dict[str, object]] = []
    for sha, path in items:
        for label in labels.get(sha, []):
            commits = _git(root, "log", "--format=%h", f"--find-object={sha}", *range_args,
                           check=False).stdout.split()
            findings.append({"path": path, "label": label, "commits": commits})
    return findings


def _history_rewrite_hint(root: Path, branch: str, has_upstream: bool) -> str:
    if has_upstream:
        return (
            "An unpushed commit still contains the secret, even if the file is redacted now. "
            "Link does not rewrite history for you. To drop the secret from your unpushed commits "
            "(keeping the redacted files), run "
            f"`git -C {root} reset --soft origin/{branch}` and sync again."
        )
    return (
        "An unpushed commit still contains the secret, even if the file is redacted now. "
        "Link does not rewrite history for you. Nothing has reached the remote yet, so after redacting "
        f"run `git -C {root} update-ref -d HEAD` (your files stay as they are) and sync again. "
        "That starts the workspace's git history over: if you kept history here before syncing, "
        "remove the secret with an interactive rebase instead."
    )


def sync_init(root: Path, remote: str | None = None) -> dict[str, object]:
    """Turn the workspace into a sync-ready git repo. Idempotent."""
    root = root.expanduser().resolve()
    if not _git_available():
        raise SyncError("git is not installed; install git to use lnk sync")
    # Validate before touching anything: this used to commit the whole
    # directory, rewrite .gitignore and untrack files in someone's project
    # repo, and only then refuse to re-point its origin.
    if remote and _is_repo(root):
        existing = _remote_url(root)
        if existing and existing != remote:
            # Re-pointing someone's existing origin (a workspace that lives
            # inside a project repo, say) would push the whole repo to the
            # memory remote. Make the person do that on purpose.
            raise SyncError(
                f"this workspace is already a git repo with origin {existing}; "
                "refusing to re-point it. Use a dedicated workspace, or run "
                "`git remote remove origin` there first if that is really what you want."
            )
    created = False
    if not _is_repo(root):
        _git(root, "init", "--initial-branch", "main", check=False)
        if not _is_repo(root):
            _git(root, "init")  # older git without --initial-branch
        created = True
    _ensure_commit_identity(root)
    ignore_updated = ensure_sync_gitignore(root)
    _stage_all(root)
    committed = False
    findings = _staged_secret_findings(root)
    if _has_staged_changes(root) and not findings:
        _git(root, "commit", "-m", "link sync: initial workspace")
        committed = True
    remote_set = False
    if remote:
        if not _remote_url(root):
            _git(root, "remote", "add", "origin", remote)
        remote_set = True
    private_tracked = tracked_private_paths(root)
    return {
        "initialized": created,
        "gitignore_updated": ignore_updated,
        "committed": committed,
        "remote": _remote_url(root),
        "remote_set": remote_set,
        "branch": _current_branch(root),
        "secret_findings": findings,
        "private_tracked": private_tracked,
        "warnings": [_private_tracked_warning(root, private_tracked)] if private_tracked else [],
    }


def sync_status(root: Path) -> dict[str, object]:
    root = root.expanduser().resolve()
    if not _git_available():
        return {"ready": False, "reason": "git is not installed"}
    if not _is_repo(root):
        return {"ready": False, "reason": "workspace is not a sync repo yet (run: lnk sync --init <remote-url>)"}
    branch = _current_branch(root)
    remote = _remote_url(root)
    dirty = bool(_git(root, "status", "--porcelain").stdout.strip())
    ahead = behind = None
    if remote:
        _git(root, "fetch", "origin", check=False)
        counts = _git(
            root, "rev-list", "--left-right", "--count",
            f"HEAD...origin/{branch}", check=False,
        ).stdout.split()
        if len(counts) == 2:
            ahead, behind = int(counts[0]), int(counts[1])
    return {
        "ready": bool(remote),
        "branch": branch,
        "remote": remote,
        "dirty": dirty,
        "ahead": ahead,
        "behind": behind,
    }


_MARKER_START = re.compile(rb"^<{7} ", re.MULTILINE)
_MARKER_END = re.compile(rb"^>{7} ", re.MULTILINE)


def _has_conflict_markers(data: bytes) -> bool:
    return bool(_MARKER_START.search(data) and _MARKER_END.search(data))


def _resolve_conflicts(
    root: Path,
    wiki_dir: Path,
    conflicted: list[str],
) -> list[dict[str, str]]:
    """Resolve merge conflicts without ever leaving markers in wiki files."""
    resolutions: list[dict[str, str]] = []
    for rel in conflicted:
        linked = _symlinked_component(root, rel)
        if linked:
            raise SyncError(f"refusing to merge {rel}: {linked} is a symlink")
        path = root / rel
        ours = _git_bytes(root, "show", f":2:{rel}").stdout
        theirs = _git_bytes(root, "show", f":3:{rel}").stdout
        written: bytes | None = None
        if rel == "wiki/log.md":
            merged = merge_log_texts(
                ours.decode("utf-8", errors="replace"), theirs.decode("utf-8", errors="replace"),
            ).encode("utf-8")
            path.write_bytes(merged)
            written = merged
            resolutions.append({"path": rel, "resolution": "log_union"})
        elif rel in GENERATED_WIKI_FILES:
            path.write_bytes(ours)
            written = ours
            resolutions.append({"path": rel, "resolution": "regenerated"})
        elif rel.startswith("wiki/") and rel.endswith(".md") and ours.strip() and theirs.strip():
            # Both machines changed this page: the remote version keeps the
            # original path; the local version becomes a sibling memory the
            # consolidate/duplicate machinery will pair for review.
            path.write_bytes(theirs)
            written = theirs
            sibling = path.with_name(f"{path.stem}-local-{platform.node().split('.')[0]}{path.suffix}")
            counter = 2
            while sibling.exists() or sibling.is_symlink():
                sibling = path.with_name(f"{path.stem}-local-{counter}{path.suffix}")
                counter += 1
            sibling.write_bytes(ours)
            _git(root, "--literal-pathspecs", "add", "--", str(sibling.relative_to(root)))
            resolutions.append({
                "path": rel,
                "resolution": "both_versions",
                "local_copy": str(sibling.relative_to(root)),
            })
        else:
            # Deleted on one side, or non-markdown: prefer the remote view.
            if theirs.strip():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(theirs)
                written = theirs
            elif path.exists():
                _git(root, "--literal-pathspecs", "rm", "-q", "--ignore-unmatch", "--", rel, check=False)
            resolutions.append({"path": rel, "resolution": "theirs"})
        if (written is not None and _has_conflict_markers(written)
                and not (_has_conflict_markers(ours) or _has_conflict_markers(theirs))):
            raise SyncError(f"refusing to commit {rel}: it still contains conflict markers")
        _git(root, "--literal-pathspecs", "add", "--", rel, check=False)
    return resolutions


def _private_files_on_disk(root: Path) -> list[str]:
    """Tracked private files that exist on disk (a pull must not delete them)."""
    if not _has_commit(root):
        return []
    listing = _git(root, "ls-tree", "-r", "-z", "--name-only", "HEAD", "--", *PRIVATE_TRACKED_PATHS,
                   check=False).stdout
    return [rel for rel in _z_names(listing) if (root / rel).is_file() and not (root / rel).is_symlink()]


def _set_aside_dirty_private(root: Path) -> tuple[dict[str, bytes], list[str]]:
    """Local edits to still-tracked private files, reset so a merge can run.

    Sync never stages private files, so an edit to a tracked raw/ capture
    (redact-capture edits in place) stayed dirty, and every later merge that
    touched it refused: "your local changes would be overwritten". Their
    bytes are kept here and written back after the merge; private files
    never sync, so the local copy always wins.
    """
    listing = _git(root, "diff", "--name-only", "-z", "HEAD", "--", *PRIVATE_TRACKED_PATHS, check=False).stdout
    saved: dict[str, bytes] = {}
    missing: list[str] = []
    for rel in _z_names(listing):
        path = root / rel
        if path.is_symlink() or _symlinked_component(root, str(Path(rel).parent)):
            continue
        if path.is_file():
            saved[rel] = path.read_bytes()
        elif not path.exists():
            missing.append(rel)
    if saved or missing:
        _git(root, "checkout", "HEAD", "--", *saved, *missing, check=False)
    return saved, missing


def _put_back_private(root: Path, saved: dict[str, bytes], missing: list[str]) -> None:
    for rel, data in saved.items():
        path = root / rel
        if path.is_symlink() or _symlinked_component(root, str(Path(rel).parent)):
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    for rel in missing:
        path = root / rel
        if path.is_file() and not path.is_symlink():
            path.unlink()


def _restore_private_files(root: Path, before: str, paths: list[str]) -> list[str]:
    """Put back private files the merge removed from disk (as untracked files).

    A remote commit that untracks raw/ would otherwise delete this
    machine's captures. The merge only deletes files identical to the
    pre-merge commit, so restoring from it is exact.
    """
    restored: list[str] = []
    for rel in paths:
        path = root / rel
        if path.exists() or path.is_symlink() or _symlinked_component(root, str(Path(rel).parent)):
            continue
        blob = _git_bytes(root, "show", f"{before}:{rel}")
        if blob.returncode != 0:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob.stdout)
        restored.append(rel)
    return restored


def _blocked(committed: bool, pulled: int, resolutions: list[dict[str, str]],
             findings: list[dict[str, object]], message: str, **extra: object) -> dict[str, object]:
    return {
        "synced": False,
        "committed": committed,
        "pulled": pulled,
        "pushed": False,
        "resolutions": resolutions,
        "secret_findings": findings,
        "message": message,
        **extra,
    }


def _merge_remote(root: Path, wiki_dir: Path, branch: str, regenerate: Callable[[], None]) -> list[dict[str, str]]:
    """Merge origin/<branch> into HEAD, resolving the conflicts Link understands."""
    resolutions: list[dict[str, str]] = []
    # --allow-unrelated-histories: two teammates (or two machines)
    # that ran --init independently share a remote without a common
    # ancestor; their first sync is exactly this bootstrap merge.
    merge = _git(root, "merge", "--no-edit", "--allow-unrelated-histories", f"origin/{branch}", check=False)
    if merge.returncode != 0:
        conflicted = _z_names(_git(root, "diff", "--name-only", "-z", "--diff-filter=U").stdout)
        if not conflicted:
            # The merge failed for another reason (untracked files in
            # the way, a hook, a lock). Committing and pushing on top
            # of that left MERGE_HEAD behind and a non-fast-forward
            # push; stop cleanly instead.
            _git(root, "merge", "--abort", check=False)
            detail = (merge.stderr or merge.stdout or "").strip()[:300]
            raise SyncError(f"could not merge the remote changes: {detail}")
        try:
            resolutions = _resolve_conflicts(root, wiki_dir, conflicted)
            unresolved = _z_names(_git(root, "diff", "--name-only", "-z", "--diff-filter=U").stdout)
            if unresolved:
                raise SyncError("could not resolve merge conflicts in: " + ", ".join(unresolved[:5]))
        except SyncError:
            _git(root, "merge", "--abort", check=False)
            raise
        regenerate()
        both = [r for r in resolutions if r["resolution"] == "both_versions"]
        append_log(
            wiki_dir,
            utc_timestamp(),
            "sync-merge",
            f"Merged remote changes with {len(resolutions)} conflict(s) resolved",
            [
                f"{r['path']}: {r['resolution']}" for r in resolutions
            ] + (["Hash chain re-anchored by this entry."]
                 if any(r["resolution"] == "log_union" for r in resolutions) else [])
              + ([f"Review both versions: run consolidate ({len(both)} pair(s))."] if both else []),
        )
        _stage_all(root)
        _git(root, "commit", "--no-edit", check=False)
    else:
        _rechain_clean_merged_log(root, wiki_dir)
        # A clean pull can bring new pages; index and backlinks are
        # generated, so rebuild them instead of trusting the merge.
        regenerate()
    return resolutions


def _rechain_clean_merged_log(root: Path, wiki_dir: Path) -> None:
    """Rebuild the log chain when git combined both machines' logs by itself.

    Only a conflicted log went through merge_log_texts. When git merged
    wiki/log.md cleanly, one machine's entries sat after the other's with
    their own previous hashes, and `lnk doctor` reported a broken chain on
    both machines after ordinary two-machine use.
    """
    parents = _git(root, "rev-list", "--parents", "-n", "1", "HEAD", check=False).stdout.split()
    if len(parents) < 3:
        return  # a fast-forward: the log is exactly one side's
    rel = "wiki/log.md"
    ours = _git_bytes(root, "show", f"{parents[1]}:{rel}")
    theirs = _git_bytes(root, "show", f"{parents[2]}:{rel}")
    path = root / rel
    if ours.returncode != 0 or theirs.returncode != 0 or not path.is_file() or path.is_symlink():
        return
    current = path.read_bytes()
    if current in (ours.stdout, theirs.stdout):
        return  # git took one side whole; that side's chain is intact
    merged = merge_log_texts(
        ours.stdout.decode("utf-8", errors="replace"), theirs.stdout.decode("utf-8", errors="replace"),
    )
    path.write_text(merged, encoding="utf-8")
    append_log(
        wiki_dir, utc_timestamp(), "sync-merge", "Merged remote log",
        ["wiki/log.md: log_union", "Hash chain re-anchored by this entry."],
    )
    _git(root, "add", "--", rel)
    _git(root, "commit", "-m", "link sync: re-chain merged log", check=False)


def sync_workspace(
    root: Path,
    wiki_dir: Path,
    *,
    regenerate: Callable[[], None],
    forbid_symlinks: bool = False,
) -> dict[str, object]:
    """The daily verb: scan, commit, integrate the remote, gate secrets, push.

    `forbid_symlinks` is for shared (team) repos: any symlink in the
    worktree or in the incoming remote tree stops the sync before anything
    is read, written or merged through it.
    """
    root = root.expanduser().resolve()
    if not _git_available():
        raise SyncError("git is not installed; install git to use lnk sync")
    if not _is_repo(root):
        raise SyncError("workspace is not a sync repo yet (run: lnk sync --init <remote-url>)")
    branch = _current_branch(root)
    remote = _remote_url(root)
    if not remote:
        raise SyncError("no remote configured (run: lnk sync --init <remote-url>)")
    if forbid_symlinks:
        _refuse_symlinks(_symlinks_under(root), str(root))

    _ensure_commit_identity(root)
    ensure_sync_gitignore(root)
    private_tracked = tracked_private_paths(root)
    warnings = [_private_tracked_warning(root, private_tracked)] if private_tracked else []
    _stage_all(root)
    # Scan before committing: a blocked push used to leave the secret in a
    # local commit, which the next (redacted) sync then pushed.
    staged_findings = _staged_secret_findings(root)
    if staged_findings:
        return _blocked(
            False, 0, [], staged_findings,
            "Sync stopped before committing: changes contain secret-looking values. "
            "Redact them (lnk redact-capture / edit the page), then sync again.",
            warnings=warnings, private_tracked=private_tracked,
        )
    committed = False
    if _has_staged_changes(root):
        host = platform.node().split(".")[0]
        _git(root, "commit", "-m", f"link sync: {host} {utc_timestamp()}")
        committed = True

    fetch = _git(root, "fetch", "origin", check=False)
    if fetch.returncode != 0:
        raise SyncError(f"could not reach the remote: {(fetch.stderr or '').strip()[:300]}")

    resolutions: list[dict[str, str]] = []
    restored_private: list[str] = []
    pulled = 0
    has_remote_branch = _has_commit(root, f"origin/{branch}")
    if has_remote_branch:
        if forbid_symlinks:
            _refuse_symlinks(_tracked_symlinks(root, f"origin/{branch}"), "the shared remote")
        behind = _git(root, "rev-list", "--count", f"HEAD..origin/{branch}", check=False).stdout.strip()
        pulled = int(behind or 0)
        if pulled:
            before = _git(root, "rev-parse", "HEAD", check=False).stdout.strip()
            private_before = _private_files_on_disk(root)
            dirty_private, deleted_private = _set_aside_dirty_private(root)
            try:
                resolutions = _merge_remote(root, wiki_dir, branch, regenerate)
            finally:
                _put_back_private(root, dirty_private, deleted_private)
            restored_private = _restore_private_files(root, before, private_before)
            # The pulled log is another machine's history, verified by its
            # chain; accept its head as this machine's anchor.
            refresh_log_anchor(wiki_dir)

    findings = _outgoing_secret_findings(root, branch)
    pushed = False
    if findings:
        return _blocked(
            committed, pulled, resolutions, findings,
            "Push blocked: outgoing commits contain secret-looking values. "
            "Redact them (lnk redact-capture / edit the page). "
            + _history_rewrite_hint(root, branch, has_remote_branch),
            warnings=warnings, private_tracked=private_tracked,
        )
    ahead = _git(root, "rev-list", "--count", f"origin/{branch}..HEAD", check=False).stdout.strip() if has_remote_branch else "1"
    if not has_remote_branch or int(ahead or 0) > 0:
        push = _git(root, "push", "-u", "origin", branch, check=False)
        if push.returncode != 0:
            raise SyncError(f"push failed: {(push.stderr or '').strip()[:300]}")
        pushed = True
    return {
        "synced": True,
        "committed": committed,
        "pulled": pulled,
        "pushed": pushed,
        "resolutions": resolutions,
        "secret_findings": [],
        "private_tracked": private_tracked,
        "restored_private": restored_private,
        "warnings": warnings,
        "both_versions": [r for r in resolutions if r["resolution"] == "both_versions"],
    }


# ── Team memory: shared visibility:team memories on the same sync rails ──
# The team repo is deliberately a mini Link workspace (wiki/memories plus
# its own tamper-evident log), so every sync guarantee — secret push-gate,
# both-versions conflicts, log-chain union — applies to the shared brain
# verbatim. Only memories the user explicitly marked visibility: team ever
# enter it; private and project memories never leave the personal wiki.


def team_config(root: Path) -> dict[str, str] | None:
    """The machine-local team configuration, or None when not set up."""
    path = root.expanduser().resolve() / TEAM_CONFIG_FILE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    team_dir = str(payload.get("dir") or "").strip()
    return {"dir": team_dir} if team_dir else None


def team_init(root: Path, team_dir: Path, remote: str | None = None) -> dict[str, object]:
    """Create/attach the shared team workspace and remember where it lives."""
    root = root.expanduser().resolve()
    team_root = team_dir.expanduser().resolve()
    if team_root.exists():
        _refuse_symlinks(_symlinks_under(team_root), str(team_root))
    team_wiki = team_root / "wiki"
    (team_wiki / "memories").mkdir(parents=True, exist_ok=True)
    log_path = team_wiki / "log.md"
    if not log_path.exists():
        log_path.write_text("# Link Team Log\n\n", encoding="utf-8")
    readme = team_root / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Link team memory\n\n"
            "Shared `visibility: team` memories, synced by `lnk team-sync`.\n"
            "Every entry was reviewed by the teammate who shared it; the log\n"
            "is hash-chained and merges declare their re-anchor.\n",
            encoding="utf-8",
        )
    init_report = sync_init(team_root, remote=remote)
    (root / TEAM_CONFIG_FILE).write_text(
        json.dumps({"dir": str(team_root)}, indent=2) + "\n", encoding="utf-8",
    )
    ensure_sync_gitignore(root)
    return {**init_report, "team_dir": str(team_root)}


def _memory_visibility(path: Path) -> str:
    try:
        meta, _ = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""
    return str(meta.get("visibility") or "").strip().lower()


def _memory_is_active(path: Path) -> bool:
    try:
        meta, _ = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False
    return str(meta.get("status") or "active").strip().lower() == "active"


def _imported_from_team(path: Path) -> bool:
    try:
        meta, _ = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False
    # A reviewed import the person then edited carries originally_imported_from
    # (memory.update_memory_page): still the teammate's memory, with a local
    # change. Exporting it overwrote their page and undid their deletions.
    return "team" in {
        str(meta.get("imported_from") or "").strip().lower(),
        str(meta.get("originally_imported_from") or "").strip().lower(),
    }


def _refuse_symlinked_dirs(*paths: Path) -> None:
    linked = [str(path) for path in paths if path.is_symlink()]
    if linked:
        raise SyncError(
            "refusing to use the team workspace: " + ", ".join(linked) + " is a symlink. "
            "A symlink in a shared repo can point anywhere on your disk; remove it and sync again."
        )


def export_team_memories(wiki_dir: Path, team_wiki: Path) -> list[str]:
    """Mirror local active visibility:team memories into the team repo.

    Only memories authored here are shared. A page carrying
    `imported_from: team` is a teammate's memory this machine merely
    imported; exporting it undid the teammate's deletion (and pushed the
    local pending-review copy back). To re-share one deliberately, remove
    `imported_from` from its frontmatter.
    """
    exported: list[str] = []
    source_dir = wiki_dir / "memories"
    target_dir = team_wiki / "memories"
    _refuse_symlinked_dirs(team_wiki, target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    if not source_dir.exists():
        return exported
    for path in sorted(source_dir.glob("*.md")):
        # A symlink is not a memory someone reviewed; and writing through a
        # symlinked target would overwrite whatever file it points at.
        if path.is_symlink() or not path.is_file():
            continue
        if _memory_visibility(path) != "team" or not _memory_is_active(path):
            continue
        if _imported_from_team(path):
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        target = target_dir / path.name
        if target.is_symlink():
            continue
        if target.exists() and target.read_text(encoding="utf-8", errors="replace") == content:
            continue
        target.write_text(content, encoding="utf-8")
        exported.append(path.stem)
    return exported


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_import_ledger(path: Path) -> dict[str, dict[str, str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    imported = payload.get("imported") if isinstance(payload, dict) else None
    return {str(k): dict(v) for k, v in imported.items() if isinstance(v, dict)} if isinstance(imported, dict) else {}


def _save_import_ledger(path: Path, ledger: dict[str, dict[str, str]]) -> None:
    path.write_text(json.dumps({"imported": ledger}, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def import_team_memories(
    team_wiki: Path,
    wiki_dir: Path,
    *,
    ledger_path: Path | None = None,
) -> dict[str, list]:
    """Bring teammates' memories into the local wiki, through the review gate.

    A teammate reviewed a memory for their own use; that is not your review.
    So a team memory arrives as `review_status: pending` with
    `imported_from: team`, and it has to earn its place like any capture:
    it must really be `visibility: team` and active, carry no secret-shaped
    value and no injection-shaped instruction, and be a regular file (a
    symlink in a shared repo can point at any file on your disk). Anything
    else is rejected and reported, never written. Local versions win, and a
    memory you forgot or archived after importing it stays gone.
    """
    imported: list[str] = []
    conflicts: list[str] = []
    rejected: list[dict[str, str]] = []
    skipped_forgotten: list[str] = []
    source_dir = team_wiki / "memories"
    target_dir = wiki_dir / "memories"
    _refuse_symlinked_dirs(team_wiki, source_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    ledger_file = ledger_path or (wiki_dir.parent / TEAM_IMPORT_LEDGER)
    ledger = _load_import_ledger(ledger_file)
    changed_ledger = False
    result: dict[str, list] = {
        "imported": imported, "conflicts": conflicts,
        "rejected": rejected, "skipped_forgotten": skipped_forgotten,
    }
    if not source_dir.exists():
        return result
    for path in sorted(source_dir.glob("*.md")):
        name = path.stem
        if path.is_symlink() or not path.is_file():
            rejected.append({"name": name, "reason": "not a regular file (symlink)"})
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        meta, _ = parse_frontmatter(content)
        if str(meta.get("visibility") or "").strip().lower() != "team":
            rejected.append({"name": name, "reason": "not marked visibility: team"})
            continue
        if str(meta.get("status") or "active").strip().lower() != "active":
            rejected.append({"name": name, "reason": f"status is {meta.get('status')}"})
            continue
        secrets = secret_value_warnings(content)
        if secrets:
            rejected.append({"name": name, "reason": "secret-looking value: " + ", ".join(secrets)})
            continue
        injections = injected_instruction_warnings(content)
        if injections:
            rejected.append({"name": name, "reason": "injection-shaped instruction: " + ", ".join(injections)})
            continue
        team_hash = _sha256(content)
        target = target_dir / path.name
        if target.is_symlink():
            rejected.append({"name": name, "reason": "local path is a symlink"})
            continue
        previous = ledger.get(name)
        if not target.exists():
            if previous:
                # Imported before and gone now: the person forgot or moved it.
                skipped_forgotten.append(name)
                continue
            gated = update_frontmatter_fields(content, {
                "review_status": "pending",
                "imported_from": "team",
            }, remove={"reviewed_at"})
            target.write_text(gated, encoding="utf-8")
            ledger[name] = {"team_sha256": team_hash}
            changed_ledger = True
            imported.append(name)
            continue
        if previous and previous.get("team_sha256") != team_hash:
            # The teammate changed it since you imported it; yours stays.
            conflicts.append(name)
        elif not previous and target.read_text(encoding="utf-8", errors="replace") != content:
            conflicts.append(name)
    if changed_ledger:
        _save_import_ledger(ledger_file, ledger)
    return result


def team_sync_workspace(
    root: Path,
    wiki_dir: Path,
    *,
    regenerate: Callable[[], None],
) -> dict[str, object]:
    """Export team memories, sync the shared repo, import teammates' memories."""
    root = root.expanduser().resolve()
    config = team_config(root)
    if not config:
        raise SyncError(
            "team memory is not set up (run: lnk team-sync --init --remote <git-url>)"
        )
    team_root = Path(config["dir"])
    team_wiki = team_root / "wiki"
    if not team_wiki.exists():
        raise SyncError(f"team workspace missing at {team_root} (re-run: lnk team-sync --init)")
    # Nothing in the shared repo is read or written through a symlink: a
    # teammate's committed `wiki/log.md -> ~/.zshrc` made the next log
    # append (or log merge) write into that file.
    _refuse_symlinks(_symlinks_under(team_root), str(team_root))

    exported = export_team_memories(wiki_dir, team_wiki)
    if exported:
        append_log(
            team_wiki, utc_timestamp(), "team-export",
            f"Shared {len(exported)} team memory(ies) from {platform.node().split('.')[0]}",
            [f"memory: {name}" for name in exported],
        )
    sync_report = sync_workspace(team_root, team_wiki, regenerate=lambda: None, forbid_symlinks=True)
    _refuse_symlinks(_symlinks_under(team_root), str(team_root))
    imports = import_team_memories(team_wiki, wiki_dir, ledger_path=root / TEAM_IMPORT_LEDGER)
    if imports["imported"] or imports["conflicts"] or imports["rejected"]:
        append_log(
            wiki_dir, utc_timestamp(), "team-sync",
            f"Imported {len(imports['imported'])} team memory(ies) for review; "
            f"{len(imports['conflicts'])} kept local over team version; "
            f"{len(imports['rejected'])} rejected",
            [f"imported (pending review): {name}" for name in imports["imported"]]
            + [f"kept local: {name}" for name in imports["conflicts"]]
            + [f"rejected: {item['name']} ({item['reason']})" for item in imports["rejected"]],
        )
        if imports["imported"]:
            regenerate()
    return {
        "exported": exported,
        "imported": imports["imported"],
        "conflicts": imports["conflicts"],
        "rejected": imports["rejected"],
        "skipped_forgotten": imports["skipped_forgotten"],
        "team_dir": str(team_root),
        "sync": sync_report,
    }
