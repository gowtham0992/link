"""A folder marked untrusted gets no memory from Link and gives none."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mcp_package"))

import link  # noqa: E402
from link_core.folder_trust import set_folder_trust, untrusted_folders, untrusted_parent  # noqa: E402
from link_core.tool_hooks import is_link_governance, post_tool_output  # noqa: E402


def _run(*argv: str, stdin: str = "") -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(sys, "argv", ["link.py", *argv]), mock.patch.object(sys, "stdin", io.StringIO(stdin)), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = link.main()
        except SystemExit as exc:
            code = int(exc.code or 0)
    return int(code or 0), out.getvalue(), err.getvalue()


class FolderTrustTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="link-folder-trust-")
        base = Path(os.path.realpath(self.temp.name))
        self.workspace = base / "link"
        self.vendor = base / "vendor"
        (self.vendor / "deep" / "er").mkdir(parents=True)
        self.project = base / "project"
        self.project.mkdir()
        self.assertEqual(_run("init", str(self.workspace))[0], 0)
        self.assertEqual(_run("remember", "Never deploy on Friday afternoons", str(self.workspace),
                              "--type", "preference")[0], 0)
        self.assertEqual(_run("review-memory", "never-deploy-on-friday-afternoons", str(self.workspace))[0], 0)

    def tearDown(self):
        self.temp.cleanup()

    def _hook(self, event: str, payload: dict[str, object], *extra: str) -> str:
        code, out, _ = _run("hook", event, str(self.workspace), *extra, stdin=json.dumps(payload))
        self.assertEqual(code, 0)
        return out

    def test_marking_covers_the_folder_and_everything_below_it(self):
        self.assertEqual(untrusted_parent(self.workspace, self.vendor), "")
        result = set_folder_trust(self.workspace, self.vendor, untrusted=True)
        self.assertTrue(result["changed"])
        self.assertEqual(untrusted_folders(self.workspace), [str(self.vendor)])
        self.assertEqual(untrusted_parent(self.workspace, self.vendor / "deep" / "er"), str(self.vendor))
        self.assertEqual(untrusted_parent(self.workspace, self.project), "")
        # A sibling whose name merely starts the same is not inside it.
        (self.vendor.parent / "vendor-tools").mkdir()
        self.assertEqual(untrusted_parent(self.workspace, self.vendor.parent / "vendor-tools"), "")
        # Trusting a subfolder does not quietly trust the marked parent.
        result = set_folder_trust(self.workspace, self.vendor / "deep", untrusted=False)
        self.assertFalse(result["changed"])
        self.assertEqual(result["covered_by"], str(self.vendor))
        self.assertTrue(set_folder_trust(self.workspace, self.vendor, untrusted=False)["changed"])
        self.assertEqual(untrusted_folders(self.workspace), [])

    def test_a_symlink_into_an_untrusted_folder_is_untrusted_too(self):
        set_folder_trust(self.workspace, self.vendor, untrusted=True)
        alias = self.vendor.parent / "alias"
        alias.symlink_to(self.vendor / "deep")
        self.assertEqual(untrusted_parent(self.workspace, alias), str(self.vendor))

    def test_the_workspace_and_its_parents_cannot_be_marked(self):
        for folder in (self.workspace, self.workspace.parent):
            with self.assertRaises(ValueError):
                set_folder_trust(self.workspace, folder, untrusted=True)
        with self.assertRaises(ValueError):
            set_folder_trust(self.workspace, self.vendor / "missing", untrusted=True)

    def test_session_start_gives_no_memory_in_an_untrusted_folder(self):
        trusted = self._hook("session-start", {"cwd": str(self.project), "session_id": "a"})
        self.assertIn("Never deploy on Friday", trusted)
        set_folder_trust(self.workspace, self.vendor, untrusted=True)
        quiet = self._hook("session-start", {"cwd": str(self.vendor / "deep"), "session_id": "b"})
        self.assertNotIn("Never deploy on Friday", quiet)
        self.assertIn("untrusted folder", quiet)
        self.assertNotIn("--trusted", quiet)  # the agent is not handed the way to undo it
        # Every agent's envelope carries the notice, not the brief.
        cursor = json.loads(self._hook("session-start", {"workspace_roots": [str(self.vendor)]}, "--emit", "cursor"))
        self.assertIn("untrusted folder", cursor["additional_context"])
        self.assertNotIn("Friday", cursor["additional_context"])
        # Other folders are untouched.
        self.assertIn("Never deploy on Friday", self._hook("session-start", {"cwd": str(self.project), "session_id": "c"}))

    def test_session_end_captures_nothing_from_an_untrusted_folder(self):
        transcript = self.vendor.parent / "transcript.jsonl"
        turns = [
            "From now on always run the linter before every commit in this repository please.",
            "We decided the billing service uses Postgres and never MySQL from now on.",
            "I prefer small pull requests that touch one concern at a time, always.",
            "Please also remember that staging deploys need two approvals from now on.",
        ]
        transcript.write_text("".join(
            json.dumps({"type": "user", "message": {"role": "user", "content": turn}}) + "\n"
            + json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "Understood. " * 20}]}}) + "\n"
            for turn in turns
        ), encoding="utf-8")
        captures = self.workspace / "raw" / "memory-captures"
        set_folder_trust(self.workspace, self.vendor, untrusted=True)
        out = self._hook("session-end", {"cwd": str(self.vendor), "transcript_path": str(transcript)}, "--explain")
        self.assertIn("marked untrusted", out)
        self.assertEqual(list(captures.glob("*.md")) if captures.exists() else [], [])
        # The same session in a trusted folder is captured: the gate is the folder, not the transcript.
        self._hook("session-end", {"cwd": str(self.project), "transcript_path": str(transcript)})
        self.assertEqual(len(list(captures.glob("*.md"))), 1)

    def test_post_tool_reminders_stay_out_of_an_untrusted_folder(self):
        set_folder_trust(self.workspace, self.vendor, untrusted=True)
        event = {"tool_name": "Read", "tool_input": {"file_path": str(self.vendor / "x.py")}, "cwd": str(self.vendor)}
        self.assertEqual(post_tool_output(self.workspace, event, project=None), "")

    def test_only_the_person_changes_folder_trust(self):
        for words in (["lnk", "folder", "--trusted", "."], ["python3", "link.py", "folder", "--untr", "/x"],
                      ["lnk", "folder", "--untrusted=/x"], ["python3", "-m", "link_cli", "folder", "--trusted", "."]):
            self.assertTrue(is_link_governance(words), words)
        for words in (["lnk", "folder"], ["lnk", "folder", "--json"], ["ls", "folder", "--trusted"],
                      ["lnk", "recall", "untrusted folder"]):
            self.assertFalse(is_link_governance(words), words)

    def test_cli_marks_lists_and_trusts_again(self):
        code, out, _ = _run("folder", str(self.workspace))
        self.assertEqual(code, 0)
        self.assertIn("No folder is marked untrusted", out)
        code, out, _ = _run("folder", "--untrusted", str(self.vendor), str(self.workspace))
        self.assertEqual(code, 0)
        self.assertIn("Marked untrusted", out)
        code, out, _ = _run("folder", str(self.workspace), "--json")
        self.assertEqual(json.loads(out)["folders"], [str(self.vendor)])
        code, out, _ = _run("folder", "--trusted", str(self.vendor / "deep"), str(self.workspace))
        self.assertIn("is inside", out)
        code, out, _ = _run("folder", "--trusted", str(self.vendor), str(self.workspace))
        self.assertIn("Trusted again", out)
        code, _, err = _run("folder", "--untrusted", str(self.workspace.parent), str(self.workspace))
        self.assertEqual(code, 1)
        self.assertIn("mark a project folder", err)


if __name__ == "__main__":
    unittest.main()
