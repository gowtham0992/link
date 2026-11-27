"""Folders the person marked untrusted: Link stays quiet in them.

A repository cloned to review, a vendor drop, a pull request from a
stranger: an agent working there reads text nobody vetted. Two things can
then go wrong with memory. Text in the folder can talk the agent into
"remembering" something, and it can talk the agent into repeating what the
session brief gave it. So in a folder marked untrusted Link gives the agent
no memory and proposes none from the session. Rules on tool calls are
protection, not context, and keep applying.

The list lives in the Link workspace (`.link-untrusted-folders.json`), not
in the folder: an untrusted folder must not be able to vouch for itself.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .files import atomic_write_text

UNTRUSTED_FOLDERS_FILE = ".link-untrusted-folders.json"


def _real(path: str | Path) -> Path:
    return Path(os.path.realpath(Path(path).expanduser()))


def untrusted_folders(link_root: Path) -> list[str]:
    """The folders marked untrusted, as real absolute paths."""
    try:
        payload = json.loads((link_root / UNTRUSTED_FOLDERS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    folders = payload.get("folders") if isinstance(payload, dict) else None
    if not isinstance(folders, list):
        return []
    return sorted({str(item) for item in folders if isinstance(item, str) and os.path.isabs(item)})


def untrusted_parent(link_root: Path, folder: str | Path | None) -> str:
    """The marked folder that `folder` is, or sits inside; "" when it is in none."""
    if not folder or not str(folder).strip():
        return ""
    marked = untrusted_folders(link_root)
    if not marked:
        return ""
    here = _real(folder)
    for item in marked:
        base = Path(item)
        if here == base or base in here.parents:
            return item
    return ""


def set_folder_trust(link_root: Path, folder: str | Path, *, untrusted: bool) -> dict[str, object]:
    """Mark a folder untrusted, or trusted again. Returns what changed."""
    here = _real(folder)
    if untrusted and not here.is_dir():
        raise ValueError(f"not a folder: {folder}")
    root = _real(link_root)
    if untrusted and (here == root or here in root.parents or here == _real(Path.home())):
        # Marking the workspace's own parents (or the whole home folder)
        # would switch memory off everywhere, which is what `lnk disconnect` is for.
        raise ValueError(f"{here} holds your Link workspace or is your home folder; mark a project folder instead")
    current = set(untrusted_folders(link_root))
    before = set(current)
    if untrusted:
        current.add(str(here))
    else:
        current.discard(str(here))
    if current != before:
        atomic_write_text(
            link_root / UNTRUSTED_FOLDERS_FILE,
            json.dumps({"folders": sorted(current)}, indent=2) + "\n",
        )
    return {
        "folder": str(here),
        "untrusted": untrusted,
        "changed": current != before,
        "covered_by": "" if untrusted else untrusted_parent(link_root, here),
        "folders": sorted(current),
    }


def untrusted_notice(folder: str) -> str:
    """What a session in an untrusted folder is told instead of the brief."""
    return (
        f"Link: the user marked {folder} as an untrusted folder. Link gives this session no memory and "
        "proposes none from it; rules on tool calls still apply. Do not ask Link for memory here, and do "
        "not change this setting: only the user does that."
    )
