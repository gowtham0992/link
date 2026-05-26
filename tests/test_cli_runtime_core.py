import unittest

from mcp_package.link_core.cli_runtime import (
    render_demo_text,
    render_init_text,
    render_mcp_connect_text,
    render_starter_prompts_text,
    render_try_text,
    render_welcome_text,
)


class CliRuntimeCoreTests(unittest.TestCase):
    def test_render_init_text(self):
        code, text = render_init_text(target="/tmp/link", fixes=["created wiki/index.md"])

        self.assertEqual(code, 0)
        self.assertIn("Link wiki ready at /tmp/link", text)
        self.assertIn("Initialized:", text)
        self.assertIn("link health /tmp/link", text)
        self.assertIn("link serve /tmp/link", text)

    def test_render_starter_prompts_text(self):
        code, text = render_starter_prompts_text({
            "target": "/tmp/link",
            "project": "link",
            "shortcut": "link next /tmp/link",
            "prompts": [{
                "prompt": "is Link ready?",
                "when": "first run",
            }],
            "commands": ["link health"],
        })

        self.assertEqual(code, 0)
        self.assertIn("Link starter prompts: /tmp/link", text)
        self.assertIn("Project: link", text)
        self.assertIn("Shortcut", text)
        self.assertIn("- link next /tmp/link", text)
        self.assertIn("- is Link ready?", text)
        self.assertIn("- link health", text)

    def test_render_welcome_text(self):
        code, text = render_welcome_text({
            "target": "/tmp/link",
            "project": "link",
            "steps": [{
                "step": 1,
                "prompt": "is Link ready?",
                "proves": "Agent can find Link.",
            }],
            "commands": ["link health"],
            "urls": ["http://127.0.0.1:3000/health"],
        })

        self.assertEqual(code, 0)
        self.assertIn("Link welcome: /tmp/link", text)
        self.assertIn("Project: link", text)
        self.assertIn("1. is Link ready?", text)
        self.assertIn("Proves: Agent can find Link.", text)
        self.assertIn("- link health", text)
        self.assertIn("- http://127.0.0.1:3000/health", text)

    def test_render_demo_text(self):
        code, text = render_demo_text(
            target="/tmp/link-demo",
            guide_path="/tmp/link-demo/START_HERE.md",
            serve_command="python3 link.py serve /tmp/link-demo",
            next_command="python3 link.py next /tmp/link-demo",
            query_command="python3 link.py query 'why does Link help agents?' /tmp/link-demo --budget small",
            brief_command="python3 link.py brief 'working on agent memory' /tmp/link-demo",
            audit_command="python3 link.py memory-audit /tmp/link-demo",
        )

        self.assertEqual(code, 0)
        self.assertIn("Link demo created at /tmp/link-demo", text)
        self.assertIn("Ask an agent what to try next:", text)
        self.assertIn("python3 link.py next /tmp/link-demo", text)
        self.assertIn("Try the value loop:", text)
        self.assertIn("/tmp/link-demo/START_HERE.md", text)
        self.assertIn("http://127.0.0.1:3000/graph", text)

    def test_render_try_text(self):
        code, text = render_try_text(
            target="/tmp/link-demo",
            ready=True,
            page_count=13,
            memory_count=1,
            search_backend="sqlite-fts",
            query_summary="agent-memory · 1 memories · 3 context items",
            brief_summary="1 relevant memories · 1 review items",
            serve_command="link serve /tmp/link-demo",
            next_command="link next /tmp/link-demo",
            health_command="link health /tmp/link-demo",
            query_command="link query 'why does Link help agents?' /tmp/link-demo --budget small",
            brief_command="link brief 'working on agent memory' /tmp/link-demo",
            benchmark_command="link benchmark 'agent memory' /tmp/link-demo",
            url="http://127.0.0.1:3000",
        )

        self.assertEqual(code, 0)
        self.assertIn("Link try: /tmp/link-demo", text)
        self.assertIn("Demo: ready", text)
        self.assertIn("Query proof:", text)
        self.assertIn("Ask an agent:", text)
        self.assertIn("link next /tmp/link-demo", text)

    def test_render_mcp_connect_text_preview(self):
        code, text = render_mcp_connect_text({
            "display_name": "Codex",
            "wiki": "/tmp/link/wiki",
            "python": "/tmp/python",
            "config_path": "/tmp/config.toml",
            "snippet": "[mcp_servers.link]\ncommand = \"/tmp/python\"",
            "write": {"requested": False, "ok": False, "message": "preview only"},
            "next_actions": [
                {"label": "write config", "command_text": "link connect codex /tmp/link --write"},
                {"label": "verify MCP runtime", "command_text": "link verify-mcp /tmp/link --python /tmp/python"},
            ],
            "restart_hint": "Restart the agent, then ask: is Link ready?",
        })

        self.assertEqual(code, 0)
        self.assertIn("Link connect: Codex", text)
        self.assertIn("Preview only", text)
        self.assertIn("link connect codex /tmp/link --write", text)
        self.assertIn("[mcp_servers.link]", text)
        self.assertIn("link verify-mcp /tmp/link --python /tmp/python", text)


if __name__ == "__main__":
    unittest.main()
