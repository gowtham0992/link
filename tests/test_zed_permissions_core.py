"""Reviewed rules as Zed's own tool permissions, written into a settings file that belongs to the person."""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.global_compile import apply_global_plan, owned_global_targets, plan_global_compile  # noqa: E402
from link_core.mcp_connect import _jsonc_loads  # noqa: E402
from link_core.zed_permissions import (  # noqa: E402
    MARKER,
    command_regex,
    compile_permissions,
    path_regex,
    splice,
)

RULES = ["ask command: git push --force*", "deny write: migrations/**", "ask read: .env"]


def _memory(name="no-force-push", rules=RULES, **extra):
    record = {"name": name, "title": "Never force-push", "tldr": "Never force-push shared branches.",
              "memory_type": "preference", "scope": "user", "visibility": "private", "status": "active",
              "review_status": "reviewed", "enforce": rules}
    record.update(extra)
    return record


def _hits(regex, text):
    return re.search(regex, text, re.IGNORECASE) is not None  # Zed's matching is case-insensitive


class TranslationTests(unittest.TestCase):
    def test_commands_match_as_links_own_matcher_does(self):
        regex = command_regex("git push --force*")
        for command in ("git push --force", "git push --force origin main", "sudo git push --force",
                        "env GIT_TRACE=1 git push --force-with-lease", "/usr/bin/git  push --force"):
            self.assertTrue(_hits(regex, command), command)
        for command in ("git push origin main", "echo git push --force", "git pushx --force"):
            self.assertFalse(_hits(regex, command), command)
        for command in ("sudo -u deploy git push --force", "nice -n 5 git push --force",
                        "env -u FOO git push --force", "xargs git push --force", "\\git push --force"):
            self.assertTrue(_hits(regex, command), "a wrapper's option values: " + command)

    def test_paths_match_at_any_depth(self):
        self.assertTrue(_hits(path_regex("migrations/**"), "app/migrations/0001_init.sql"))
        self.assertTrue(_hits(path_regex("migrations/**"), "migrations/x.sql"))
        self.assertFalse(_hits(path_regex("migrations/**"), "src/migrations_helper.py"))
        self.assertTrue(_hits(path_regex("migrations/**"), "proj/migrations"), "deleting the folder itself")
        self.assertTrue(_hits(path_regex(".env"), "project/.env"))
        self.assertFalse(_hits(path_regex(".env"), "project/.env.example"))
        self.assertFalse(_hits(path_regex(".env"), "project/xenv"), "the dot is literal")

    def test_rules_become_zeds_shape_and_reads_are_reported(self):
        permissions, skipped, names = compile_permissions([_memory()])
        tools = permissions["tools"]
        self.assertEqual(sorted(tools), ["copy_path", "create_directory", "delete_path", "edit_file", "move_path",
                                         "terminal", "write_file"])
        self.assertEqual(list(tools["terminal"]), ["always_confirm"])
        self.assertEqual(list(tools["edit_file"]), ["always_deny"])
        self.assertEqual([s["reason"] for s in skipped], ["Zed has no rule for reading files"])
        self.assertEqual(names, ["no-force-push"])
        self.assertEqual(compile_permissions([_memory(review_status="pending")])[0], {},
                         "a rule that was never reviewed is not in force")


class SpliceTests(unittest.TestCase):
    PERMS = {"tools": {"terminal": {"always_deny": [{"pattern": "^rm"}]}}}

    def test_comments_and_everything_else_survive(self):
        text = '// my settings\n{\n  "theme": "One Dark", // dark\n  "agent": {\n    "default_model": {"provider": "x"},\n  },\n}\n'
        updated = splice(text, self.PERMS)
        self.assertIn("// my settings", updated)
        self.assertIn("// dark", updated)
        self.assertIn(MARKER, updated)
        parsed = _jsonc_loads(updated)
        self.assertEqual(parsed["agent"]["tool_permissions"], self.PERMS)
        self.assertEqual(parsed["agent"]["default_model"], {"provider": "x"})
        changed = {"tools": {"terminal": {"always_confirm": [{"pattern": "^git"}]}}}
        again = splice(updated, changed)
        self.assertEqual(_jsonc_loads(again)["agent"]["tool_permissions"], changed)
        self.assertEqual(again.count(MARKER), 1)
        removed = splice(again, {})
        self.assertNotIn(MARKER, removed)
        self.assertNotIn("tool_permissions", _jsonc_loads(removed)["agent"])
        self.assertEqual(_jsonc_loads(removed)["theme"], "One Dark")

    def test_new_files_and_files_without_an_agent_setting(self):
        self.assertEqual(_jsonc_loads(splice(None, self.PERMS))["agent"]["tool_permissions"], self.PERMS)
        self.assertEqual(_jsonc_loads(splice('{"vim_mode": true}', self.PERMS))["vim_mode"], True)
        self.assertIsNone(splice(None, {}))
        self.assertEqual(splice('{"a": 1}', {}), '{"a": 1}')

    def test_the_persons_own_permissions_are_never_touched(self):
        mine = '{"agent": {"tool_permissions": {"default": "confirm"}}}'
        with self.assertRaises(ValueError) as caught:
            splice(mine, self.PERMS)
        self.assertIn("of your own", str(caught.exception))
        with self.assertRaises(ValueError):
            splice('{"agent": ', self.PERMS)


class GlobalCompileZedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        (self.home / ".config" / "zed").mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_rules_reach_zeds_settings_and_follow_the_memory(self):
        settings = self.home / ".config" / "zed" / "settings.json"
        settings.write_text('{\n  // keep me\n  "theme": "Ayu"\n}\n', encoding="utf-8")
        apply_global_plan(plan_global_compile([_memory()], self.home, targets=["zed", "zed-permissions"]))
        parsed = _jsonc_loads(settings.read_text(encoding="utf-8"))
        self.assertIn("terminal", parsed["agent"]["tool_permissions"]["tools"])
        self.assertIn("// keep me", settings.read_text(encoding="utf-8"))
        self.assertIn("zed-permissions", owned_global_targets(self.home))
        refresh = plan_global_compile([_memory(status="archived")], self.home, targets=["zed-permissions"])
        self.assertNotIn(".config/zed/AGENTS.md", refresh.files, "a settings refresh never creates AGENTS.md")
        apply_global_plan(refresh)
        self.assertNotIn("tool_permissions", json.dumps(_jsonc_loads(settings.read_text(encoding="utf-8"))))

    def test_project_rules_stay_out_and_own_permissions_get_a_snippet(self):
        plan = plan_global_compile([_memory(scope="project", project="api")], self.home,
                                   targets=["zed", "zed-permissions"])
        self.assertNotIn(".config/zed/settings.json", plan.files)
        settings = self.home / ".config" / "zed" / "settings.json"
        settings.write_text('{"agent": {"tool_permissions": {"default": "allow"}}}', encoding="utf-8")
        plan = plan_global_compile([_memory()], self.home, targets=["zed", "zed-permissions"])
        self.assertNotIn(".config/zed/settings.json", plan.files)
        self.assertIn("tool_permissions", plan.zed_snippet)
        self.assertTrue(any(c["path"] == ".config/zed/settings.json" for c in plan.conflicts))

    def test_a_refresh_never_starts_editing_settings(self):
        settings = self.home / ".config" / "zed" / "settings.json"
        settings.write_text('{\n  // mine\n  "theme": "Ayu"\n}\n', encoding="utf-8")
        apply_global_plan(plan_global_compile([_memory()], self.home, targets=["zed"]))  # AGENTS.md only
        self.assertEqual(owned_global_targets(self.home), ["zed"])
        refresh = plan_global_compile([_memory()], self.home, targets=owned_global_targets(self.home))
        self.assertNotIn(".config/zed/settings.json", refresh.files)
        settings.unlink()
        refresh = plan_global_compile([_memory()], self.home, targets=owned_global_targets(self.home))
        self.assertNotIn(".config/zed/settings.json", refresh.files, "nor creates the file")

    def test_the_persons_comments_beside_links_block_survive(self):
        permissions, _, _ = compile_permissions([_memory()])
        other, _, _ = compile_permissions([_memory(rules=["deny command: rm -rf /*"])])
        start = '{\n  "agent": {\n    "default_model": {"provider": "x"}, // my model note\n  },\n  "theme": "y"\n}\n'
        written = splice(start, permissions)
        self.assertIn("// my model note", written)
        mine = written.replace(MARKER, "// above Link's block\n    " + MARKER)
        replaced = splice(mine, other)
        self.assertIn("// my model note", replaced)
        self.assertIn("// above Link's block", replaced)
        self.assertEqual(splice(replaced, other), replaced, "applying twice changes nothing")
        removed = splice(replaced, {})
        self.assertIn("// my model note", removed)
        self.assertIn("// above Link's block", removed)
        self.assertNotIn("tool_permissions", removed)
        self.assertEqual(splice(splice(start, permissions), {}), start, "the original back, byte for byte")


if __name__ == "__main__":
    unittest.main()
