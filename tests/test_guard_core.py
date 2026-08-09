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
