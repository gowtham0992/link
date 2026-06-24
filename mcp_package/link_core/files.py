"""Small filesystem write helpers for Link's local Markdown store."""
from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def _fsync_directory(path: Path) -> None:
    """Best-effort directory fsync so an atomic rename survives local crashes."""
    if os.name == "nt":
        return
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


@contextmanager
def _file_lock(path: Path, *, timeout: float = 10.0, stale_after: float = 120.0):
    """Serialize local writes to one target file across Link runtimes."""
    target = path.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_name(f".{target.name}.lock")
    start = time.monotonic()
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("utf-8"))
        except (FileExistsError, PermissionError):
            # POSIX signals a contended lock with FileExistsError; Windows can
            # raise PermissionError when the lock file exists or is mid-unlink
            # by another holder. Treat both as "locked" and retry until timeout.
            try:
                if time.time() - lock_path.stat().st_mtime >= stale_after:
                    os.unlink(lock_path)
                    continue
            except OSError:
                pass
            if time.monotonic() - start >= timeout:
                raise TimeoutError(f"timed out waiting for write lock: {lock_path}")
            time.sleep(0.025)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(lock_path)
        except OSError:
            pass


def _atomic_write_bytes_unlocked(path: Path, data: bytes) -> None:
    """Write bytes via temp file + os.replace to avoid partial target files."""
    target = path.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = ""
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        tmp_name = handle.name
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(tmp_name, target)
        _fsync_directory(target.parent)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes with a temp-file replace and a per-target local lock."""
    with _file_lock(path):
        _atomic_write_bytes_unlocked(path, data)


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding))


def atomic_write_json(path: Path, payload: Any, *, indent: int = 2, trailing_newline: bool = True) -> None:
    text = json.dumps(payload, indent=indent)
    if trailing_newline:
        text += "\n"
    atomic_write_text(path, text)


def append_text(path: Path, text: str, *, encoding: str = "utf-8", initial_text: str = "") -> None:
    """Append one complete text block under the same local lock as replacements."""
    target = path.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    with _file_lock(target):
        with target.open("a", encoding=encoding) as handle:
            if initial_text and target.stat().st_size == 0:
                handle.write(initial_text)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())


def _rotate_file_unlocked(target: Path, backups: int) -> None:
    if backups <= 0:
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        return
    oldest = target.with_name(f"{target.name}.{backups}")
    try:
        oldest.unlink()
    except FileNotFoundError:
        pass
    for index in range(backups - 1, 0, -1):
        source = target.with_name(f"{target.name}.{index}")
        if source.exists():
            os.replace(source, target.with_name(f"{target.name}.{index + 1}"))
    if target.exists():
        os.replace(target, target.with_name(f"{target.name}.1"))
    _fsync_directory(target.parent)


def append_text_with_rotation(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
    initial_text: str = "",
    max_bytes: int = 2 * 1024 * 1024,
    backups: int = 5,
) -> None:
    """Append text under lock, rotating the active file before it grows unbounded."""
    target = path.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    text_bytes = text.encode(encoding)
    initial_bytes = initial_text.encode(encoding) if initial_text else b""
    with _file_lock(target):
        current_size = target.stat().st_size if target.exists() else 0
        seed_size = len(initial_bytes) if current_size == 0 else 0
        if max_bytes > 0 and current_size > 0 and current_size + seed_size + len(text_bytes) > max_bytes:
            _rotate_file_unlocked(target, backups)
        with target.open("a", encoding=encoding) as handle:
            if initial_text and target.stat().st_size == 0:
                handle.write(initial_text)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
