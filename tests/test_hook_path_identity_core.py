"""The hook knows a protected file or a project however it is named.

A path is compared by what it is, not only how it is spelt: the macOS
/System/Volumes/Data firmlink, a decomposed é and a hard link all name a
memory file the hook protects. A git worktree belongs to its project, and a
request to the viewer's memory endpoints is a governance command.
"""
import json
import os
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.memory import mark_memory_reviewed, write_memory_page  # noqa: E402
from link_core.project_scope import default_project_for_target  # noqa: E402
from link_core.tool_hooks import evaluate_tool_call, load_hook_index, pre_tool_reply  # noqa: E402

_DATA = Path("/System/Volumes/Data")


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=cwd,
                   check=True, capture_output=True)


class _Store(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        # A non-ASCII folder, so the NFD spelling of the path differs from the NFC one.
        self.base = Path(self.temp.name).resolve() / unicodedata.normalize("NFC", "José")
        self.wiki = self.base / "wiki"
        (self.wiki / "memories").mkdir(parents=True)
        (self.wiki / "index.md").write_text("# Index\n", encoding="utf-8")
        self.repo = self.base / "repo"
        (self.repo / "migrations").mkdir(parents=True)
        saved = write_memory_page(self.wiki, "Migrations are generated; force pushes need my OK.", None,
                                  "preference", "user", None, "test", "2026-10-28T00:00:00Z",
                                  contradiction_scorer=None,
                                  enforce=["deny write: migrations/**", "ask command: git push --force*"])
        mark_memory_reviewed(self.wiki, saved["name"], None, "2026-10-28T00:01:00Z")
        self.page = self.wiki / "memories" / f"{saved['name']}.md"
        self.protected = [self.wiki / "memories", self.base / ".link-cache"]

    def tearDown(self):
        self.temp.cleanup()

    def _decide(self, tool_name, context=None, **tool_input):
        index = load_hook_index(self.wiki, self.base)
        return evaluate_tool_call(index, {"tool_name": tool_name, "tool_input": tool_input}, repo_root=self.repo,
                                  context_path=str(context or self.repo), protected=self.protected)


class ProtectedFileIdentityTests(_Store):
    @unittest.skipUnless(sys.platform == "darwin" and _DATA.is_dir(), "the firmlink is macOS's")
    def test_the_macos_data_volume_spelling_is_still_a_memory_file(self):
        firmlinked = Path(str(_DATA) + str(self.page))
        if not (firmlinked.exists() and os.path.samefile(firmlinked, self.page)):
            self.skipTest("this temporary folder is not on the data volume")
        for tool, extra in (("Write", {"content": "---\nstatus: archived\n---\n"}),
                            ("Edit", {"old_string": "enforce", "new_string": "x"})):
            with self.subTest(tool=tool):
                decision = self._decide(tool, file_path=str(firmlinked), **extra)
                self.assertIsNotNone(decision)
                self.assertTrue(decision["governance"])
        decision = self._decide("Bash", command=f"rm {firmlinked}")
        self.assertIsNotNone(decision)
        self.assertTrue(decision["governance"])
        # And a whole-tree delete of the folder above it.
        self.assertTrue(self._decide("Bash", command=f"rm -rf {_DATA}{self.wiki}")["governance"])

    def test_a_decomposed_spelling_is_still_a_memory_file(self):
        decomposed = str(self.page).replace(unicodedata.normalize("NFC", "José"),
                                            unicodedata.normalize("NFD", "José"))
        self.assertNotEqual(decomposed, str(self.page))
        decision = self._decide("Write", file_path=decomposed, content="x")
        self.assertIsNotNone(decision)
        self.assertTrue(decision["governance"])

    def test_a_hard_link_to_a_memory_file_is_a_memory_file(self):
        alias = self.repo / "notes.md"
        try:
            os.link(self.page, alias)
        except OSError:
            self.skipTest("no hard links here")
        decision = self._decide("Write", file_path=str(alias), content="x")
        self.assertIsNotNone(decision)
        self.assertTrue(decision["governance"])
        # An ordinary file beside it is not.
        (self.repo / "plain.md").write_text("x", encoding="utf-8")
        self.assertIsNone(self._decide("Write", file_path=str(self.repo / "plain.md"), content="y"))

    def test_a_write_rule_reads_the_checkout_by_identity(self):
        # The agent's folder named another way (here: NFD) still lies inside the checkout.
        elsewhere = Path(str(self.repo / "migrations").replace(unicodedata.normalize("NFC", "José"),
                                                               unicodedata.normalize("NFD", "José")))
        if not elsewhere.exists():
            self.skipTest("this file system tells NFC and NFD names apart")
        decision = self._decide("Write", context=elsewhere, file_path="0002.sql", content="x")
        self.assertIsNotNone(decision)
        self.assertEqual(decision["decision"], "deny")


class ViewerGovernanceTests(_Store):
    def test_a_request_to_the_viewers_memory_endpoints_is_governance(self):
        for command in (
            "curl -s -X POST -H 'X-Link-Local-Action: true' -H 'Content-Type: application/json' "
            "-d '{\"memory\":\"x\"}' http://127.0.0.1:3000/api/archive-memory",
            "wget -q --post-data='{\"memory\":\"x\"}' --header='X-Link-Local-Action: true' "
            "http://localhost:3000/api/review-memory",
            "http POST localhost:41234/api/restore-memory memory=x X-Link-Local-Action:true",
            "python3 -c \"import urllib.request as u; u.urlopen(u.Request('http://[::1]:3000/api/update-memory', "
            "data=b'{}', headers={'X-Link-Local-Action': 'true'}))\"",
        ):
            with self.subTest(command=command):
                decision = self._decide("Bash", command=command)
                self.assertIsNotNone(decision)
                self.assertTrue(decision["governance"])
                self.assertFalse(decision["approvable"])

    def test_reading_the_viewer_is_not(self):
        for command in ("curl -s http://127.0.0.1:3000/api/memory-inbox",
                        "curl -s 'http://127.0.0.1:3000/api/explain-memory?memory=x'"):
            with self.subTest(command=command):
                self.assertIsNone(self._decide("Bash", command=command))


class WorktreeProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.repo = self.base / "myrepo"
        self.repo.mkdir()
        _git("init", "-q", cwd=self.repo)
        _git("commit", "-q", "--allow-empty", "-m", "start", cwd=self.repo)

    def tearDown(self):
        self.temp.cleanup()

    def test_a_worktree_belongs_to_its_project(self):
        beside = self.base / "myrepo-hotfix"
        inside = self.repo / ".claude" / "worktrees" / "fix-login"
        _git("worktree", "add", "-q", str(beside), cwd=self.repo)
        _git("worktree", "add", "-q", str(inside), cwd=self.repo)
        for checkout in (self.repo, beside, inside):
            with self.subTest(checkout=checkout.name):
                self.assertEqual(default_project_for_target(checkout), "myrepo")

    def test_a_submodule_keeps_its_own_name(self):
        sub = self.base / "vendor-lib"
        (self.repo / ".git" / "modules" / "vendor-lib").mkdir(parents=True)
        sub.mkdir()
        (sub / ".git").write_text(f"gitdir: {self.repo / '.git' / 'modules' / 'vendor-lib'}\n", encoding="utf-8")
        self.assertEqual(default_project_for_target(sub), "vendor-lib")

    def test_a_project_rule_holds_in_a_worktree_of_the_project(self):
        ws = self.base / "ws"
        wiki = ws / "wiki"
        (wiki / "memories").mkdir(parents=True)
        (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
        saved = write_memory_page(wiki, "Migrations in myrepo are generated.", None, "preference", "project",
                                  None, "test", "2026-10-28T00:00:00Z", project="myrepo",
                                  contradiction_scorer=None,
                                  enforce=["deny write: migrations/**", "ask command: git push --force*"])
        mark_memory_reviewed(wiki, saved["name"], None, "2026-10-28T00:01:00Z")
        worktree = self.repo / ".claude" / "worktrees" / "fix-login"
        _git("worktree", "add", "-q", str(worktree), cwd=self.repo)
        reply = pre_tool_reply(ws, {"tool_name": "Bash", "cwd": str(worktree),
                                    "tool_input": {"command": "git push --force origin main"}},
                               project=None, emit="text", environ={})
        self.assertEqual(json.loads(reply.stdout)["hookSpecificOutput"]["permissionDecision"], "ask")
        reply = pre_tool_reply(ws, {"tool_name": "Write", "cwd": str(worktree),
                                    "tool_input": {"file_path": str(worktree / "migrations" / "1.sql"),
                                                   "content": "x"}},
                               project=None, emit="text", environ={})
        self.assertEqual(json.loads(reply.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
