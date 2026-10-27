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

from link_core.compile import BLOCK_BEGIN  # noqa: E402
from link_core.global_compile import apply_global_plan, detected_global_targets, plan_global_compile  # noqa: E402

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
        rules.write_text(own, encoding="utf-8")
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


class GlobalCompileCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.home = base / "home"
        (self.home / ".config" / "zed").mkdir(parents=True)
        self.ws = base / "ws"
        self.env = {**os.environ, "HOME": str(self.home), "LINK_USAGE": "off"}
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


if __name__ == "__main__":
    unittest.main()
