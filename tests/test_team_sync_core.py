import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.team_sync import build_team_sync_payload, render_team_sync_text  # noqa: E402


def write_memory(root: Path, name: str, *, scope: str = "project", review_status: str = "reviewed") -> None:
    path = root / "wiki" / "memories" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join([
            "---",
            f"title: {name.replace('-', ' ').title()}",
            "memory_type: preference",
            f"scope: {scope}",
            "project: link",
            "status: active",
            f"review_status: {review_status}",
            "---",
            "",
            f"# {name.replace('-', ' ').title()}",
            "",
            "> **TLDR:** Team sync test memory.",
            "",
        ]),
        encoding="utf-8",
    )


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
        self.assertTrue(payload["memory_share"]["safe_for_team_git"])
        self.assertIn("ready for reviewed Git sharing", text)
        self.assertIn("Memory share gate: 0 active", text)
        self.assertIn("Safe sync loop", text)

    def test_git_workspace_without_raw_protection_warns(self):
        root = Path(tempfile.mkdtemp(prefix="link-team-sync-"))
        (root / "wiki").mkdir()
        (root / "wiki" / "_link_schema.json").write_text("{}", encoding="utf-8")
        (root / ".git").mkdir()

        payload = build_team_sync_payload(root)

        self.assertFalse(payload["ready"])
        self.assertIn("raw/ is not protected", payload["warnings"][0])

    def test_user_scoped_memories_block_team_sync_readiness(self):
        root = Path(tempfile.mkdtemp(prefix="link-team-sync-"))
        (root / "wiki").mkdir()
        (root / "wiki" / "_link_schema.json").write_text("{}", encoding="utf-8")
        (root / ".gitignore").write_text("raw/*\n", encoding="utf-8")
        (root / ".git").mkdir()
        (root / ".git" / "config").write_text(
            '[remote "origin"]\n\turl = git@example.com:team/link-memory.git\n',
            encoding="utf-8",
        )
        write_memory(root, "private-preference", scope="user", review_status="reviewed")

        payload = build_team_sync_payload(root)
        code, text = render_team_sync_text(payload)

        self.assertEqual(code, 0)
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["memory_share"]["user_scoped_count"], 1)
        self.assertFalse(payload["memory_share"]["safe_for_team_git"])
        self.assertIn("active user-scoped memories", " ".join(payload["warnings"]))
        self.assertIn("1 user-scoped", text)

    def test_unreviewed_memories_block_team_sync_readiness(self):
        root = Path(tempfile.mkdtemp(prefix="link-team-sync-"))
        (root / "wiki").mkdir()
        (root / "wiki" / "_link_schema.json").write_text("{}", encoding="utf-8")
        (root / ".gitignore").write_text("raw/*\n", encoding="utf-8")
        (root / ".git").mkdir()
        (root / ".git" / "config").write_text(
            '[remote "origin"]\n\turl = git@example.com:team/link-memory.git\n',
            encoding="utf-8",
        )
        write_memory(root, "pending-team-memory", scope="project", review_status="pending")

        payload = build_team_sync_payload(root)

        self.assertFalse(payload["ready"])
        self.assertEqual(payload["memory_share"]["review_count"], 1)
        self.assertIn("memory review inbox is not clear", " ".join(payload["warnings"]))


if __name__ == "__main__":
    unittest.main()
