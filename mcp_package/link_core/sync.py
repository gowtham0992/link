"""Serverless memory sync for Link: your own git remote, no service.

`lnk sync` moves reviewed memory between machines through a git remote the
user controls (a private GitHub repo, a homelab bare repo, anything git can
push to). Three promises distinguish it from plain git:

- **Secrets never leave.** Before anything is pushed, every outgoing wiki
  change is scanned with the same detector that guards memory writes; a
  credential-shaped value aborts the push with the file named.
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

import socket
import subprocess
from pathlib import Path
from typing import Callable

from .log import append_log, merge_log_texts, utc_timestamp
from .security import secret_value_warnings

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
)

# Regenerated after every merge instead of being merged.
GENERATED_WIKI_FILES = ("wiki/index.md", "wiki/_backlinks.json", "wiki/_link_schema.json")


class SyncError(RuntimeError):
    """A sync step failed in a way the user must resolve."""


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, timeout=120,
    )
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise SyncError(f"git {' '.join(args[:2])} failed: {message[:400]}")
    return result


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=10)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def _is_repo(root: Path) -> bool:
    return (root / ".git").exists()


def _current_branch(root: Path) -> str:
    return _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "main"


def _remote_url(root: Path) -> str | None:
    result = _git(root, "remote", "get-url", "origin", check=False)
    url = result.stdout.strip()
    return url or None


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


def sync_init(root: Path, remote: str | None = None) -> dict[str, object]:
    """Turn the workspace into a sync-ready git repo. Idempotent."""
    root = root.expanduser().resolve()
    if not _git_available():
        raise SyncError("git is not installed; install git to use lnk sync")
    created = False
    if not _is_repo(root):
        _git(root, "init", "--initial-branch", "main", check=False)
        if not _is_repo(root):
            _git(root, "init")  # older git without --initial-branch
        created = True
    ignore_updated = ensure_sync_gitignore(root)
    _git(root, "add", "-A")
    dirty = bool(_git(root, "status", "--porcelain").stdout.strip())
    committed = False
    if dirty:
        _git(root, "commit", "-m", "link sync: initial workspace")
        committed = True
    remote_set = False
    if remote:
        if _remote_url(root):
            _git(root, "remote", "set-url", "origin", remote)
        else:
            _git(root, "remote", "add", "origin", remote)
        remote_set = True
    return {
        "initialized": created,
        "gitignore_updated": ignore_updated,
        "committed": committed,
        "remote": _remote_url(root),
        "remote_set": remote_set,
        "branch": _current_branch(root),
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


def _outgoing_secret_findings(root: Path, branch: str) -> list[dict[str, str]]:
    """Scan every outgoing wiki change for secret-shaped values."""
    upstream = f"origin/{branch}"
    has_upstream = _git(root, "rev-parse", "--verify", upstream, check=False).returncode == 0
    if has_upstream:
        changed = _git(root, "diff", "--name-only", f"{upstream}..HEAD", check=False).stdout.splitlines()
    else:
        changed = _git(root, "ls-files", "wiki").stdout.splitlines()
    findings: list[dict[str, str]] = []
    for rel in changed:
        rel = rel.strip()
        if not rel.startswith("wiki/"):
            continue
        path = root / rel
        if not path.is_file():
            continue
        try:
            labels = secret_value_warnings(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        for label in labels:
            findings.append({"path": rel, "label": label})
    return findings


def _resolve_conflicts(
    root: Path,
    wiki_dir: Path,
    conflicted: list[str],
) -> list[dict[str, str]]:
    """Resolve merge conflicts without ever leaving markers in wiki files."""
    resolutions: list[dict[str, str]] = []
    for rel in conflicted:
        path = root / rel
        ours = _git(root, "show", f":2:{rel}", check=False).stdout
        theirs = _git(root, "show", f":3:{rel}", check=False).stdout
        if rel == "wiki/log.md":
            path.write_text(merge_log_texts(ours, theirs), encoding="utf-8")
            resolutions.append({"path": rel, "resolution": "log_union"})
        elif rel in GENERATED_WIKI_FILES:
            path.write_text(ours, encoding="utf-8")
            resolutions.append({"path": rel, "resolution": "regenerated"})
        elif rel.startswith("wiki/") and rel.endswith(".md") and ours.strip() and theirs.strip():
            # Both machines changed this page: the remote version keeps the
            # original path; the local version becomes a sibling memory the
            # consolidate/duplicate machinery will pair for review.
            path.write_text(theirs, encoding="utf-8")
            sibling = path.with_name(f"{path.stem}-local-{socket.gethostname().split('.')[0]}{path.suffix}")
            counter = 2
            while sibling.exists():
                sibling = path.with_name(f"{path.stem}-local-{counter}{path.suffix}")
                counter += 1
            sibling.write_text(ours, encoding="utf-8")
            _git(root, "add", str(sibling.relative_to(root)))
            resolutions.append({
                "path": rel,
                "resolution": "both_versions",
                "local_copy": str(sibling.relative_to(root)),
            })
        else:
            # Deleted on one side, or non-markdown: prefer the remote view.
            if theirs.strip():
                path.write_text(theirs, encoding="utf-8")
            elif path.exists():
                _git(root, "rm", "-q", "--ignore-unmatch", rel, check=False)
            resolutions.append({"path": rel, "resolution": "theirs"})
        _git(root, "add", rel, check=False)
    return resolutions


def sync_workspace(
    root: Path,
    wiki_dir: Path,
    *,
    regenerate: Callable[[], None],
) -> dict[str, object]:
    """The daily verb: commit, integrate the remote, gate secrets, push."""
    root = root.expanduser().resolve()
    if not _git_available():
        raise SyncError("git is not installed; install git to use lnk sync")
    if not _is_repo(root):
        raise SyncError("workspace is not a sync repo yet (run: lnk sync --init <remote-url>)")
    branch = _current_branch(root)
    remote = _remote_url(root)
    if not remote:
        raise SyncError("no remote configured (run: lnk sync --init <remote-url>)")

    ensure_sync_gitignore(root)
    _git(root, "add", "-A")
    committed = False
    if _git(root, "status", "--porcelain").stdout.strip():
        host = socket.gethostname().split(".")[0]
        _git(root, "commit", "-m", f"link sync: {host} {utc_timestamp()}")
        committed = True

    fetch = _git(root, "fetch", "origin", check=False)
    if fetch.returncode != 0:
        raise SyncError(f"could not reach the remote: {(fetch.stderr or '').strip()[:300]}")

    resolutions: list[dict[str, str]] = []
    pulled = 0
    has_remote_branch = _git(root, "rev-parse", "--verify", f"origin/{branch}", check=False).returncode == 0
    if has_remote_branch:
        behind = _git(root, "rev-list", "--count", f"HEAD..origin/{branch}", check=False).stdout.strip()
        pulled = int(behind or 0)
        if pulled:
            merge = _git(root, "merge", "--no-edit", f"origin/{branch}", check=False)
            if merge.returncode != 0:
                conflicted = [
                    line.strip() for line in
                    _git(root, "diff", "--name-only", "--diff-filter=U").stdout.splitlines()
                    if line.strip()
                ]
                resolutions = _resolve_conflicts(root, wiki_dir, conflicted)
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
                _git(root, "add", "-A")
                _git(root, "commit", "--no-edit", check=False)

    findings = _outgoing_secret_findings(root, branch)
    pushed = False
    if findings:
        return {
            "synced": False,
            "committed": committed,
            "pulled": pulled,
            "pushed": False,
            "resolutions": resolutions,
            "secret_findings": findings,
            "message": (
                "Push blocked: outgoing changes contain secret-looking values. "
                "Redact them (lnk redact-capture / edit the page), then sync again."
            ),
        }
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
        "both_versions": [r for r in resolutions if r["resolution"] == "both_versions"],
    }
