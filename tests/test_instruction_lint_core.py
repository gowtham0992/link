"""lnk stale --instructions: agent instruction files checked like memories."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.compile import BLOCK_BEGIN, BLOCK_END, OWNED_MARKER  # noqa: E402
from link_core.instruction_lint import (  # noqa: E402
    budget_findings,
    claim_lines,
    contradiction_findings,
    discover_instruction_files,
    instruction_kind,
    lint_instructions,
    user_owned_lines,
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, capture_output=True, check=True, env={
        **os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull})


class InstructionFileTests(unittest.TestCase):
    def test_every_agent_family_is_recognised(self):
        cases = {
            "AGENTS.md": "agents-md", "web/AGENTS.md": "agents-md", "CLAUDE.md": "claude-md",
            ".claude/CLAUDE.md": "claude-md", "GEMINI.md": "gemini-md", ".claude/rules/api.md": "claude-rules",
            ".cursor/rules/style.mdc": "cursor-rules", ".windsurf/rules/x.md": "windsurf-rules",
            ".kiro/steering/tech.md": "kiro-steering", ".github/copilot-instructions.md": "copilot",
            ".github/instructions/ts.instructions.md": "copilot-rules",
            "README.md": None, "node_modules/pkg/AGENTS.md": None, ".cursor/rules/notes.md": None,
        }
        for rel, kind in cases.items():
            self.assertEqual(instruction_kind(rel), kind, rel)

    def test_link_owned_content_is_not_checked_twice(self):
        text = f"# Ours\n- Keep it short and plain please.\n{BLOCK_BEGIN}\n- Compiled memory line here.\n{BLOCK_END}\nAfter.\n"
        self.assertEqual([line for _, line in user_owned_lines(text)], ["# Ours", "- Keep it short and plain please.", "After."])
        self.assertEqual(user_owned_lines(f"---\npaths: x\n---\n{OWNED_MARKER}\nbody\n"), [])

    def test_wrapped_rules_are_one_rule(self):
        lines = list(enumerate(["- Never use the check tool name", "  anywhere else in the docs.",
                                "- Second rule stands on its own.", "", "```", "npm run build", "```"], start=1))
        self.assertEqual(claim_lines(lines), [(1, "Never use the check tool name anywhere else in the docs."),
                                              (3, "Second rule stands on its own.")])

    def test_copies_are_not_contradictions_but_changed_values_are(self):
        claims = {
            "AGENTS.md": [(3, "One concern per pull request; split unrelated fixes out."),
                          (4, "Use 2 space indentation in YAML files.")],
            "CLAUDE.md": [(3, "One concern per pull request; split unrelated fixes out."),
                          (4, "Use 4 space indentation in YAML files.")],
        }
        found = contradiction_findings(claims, [])
        self.assertEqual([(f["file"], f["line"], f["other"]) for f in found], [("AGENTS.md", 4, "CLAUDE.md:4")])

    def test_option_words_inside_names_are_not_options(self):
        claims = {
            "AGENTS.md": [(5, "To change anything here, use the `mpn-feature-development` skill.")],
            "CLAUDE.md": [(8, "`master` accepts only squash merges from an up to date branch.")],
        }
        self.assertEqual(contradiction_findings(claims, []), [])

    def test_codex_budget_is_per_chain(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "tests").mkdir()
            (repo / "AGENTS.md").write_text("x" * 20_000, encoding="utf-8")
            (repo / "tests" / "AGENTS.md").write_text("y" * 20_000, encoding="utf-8")
            (repo / "other").mkdir()
            (repo / "other" / "AGENTS.md").write_text("z" * 100, encoding="utf-8")
            found = budget_findings([("AGENTS.md", "agents-md"), ("tests/AGENTS.md", "agents-md"),
                                     ("other/AGENTS.md", "agents-md")], repo)
        self.assertEqual([(f["file"], f["severity"], f["over"]) for f in found],
                         [("tests/AGENTS.md", "truncated", 40_000 - 32 * 1024)])


class InstructionRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="link-instructions-")
        self.repo = Path(self.temp.name)
        _git(self.repo, "init", "-q", "--initial-branch", "main")
        (self.repo / "PLAN.md").write_text("plan\n", encoding="utf-8")
        (self.repo / "CLAUDE.md").write_text("old\n", encoding="utf-8")
        (self.repo / "scripts").mkdir()
        (self.repo / "scripts" / "old.sh").write_text("echo\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "seed")
        _git(self.repo, "mv", "CLAUDE.md", "AGENTS.md")
        _git(self.repo, "rm", "-q", "PLAN.md", "scripts/old.sh")
        (self.repo / "web").mkdir()
        (self.repo / "web" / "AGENTS.md").write_text(
            "- See [CLAUDE.md](CLAUDE.md) for conventions.\n"
            "- Put a PLAN.md in your pull request, then delete it.\n"
            "- Run scripts/old.sh before building.\n"
            "- Read [the guide](guide.md) first.\n", encoding="utf-8")
        (self.repo / "web" / "guide.md").write_text("guide\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "move")

    def tearDown(self):
        self.temp.cleanup()

    def test_linked_and_directory_paths_count_bare_example_names_do_not(self):
        report = lint_instructions(self.repo)
        stale = [(f["file"], f["line"], f["reference"]) for f in report["findings"] if f["kind"] == "stale"]
        self.assertEqual(stale, [("web/AGENTS.md", 1, "CLAUDE.md"), ("web/AGENTS.md", 3, "scripts/old.sh")])
        self.assertIn(("AGENTS.md", "agents-md"), discover_instruction_files(self.repo))
        self.assertEqual(report["flagged"], 2)

    def test_nested_files_with_non_ascii_folders_are_found(self):
        folder = self.repo / "docs" / "é"
        folder.mkdir(parents=True)
        (folder / "AGENTS.md").write_text("- Run scripts/old.sh first.\n", encoding="utf-8")
        self.assertIn(("docs/é/AGENTS.md", "agents-md"), discover_instruction_files(self.repo))
        found = [(f["file"], f["kind"]) for f in lint_instructions(self.repo)["findings"]]
        self.assertIn(("docs/é/AGENTS.md", "stale"), found)

    def test_command_reports_and_exits_like_stale(self):
        import json
        link = [sys.executable, str(ROOT / "link.py")]
        workspace = self.repo.parent / (self.repo.name + "-ws")
        subprocess.run([*link, "init", str(workspace)], capture_output=True, check=True, stdin=subprocess.DEVNULL)
        result = subprocess.run([*link, "stale", str(workspace), "--repo", str(self.repo), "--instructions", "--json"],
                                capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)["flagged"], 2)
        text = subprocess.run([*link, "stale", str(workspace), "--repo", str(self.repo), "--instructions"],
                              capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL)
        self.assertIn("web/AGENTS.md:3  [stale] scripts/old.sh is no longer in the repository", text.stdout)

    def test_the_planted_evaluation_passes(self):
        spec = importlib.util.spec_from_file_location("eval_instructions", ROOT / "scripts" / "eval_instructions.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        result = module.planted_track()
        self.assertEqual(result["missed"], [])
        self.assertEqual(result["quiet_violations"], [])


if __name__ == "__main__":
    unittest.main()
