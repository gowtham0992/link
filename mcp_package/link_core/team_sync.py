"""Read-only Git team-sync guidance for Link workspaces."""
from __future__ import annotations

import configparser
from pathlib import Path
from typing import Mapping

from .memory import default_memory_visibility, is_active_memory, memory_inbox, memory_records
from .mcp_verify import display_command


def _link_root(target: Path) -> Path:
    root = target.expanduser().resolve()
    if root.name == "wiki" and (root / "_link_schema.json").exists():
        return root.parent
    return root


def _find_git_root(start: Path) -> Path | None:
    current = start
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _git_remote_names(git_root: Path | None) -> list[str]:
    if git_root is None:
        return []
    config_path = git_root / ".git" / "config"
    if not config_path.exists() or not config_path.is_file():
        return []
    parser = configparser.ConfigParser()
    try:
        parser.read(config_path, encoding="utf-8")
    except configparser.Error:
        return []
    names: list[str] = []
    for section in parser.sections():
        if section.startswith('remote "') and section.endswith('"'):
            names.append(section.removeprefix('remote "').removesuffix('"'))
    return sorted(names)


def _gitignore_raw_status(root: Path) -> dict[str, object]:
    path = root / ".gitignore"
    if not path.exists():
        return {"path": str(path), "exists": False, "protects_raw": False}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return {"path": str(path), "exists": True, "protects_raw": False, "error": str(exc)}
    normalized = {line.strip().replace("\\", "/") for line in lines if line.strip() and not line.lstrip().startswith("#")}
    protects_raw = any(line in {"raw/", "raw/*", "/raw/", "/raw/*"} for line in normalized)
    return {"path": str(path), "exists": True, "protects_raw": protects_raw}


def _record_visibility(record: Mapping[str, object]) -> str:
    scope = str(record.get("scope") or "user").lower()
    return str(record.get("visibility") or default_memory_visibility(scope)).lower()


def _action(label: str, command: list[str]) -> dict[str, str]:
    return {
        "label": label,
        "command_text": display_command(command),
    }


def _memory_share_status(wiki_dir: Path) -> dict[str, object]:
    if not wiki_dir.exists():
        return {
            "active_count": 0,
            "review_count": 0,
            "user_scoped_count": 0,
            "private_visibility_count": 0,
            "project_visibility_count": 0,
            "team_visibility_count": 0,
            "project_scoped_count": 0,
            "global_scoped_count": 0,
            "safe_for_team_git": False,
        }
    records = memory_records(wiki_dir, include_body=False)
    active_records = [record for record in records if is_active_memory(record)]
    review_count = int(memory_inbox(active_records, include_archived=False).get("review_count") or 0)
    user_scoped = [
        record for record in active_records
        if str(record.get("scope") or "user").lower() == "user"
    ]
    private_visibility = [
        record for record in active_records
        if _record_visibility(record) == "private"
    ]
    project_visibility = [
        record for record in active_records
        if _record_visibility(record) == "project"
    ]
    team_visibility = [
        record for record in active_records
        if _record_visibility(record) == "team"
    ]
    project_scoped = [
        record for record in active_records
        if str(record.get("scope") or "").lower() == "project"
    ]
    global_scoped = [
        record for record in active_records
        if str(record.get("scope") or "").lower() == "global"
    ]
    return {
        "active_count": len(active_records),
        "review_count": review_count,
        "user_scoped_count": len(user_scoped),
        "private_visibility_count": len(private_visibility),
        "project_visibility_count": len(project_visibility),
        "team_visibility_count": len(team_visibility),
        "project_scoped_count": len(project_scoped),
        "global_scoped_count": len(global_scoped),
        "user_scoped": [
            {
                "name": str(record.get("name") or ""),
                "title": str(record.get("title") or record.get("name") or ""),
                "path": str(record.get("path") or ""),
            }
            for record in user_scoped[:8]
        ],
        "private_visibility": [
            {
                "name": str(record.get("name") or ""),
                "title": str(record.get("title") or record.get("name") or ""),
                "path": str(record.get("path") or ""),
            }
            for record in private_visibility[:8]
        ],
        "safe_for_team_git": review_count == 0 and len(private_visibility) == 0,
    }


def build_team_sync_payload(target: Path, *, remote: str | None = None) -> dict[str, object]:
    """Return a read-only plan for sharing a Link workspace through Git."""
    root = _link_root(target)
    wiki_dir = root / "wiki"
    git_root = _find_git_root(root)
    remotes = _git_remote_names(git_root)
    gitignore = _gitignore_raw_status(root)
    memory_share = _memory_share_status(wiki_dir)
    remote_clean = str(remote or "").strip()

    warnings: list[str] = []
    if not wiki_dir.exists():
        warnings.append("Link wiki is missing. Run lnk init before preparing team sync.")
    if git_root and not bool(gitignore.get("protects_raw")):
        warnings.append("raw/ is not protected by the workspace .gitignore; do not push until raw sources are intentionally handled.")
    if git_root and not remotes and not remote_clean:
        warnings.append("Git repository has no remote configured.")
    if int(memory_share.get("review_count") or 0):
        warnings.append("memory review inbox is not clear; review or archive pending memories before team sharing.")
    if int(memory_share.get("private_visibility_count") or 0):
        warnings.append("active private memories would be included by git add wiki; do not team-sync until they are archived or marked visibility: project/team intentionally.")

    setup_actions: list[dict[str, str]] = []
    sync_actions: list[dict[str, str]] = [
        _action("check Link health", ["lnk", "health", str(root)]),
        _action("review pending memories", ["lnk", "memory-inbox", str(root)]),
        _action("validate before sharing", ["lnk", "validate", str(root)]),
        _action("backup before sharing", ["lnk", "backup", str(root)]),
    ]
    if git_root is None:
        setup_actions.extend([
            _action("initialize Git", ["git", "-C", str(root), "init"]),
            _action("stage shared memory files", ["git", "-C", str(root), "add", "wiki", "LINK.md", ".gitignore"]),
            _action("commit shared memory baseline", ["git", "-C", str(root), "commit", "-m", "Initialize Link shared memory"]),
        ])
        if remote_clean:
            setup_actions.append(_action("add remote", ["git", "-C", str(root), "remote", "add", "origin", remote_clean]))
            setup_actions.append(_action("push first branch", ["git", "-C", str(root), "push", "-u", "origin", "main"]))
    else:
        sync_actions.extend([
            _action("inspect changes", ["git", "-C", str(git_root), "status", "--short"]),
            _action("pull first", ["git", "-C", str(git_root), "pull", "--ff-only"]),
            _action("stage shared memory files", ["git", "-C", str(git_root), "add", str(root / "wiki"), str(root / "LINK.md"), str(root / ".gitignore")]),
            _action("commit reviewed memory updates", ["git", "-C", str(git_root), "commit", "-m", "Update Link shared memory"]),
        ])
        if remotes or remote_clean:
            if remote_clean and not remotes:
                sync_actions.append(_action("add remote", ["git", "-C", str(git_root), "remote", "add", "origin", remote_clean]))
            sync_actions.append(_action("push reviewed updates", ["git", "-C", str(git_root), "push"]))

    return {
        "target": str(root),
        "wiki": str(wiki_dir),
        "git_root": str(git_root) if git_root else "",
        "in_git": git_root is not None,
        "remote": remote_clean,
        "remotes": remotes,
        "gitignore": gitignore,
        "memory_share": memory_share,
        "ready": bool(
            wiki_dir.exists()
            and git_root
            and gitignore.get("protects_raw")
            and memory_share.get("safe_for_team_git")
        ),
        "warnings": warnings,
        "setup_actions": setup_actions,
        "sync_actions": sync_actions,
        "notes": [
            "Share wiki/ and LINK.md for team agent memory.",
            "Keep raw/ private unless every source is approved for the team.",
            "Keep visibility: private memories out of team Git until the user intentionally converts or archives them.",
            "Review memory inbox and validation before pushing shared memory updates.",
        ],
    }


def render_team_sync_text(payload: Mapping[str, object]) -> tuple[int, str]:
    """Render Git team-sync guidance without running Git commands."""
    ready = bool(payload.get("ready"))
    lines = [
        f"Link team sync: {payload.get('target')}",
        "",
        f"Status: {'ready for reviewed Git sharing' if ready else 'needs setup or review'}",
        f"Git: {payload.get('git_root') or 'not initialized'}",
        f"raw/ protection: {'ok' if (payload.get('gitignore') or {}).get('protects_raw') else 'needs review'}",
    ]
    memory_share = payload.get("memory_share") if isinstance(payload.get("memory_share"), Mapping) else {}
    if memory_share:
        lines.append(
            "Memory share gate: "
            f"{memory_share.get('active_count', 0)} active · "
            f"{memory_share.get('review_count', 0)} review · "
            f"{memory_share.get('private_visibility_count', 0)} private"
        )
    remotes = payload.get("remotes")
    if isinstance(remotes, list) and remotes:
        lines.append("Remotes: " + ", ".join(str(item) for item in remotes))
    warnings = payload.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"- {warning}" for warning in warnings)

    setup_actions = payload.get("setup_actions")
    if isinstance(setup_actions, list) and setup_actions:
        lines.extend(["", "One-time setup:"])
        for action in setup_actions:
            if isinstance(action, Mapping):
                lines.append(f"- {action.get('label')}: {action.get('command_text')}")

    sync_actions = payload.get("sync_actions")
    if isinstance(sync_actions, list) and sync_actions:
        lines.extend(["", "Safe sync loop:"])
        for action in sync_actions:
            if isinstance(action, Mapping):
                lines.append(f"- {action.get('label')}: {action.get('command_text')}")

    notes = payload.get("notes")
    if isinstance(notes, list) and notes:
        lines.extend(["", "Notes:"])
        lines.extend(f"- {note}" for note in notes)
    return 0, "\n".join(lines)
