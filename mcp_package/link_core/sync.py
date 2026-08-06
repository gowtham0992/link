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

import json
import platform
import subprocess
from pathlib import Path
from typing import Callable

from .frontmatter import parse_frontmatter
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
    "/.link-team.json",
    "/.link-usage.json",
    # Obsidian's per-machine UI state: changes on every open, and syncing it
    # between machines produces pointless conflicts. Themes/plugins in the
    # rest of .obsidian/ still sync so the vault feels the same everywhere.
    "/wiki/.obsidian/workspace.json",
)

TEAM_CONFIG_FILE = ".link-team.json"

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
    _ensure_commit_identity(root)
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
            sibling = path.with_name(f"{path.stem}-local-{platform.node().split('.')[0]}{path.suffix}")
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

    _ensure_commit_identity(root)
    ensure_sync_gitignore(root)
    _git(root, "add", "-A")
    committed = False
    if _git(root, "status", "--porcelain").stdout.strip():
        host = platform.node().split(".")[0]
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
            # --allow-unrelated-histories: two teammates (or two machines)
            # that ran --init independently share a remote without a common
            # ancestor; their first sync is exactly this bootstrap merge.
            merge = _git(root, "merge", "--no-edit", "--allow-unrelated-histories", f"origin/{branch}", check=False)
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


def export_team_memories(wiki_dir: Path, team_wiki: Path) -> list[str]:
    """Mirror local active visibility:team memories into the team repo."""
    exported: list[str] = []
    source_dir = wiki_dir / "memories"
    target_dir = team_wiki / "memories"
    target_dir.mkdir(parents=True, exist_ok=True)
    if not source_dir.exists():
        return exported
    for path in sorted(source_dir.glob("*.md")):
        if _memory_visibility(path) != "team" or not _memory_is_active(path):
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        target = target_dir / path.name
        if target.exists() and target.read_text(encoding="utf-8", errors="replace") == content:
            continue
        target.write_text(content, encoding="utf-8")
        exported.append(path.stem)
    return exported


def import_team_memories(team_wiki: Path, wiki_dir: Path) -> dict[str, list[str]]:
    """Bring teammates' memories into the local wiki; local versions win."""
    imported: list[str] = []
    conflicts: list[str] = []
    source_dir = team_wiki / "memories"
    target_dir = wiki_dir / "memories"
    target_dir.mkdir(parents=True, exist_ok=True)
    if not source_dir.exists():
        return {"imported": imported, "conflicts": conflicts}
    for path in sorted(source_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8", errors="replace")
        target = target_dir / path.name
        if not target.exists():
            target.write_text(content, encoding="utf-8")
            imported.append(path.stem)
            continue
        if target.read_text(encoding="utf-8", errors="replace") != content:
            # The local version wins; the pair is the human's to reconcile
            # (edit and re-share, or accept the team version deliberately).
            conflicts.append(path.stem)
    return {"imported": imported, "conflicts": conflicts}


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

    exported = export_team_memories(wiki_dir, team_wiki)
    if exported:
        append_log(
            team_wiki, utc_timestamp(), "team-export",
            f"Shared {len(exported)} team memory(ies) from {platform.node().split('.')[0]}",
            [f"memory: {name}" for name in exported],
        )
    sync_report = sync_workspace(team_root, team_wiki, regenerate=lambda: None)
    imports = import_team_memories(team_wiki, wiki_dir)
    if imports["imported"] or imports["conflicts"]:
        append_log(
            wiki_dir, utc_timestamp(), "team-sync",
            f"Imported {len(imports['imported'])} team memory(ies); "
            f"{len(imports['conflicts'])} kept local over team version",
            [f"imported: {name}" for name in imports["imported"]]
            + [f"kept local: {name}" for name in imports["conflicts"]],
        )
        if imports["imported"]:
            regenerate()
    return {
        "exported": exported,
        "imported": imports["imported"],
        "conflicts": imports["conflicts"],
        "team_dir": str(team_root),
        "sync": sync_report,
    }
