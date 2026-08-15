"""Proactive guard: precision-first constraint reminders."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.guard import guard_reminder, is_constraint_memory, render_guard_text  # noqa: E402

RECORDS = [
    {"name": "deploy-tuesdays", "title": "Only deploy on Tuesdays",
     "tldr": "I only deploy the payments service on Tuesdays.",
     "memory_type": "preference", "scope": "user", "status": "active"},
    {"name": "no-force-push", "title": "Never force-push shared branches",
     "tldr": "Never use force-push on shared branches.",
     "memory_type": "preference", "scope": "user", "status": "active"},
    {"name": "likes-tabs", "title": "Prefers tabs",
     "tldr": "The user prefers tabs, not spaces.",
     "memory_type": "preference", "scope": "user", "status": "active"},
]


class GuardPrecisionTests(unittest.TestCase):
    def test_fires_on_constraint_adjacent_requests(self):
        hit = guard_reminder(RECORDS, "lets deploy the payments service on friday")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["name"], "deploy-tuesdays")
        hit2 = guard_reminder(RECORDS, "force push this to the shared branch please")
        self.assertEqual(hit2["name"], "no-force-push")

    def test_silence_is_the_default(self):
        for prompt in (
            "write a haiku about the ocean",     # unrelated
            "hi",                                 # too short
            "can you deploy it",                  # one weak shared token
            "",                                   # empty
        ):
            self.assertIsNone(guard_reminder(RECORDS, prompt), prompt)

    def test_non_constraint_memories_never_interrupt(self):
        # "tabs" overlaps strongly, but a preference without an absolute cue
        # is not worth an interruption.
        self.assertIsNone(guard_reminder(
            [RECORDS[2]], "should I use tabs or spaces in this file"))

    def test_constraint_detection(self):
        self.assertTrue(is_constraint_memory(RECORDS[0]))
        self.assertTrue(is_constraint_memory(RECORDS[1]))
        self.assertFalse(is_constraint_memory(RECORDS[2]))

    def test_render_names_the_memory(self):
        hit = guard_reminder(RECORDS, "lets deploy the payments service on friday")
        text = render_guard_text(hit)
        self.assertIn("deploy-tuesdays", text)
        self.assertIn("confirm with the user", text)


class GuardHookWiringTests(unittest.TestCase):
    def test_claude_code_plan_includes_prompt_check(self):
        from link_core.agent_hooks import HOOK_AGENT_CONFIGS, _event_plan
        config = next(c for c in HOOK_AGENT_CONFIGS if c.name == "claude-code")
        plan = _event_plan(config, "python3", Path("/tmp/link.py"), Path("/tmp/ws"))
        events = [item["event_name"] for item in plan]
        self.assertIn("UserPromptSubmit", events)
        guard = next(item for item in plan if item["event_name"] == "UserPromptSubmit")
        self.assertIn("prompt-check", str(guard["entry"]))

    def test_other_agents_do_not_get_the_guard(self):
        from link_core.agent_hooks import HOOK_AGENT_CONFIGS, _event_plan
        for config in HOOK_AGENT_CONFIGS:
            if config.name == "claude-code":
                continue
            plan = _event_plan(config, "python3", Path("/tmp/link.py"), Path("/tmp/ws"))
            self.assertNotIn("UserPromptSubmit", [item["event_name"] for item in plan], config.name)


if __name__ == "__main__":
    unittest.main()


class SwitchIntentTests(unittest.TestCase):
    """The handoff must suggest itself at stop/switch moments - and only then."""

    def test_fires_on_switch_and_stop_announcements(self):
        from link_core.guard import switch_intent
        for prompt in (
            "im switching to codex for this",
            "hit my rate limit again",
            "lets continue this tomorrow",
            "continue in cursor please",
            "stopping here for today",
            "calling it a night",
            "out of tokens, wrapping up for now",
            "resume next session",
        ):
            self.assertTrue(switch_intent(prompt), prompt)

    def test_silent_on_ordinary_work_phrases(self):
        from link_core.guard import switch_intent
        for prompt in (
            "switch the order of these functions",
            "switching to a recursive approach",
            "continue with the refactor",
            "continue in the same file",
            "stop the server",
            "tomorrow is the deadline",
            "the rate of failures is limited",
        ):
            self.assertFalse(switch_intent(prompt), prompt)

    def test_nudge_names_the_command(self):
        from link_core.guard import render_switch_nudge
        self.assertIn("lnk handoff", render_switch_nudge())


class GuardCooldownTests(unittest.TestCase):
    """One reminder is a guard, ten is a nag."""

    def test_same_memory_does_not_repeat_within_cooldown(self):
        import tempfile
        from pathlib import Path as P
        from link_core.guard import recently_guarded
        from link_core.usage import record_retrieval
        with tempfile.TemporaryDirectory() as temp:
            root = P(temp)
            self.assertFalse(recently_guarded(root, "deploy-tuesdays"))
            record_retrieval(root, "guard", ["deploy-tuesdays"])
            self.assertTrue(recently_guarded(root, "deploy-tuesdays"))
            # A different constraint is still allowed to fire.
            self.assertFalse(recently_guarded(root, "no-force-push"))


class McpGuardTests(unittest.TestCase):
    """Every agent gets the guard through recall - not just the hooked one."""

    def test_recall_packet_carries_guard_on_conflicting_query(self):
        import json
        import tempfile
        from pathlib import Path as P
        from link_core.memory import write_memory_page
        from mcp_harness import mcp_server
        with tempfile.TemporaryDirectory() as temp:
            root = P(temp)
            wiki = root / "wiki"
            (wiki / "memories").mkdir(parents=True)
            (wiki / "index.md").write_text("# I\n", encoding="utf-8")
            (wiki / "log.md").write_text("# L\n", encoding="utf-8")
            write_memory_page(
                wiki, "I only deploy the payments service on Tuesdays.",
                title="Only deploy on Tuesdays", memory_type="preference",
                scope="user", tags=None, source="t",
                timestamp="2026-08-01T00:00:00Z",
            )
            with mcp_server(root) as server:
                first = json.loads(server.recall(
                    query="deploy the payments service on friday", mode="query", budget="micro"))
                self.assertIn("guard", first)
                self.assertIn("Tuesdays", first["guard"])
                # Cooldown shared through the ledger: second recall is quiet.
                second = json.loads(server.recall(
                    query="deploy payments friday", mode="query", budget="micro"))
                self.assertNotIn("guard", second)
