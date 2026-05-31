import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.mcp_connect import build_mcp_connect_payload, supported_agents  # noqa: E402


class McpConnectCoreTests(unittest.TestCase):
    def test_supported_agents_include_primary_install_targets(self):
        agents = supported_agents()

        for agent in ("codex", "kiro", "claude-code", "cursor", "antigravity", "vscode", "copilot"):
            self.assertIn(agent, agents)

    def test_build_codex_preview_uses_marker_python(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wiki = root / "wiki"
            wiki.mkdir()
            (root / ".link-mcp-python").write_text("/tmp/Link Python/bin/python\n", encoding="utf-8")

            payload = build_mcp_connect_payload(
                target=root,
                wiki_dir=wiki,
                agent="codex",
                expected_version="1.3.0",
                init_command=["link", "init", str(root)],
                default_python="python3",
            )

        self.assertEqual(payload["agent"], "codex")
        self.assertEqual(payload["python"], "/tmp/Link Python/bin/python")
        self.assertIn("[mcp_servers.link]", str(payload["snippet"]))
        self.assertIn(json.dumps(str(wiki)), str(payload["snippet"]))

    def test_write_codex_config_replaces_existing_link_block(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wiki = root / "wiki"
            wiki.mkdir()
            config = root / "config.toml"
            config.write_text("[mcp_servers.link]\ncommand = \"old\"\n\n[ui]\ntheme = \"dark\"\n", encoding="utf-8")

            payload = build_mcp_connect_payload(
                target=root,
                wiki_dir=wiki,
                agent="codex",
                expected_version="1.3.0",
                init_command=["link", "init", str(root)],
                python_cmd="/tmp/python",
                default_python="python3",
                config_path=str(config),
                write=True,
            )

            text = config.read_text(encoding="utf-8")

        self.assertTrue(payload["write"]["ok"])
        self.assertIn('command = "/tmp/python"', text)
        self.assertIn("[ui]", text)
        self.assertNotIn('command = "old"', text)

    def test_write_json_config_preserves_existing_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wiki = root / "wiki"
            wiki.mkdir()
            config = root / "mcp.json"
            config.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")

            payload = build_mcp_connect_payload(
                target=root,
                wiki_dir=wiki,
                agent="kiro",
                expected_version="1.3.0",
                init_command=["link", "init", str(root)],
                python_cmd="/tmp/python",
                default_python="python3",
                config_path=str(config),
                write=True,
            )
            data = json.loads(config.read_text(encoding="utf-8"))

        self.assertTrue(payload["write"]["ok"])
        self.assertEqual(data["mcpServers"]["other"]["command"], "x")
        self.assertEqual(data["mcpServers"]["link"]["command"], "/tmp/python")
        self.assertFalse(data["mcpServers"]["link"]["disabled"])

    def test_vscode_uses_servers_top_key_and_stdio_type(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wiki = root / "wiki"
            wiki.mkdir()
            config = root / "mcp.json"

            payload = build_mcp_connect_payload(
                target=root,
                wiki_dir=wiki,
                agent="vscode",
                expected_version="1.3.0",
                init_command=["link", "init", str(root)],
                python_cmd="/tmp/python",
                default_python="python3",
                config_path=str(config),
                write=True,
            )
            data = json.loads(config.read_text(encoding="utf-8"))

        self.assertTrue(payload["write"]["ok"])
        self.assertEqual(data["servers"]["link"]["type"], "stdio")
        self.assertEqual(data["servers"]["link"]["args"], ["-m", "link_mcp", "--wiki", str(wiki)])

    def test_unknown_agent_is_clear(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wiki = root / "wiki"
            wiki.mkdir()

            with self.assertRaisesRegex(ValueError, "unsupported agent"):
                build_mcp_connect_payload(
                    target=root,
                    wiki_dir=wiki,
                    agent="not-real",
                    expected_version="1.3.0",
                    init_command=["link", "init", str(root)],
                    default_python="python3",
                )


if __name__ == "__main__":
    unittest.main()
