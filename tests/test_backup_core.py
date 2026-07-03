import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.backup import BackupError, RestoreError, create_backup, list_backups, restore_backup


class BackupCoreTests(unittest.TestCase):
    def make_root(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="link-backup-core-"))
        (root / "wiki/concepts").mkdir(parents=True)
        (root / "raw").mkdir()
        (root / "wiki/index.md").write_text("# Index\n", encoding="utf-8")
        (root / "wiki/concepts/agent-memory.md").write_text("# Agent Memory\n", encoding="utf-8")
        (root / "raw/secret-session.md").write_text("api key: test-secret\n", encoding="utf-8")
        return root

    def test_backup_includes_wiki_and_excludes_raw_by_default(self):
        root = self.make_root()

        result = create_backup(root, label="unit test")

        self.assertTrue(result["created"])
        self.assertEqual(result["included"], ["wiki"])
        self.assertFalse(result["include_raw"])
        archive = Path(result["path"])
        self.assertTrue(archive.exists())
        with tarfile.open(archive, "r:gz") as tar:
            names = set(tar.getnames())
        self.assertIn("wiki/index.md", names)
        self.assertIn("wiki/concepts/agent-memory.md", names)
        self.assertNotIn("raw/secret-session.md", names)

    def test_backup_can_include_raw_when_requested_and_lists_archives(self):
        root = self.make_root()

        result = create_backup(root, label="with raw", include_raw=True)
        listing = list_backups(root)

        with tarfile.open(result["path"], "r:gz") as tar:
            names = set(tar.getnames())
        self.assertIn("raw/secret-session.md", names)
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["backups"][0]["name"], result["name"])

    def test_list_backups_reports_unreadable_archive_metadata(self):
        root = self.make_root()
        result = create_backup(root, label="unit test")
        archive = Path(result["path"])
        original_stat = Path.stat

        def flaky_stat(path: Path, *args, **kwargs):
            if path.name == archive.name:
                raise OSError("permission denied")
            return original_stat(path, *args, **kwargs)

        with patch.object(Path, "stat", flaky_stat):
            listing = list_backups(root)

        self.assertEqual(listing["count"], 0)
        self.assertEqual(listing["warning_count"], 1)
        self.assertEqual(listing["warnings"][0]["backup"], archive.name)

    def test_backup_requires_wiki(self):
        root = Path(tempfile.mkdtemp(prefix="link-backup-core-"))

        with self.assertRaises(FileNotFoundError):
            create_backup(root)

    def test_backup_failure_removes_partial_archive(self):
        root = self.make_root()
        original_add = tarfile.TarFile.add

        def flaky_add(tar, name, *args, **kwargs):
            if Path(name).name == "agent-memory.md":
                raise OSError("permission denied")
            return original_add(tar, name, *args, **kwargs)

        with patch.object(tarfile.TarFile, "add", flaky_add):
            with self.assertRaisesRegex(BackupError, "wiki/concepts/agent-memory.md"):
                create_backup(root, label="partial")

        self.assertEqual(list((root / ".link-backups").glob("*.tar.gz")), [])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are not available")
    def test_backup_skips_symlinks(self):
        root = self.make_root()
        outside = root.parent / "outside-secret.txt"
        outside.write_text("outside", encoding="utf-8")
        os.symlink(outside, root / "wiki/concepts/outside-link.md")

        result = create_backup(root)

        with tarfile.open(result["path"], "r:gz") as tar:
            names = set(tar.getnames())
        self.assertNotIn("wiki/concepts/outside-link.md", names)

    def test_restore_backup_previews_then_restores_wiki(self):
        root = self.make_root()
        created = create_backup(root, label="restore test")
        (root / "wiki/index.md").write_text("# Broken\n", encoding="utf-8")

        preview = restore_backup(root, created["name"])

        self.assertFalse(preview["restored"])
        self.assertTrue(preview["confirmation_required"])
        self.assertEqual(preview["restore_roots"], ["wiki"])
        self.assertEqual((root / "wiki/index.md").read_text(encoding="utf-8"), "# Broken\n")

        restored = restore_backup(root, created["name"], confirm=True)

        self.assertTrue(restored["restored"])
        self.assertFalse(restored["confirmation_required"])
        self.assertEqual((root / "wiki/index.md").read_text(encoding="utf-8"), "# Index\n")
        self.assertIn("safety_backup", restored)
        self.assertTrue(restored["integrity"]["checked"])
        self.assertIn("passed", restored["integrity"])

    def test_restore_backup_skips_raw_unless_requested(self):
        root = self.make_root()
        created = create_backup(root, label="with raw", include_raw=True)
        (root / "raw/secret-session.md").write_text("changed\n", encoding="utf-8")

        restored = restore_backup(root, created["name"], confirm=True, safety_backup=False)

        self.assertTrue(restored["restored"])
        self.assertEqual(restored["skipped_roots"], ["raw"])
        self.assertEqual((root / "raw/secret-session.md").read_text(encoding="utf-8"), "changed\n")

        restored_with_raw = restore_backup(root, created["name"], include_raw=True, confirm=True, safety_backup=False)

        self.assertTrue(restored_with_raw["restored"])
        self.assertEqual((root / "raw/secret-session.md").read_text(encoding="utf-8"), "api key: test-secret\n")

    def test_restore_backup_rejects_unsafe_tar_paths(self):
        root = self.make_root()
        archive = root / ".link-backups" / "bad.tar.gz"
        archive.parent.mkdir()
        payload = root / "payload.txt"
        payload.write_text("bad\n", encoding="utf-8")
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(payload, arcname="../outside.txt")

        with self.assertRaisesRegex(RestoreError, "unsafe path"):
            restore_backup(root, archive)


if __name__ == "__main__":
    unittest.main()
