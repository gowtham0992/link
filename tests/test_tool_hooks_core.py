"""Memory that acts when the agent acts: enforced rules, code reminders, delivery, approvals."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.enforce_rules import parse_enforce_rule, suggest_enforce_rules  # noqa: E402
from link_core.memory import (  # noqa: E402
    mark_memory_reviewed,
    memory_records,
    memory_review_issues,
    set_memory_enforce,
    update_frontmatter_fields,
    write_memory_page,
)
from link_core.tool_hooks import (  # noqa: E402
    evaluate_tool_call,
    load_hook_index,
    verify_deliveries,
    wrap_for_delivery,
)
from link_core.usage import load_usage, memory_receipts  # noqa: E402

LINK = [sys.executable, str(ROOT / "link.py")]


def _hook(event, target, payload, *extra):
    return subprocess.run([*LINK, "hook", event, str(target), *extra], input=json.dumps(payload),
                          capture_output=True, text=True, check=True).stdout


class _Store(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.wiki = self.base / "wiki"
        (self.wiki / "memories").mkdir(parents=True)
        (self.wiki / "index.md").write_text("# Index\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def _memory(self, text, rules=(), reviewed=True, **kwargs):
        result = write_memory_page(self.wiki, text, None, kwargs.pop("memory_type", "preference"),
                                   kwargs.pop("scope", "user"), None, "test", "2026-09-28T00:00:00Z",
                                   contradiction_scorer=None, enforce=list(rules), **kwargs)
        if reviewed:
            mark_memory_reviewed(self.wiki, result["name"], None, "2026-09-28T00:01:00Z")
        return result["name"]

    def _decide(self, tool_name, **tool_input):
        index = load_hook_index(self.wiki, self.base)
        return evaluate_tool_call(index, {"tool_name": tool_name, "tool_input": tool_input}, repo_root=self.base)


class RuleTests(_Store):
    def test_rule_grammar(self):
        self.assertEqual(parse_enforce_rule("git push --force*".join(["command: ", ""])).action, "ask")
        self.assertEqual(parse_enforce_rule("deny write: migrations/**").action, "deny")
        for bad in ("", "run: rm", "command: *", "command:"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_enforce_rule(bad)

    def test_a_named_command_is_suggested_and_a_file_is_not(self):
        self.assertEqual(suggest_enforce_rules("Never run `git push --force` on main."),
                         ["ask command: git push --force*"])
        self.assertEqual(suggest_enforce_rules("Never edit `src/app.py` by hand."), [])
        self.assertEqual(suggest_enforce_rules("We always use `pytest -q`."), [])

    def test_a_rule_acts_only_after_review(self):
        self._memory("Never force-push to main.", ["ask command: git push --force*"], reviewed=False)
        self.assertIsNone(self._decide("Bash", command="git push --force origin main"))

    def test_ask_by_default_deny_when_asked(self):
        self._memory("Never force-push to main.", ["command: git push --force*"])
        self._memory("Migrations are generated, never hand-edited.", ["deny write: migrations/**"])
        asked = self._decide("Bash", command="cd api && sudo git push --force origin main")
        self.assertEqual(asked["decision"], "ask")
        self.assertIn("never-force-push-to-main", asked["reason"])
        denied = self._decide("Edit", file_path=str(self.base / "db" / "migrations" / "0001_init.py"))
        self.assertEqual(denied["decision"], "deny")

    def test_unrelated_calls_pass(self):
        self._memory("Never force-push to main.", ["ask command: git push --force*"])
        self._memory("Secrets stay out of the agent's context.", ["ask read: .env*"])
        self.assertIsNone(self._decide("Bash", command="git push origin main"))
        self.assertIsNone(self._decide("Bash", command="echo git push --force"))
        self.assertIsNone(self._decide("Read", file_path=str(self.base / "README.md")))
        self.assertEqual(self._decide("Read", file_path=str(self.base / ".env.local"))["decision"], "ask")

    def test_new_rules_send_the_memory_back_to_review(self):
        name = self._memory("Never force-push to main.")
        result = set_memory_enforce(self.wiki, name, ["ask command: git push --force*"], "2026-09-28T01:00:00Z")
        self.assertEqual(result["review_status"], "pending")
        self.assertIsNone(self._decide("Bash", command="git push --force"))
        mark_memory_reviewed(self.wiki, name, None, "2026-09-28T01:01:00Z")
        self.assertEqual(self._decide("Bash", command="git push --force")["decision"], "ask")

    def test_a_malformed_rule_is_ignored_and_reported(self):
        name = self._memory("Never force-push to main.")
        page = self.wiki / "memories" / f"{name}.md"
        page.write_text(update_frontmatter_fields(page.read_text(encoding="utf-8"), {"enforce": ["run: *"]}),
                        encoding="utf-8")
        self.assertIsNone(self._decide("Bash", command="git push --force"))
        (record,) = memory_records(self.wiki)
        self.assertIn("invalid_enforce_rule", [issue["code"] for issue in memory_review_issues(record)])

    def test_project_rules_stay_in_their_project(self):
        self._memory("Never run the seed script.", ["ask command: make seed*"], scope="project",
                     project="api", project_explicit=True)
        index = load_hook_index(self.wiki, self.base)
        event = {"tool_name": "Bash", "tool_input": {"command": "make seed"}}
        self.assertIsNotNone(evaluate_tool_call(index, event, project="api"))
        self.assertIsNone(evaluate_tool_call(index, event, project="web"))


class PreToolHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ws = Path(self.temp.name) / "ws"
        subprocess.run([*LINK, "demo", str(self.ws), "--force"], check=True, capture_output=True)
        subprocess.run([*LINK, "remember", "Never run `git push --force` on main", str(self.ws),
                        "--enforce", "ask command: git push --force*"], check=True, capture_output=True)
        name = next(p.stem for p in (self.ws / "wiki" / "memories").glob("never-run-git-push*.md"))
        subprocess.run([*LINK, "review-memory", name, str(self.ws)], check=True, capture_output=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_claude_code_gets_a_permission_decision(self):
        out = _hook("pre-tool", self.ws, {"session_id": "s", "tool_name": "Bash",
                                          "tool_input": {"command": "git push --force"}})
        decision = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "ask")
        self.assertEqual(_hook("pre-tool", self.ws, {"tool_name": "Bash", "tool_input": {"command": "ls"}}), "")
        kinds = [event["kind"] for event in load_usage(self.ws)]
        self.assertIn("enforce", kinds)

    def test_cursor_always_gets_an_answer(self):
        self.assertEqual(json.loads(_hook("pre-tool", self.ws, {"command": "ls"}, "--emit", "cursor")),
                         {"permission": "allow"})
        self.assertEqual(json.loads(_hook("pre-tool", self.ws, {"command": "git push --force"}, "--emit",
                                          "cursor"))["permission"], "ask")

    def test_the_hook_is_fast_on_a_large_store(self):
        memories = self.ws / "wiki" / "memories"
        template = next(memories.glob("never-run-git-push*.md")).read_text(encoding="utf-8")
        for number in range(400):
            (memories / f"bulk-{number}.md").write_text(template.replace("git push --force", f"tool-{number}"),
                                                        encoding="utf-8")
        payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        _hook("pre-tool", self.ws, payload)  # builds the index once
        started = time.perf_counter()
        _hook("pre-tool", self.ws, payload)
        self.assertLess(time.perf_counter() - started, 2.0, "the cached index keeps each call cheap")


class CodeReminderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.ws = base / "ws"
        self.repo = base / "repo"
        subprocess.run([*LINK, "demo", str(self.ws), "--force"], check=True, capture_output=True)
        self.repo.mkdir()
        (self.repo / "app.py").write_text("import os\n\ndef parse_config(path):\n    return {}\n", encoding="utf-8")
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.invalid",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.invalid"}
        for args in (["init", "-q"], ["add", "."], ["commit", "-qm", "init"]):
            subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, env=env)
        subprocess.run([*LINK, "remember", "`parse_config` in app.py must stay side-effect free", str(self.ws),
                        "--type", "decision"], cwd=self.repo, check=True, capture_output=True)
        self.name = next(p.stem for p in (self.ws / "wiki" / "memories").glob("parse-config*.md"))
        subprocess.run([*LINK, "review-memory", self.name, str(self.ws)], check=True, capture_output=True)

    def tearDown(self):
        self.temp.cleanup()

    def _read(self, session, path=None):
        return _hook("post-tool", self.ws, {"session_id": session, "cwd": str(self.repo), "tool_name": "Read",
                                            "tool_input": {"file_path": str(path or self.repo / "app.py")}})

    def test_shown_once_per_session_with_a_delivery_marker(self):
        first = json.loads(self._read("s1"))["hookSpecificOutput"]["additionalContext"]
        self.assertIn(self.name, first)
        self.assertIn("(link:", first)
        self.assertEqual(self._read("s1"), "")
        self.assertIn(self.name, self._read("s2"))

    def test_not_shown_when_the_symbol_is_gone_or_the_file_is_unrelated(self):
        (self.repo / "other.py").write_text("x = 1\n", encoding="utf-8")
        self.assertEqual(self._read("s3", self.repo / "other.py"), "")
        (self.repo / "app.py").write_text("def load(path):\n    return {}\n", encoding="utf-8")
        self.assertEqual(self._read("s4"), "")


class DeliveryTests(unittest.TestCase):
    def test_wrap_and_verify(self):
        text, cut = wrap_for_delivery("Header\nline one\nline two", "abc123")
        self.assertFalse(cut)
        self.assertTrue(text.startswith("Header (link:abc123)"))
        self.assertEqual(verify_deliveries(text, ["abc123"]), {"abc123": "delivered"})
        self.assertEqual(verify_deliveries(text[:20], ["abc123"]), {"abc123": "truncated"})
        self.assertEqual(verify_deliveries("", ["abc123"]), {"abc123": "missing"})

    def test_an_oversized_brief_is_cut_and_says_so(self):
        text, cut = wrap_for_delivery("Header\n" + "\n".join("x" * 80 for _ in range(400)), "abc123")
        self.assertTrue(cut)
        self.assertLess(len(text), 9000)
        self.assertIn("shortened to fit", text)
        self.assertTrue(text.rstrip().endswith("(link:abc123 end)"))

    def test_session_end_marks_the_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            ws = Path(temp) / "ws"
            subprocess.run([*LINK, "demo", str(ws), "--force"], check=True, capture_output=True)
            brief = _hook("session-start", ws, {"session_id": "d1", "source": "startup"})
            transcript = Path(temp) / "t.jsonl"
            transcript.write_text(json.dumps({"attachment": {"type": "hook_success", "content": brief[: len(brief) // 2]}}) + "\n",
                                  encoding="utf-8")
            _hook("session-end", ws, {"session_id": "d1", "transcript_path": str(transcript)})
            (receipt,) = memory_receipts(load_usage(ws), sessions=1)
            self.assertEqual(receipt["briefs"][0]["delivery"], "truncated")
            self.assertTrue(receipt["anything_undelivered"])


class SessionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ws = Path(self.temp.name) / "ws"
        subprocess.run([*LINK, "demo", str(self.ws), "--force"], check=True, capture_output=True)

    def tearDown(self):
        self.temp.cleanup()

    def _end(self, entries, session="e1"):
        transcript = Path(self.temp.name) / f"{session}.jsonl"
        transcript.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8")
        return _hook("session-end", self.ws, {"session_id": session, "transcript_path": str(transcript)},
                     "--explain")

    @staticmethod
    def _user(text):
        return {"type": "user", "message": {"role": "user", "content": text}}

    def test_a_short_session_without_a_standing_rule_proposes_nothing(self):
        trail = self._end([self._user("Rename the variable in utils and run the tests again when you are "
                                      "done, then summarise what changed in the payments module for me please. "
                                      "Also check the retry wrapper in the webhook sender and tell me whether the "
                                      "timeout there is still thirty seconds after the refactor last week.")])
        self.assertIn("fewer than 3", trail)
        self.assertFalse(list((self.ws / "raw" / "memory-captures").glob("*.md")))

    def test_outside_content_marks_the_capture_and_the_brief(self):
        trail = self._end([
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "WebFetch", "input": {"url": "https://example.invalid"}}]}},
            self._user("From now on we always run the integration tests before merging to develop, and never "
                       "skip them for hotfixes, because skipping them broke production twice last quarter and cost "
                       "the whole team a weekend of rollbacks, apologies and a very long incident review."),
        ])
        self.assertIn("outside content (web)", trail)
        (capture,) = (self.ws / "raw" / "memory-captures").glob("*.md")
        self.assertIn('untrusted_inputs: "web"', capture.read_text(encoding="utf-8"))
        brief = _hook("session-start", self.ws, {"session_id": "e2", "source": "startup"})
        self.assertIn("Waiting for the user's OK", brief)
        self.assertIn("session read web content", brief)
        self.assertIn("accept-capture", brief)

    def test_a_repeated_end_event_is_skipped(self):
        entries = [self._user("From now on we always squash-merge pull requests into develop and keep the "
                              "history linear, because the release notes are generated from commit titles and "
                              "a merge commit in the middle of them produced garbage notes for the last release.")]
        self._end(entries, "r1")
        again = self._end(entries, "r1")
        self.assertIn("already captured", again)


if __name__ == "__main__":
    unittest.main()
