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
    ZED_PERMISSIONS,
    apply_global_plan,
    detected_global_targets,
    kiro_start_hook,
    owned_global_targets,
    plan_global_compile,
    refresh_after_memory_change,
    refresh_global_files,
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
        self.assertEqual(detected_global_targets(self.home), ["windsurf", "kiro", "zed", "zed-permissions"])
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

    def test_rewriting_is_idempotent_and_an_empty_set_empties_the_block(self):
        records = [_memory("short-answers", "Keep answers short.")]
        apply_global_plan(plan_global_compile(records, self.home, targets=["zed"]))
        again = plan_global_compile(records, self.home, targets=["zed"])
        self.assertEqual(again.files, {})
        self.assertEqual(again.unchanged, [".config/zed/AGENTS.md"])
        zed = self.home / ".config/zed/AGENTS.md"
        zed.write_text("# Zed notes\n\n" + zed.read_text(encoding="utf-8"), encoding="utf-8")
        apply_global_plan(plan_global_compile([], self.home, targets=["zed"]))
        text = zed.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Zed notes\n"))
        self.assertNotIn("Keep answers short", text)
        self.assertIn(BLOCK_BEGIN, text, "an empty block keeps the file Link's to refresh")

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
        self.assertEqual([item["path"] for item in plan.no_room], [".codeium/windsurf/memories/global_rules.md"])

    def test_no_room_never_takes_links_block_away_and_the_block_fills_again(self):
        memory = _memory("a", "Keep answers short.")
        rules = self.home / ".codeium/windsurf/memories/global_rules.md"
        apply_global_plan(plan_global_compile([memory], self.home, targets=["windsurf"]))
        block = rules.read_text(encoding="utf-8")
        rules.write_text("x" * 5990 + "\n\n" + block, encoding="utf-8")  # the person's own text fills the limit
        warnings = []
        refresh_global_files([memory], self.home, warnings)
        text = rules.read_text(encoding="utf-8")
        self.assertIn(BLOCK_BEGIN, text, "a refresh never deletes Link's block for lack of room")
        self.assertNotIn("Keep answers short", text)
        self.assertTrue(text.startswith("x" * 5990), "the person's text is kept")
        self.assertEqual(owned_global_targets(self.home), ["windsurf"])
        self.assertEqual([w["path"] for w in warnings], [".codeium/windsurf/memories/global_rules.md"])
        self.assertIn("shorten", warnings[0]["reason"])
        rules.write_text(text[5990:].lstrip(), encoding="utf-8")  # the person makes room
        refresh_global_files([memory], self.home)
        self.assertIn("Keep answers short", rules.read_text(encoding="utf-8"), "the next refresh fills it again")

    def test_kiro_keeps_its_steering_copy_with_links_hooks_for_the_ide(self):
        memory = _memory("a", "Keep answers short.")
        steering = self.home / ".kiro/steering/link-memory.md"
        apply_global_plan(plan_global_compile([memory], self.home, targets=["kiro"]))
        self.assertTrue(steering.exists())
        self.assertEqual(kiro_start_hook(self.home), "")
        hooks = self.home / ".kiro/hooks/link.json"
        hooks.parent.mkdir(parents=True)
        pre_tool = {"name": "Link pre-tool", "trigger": "PreToolUse",
                    "action": {"type": "command", "command": "python3 /opt/link/link_hook.py hook pre-tool /ws"}}
        hooks.write_text(json.dumps({"version": "v1", "hooks": [pre_tool]}), encoding="utf-8")
        self.assertEqual(kiro_start_hook(self.home), "", "rule checks alone do not hand Kiro the brief")
        start = {"name": "Link session-start", "trigger": "SessionStart",
                 "action": {"type": "command", "command": "python3 /opt/link/link.py hook session-start /ws"}}
        hooks.write_text(json.dumps({"version": "v1", "hooks": [start, pre_tool]}), encoding="utf-8")
        self.assertEqual(kiro_start_hook(self.home), ".kiro/hooks/link.json")
        self.assertIn("kiro", detected_global_targets(self.home), "the Kiro IDE reads hooks per workspace only")
        refresh_global_files([memory], self.home)
        self.assertIn("Keep answers short", steering.read_text(encoding="utf-8"))

    def test_ownership_survives_the_last_memory_leaving_and_refresh_brings_it_back(self):
        memory = _memory("a", "Keep answers short.")
        apply_global_plan(plan_global_compile([memory], self.home, targets=["windsurf", "kiro", "zed"]))
        kiro = self.home / ".kiro/steering/link-memory.md"
        self.assertTrue(kiro.exists())
        refresh_global_files([], self.home)
        self.assertTrue(kiro.exists(), "Kiro's file stays, with an empty block, so it stays Link's")
        self.assertNotIn("Keep answers short", kiro.read_text(encoding="utf-8"))
        self.assertEqual(sorted(owned_global_targets(self.home)), ["kiro", "windsurf", "zed"])
        written = refresh_global_files([memory], self.home)
        self.assertEqual(len(written), 3, "restoring the memory refreshes every file again")
        for rel in (".codeium/windsurf/memories/global_rules.md", ".kiro/steering/link-memory.md",
                    ".config/zed/AGENTS.md"):
            self.assertIn("Keep answers short", (self.home / rel).read_text(encoding="utf-8"))
        self.assertEqual(plan_global_compile([memory], self.home, targets=owned_global_targets(self.home)).files, {})

    def test_an_explicit_target_with_no_memory_yet_is_set_up_and_a_detected_one_is_not(self):
        self.assertEqual(plan_global_compile([], self.home).files, {})
        apply_global_plan(plan_global_compile([], self.home, targets=["kiro"]))
        self.assertEqual(owned_global_targets(self.home), ["kiro"])
        refresh_global_files([_memory("a", "Keep answers short.")], self.home)
        self.assertIn("Keep answers short",
                      (self.home / ".kiro/steering/link-memory.md").read_text(encoding="utf-8"))

    def test_zeds_permissions_stay_links_while_no_rule_is_left(self):
        ruled = _memory("no-force-push", "Never force-push.", memory_type="decision",
                        enforce=["deny command: git push --force*"])
        settings = self.home / ".config/zed/settings.json"
        apply_global_plan(plan_global_compile([ruled], self.home, targets=["zed", ZED_PERMISSIONS]))
        self.assertIn("always_deny", settings.read_text(encoding="utf-8"))
        refresh_global_files([], self.home)
        self.assertNotIn("always_deny", settings.read_text(encoding="utf-8"))
        self.assertIn(ZED_PERMISSIONS, owned_global_targets(self.home), "recorded in Zed's AGENTS.md block")
        refresh_global_files([ruled], self.home)
        self.assertIn("always_deny", settings.read_text(encoding="utf-8"), "the rule comes back on its own")
        self.assertNotIn("no rule at the moment", (self.home / ".config/zed/AGENTS.md").read_text(encoding="utf-8"))
        # Taking the settings block back by hand while it has rules is an opt-out a refresh respects.
        settings.write_text("{}\n", encoding="utf-8")
        refresh_global_files([ruled], self.home)
        self.assertEqual(settings.read_text(encoding="utf-8"), "{}\n")

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

    def test_global_compile_follows_the_personal_workspace_wherever_it_is_run(self):
        other = Path(self.temp.name) / "other"
        subprocess.run([*LINK, "init", str(other)], check=True, capture_output=True, env=self.env)
        result = subprocess.run([*LINK, "compile", "--global", "--json"], capture_output=True, text=True,
                                env=self.env, cwd=other)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["included"]["zed"], "the personal workspace's memories")
        self.assertIn("personal workspace", result.stderr)
        refused = subprocess.run([*LINK, "compile", str(other), "--global"], capture_output=True, text=True,
                                 env=self.env)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("personal workspace only", refused.stderr)
        zed = self.home / ".config" / "zed" / "AGENTS.md"
        self.assertIn("- ", zed.read_text(encoding="utf-8"), "a refused run leaves the file as it was")

    def test_nothing_to_write_for_named_targets_says_why(self):
        (self.home / ".kiro" / ".git").mkdir(parents=True)
        result = self._run("compile", str(self.ws), "--global", "--targets", "kiro")
        self.assertIn("Nothing written to kiro: see why below.", result.stdout)
        self.assertNotIn("install found", result.stdout)
        self.assertIn("git work tree", result.stdout)

    def test_a_file_with_no_room_says_so_when_compiled_and_when_a_memory_changes(self):
        self._run("compile", str(self.ws), "--global", "--targets", "windsurf")
        rules = self.home / ".codeium/windsurf/memories/global_rules.md"
        rules.write_text("x" * 5990 + "\n\n" + rules.read_text(encoding="utf-8"), encoding="utf-8")
        name = json.loads(self._run("compile", str(self.ws), "--global", "--dry-run", "--json").stdout)[
            "included"]["zed"][0]
        archived = self._run("archive-memory", name, str(self.ws))
        self.assertIn("No room for your memory in ~/.codeium/windsurf/memories/global_rules.md", archived.stderr)
        self.assertIn(BLOCK_BEGIN, rules.read_text(encoding="utf-8"))
        compiled = self._run("compile", str(self.ws), "--global", "--targets", "windsurf")
        self.assertIn("No room: ~/.codeium/windsurf/memories/global_rules.md", compiled.stdout)


if __name__ == "__main__":
    unittest.main()
