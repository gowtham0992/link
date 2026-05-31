import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.web_memory import (  # noqa: E402
    memory_dashboard_next_actions,
    render_capture_card,
    render_memory_action_button,
    render_memory_card,
    render_memory_next_actions,
    render_memory_section,
)


def page_href(name: str) -> str:
    return f"/page/{name}"


class WebMemoryCoreTests(unittest.TestCase):
    def test_memory_card_escapes_content_and_renders_actions(self):
        record = {
            "name": "local-memory",
            "title": "<Local Memory>",
            "tldr": "Use <local> memory.",
            "memory_type": "preference",
            "scope": "user",
            "status": "active",
            "actions": [{
                "label": "Review",
                "kind": "review",
                "command": "lnk review-memory local-memory",
                "arguments": {"identifier": "local-memory"},
            }],
        }

        html = render_memory_card(record, page_href=page_href)

        self.assertIn('<a href="/page/local-memory">&lt;Local Memory&gt;</a>', html)
        self.assertIn('/explain-memory?memory=local-memory', html)
        self.assertIn('/graph?focus=local-memory&amp;depth=2', html)
        self.assertIn("Use &lt;local&gt; memory.", html)
        self.assertIn('data-memory-action="review"', html)
        self.assertIn('data-copy-text="lnk review-memory local-memory"', html)
        self.assertNotIn("<Local Memory>", html)

    def test_memory_card_escapes_generated_trust_links(self):
        html = render_memory_card(
            {"name": 'memory <one>', "title": "Memory"},
            page_href=lambda name: f'/page/{name}',
        )

        self.assertIn('/page/memory &lt;one&gt;', html)
        self.assertIn('/explain-memory?memory=memory%20%3Cone%3E', html)
        self.assertIn('/graph?focus=memory%20%3Cone%3E&amp;depth=2', html)

    def test_memory_section_uses_action_hints_when_record_has_no_actions(self):
        record = {"name": "agent-memory", "title": "Agent Memory"}

        html = render_memory_section(
            "Memories",
            [record],
            "No memories.",
            page_href=page_href,
            action_hints=lambda _record: [{
                "label": "Archive",
                "kind": "archive",
                "command": "lnk archive-memory agent-memory",
                "arguments": {"identifier": "agent-memory"},
            }],
            href="/inbox",
        )

        self.assertIn('<a href="/inbox">view all</a>', html)
        self.assertIn('data-memory-action="archive"', html)
        self.assertIn("lnk archive-memory agent-memory", html)

    def test_capture_card_escapes_warnings_and_commands(self):
        html = render_capture_card({
            "title": "Raw <Capture>",
            "path": "raw/memory-captures/session.md",
            "secret_warnings": ["OpenAI <key>"],
            "commands": {
                "accept": "accept-capture",
                "redact": "redact-capture",
            },
        })

        self.assertIn("Raw &lt;Capture&gt;", html)
        self.assertIn("OpenAI &lt;key&gt;", html)
        self.assertIn("accept-capture", html)
        self.assertIn('data-copy-text="accept-capture"', html)
        self.assertIn('data-copy-text="redact-capture"', html)
        self.assertNotIn("Raw <Capture>", html)

    def test_memory_action_button_requires_supported_kind_and_identifier(self):
        self.assertIn("Mark reviewed", render_memory_action_button({
            "kind": "review",
            "arguments": {"identifier": "one"},
        }))
        self.assertEqual("", render_memory_action_button({"kind": "forget", "arguments": {"identifier": "one"}}))
        self.assertEqual("", render_memory_action_button({"kind": "review", "arguments": {}}))

    def test_next_actions_render_commands(self):
        html = render_memory_next_actions([{
            "label": "Review",
            "detail": "Open inbox.",
            "command": "lnk memory-inbox",
            "href": "/inbox",
        }])

        self.assertIn('<a href="/inbox">Review</a>', html)
        self.assertIn("Open inbox.", html)
        self.assertIn("lnk memory-inbox", html)
        self.assertIn('data-copy-text="lnk memory-inbox"', html)

    def test_memory_dashboard_next_actions_cover_empty_ready_and_review_states(self):
        empty_actions = memory_dashboard_next_actions(
            memory_count=0,
            review_count=0,
            updated_count=0,
            archived_count=0,
        )
        ready_actions = memory_dashboard_next_actions(
            memory_count=2,
            review_count=0,
            updated_count=0,
            archived_count=0,
        )
        review_actions = memory_dashboard_next_actions(
            memory_count=1,
            review_count=1,
            updated_count=0,
            archived_count=0,
        )

        self.assertEqual(empty_actions[0]["label"], "Create the first memory")
        self.assertIn("remember", empty_actions[0]["command"])
        self.assertEqual(ready_actions[0]["label"], "Memory is recall-ready")
        self.assertEqual(ready_actions[0]["href"], "/profile")
        self.assertIn("1 memory needs confirmation", review_actions[0]["detail"])

    def test_memory_dashboard_next_actions_prioritize_capture_warnings(self):
        actions = memory_dashboard_next_actions(
            memory_count=2,
            review_count=1,
            updated_count=1,
            archived_count=1,
            capture_count=1,
            capture_warning_count=1,
        )

        self.assertEqual(actions[0]["label"], "Redact capture warnings")
        self.assertEqual(actions[1]["label"], "Review pending memories")
        self.assertEqual(actions[2]["label"], "Audit recent memory updates")


if __name__ == "__main__":
    unittest.main()
