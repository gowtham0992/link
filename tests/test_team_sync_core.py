import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.team_sync import build_team_sync_payload, render_team_sync_text  # noqa: E402


class TeamSyncCoreTests(unittest.TestCase):
    def test_plan_for_workspace_without_git_includes_safe_setup(self):
        root = Path(tempfile.mkdtemp(prefix="link-team-sync-"))
        (root / "wiki").mkdir()
        (root / "wiki" / "_link_schema.json").write_text("{}", encoding="utf-8")
        (root / ".gitignore").write_text("raw/*\n.link-backups/\n", encoding="utf-8")

        payload = build_team_sync_payload(root, remote="git@example.com:team/link-memory.git")

        self.assertFalse(payload["in_git"])
        self.assertFalse(payload["ready"])
        self.assertTrue(payload["gitignore"]["protects_raw"])
        commands = [action["command_text"] for action in payload["setup_actions"]]
        self.assertTrue(any("git" in command and "init" in command for command in commands))
        self.assertTrue(any("remote" in command and "add" in command for command in commands))

    def test_git_workspace_with_raw_protection_is_ready(self):
        root = Path(tempfile.mkdtemp(prefix="link-team-sync-"))
        (root / "wiki").mkdir()
        (root / "wiki" / "_link_schema.json").write_text("{}", encoding="utf-8")
        (root / "LINK.md").write_text("# Link\n", encoding="utf-8")
        (root / ".gitignore").write_text("raw/*\n.link-backups/\n", encoding="utf-8")
        (root / ".git").mkdir()
        (root / ".git" / "config").write_text(
            '[remote "origin"]\n\turl = git@example.com:team/link-memory.git\n',
            encoding="utf-8",
        )

        payload = build_team_sync_payload(root)
        code, text = render_team_sync_text(payload)

        self.assertEqual(code, 0)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["remotes"], ["origin"])
        self.assertIn("ready for reviewed Git sharing", text)
        self.assertIn("Safe sync loop", text)

    def test_git_workspace_without_raw_protection_warns(self):
        root = Path(tempfile.mkdtemp(prefix="link-team-sync-"))
        (root / "wiki").mkdir()
        (root / "wiki" / "_link_schema.json").write_text("{}", encoding="utf-8")
        (root / ".git").mkdir()

        payload = build_team_sync_payload(root)

        self.assertFalse(payload["ready"])
        self.assertIn("raw/ is not protected", payload["warnings"][0])


if __name__ == "__main__":
    unittest.main()
