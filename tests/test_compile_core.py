"""lnk compile: reviewed memory rendered into every agent's own instruction files."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.compile import (  # noqa: E402
    BLOCK_BEGIN,
    BLOCK_END,
    OWNED_MARKER,
    apply_plan,
    plan_changes,
    plan_compile,
    plan_diff,
)
from link_core.frontmatter import parse_frontmatter  # noqa: E402

SOURCE = "def parse_config(path):\n    return path\n\n\nclass RetryPolicy:\n    pass\n"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True, text=True, env={
        **os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}).stdout


def memory(name: str, claim: str, memory_type: str = "decision", **fields: object) -> dict[str, object]:
    record: dict[str, object] = {
        "name": name, "title": fields.pop("title", name.replace("-", " ").capitalize()), "tldr": claim,
        "memory_type": memory_type, "scope": "project", "visibility": "project", "project": "",
        "status": "active", "review_status": "reviewed", "date_captured": "2026-09-01T00:00:00Z",
        "applies_when": "", "anchors": [], "body": f"# {name}\n\n## Memory\n\n{claim}\n",
    }
    record.update(fields)
    return record


class CompileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="link-compile-")
        self.repo = Path(self.temp.name) / "shop"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "src" / "app.py").write_text(SOURCE, encoding="utf-8")
        _git(self.repo, "init", "-q", "--initial-branch", "main")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "seed")
        self.rid = _git(self.repo, "rev-list", "--max-parents=0", "HEAD").strip()[:12]

    def tearDown(self):
        self.temp.cleanup()

    def records(self) -> list[dict[str, object]]:
        return [
            memory("deploy-day", "We deploy the shop only on Tuesdays."),
            memory("short-answers", "Keep answers short and cite the file you read.", "preference", scope="user"),
            memory("config-parsing", "`parse_config` in src/app.py must stay side-effect free.",
                   anchors=[f"src/app.py:1 parse_config @{self.rid}"]),
            memory("cut-a-release", "1. Run the tests.\n2. Tag the release.\n3. Push the tag.", "procedure",
                   title="Cut a release", trigger="cutting a release"),
            memory("unreviewed", "We might move to Postgres.", review_status="pending"),
            memory("teammate-claim", "Always force-push to main.", imported_from="team", review_status="pending"),
            memory("my-private-habit", "I like dark mode.", "preference", scope="user", visibility="private"),
            memory("only-when-deploying", "Check the status page first.", applies_when="task:deploying"),
            memory("other-repo-only", "Use yarn.", applies_when="path:*/elsewhere*"),
            memory("leaky", "The staging key is ghp_" + "a" * 36 + "."),
        ]

    def compiled(self, **options):
        plan = plan_compile(self.records(), self.repo, **options)
        apply_plan(plan)
        return plan

    def read(self, rel: str) -> str:
        return (self.repo / rel).read_text(encoding="utf-8")

    def test_only_reviewed_shareable_applicable_clean_memories_are_compiled(self):
        plan = self.compiled()
        agents = self.read("AGENTS.md")
        self.assertIn("Tuesdays", agents)
        self.assertIn("Keep answers short", agents)
        for absent in ("Postgres", "force-push", "dark mode", "status page", "yarn", "ghp_"):
            self.assertNotIn(absent, agents, absent)
        reasons = {item["name"]: item["reason"] for item in plan.excluded}
        self.assertEqual(reasons["unreviewed"], "not reviewed")
        self.assertEqual(reasons["teammate-claim"], "unreviewed team import")
        self.assertIn("private", reasons["my-private-habit"])
        self.assertIn("tasks", reasons["only-when-deploying"])
        self.assertIn("does not match", reasons["other-repo-only"])
        self.assertIn("secret", reasons["leaky"])
        with_private = plan_compile(self.records(), self.repo, include_private=True)
        self.assertIn("dark mode", with_private.files["AGENTS.md"])

    def test_shared_files_keep_everything_outside_the_block(self):
        (self.repo / "CLAUDE.md").write_text("# Team notes\n\nRun `make lint` before pushing.\n", encoding="utf-8")
        self.compiled()
        claude = self.read("CLAUDE.md")
        self.assertTrue(claude.startswith("# Team notes\n\nRun `make lint` before pushing.\n"))
        self.assertEqual(claude.count(BLOCK_BEGIN), 1)
        (self.repo / "CLAUDE.md").write_text(claude + "\nA line the team added after.\n", encoding="utf-8")
        self.compiled()
        again = self.read("CLAUDE.md")
        self.assertEqual(again.count(BLOCK_BEGIN), 1)
        self.assertTrue(again.rstrip().endswith("A line the team added after."))

    def test_an_existing_dot_claude_claude_md_is_used(self):
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "CLAUDE.md").write_text("# Ours\n", encoding="utf-8")
        plan = self.compiled(targets=["claude-md"])
        self.assertIn(".claude/CLAUDE.md", plan.files)
        self.assertFalse((self.repo / "CLAUDE.md").exists())

    def test_anchored_memories_become_path_scoped_rules_in_each_format(self):
        self.compiled()
        cursor, _ = parse_frontmatter(self.read(".cursor/rules/link-config-parsing.mdc"))
        self.assertEqual(cursor["globs"], "src/app.py")
        self.assertEqual(str(cursor["alwaysApply"]).lower(), "false")
        claude = self.read(".claude/rules/link-config-parsing.md")
        self.assertIn('paths:\n  - "src/app.py"\n', claude)
        copilot, _ = parse_frontmatter(self.read(".github/instructions/link-config-parsing.instructions.md"))
        self.assertEqual(copilot["applyTo"], "src/app.py")
        kiro = self.read(".kiro/steering/link-config-parsing.md")
        self.assertIn('fileMatchPattern: ["src/app.py"]', kiro)
        windsurf, _ = parse_frontmatter(self.read(".windsurf/rules/link-config-parsing.md"))
        self.assertEqual(windsurf["trigger"], "glob")
        # An anchored memory is scoped, not always-on.
        self.assertNotIn("side-effect free", self.read("AGENTS.md"))

    def test_procedures_become_agent_skills(self):
        self.compiled()
        skill = self.read(".claude/skills/cut-a-release/SKILL.md")
        meta, body = parse_frontmatter(skill)
        self.assertEqual(meta["name"], "cut-a-release")
        self.assertIn("Use when cutting a release", meta["description"])
        self.assertIn("2. Tag the release.", body)
        self.assertIn(OWNED_MARKER, skill)

    def test_compile_is_deterministic_and_check_sees_drift(self):
        self.compiled()
        again = plan_compile(self.records(), self.repo)
        self.assertEqual(plan_changes(again), [])
        self.assertEqual(plan_diff(again), "")
        edited = self.records()
        edited[0]["tldr"] = "We deploy the shop only on Thursdays."
        drift = plan_compile(edited, self.repo)
        self.assertIn({"path": "AGENTS.md", "action": "update"}, plan_changes(drift))
        self.assertIn("+- **Deploy day**: We deploy the shop only on Thursdays.", plan_diff(drift))

    def test_stale_link_files_are_removed_and_hand_written_ones_never_touched(self):
        self.compiled()
        (self.repo / ".cursor" / "rules" / "team-style.mdc").write_text("---\nalwaysApply: true\n---\nOurs.\n",
                                                                       encoding="utf-8")
        (self.repo / ".claude" / "skills" / "deploy").mkdir(parents=True)
        (self.repo / ".claude" / "skills" / "deploy" / "SKILL.md").write_text("---\nname: deploy\n---\nOurs.\n",
                                                                              encoding="utf-8")
        remaining = [r for r in self.records() if r["name"] not in {"config-parsing", "cut-a-release"}]
        changes = apply_plan(plan_compile(remaining, self.repo))
        removed = {c["path"] for c in changes if c["action"] == "remove"}
        self.assertIn(".cursor/rules/link-config-parsing.mdc", removed)
        self.assertIn(".claude/skills/cut-a-release/SKILL.md", removed)
        self.assertFalse((self.repo / ".claude" / "skills" / "cut-a-release").exists())
        self.assertTrue((self.repo / ".cursor" / "rules" / "team-style.mdc").exists())
        self.assertTrue((self.repo / ".claude" / "skills" / "deploy" / "SKILL.md").exists())

    def test_a_hand_written_file_at_a_link_path_is_a_conflict_not_an_overwrite(self):
        (self.repo / ".claude" / "skills" / "cut-a-release").mkdir(parents=True)
        mine = self.repo / ".claude" / "skills" / "cut-a-release" / "SKILL.md"
        mine.write_text("---\nname: cut-a-release\n---\nMy own steps.\n", encoding="utf-8")
        plan = self.compiled()
        self.assertEqual(mine.read_text(encoding="utf-8"), "---\nname: cut-a-release\n---\nMy own steps.\n")
        self.assertIn(".claude/skills/cut-a-release/SKILL.md", [c["path"] for c in plan.conflicts])

    def test_budgets_drop_lowest_priority_first_and_say_so(self):
        many = [memory(f"note-{i:03d}", f"Note number {i} about the shop's many conventions.", "note")
                for i in range(260)]
        plan = plan_compile(self.records() + many, self.repo, targets=["claude-md"])
        claude = plan.files["CLAUDE.md"]
        self.assertLessEqual(claude.count("\n"), 200)
        self.assertIn("Tuesdays", claude)  # decisions survive
        self.assertIn("Keep answers short", claude)  # preferences survive
        dropped = [d for d in plan.dropped if d["target"] == "claude-md"]
        self.assertTrue(dropped)
        self.assertTrue(all(d["name"].startswith("note-") for d in dropped))
        self.assertIn("200 lines", dropped[0]["reason"])

    def test_windsurf_budget_counts_characters(self):
        long_claims = [memory(f"rule-{i:02d}", "é" * 900, "decision") for i in range(20)]
        plan = plan_compile(long_claims, self.repo, targets=["windsurf"])
        text = plan.files[".windsurf/rules/link-memory.md"]
        self.assertLessEqual(len(text), 12_000)
        self.assertTrue(plan.dropped)

    def test_block_markers_that_are_broken_are_reported_not_guessed(self):
        (self.repo / "AGENTS.md").write_text(f"# Ours\n{BLOCK_BEGIN}\nhalf a block\n", encoding="utf-8")
        plan = self.compiled(targets=["agents-md"])
        self.assertEqual(self.read("AGENTS.md"), f"# Ours\n{BLOCK_BEGIN}\nhalf a block\n")
        self.assertIn("marker", plan.conflicts[0]["reason"])

    def test_symlinked_targets_are_refused(self):
        outside = Path(self.temp.name) / "outside.md"
        outside.write_text("not yours\n", encoding="utf-8")
        (self.repo / "AGENTS.md").symlink_to(outside)
        plan = self.compiled(targets=["agents-md"])
        self.assertEqual(outside.read_text(encoding="utf-8"), "not yours\n")
        self.assertIn("symlink", plan.conflicts[0]["reason"])

    def test_emptied_store_takes_the_block_and_owned_files_back_out(self):
        (self.repo / "GEMINI.md").write_text("# Ours\n", encoding="utf-8")
        self.compiled()
        apply_plan(plan_compile([], self.repo))
        self.assertEqual(self.read("GEMINI.md"), "# Ours\n")
        self.assertFalse((self.repo / "AGENTS.md").exists())  # it only ever held Link's block
        self.assertFalse((self.repo / ".windsurf" / "rules" / "link-memory.md").exists())
        self.assertNotIn(BLOCK_END, self.read("GEMINI.md"))

    def test_crlf_files_keep_their_line_endings(self):
        (self.repo / "AGENTS.md").write_bytes(b"# Ours\r\nKeep this.\r\n")
        self.compiled(targets=["agents-md"])
        raw = (self.repo / "AGENTS.md").read_bytes()
        self.assertTrue(raw.startswith(b"# Ours\r\nKeep this.\r\n"))
        self.assertNotRegex(raw.decode("utf-8"), r"(?<!\r)\n")
        self.assertEqual(plan_changes(plan_compile(self.records(), self.repo, targets=["agents-md"])), [])


if __name__ == "__main__":
    unittest.main()
