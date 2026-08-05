"""lnk sync integration: two machines, one bare remote, no server.

Uses real git against a local bare repository — the full sync loop without
any network. The three promises under test: secrets never leave, conflicts
become review items (never markers), and the log chain stays verifiable.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.log import append_log, verify_log_integrity  # noqa: E402
from link_core.sync import (  # noqa: E402
    SyncError,
    sync_init,
    sync_status,
    sync_workspace,
)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _make_workspace(root: Path) -> Path:
    wiki = root / "wiki"
    (wiki / "memories").mkdir(parents=True)
    (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
    (wiki / "log.md").write_text("# Link Log\n\n", encoding="utf-8")
    return wiki


def _configure_git_identity(root: Path) -> None:
    _git(root, "config", "user.email", "sync-test@example.invalid")
    _git(root, "config", "user.name", "Link Sync Test")


def _write_memory(wiki: Path, name: str, text: str) -> None:
    (wiki / "memories" / f"{name}.md").write_text(
        "---\n"
        f"title: \"{name}\"\n"
        "type: preference\n"
        "scope: user\n"
        "status: active\n"
        "---\n\n"
        f"# {name}\n\n{text}\n",
        encoding="utf-8",
    )
    append_log(wiki, "2026-08-03T00:00:00Z", "remember", f"saved {name}", [f"text: {text[:40]}"])


class SyncRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="link-sync-")
        base = Path(self.temp.name)
        self.remote = base / "remote.git"
        subprocess.run(["git", "init", "--bare", str(self.remote)], capture_output=True)
        self.machine_a = base / "machine-a"
        self.machine_a.mkdir()
        self.wiki_a = _make_workspace(self.machine_a)
        sync_init(self.machine_a, remote=str(self.remote))
        _configure_git_identity(self.machine_a)
        # push the initial state so machine B can clone
        sync_workspace(self.machine_a, self.wiki_a, regenerate=lambda: None)
        clone = subprocess.run(
            ["git", "clone", str(self.remote), "machine-b"],
            cwd=base, capture_output=True, text=True,
        )
        self.assertEqual(clone.returncode, 0, clone.stderr)
        self.machine_b = base / "machine-b"
        self.wiki_b = self.machine_b / "wiki"
        _configure_git_identity(self.machine_b)

    def tearDown(self):
        self.temp.cleanup()

    def test_round_trip_memory_travels_both_ways(self):
        _write_memory(self.wiki_a, "prefers-tabs", "The user prefers tabs.")
        result = sync_workspace(self.machine_a, self.wiki_a, regenerate=lambda: None)
        self.assertTrue(result["pushed"])

        result = sync_workspace(self.machine_b, self.wiki_b, regenerate=lambda: None)
        self.assertGreaterEqual(int(str(result["pulled"])), 1)
        self.assertTrue((self.wiki_b / "memories" / "prefers-tabs.md").exists())

        _write_memory(self.wiki_b, "prefers-dark-mode", "The user prefers dark mode.")
        sync_workspace(self.machine_b, self.wiki_b, regenerate=lambda: None)
        sync_workspace(self.machine_a, self.wiki_a, regenerate=lambda: None)
        self.assertTrue((self.wiki_a / "memories" / "prefers-dark-mode.md").exists())

    def test_conflict_becomes_both_versions_never_markers(self):
        _write_memory(self.wiki_a, "release-notes", "Release notes stay short.")
        sync_workspace(self.machine_a, self.wiki_a, regenerate=lambda: None)
        sync_workspace(self.machine_b, self.wiki_b, regenerate=lambda: None)

        # Both machines now edit the same memory divergently.
        _write_memory(self.wiki_a, "release-notes", "Release notes stay short and bulleted.")
        sync_workspace(self.machine_a, self.wiki_a, regenerate=lambda: None)
        _write_memory(self.wiki_b, "release-notes", "Release notes carry migration guidance.")
        result = sync_workspace(self.machine_b, self.wiki_b, regenerate=lambda: None)

        both = result["both_versions"]
        self.assertEqual(len(both), 1, result)
        local_copy = self.machine_b / str(both[0]["local_copy"])
        self.assertTrue(local_copy.exists())
        # The remote version holds the original path; ours is the sibling.
        original = (self.wiki_b / "memories" / "release-notes.md").read_text(encoding="utf-8")
        self.assertIn("bulleted", original)
        self.assertIn("migration guidance", local_copy.read_text(encoding="utf-8"))
        # No git conflict markers anywhere in the wiki.
        for path in self.wiki_b.rglob("*.md"):
            self.assertNotIn("<<<<<<<", path.read_text(encoding="utf-8"), path)
        # The union-merged log chain verifies, and declares the merge.
        integrity = verify_log_integrity(self.wiki_b)
        self.assertTrue(integrity.get("passed"), integrity)
        self.assertIn("sync-merge", (self.wiki_b / "log.md").read_text(encoding="utf-8"))
        # Machine A pulls the resolution and sees both versions too.
        sync_workspace(self.machine_a, self.wiki_a, regenerate=lambda: None)
        self.assertTrue((self.machine_a / str(both[0]["local_copy"])).exists())

    def test_secrets_never_leave_the_machine(self):
        token = "ghp_" + "aB3dE6gH9jK2mN5pQ8sT1vW4yZ7cF0rL6xN2"
        _write_memory(self.wiki_a, "poisoned", f"The deploy token is {token} for CI.")
        result = sync_workspace(self.machine_a, self.wiki_a, regenerate=lambda: None)
        self.assertFalse(result["synced"])
        findings = result["secret_findings"]
        self.assertTrue(findings)
        self.assertIn("memories/poisoned.md", str(findings[0]["path"]))
        # The remote never received the secret.
        remote_files = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "HEAD"],
            cwd=self.remote, capture_output=True, text=True,
        ).stdout
        self.assertNotIn("poisoned", remote_files)

    def test_status_reports_ahead_behind(self):
        _write_memory(self.wiki_a, "prefers-tabs", "The user prefers tabs.")
        sync_workspace(self.machine_a, self.wiki_a, regenerate=lambda: None)
        status = sync_status(self.machine_b)
        self.assertTrue(status["ready"])
        self.assertEqual(status["behind"], 1)

    def test_sync_without_remote_guides_to_init(self):
        with tempfile.TemporaryDirectory() as temp:
            loose = Path(temp) / "loose"
            loose.mkdir()
            wiki = _make_workspace(loose)
            with self.assertRaises(SyncError):
                sync_workspace(loose, wiki, regenerate=lambda: None)


if __name__ == "__main__":
    unittest.main()


class TeamMemoryTests(unittest.TestCase):
    """Two teammates share visibility:team memories; private never leaves."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="link-team-")
        base = Path(self.temp.name)
        self.remote = base / "team-remote.git"
        subprocess.run(["git", "init", "--bare", str(self.remote)], capture_output=True)
        from link_core.sync import team_init
        self.alice = base / "alice"
        self.alice.mkdir()
        self.wiki_alice = _make_workspace(self.alice)
        team_init(self.alice, base / "alice-team", remote=str(self.remote))
        _configure_git_identity(base / "alice-team")
        self.bob = base / "bob"
        self.bob.mkdir()
        self.wiki_bob = _make_workspace(self.bob)
        team_init(self.bob, base / "bob-team", remote=str(self.remote))
        _configure_git_identity(base / "bob-team")

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _write_visible(wiki: Path, name: str, text: str, visibility: str) -> None:
        (wiki / "memories" / f"{name}.md").write_text(
            "---\n"
            f"title: \"{name}\"\n"
            "type: decision\n"
            "scope: project\n"
            "status: active\n"
            f"visibility: {visibility}\n"
            "---\n\n"
            f"# {name}\n\n{text}\n",
            encoding="utf-8",
        )

    def test_team_memories_travel_and_private_never_leaves(self):
        from link_core.sync import team_sync_workspace
        self._write_visible(self.wiki_alice, "deploy-window", "Deploys happen on Tuesdays.", "team")
        self._write_visible(self.wiki_alice, "my-secret-habit", "I check twitter first.", "private")

        report = team_sync_workspace(self.alice, self.wiki_alice, regenerate=lambda: None)
        self.assertEqual(report["exported"], ["deploy-window"])

        report = team_sync_workspace(self.bob, self.wiki_bob, regenerate=lambda: None)
        self.assertEqual(report["imported"], ["deploy-window"])
        imported = self.wiki_bob / "memories" / "deploy-window.md"
        self.assertTrue(imported.exists())
        self.assertIn("visibility: team", imported.read_text(encoding="utf-8"))
        # Privacy: the shared remote never saw the private memory.
        remote_files = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "HEAD"],
            cwd=self.remote, capture_output=True, text=True,
        ).stdout
        self.assertIn("deploy-window", remote_files)
        self.assertNotIn("my-secret-habit", remote_files)
        self.assertFalse((self.wiki_bob / "memories" / "my-secret-habit.md").exists())

    def test_local_edit_wins_over_team_version(self):
        from link_core.sync import team_sync_workspace
        self._write_visible(self.wiki_alice, "deploy-window", "Deploys happen on Tuesdays.", "team")
        team_sync_workspace(self.alice, self.wiki_alice, regenerate=lambda: None)
        team_sync_workspace(self.bob, self.wiki_bob, regenerate=lambda: None)

        # Bob edits his copy locally; Alice re-shares a different wording.
        self._write_visible(self.wiki_bob, "deploy-window", "Deploys happen on Wednesdays.", "team")
        self._write_visible(self.wiki_alice, "deploy-window", "Deploys happen on Tuesdays after standup.", "team")
        team_sync_workspace(self.alice, self.wiki_alice, regenerate=lambda: None)
        report = team_sync_workspace(self.bob, self.wiki_bob, regenerate=lambda: None)

        # Bob exported his version too; the team repo resolves via sync's
        # both-versions machinery, and Bob's local wiki keeps his wording.
        local = (self.wiki_bob / "memories" / "deploy-window.md").read_text(encoding="utf-8")
        self.assertIn("Wednesdays", local)
        self.assertTrue(report["conflicts"] or report["exported"], report)

    def test_unconfigured_team_sync_raises_with_guidance(self):
        from link_core.sync import SyncError, team_sync_workspace
        with tempfile.TemporaryDirectory() as temp:
            loose = Path(temp) / "loose"
            loose.mkdir()
            wiki = _make_workspace(loose)
            with self.assertRaises(SyncError):
                team_sync_workspace(loose, wiki, regenerate=lambda: None)
