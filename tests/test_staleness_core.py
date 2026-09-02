from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.staleness import (  # noqa: E402
    StalenessChecker,
    describe_findings,
    repo_path_references,
    stale_findings,
)


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=str(root),
        check=True,
        capture_output=True,
        # Inherit the real environment so git resolves on every platform; a
        # hardcoded POSIX PATH silently found no git on Windows. Identity and
        # config are pinned so the host's settings cannot leak in.
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.test",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
        },
    )


class StalenessReferenceTests(unittest.TestCase):
    def test_extracts_paths_and_bare_source_filenames(self):
        refs = repo_path_references("see src/app/main.ts and also watch.sh for details")
        self.assertIn("src/app/main.ts", refs)
        self.assertIn("watch.sh", refs)

    def test_windows_separators_are_recognised(self):
        # A memory written on Windows must be checked like any other.
        refs = repo_path_references(r"the parser lives in src\\old.py and tool.sh")
        self.assertIn("src/old.py", refs)
        self.assertIn("tool.sh", refs)

    def test_ignores_prose_that_merely_contains_dots(self):
        for text in ["we shipped 2.3.0 on Tuesday", "see e.g. the notes", "about 3.5 percent"]:
            self.assertEqual(repo_path_references(text), [], text)

    def test_ignores_the_memory_store_itself(self):
        # Wiki pages move for their own reasons and are not code.
        self.assertEqual(repo_path_references("wiki/memories/foo.md moved"), [])


class StalenessFindingTests(unittest.TestCase):
    """A memory is only questioned when git proves the path was real and is gone."""

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.repo = Path(self._temp.name)
        _git(self.repo, "init", "--initial-branch", "main")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "old.py").write_text("x = 1\n", encoding="utf-8")
        (self.repo / "src" / "kept.py").write_text("y = 2\n", encoding="utf-8")
        (self.repo / "tool.sh").write_text("echo hi\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-m", "seed")

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _delete(self, relative: str) -> None:
        _git(self.repo, "rm", "-q", relative)
        _git(self.repo, "commit", "-m", f"remove {relative}")

    def test_silent_while_the_path_still_exists(self):
        self.assertEqual(stale_findings("logic lives in src/kept.py", self.repo), [])

    def test_flags_a_path_git_tracked_and_no_longer_has(self):
        self._delete("src/old.py")
        findings = stale_findings("the parser lives in src/old.py", self.repo)
        self.assertEqual([f["path"] for f in findings], ["src/old.py"])
        self.assertEqual(findings[0]["reason"], "removed")

    def test_flags_a_removed_root_level_file(self):
        self._delete("tool.sh")
        self.assertEqual([f["path"] for f in stale_findings("run tool.sh first", self.repo)], ["tool.sh"])

    def test_silent_for_a_path_the_repository_never_had(self):
        # Prose, not a stale reference. Flagging this is the noise that makes
        # people stop reading the flag.
        self.assertEqual(stale_findings("put it in config/settings.py", self.repo), [])

    def test_reports_the_successor_when_git_recorded_a_rename(self):
        _git(self.repo, "mv", "src/old.py", "src/new.py")
        _git(self.repo, "commit", "-m", "rename")
        findings = stale_findings("the parser lives in src/old.py", self.repo)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["reason"], "renamed")
        self.assertEqual(findings[0]["successor"], "src/new.py")
        self.assertIn("renamed to src/new.py", describe_findings(findings)[0])

    def test_degrades_silently_where_git_cannot_answer(self):
        with tempfile.TemporaryDirectory() as plain:
            self.assertEqual(stale_findings("src/old.py is gone", Path(plain)), [])

    def test_checker_resolves_each_path_against_git_once(self):
        # Fifty memories citing the same moved file must cost one lookup.
        self._delete("src/old.py")
        calls: list[str] = []

        def runner(root: Path, arguments: list[str]) -> str:
            calls.append(" ".join(arguments))
            return "abc123 seed\n" if arguments[-1] == "src/old.py" and "log" in arguments and "-1" in arguments else ""

        checker = StalenessChecker(self.repo, runner=runner)
        for _ in range(50):
            self.assertEqual([f["path"] for f in checker.findings("see src/old.py")], ["src/old.py"])
        known_lookups = [c for c in calls if c.endswith("-- src/old.py")]
        rename_scans = [c for c in calls if "--diff-filter=R" in c]
        self.assertEqual(len(known_lookups), 1)
        self.assertEqual(len(rename_scans), 1)

    def test_lookups_are_capped(self):
        text = " ".join(f"src/gone{index}.py" for index in range(40))
        calls: list[str] = []

        def runner(_root: Path, arguments: list[str]) -> str:
            calls.append(arguments[-1])
            return ""

        stale_findings(text, self.repo, runner=runner, limit=5)
        self.assertLessEqual(len(set(calls)), 5)


class StaleCommandTests(unittest.TestCase):
    """The command must stay quiet on a healthy workspace and never write."""

    def test_command_is_registered_and_documented(self):
        from scripts import check_tool_contract as contract  # noqa: PLC0415

        self.assertIn("stale", contract.EXPECTED_CLI_COMMANDS)
        self.assertEqual(contract.check_tool_contract(), [])

    def test_reports_findings_without_modifying_any_memory(self):
        import subprocess as sp  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as repo_dir:
            repo = Path(repo_dir)
            _git(repo, "init", "--initial-branch", "main")
            (repo / "gone.py").write_text("x = 1\n", encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-m", "seed")
            _git(repo, "rm", "-q", "gone.py")
            _git(repo, "commit", "-m", "remove")

            # The child link.py must be able to spawn git itself. On Windows,
            # CreateProcess searches the parent's PATH for the test's own git
            # calls, which hid the fact that a POSIX-only PATH reached the child.
            env = {**os.environ, "HOME": workspace, "USERPROFILE": workspace}
            sp.run([sys.executable, str(ROOT / "link.py"), "demo", workspace, "--force"],
                   check=True, capture_output=True, env=env)
            sp.run([sys.executable, str(ROOT / "link.py"), "remember",
                    "the parser lives in gone.py", workspace], check=True, capture_output=True, env=env)

            pages = sorted((Path(workspace) / "wiki" / "memories").glob("*.md"))
            before = {p: p.read_bytes() for p in pages}

            # An archived memory naming the same gone path must not be reported.
            archived = Path(workspace) / "wiki" / "memories" / "archived-note.md"
            archived.write_text(
                "---\ntype: memory\ntitle: \"old\"\nmemory_type: note\nscope: user\n"
                "status: archived\ndate_captured: \"2026-01-01T00:00:00Z\"\nsource: \"t\"\n---\n\n"
                "# old\n\nthe parser used to live in gone.py\n",
                encoding="utf-8",
            )
            pages = sorted((Path(workspace) / "wiki" / "memories").glob("*.md"))
            before = {p: p.read_bytes() for p in pages}
            result = sp.run([sys.executable, str(ROOT / "link.py"), "stale", workspace, "--repo", str(repo)],
                            capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("gone.py", result.stdout)
            self.assertNotIn("archived-note", result.stdout)
            self.assertIn("Nothing was changed", result.stdout)
            self.assertEqual({p: p.read_bytes() for p in pages}, before, "stale must not write")


class RecallPacketMarkerTests(unittest.TestCase):
    """Staleness reaches the agent in the recall packet, only when it applies."""

    def _packet(self, repo_root):
        from link_core.memory import memory_records, write_memory_page
        from link_core.query import query_link
        from link_core.wiki import build_wiki_cache

        with tempfile.TemporaryDirectory() as t:
            wiki = Path(t) / "wiki"
            (wiki / "memories").mkdir(parents=True)
            (wiki / "index.md").write_text("# Index\n")
            (wiki / "log.md").write_text("# Log\n")
            write_memory_page(wiki, "the parser lives in src/old.py", title="parser", memory_type="note",
                              scope="user", tags=None, source="t", timestamp="2026-08-01T00:00:00Z",
                              allow_duplicate=True, allow_conflict=True)
            cache = build_wiki_cache(wiki)
            return query_link(wiki, "parser", cache, memory_records(wiki), budget="micro", repo_root=repo_root)

    def test_marks_a_memory_naming_a_removed_path(self):
        with tempfile.TemporaryDirectory() as repo_dir:
            repo = Path(repo_dir)
            _git(repo, "init", "--initial-branch", "main")
            (repo / "src").mkdir()
            (repo / "src" / "old.py").write_text("x\n", encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-m", "seed")
            _git(repo, "rm", "-q", "src/old.py")
            _git(repo, "commit", "-m", "rm")
            packet = self._packet(repo)
        memories = packet["memory"]["items"]
        self.assertTrue(memories)
        self.assertEqual([m["path"] for m in memories[0]["stale_paths"]], ["src/old.py"])
        # The marker must arrive with an instruction, or the agent has a flag and no idea what it means.
        self.assertTrue(any("stale_paths" in line for line in packet["agent_guidance"]))

    def test_no_marker_without_a_repository(self):
        with tempfile.TemporaryDirectory() as plain:
            packet = self._packet(Path(plain))          # exists, but no .git
        self.assertNotIn("stale_paths", packet["memory"]["items"][0])
        self.assertFalse(any("stale_paths" in line for line in packet["agent_guidance"]))
        packet = self._packet(None)                    # opt-in not given
        self.assertNotIn("stale_paths", packet["memory"]["items"][0])
