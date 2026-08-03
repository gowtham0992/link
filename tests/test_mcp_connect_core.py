import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.mcp_connect import (  # noqa: E402
    agent_alias_matches,
    build_mcp_connect_payload,
    read_agent_link_server,
    supported_agents,
)


def _ready_runtime(python_cmd, expected_version, *, provision=False):
    return {
        "ready": True,
        "python": python_cmd,
        "status": {"installed": True, "version": expected_version, "mcp_sdk": True, "error": None},
        "provisioned": False,
        "notes": [],
    }


def _broken_runtime(python_cmd, expected_version, *, provision=False):
    return {
        "ready": False,
        "python": python_cmd,
        "status": {"installed": False, "version": None, "mcp_sdk": False, "error": "No module named link_mcp"},
        "provisioned": False,
        "notes": [f"{python_cmd}: link-mcp not importable"],
    }


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
                runtime_check=_ready_runtime,
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
                runtime_check=_ready_runtime,
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
                runtime_check=_ready_runtime,
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
                runtime_check=_ready_runtime,
            )
            data = json.loads(config.read_text(encoding="utf-8"))

        self.assertTrue(payload["write"]["ok"])
        self.assertEqual(data["servers"]["link"]["type"], "stdio")
        self.assertEqual(
            data["servers"]["link"]["args"],
            ["-m", "link_mcp", "--wiki", str(wiki), "--surface", "slim"],
        )

    def test_write_refused_when_mcp_runtime_is_broken(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wiki = root / "wiki"
            wiki.mkdir()
            config = root / "mcp.json"

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
                runtime_check=_broken_runtime,
            )

        self.assertFalse(payload["write"]["ok"])
        self.assertIn("not written", str(payload["write"]["message"]))
        self.assertFalse(config.exists())
        self.assertFalse(payload["mcp_runtime"]["ready"])

    def test_write_repoints_to_provisioned_venv_and_persists_marker(self):
        def venv_runtime(python_cmd, expected_version, *, provision=False):
            return {
                "ready": True,
                "python": "/home/user/.link-mcp-venv/bin/python",
                "status": {"installed": True, "version": expected_version, "mcp_sdk": True, "error": None},
                "provisioned": True,
                "notes": ["provisioned ~/.link-mcp-venv"],
            }

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wiki = root / "wiki"
            wiki.mkdir()
            config = root / "mcp.json"

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
                runtime_check=venv_runtime,
            )
            data = json.loads(config.read_text(encoding="utf-8"))
            marker = (root / ".link-mcp-python").read_text(encoding="utf-8").strip()

        self.assertTrue(payload["write"]["ok"])
        self.assertEqual(data["mcpServers"]["link"]["command"], "/home/user/.link-mcp-venv/bin/python")
        self.assertEqual(marker, "/home/user/.link-mcp-venv/bin/python")
        self.assertTrue(payload["mcp_runtime"]["provisioned"])

    def test_agent_alias_matches_names_and_aliases_only(self):
        self.assertTrue(agent_alias_matches("claude-code"))
        self.assertTrue(agent_alias_matches("claude"))
        self.assertTrue(agent_alias_matches("Codex"))
        self.assertFalse(agent_alias_matches("./my-workspace"))
        self.assertFalse(agent_alias_matches("link-demo"))

    def test_read_agent_link_server_from_json_config(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "claude.json"
            config.write_text(json.dumps({
                "mcpServers": {
                    "link": {
                        "command": "/venv/bin/python",
                        "args": ["-m", "link_mcp", "--wiki", "/home/u/link/wiki", "--surface", "slim"],
                    }
                }
            }), encoding="utf-8")

            server = read_agent_link_server("claude-code", config_path=str(config))

        self.assertTrue(server["configured"])
        self.assertEqual(server["python"], "/venv/bin/python")
        self.assertEqual(server["wiki"], "/home/u/link/wiki")

    def test_read_agent_link_server_from_codex_toml(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.toml"
            config.write_text(
                '[mcp_servers.link]\ncommand = "/venv/bin/python"\n'
                'args = ["-m", "link_mcp", "--wiki", "/home/u/link/wiki", "--surface", "slim"]\n',
                encoding="utf-8",
            )

            server = read_agent_link_server("codex", config_path=str(config))

        self.assertTrue(server["configured"])
        self.assertEqual(server["python"], "/venv/bin/python")
        self.assertEqual(server["wiki"], "/home/u/link/wiki")

    def test_read_agent_link_server_reports_unconfigured(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = read_agent_link_server("cursor", config_path=str(Path(temp) / "nope.json"))
            other_only = Path(temp) / "mcp.json"
            other_only.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")
            no_link = read_agent_link_server("cursor", config_path=str(other_only))

        self.assertFalse(missing["configured"])
        self.assertFalse(no_link["configured"])

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
                    runtime_check=_ready_runtime,
                )


if __name__ == "__main__":
    unittest.main()


class DetectInstalledAgentsTests(unittest.TestCase):
    def test_detects_agents_by_config_footprint(self):
        import tempfile
        from pathlib import Path
        from mcp_package.link_core.mcp_connect import detect_installed_agents
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self.assertEqual(detect_installed_agents(home=home), [])
            (home / ".claude").mkdir()
            (home / ".codex").mkdir()
            (home / ".cursor").mkdir()
            (home / ".codeium" / "windsurf").mkdir(parents=True)
            (home / ".config" / "zed").mkdir(parents=True)
            detected = detect_installed_agents(home=home)
            self.assertEqual(sorted(detected), ["claude-code", "codex", "cursor", "windsurf", "zed"])
            # Project-scoped configs (.vscode) never auto-detect.
            (home / ".vscode").mkdir()
            self.assertNotIn("vscode", detect_installed_agents(home=home))
