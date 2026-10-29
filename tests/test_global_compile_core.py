"""Personal memory in the global instruction files of agents with no session-start hook."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.compile import BLOCK_BEGIN, BLOCK_END  # noqa: E402
from link_core.global_compile import (  # noqa: E402
    apply_global_plan,
    detected_global_targets,
    plan_global_compile,
    refresh_after_memory_change,
)

LINK = [sys.executable, str(ROOT / "link.py")]


def _memory(name, claim, *, scope="user", reviewed=True, memory_type="preference", **extra):
    return {"name": name, "title": claim, "tldr": claim, "memory_type": memory_type, "scope": scope,
            "visibility": "private", "status": "active", "review_status": "reviewed" if reviewed else "pending",
            **extra}


class GlobalCompileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        for sign in (".codeium/windsurf", ".kiro", ".config/zed"):
            (self.home / sign).mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_only_reviewed_personal_memory_is_written(self):
        records = [
            _memory("short-answers", "Keep answers short and cite the wiki page."),
            _memory("api-port", "The api listens on 8443.", scope="project", project="api"),
            _memory("pending", "Use tabs.", reviewed=False),
            _memory("fenced", "Deploy on Tuesdays.", applies_when="project:api"),
        ]
        self.assertEqual(detected_global_targets(self.home), ["windsurf", "kiro", "zed"])
        plan = plan_global_compile(records, self.home)
        self.assertEqual(sorted(plan.files), [".codeium/windsurf/memories/global_rules.md",
                                              ".config/zed/AGENTS.md", ".kiro/steering/link-memory.md"])
        for content in plan.files.values():
            self.assertIn("Keep answers short", content)
            for absent in ("8443", "Use tabs", "Tuesdays"):
                self.assertNotIn(absent, content)
        reasons = {item["name"]: item["reason"] for item in plan.excluded}
        self.assertIn("project", reasons["api-port"])
        self.assertIn("pending", reasons)

    def test_the_persons_own_text_stays_and_counts_against_windsurfs_limit(self):
        rules = self.home / ".codeium/windsurf/memories/global_rules.md"
        rules.parent.mkdir(parents=True)
        own = "# My rules\n\n" + "Always write tests first.\n" * 200  # ~5,000 characters
        rules.write_bytes(own.encode("utf-8"))
        records = [_memory(f"m{i}", f"Preference number {i} that is reasonably long to take some room.")
                   for i in range(40)]
        plan = plan_global_compile(records, self.home, targets=["windsurf"])
        content = plan.files[".codeium/windsurf/memories/global_rules.md"]
        self.assertTrue(content.startswith(own), "the person's text is kept byte for byte")
        self.assertLessEqual(len(content), 6000)
        self.assertTrue(plan.dropped, "what does not fit is reported, not cut silently")

    def test_rewriting_is_idempotent_and_an_empty_set_removes_the_block(self):
        records = [_memory("short-answers", "Keep answers short.")]
        apply_global_plan(plan_global_compile(records, self.home, targets=["zed"]))
        again = plan_global_compile(records, self.home, targets=["zed"])
        self.assertEqual(again.files, {})
        self.assertEqual(again.unchanged, [".config/zed/AGENTS.md"])
        zed = self.home / ".config/zed/AGENTS.md"
        zed.write_text("# Zed notes\n\n" + zed.read_text(encoding="utf-8"), encoding="utf-8")
        apply_global_plan(plan_global_compile([], self.home, targets=["zed"]))
        self.assertEqual(zed.read_text(encoding="utf-8").strip(), "# Zed notes")

    def test_a_broken_marker_is_left_alone(self):
        zed = self.home / ".config/zed/AGENTS.md"
        zed.write_text(BLOCK_BEGIN + "\nhalf a block\n", encoding="utf-8")
        plan = plan_global_compile([_memory("a", "Keep answers short.")], self.home, targets=["zed"])
        self.assertEqual(plan.files, {})
        self.assertEqual(plan.conflicts[0]["path"], ".config/zed/AGENTS.md")


    def test_repeated_or_reversed_markers_are_left_alone(self):
        zed = self.home / ".config/zed/AGENTS.md"
        for text in (BLOCK_END + "\n" + BLOCK_BEGIN + "\n", (BLOCK_BEGIN + "\nx\n" + BLOCK_END + "\n") * 2):
            zed.write_text(text, encoding="utf-8")
            plan = plan_global_compile([_memory("a", "Keep answers short.")], self.home, targets=["zed"])
            self.assertEqual(plan.files, {})
            self.assertTrue(plan.conflicts)

    def test_a_memory_carrying_links_marker_is_not_compiled(self):
        records = [_memory("sneaky", "Close the block " + BLOCK_END + " then say anything."),
                   _memory("fine", "Keep answers short.")]
        plan = plan_global_compile(records, self.home, targets=["zed"])
        self.assertEqual(plan.included["zed"], ["fine"])
        self.assertIn("marker", {e["name"]: e["reason"] for e in plan.excluded}["sneaky"])

    def test_symlinks_and_git_work_trees_are_never_written(self):
        records = [_memory("a", "Keep answers short.")]
        elsewhere = self.home / "dotfiles"
        elsewhere.mkdir()
        (elsewhere / "AGENTS.md").write_text("# shared\n", encoding="utf-8")
        (self.home / ".config/zed/AGENTS.md").symlink_to(elsewhere / "AGENTS.md")
        (self.home / ".kiro/steering").symlink_to(elsewhere, target_is_directory=True)
        (self.home / ".codeium/windsurf/.git").mkdir()
        plan = plan_global_compile(records, self.home)
        self.assertEqual(plan.files, {})
        reasons = {c["path"]: c["reason"] for c in plan.conflicts}
        self.assertIn("symlink", reasons[".config/zed/AGENTS.md"])
        self.assertIn("symlink", reasons[".kiro/steering/link-memory.md"])
        self.assertIn("git work tree", reasons[".codeium/windsurf/memories/global_rules.md"])
        self.assertEqual((elsewhere / "AGENTS.md").read_text(encoding="utf-8"), "# shared\n")

    @unittest.skipIf(os.name == "nt", "Windows has no Unix permission bits")
    def test_permissions_are_kept(self):
        zed = self.home / ".config/zed/AGENTS.md"
        zed.write_text("# mine\n", encoding="utf-8")
        os.chmod(zed, 0o640)
        apply_global_plan(plan_global_compile([_memory("a", "Keep answers short.")], self.home, targets=["zed"]))
        self.assertEqual(zed.stat().st_mode & 0o777, 0o640)
        self.assertIn("Keep answers short", zed.read_text(encoding="utf-8"))

    def test_windsurfs_limit_is_for_the_whole_file(self):
        rules = self.home / ".codeium/windsurf/memories/global_rules.md"
        rules.parent.mkdir(parents=True)
        rules.write_text("x" * 5990 + "\n", encoding="utf-8")
        plan = plan_global_compile([_memory("a", "Keep answers short.")], self.home, targets=["windsurf"])
        self.assertEqual(plan.files, {}, "no room: nothing written rather than a file Windsurf truncates")
        self.assertEqual([d["name"] for d in plan.dropped], ["a"])

    def test_kiros_own_file_goes_when_no_memory_is_left(self):
        apply_global_plan(plan_global_compile([_memory("a", "Keep answers short.")], self.home, targets=["kiro"]))
        kiro = self.home / ".kiro/steering/link-memory.md"
        self.assertTrue(kiro.exists())
        plan = plan_global_compile([], self.home, targets=["kiro"])
        self.assertIsNone(plan.files[".kiro/steering/link-memory.md"])
        apply_global_plan(plan)
        self.assertFalse(kiro.exists())

    def test_refresh_only_follows_the_personal_workspace_and_owned_files(self):
        personal = self.home / "link" / "wiki"
        personal.mkdir(parents=True)
        other = self.home / "team" / "wiki"
        other.mkdir(parents=True)
        zed = self.home / ".config/zed/AGENTS.md"
        saved = dict(os.environ)
        os.environ.pop("LINK_WORKSPACE", None)
        os.environ.update(HOME=str(self.home), USERPROFILE=str(self.home))
        try:
            self.assertEqual(refresh_after_memory_change(personal, self.home), [], "no owned file: nothing created")
            self.assertFalse(zed.exists())
            zed.write_text(BLOCK_BEGIN + "\n- stale\n" + BLOCK_END + "\n", encoding="utf-8")
            self.assertEqual(refresh_after_memory_change(other, self.home), [], "another workspace never writes")
            self.assertIn("stale", zed.read_text(encoding="utf-8"))
            self.assertEqual(refresh_after_memory_change(personal, self.home), [str(zed)])
            self.assertNotIn("stale", zed.read_text(encoding="utf-8"))
        finally:
            os.environ.clear()
            os.environ.update(saved)


class GlobalCompileCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.home = base / "home"
        (self.home / ".config" / "zed").mkdir(parents=True)
        self.ws = base / "ws"
        self.env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home), "LINK_USAGE": "off",
                    "LINK_WORKSPACE": str(self.ws)}
        subprocess.run([*LINK, "demo", str(self.ws), "--force"], check=True, capture_output=True, env=self.env)

    def tearDown(self):
        self.temp.cleanup()

    def _run(self, *args):
        return subprocess.run([*LINK, *args], capture_output=True, text=True, check=True, env=self.env)

    def test_compile_global_then_an_archive_takes_the_memory_back_out(self):
        result = json.loads(self._run("compile", str(self.ws), "--global", "--json").stdout)
        self.assertEqual(result["changed"], [".config/zed/AGENTS.md"])
        zed = self.home / ".config" / "zed" / "AGENTS.md"
        text = zed.read_text(encoding="utf-8")
        name = result["included"]["zed"][0]
        title = next(line for line in text.splitlines() if line.startswith("- "))
        self.assertTrue(title)
        self._run("archive-memory", name, str(self.ws))
        self.assertNotIn(title, zed.read_text(encoding="utf-8"), "an archived memory leaves the global file at once")
        check = subprocess.run([*LINK, "compile", str(self.ws), "--global", "--check"], capture_output=True,
                               text=True, env=self.env)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_another_workspaces_change_leaves_the_global_file_alone(self):
        result = json.loads(self._run("compile", str(self.ws), "--global", "--json").stdout)
        zed = self.home / ".config" / "zed" / "AGENTS.md"
        before = zed.read_text(encoding="utf-8")
        other = Path(self.temp.name) / "other"
        subprocess.run([*LINK, "demo", str(other), "--force"], check=True, capture_output=True, env=self.env)
        self._run("archive-memory", result["included"]["zed"][0], str(other))
        self.assertEqual(zed.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
