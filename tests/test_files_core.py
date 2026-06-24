import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.files import append_text, append_text_with_rotation, atomic_write_json, atomic_write_text  # noqa: E402


class FilesCoreTests(unittest.TestCase):
    def test_atomic_write_text_replaces_existing_file(self):
        root = Path(tempfile.mkdtemp(prefix="link-files-core-"))
        path = root / "wiki/index.md"
        path.parent.mkdir(parents=True)
        path.write_text("old\n", encoding="utf-8")

        atomic_write_text(path, "new\n")

        self.assertEqual(path.read_text(encoding="utf-8"), "new\n")
        self.assertEqual(list(path.parent.glob(".*.tmp")), [])

    def test_atomic_write_json_adds_trailing_newline(self):
        root = Path(tempfile.mkdtemp(prefix="link-files-core-"))
        path = root / "wiki/_backlinks.json"

        atomic_write_json(path, {"backlinks": {}, "forward": {}})

        self.assertTrue(path.read_text(encoding="utf-8").endswith("\n"))
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"backlinks": {}, "forward": {}})

    def test_atomic_write_preserves_existing_file_on_replace_failure(self):
        root = Path(tempfile.mkdtemp(prefix="link-files-core-"))
        path = root / "wiki/index.md"
        path.parent.mkdir(parents=True)
        path.write_text("old\n", encoding="utf-8")

        with patch.object(os, "replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                atomic_write_text(path, "new\n")

        self.assertEqual(path.read_text(encoding="utf-8"), "old\n")
        self.assertEqual(list(path.parent.glob(".*.tmp")), [])

    def test_atomic_write_recovers_stale_lock_file(self):
        root = Path(tempfile.mkdtemp(prefix="link-files-core-"))
        path = root / "wiki/index.md"
        path.parent.mkdir(parents=True)
        lock = path.parent / ".index.md.lock"
        lock.write_text("old-pid", encoding="utf-8")
        os.utime(lock, (0, 0))

        atomic_write_text(path, "new\n")

        self.assertEqual(path.read_text(encoding="utf-8"), "new\n")
        self.assertFalse(lock.exists())

    def test_lock_retries_on_transient_permission_error(self):
        # Windows raises PermissionError (not FileExistsError) for a contended
        # O_EXCL lock file; the lock must retry instead of propagating it.
        root = Path(tempfile.mkdtemp(prefix="link-files-core-"))
        path = root / "wiki/index.md"

        real_open = os.open
        calls = {"excl": 0}

        def flaky_open(*args, **kwargs):
            flags = args[1] if len(args) > 1 else kwargs.get("flags", 0)
            if flags & os.O_EXCL:
                calls["excl"] += 1
                if calls["excl"] <= 2:
                    raise PermissionError(13, "Permission denied")
            return real_open(*args, **kwargs)

        with patch.object(os, "open", side_effect=flaky_open):
            atomic_write_text(path, "locked-write\n")

        self.assertEqual(path.read_text(encoding="utf-8"), "locked-write\n")
        self.assertGreaterEqual(calls["excl"], 3)
        self.assertEqual(list(path.parent.glob(".*.lock")), [])

    def test_append_text_initializes_and_serializes_audit_log(self):
        root = Path(tempfile.mkdtemp(prefix="link-files-core-"))
        path = root / "wiki/log.md"

        def append(index: int) -> None:
            append_text(path, f"entry-{index}\n", initial_text="# Log\n\n")

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(append, range(25)))

        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.count("# Log"), 1)
        for index in range(25):
            self.assertIn(f"entry-{index}\n", text)
        self.assertEqual(list(path.parent.glob(".*.lock")), [])

    def test_append_text_with_rotation_rotates_before_append(self):
        root = Path(tempfile.mkdtemp(prefix="link-files-core-"))
        path = root / "wiki/log.md"
        path.parent.mkdir(parents=True)
        path.write_text("# Log\n\n" + ("old\n" * 12), encoding="utf-8")

        append_text_with_rotation(path, "new-entry\n", initial_text="# Log\n\n", max_bytes=40, backups=2)

        self.assertEqual(path.read_text(encoding="utf-8"), "# Log\n\nnew-entry\n")
        self.assertTrue((path.parent / "log.md.1").exists())
        self.assertIn("old\n", (path.parent / "log.md.1").read_text(encoding="utf-8"))
        self.assertFalse((path.parent / "log.md.3").exists())

    def test_append_text_with_rotation_honors_backup_limit(self):
        root = Path(tempfile.mkdtemp(prefix="link-files-core-"))
        path = root / "wiki/log.md"
        path.parent.mkdir(parents=True)
        path.write_text("active\n" * 10, encoding="utf-8")
        (path.parent / "log.md.1").write_text("first-backup\n", encoding="utf-8")
        (path.parent / "log.md.2").write_text("oldest-backup\n", encoding="utf-8")

        append_text_with_rotation(path, "fresh\n", max_bytes=1, backups=2)

        self.assertEqual(path.read_text(encoding="utf-8"), "fresh\n")
        self.assertIn("active\n", (path.parent / "log.md.1").read_text(encoding="utf-8"))
        self.assertEqual((path.parent / "log.md.2").read_text(encoding="utf-8"), "first-backup\n")
        self.assertNotIn("oldest-backup", "\n".join(item.read_text(encoding="utf-8") for item in path.parent.glob("log.md*")))


if __name__ == "__main__":
    unittest.main()
