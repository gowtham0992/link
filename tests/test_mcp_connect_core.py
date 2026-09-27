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


class JsoncConfigTests(unittest.TestCase):
    """VS Code and Zed settings carry comments; editing must keep them."""

    def test_write_into_a_commented_zed_settings_file_keeps_every_comment(self):
        from link_core.mcp_connect import _agent_by_name, _jsonc_loads, _write_json_config
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            original = ('// Zed settings\n{\n  // theme\n  "theme": "One Dark", /* keep me */\n'
                        '  "context_servers": {\n    "other": {"command": "x"}, // other server\n  },\n}\n')
            path.write_text(original, encoding="utf-8")
            _write_json_config(path, _agent_by_name("zed"), "/usr/bin/python3", Path("/w/wiki"))
            text = path.read_text(encoding="utf-8")
            for comment in ("// Zed settings", "// theme", "/* keep me */", "// other server"):
                self.assertIn(comment, text)
            parsed = _jsonc_loads(text)
            self.assertEqual(sorted(parsed["context_servers"]), ["link", "other"])
            self.assertEqual(parsed["context_servers"]["link"]["source"], "custom")

    def test_invalid_config_is_reported_not_overwritten(self):
        from link_core.mcp_connect import _agent_by_name, _write_json_config
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mcp.json"
            path.write_text('{"servers": {"x": ', encoding="utf-8")
            with self.assertRaises(ValueError):
                _write_json_config(path, _agent_by_name("vscode"), "/usr/bin/python3", Path("/w/wiki"))
            self.assertEqual(path.read_text(encoding="utf-8"), '{"servers": {"x": ')


class DisconnectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="link-disconnect-")
        self.dir = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_disconnect_removes_only_links_entry_and_hooks(self):
        from link_core.mcp_connect import build_disconnect_payload
        config = self.dir / "claude.json"
        config.write_text(json.dumps({"mcpServers": {"link": {"command": "py"}, "github": {"command": "gh"}},
                                      "theme": "dark"}), encoding="utf-8")
        settings = self.dir / "settings.json"
        settings.write_text(json.dumps({"hooks": {
            "SessionStart": [{"matcher": "startup", "hooks": [
                {"type": "command", "command": "python3 /home/me/link/link.py hook session-start /home/me/link"},
                {"type": "command", "command": "echo other hook"}]}],
            "UserPromptSubmit": [{"hooks": [
                {"type": "command", "command": "lnk hook prompt-check /home/me/link"}]}],
        }, "model": "opus"}), encoding="utf-8")
        preview = build_disconnect_payload("claude-code", config_path=str(config), hooks_settings=str(settings))
        self.assertTrue(preview["found"])
        self.assertFalse(preview["changed"])
        self.assertIn('"link"', config.read_text(encoding="utf-8"))

        done = build_disconnect_payload("claude-code", config_path=str(config), hooks_settings=str(settings), write=True)
        self.assertTrue(done["changed"])
        remaining = json.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(remaining["mcpServers"], {"github": {"command": "gh"}})
        self.assertEqual(remaining["theme"], "dark")
        hooks = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(hooks["hooks"]["SessionStart"][0]["hooks"], [{"type": "command", "command": "echo other hook"}])
        self.assertNotIn("UserPromptSubmit", hooks["hooks"])
        self.assertEqual(hooks["model"], "opus")

    def test_disconnect_codex_toml_block(self):
        from link_core.mcp_connect import build_disconnect_payload
        config = self.dir / "config.toml"
        config.write_text('model = "o4"\n\n[mcp_servers.link]\ncommand = "py"\nargs = ["-m", "link_mcp"]\n\n'
                          '[mcp_servers.other]\ncommand = "x"\n', encoding="utf-8")
        build_disconnect_payload("codex", config_path=str(config), hooks_settings=str(self.dir / "none.json"), write=True)
        text = config.read_text(encoding="utf-8")
        self.assertNotIn("mcp_servers.link", text)
        self.assertIn("[mcp_servers.other]", text)
        self.assertIn('model = "o4"', text)

    def test_disconnect_keeps_comments_in_jsonc(self):
        from link_core.mcp_connect import _jsonc_loads, build_disconnect_payload
        config = self.dir / "settings.json"
        config.write_text('{\n  // editor\n  "context_servers": {\n    "link": {"command": "py", "source": "custom"},\n'
                          '    "other": {"command": "x"} // keep\n  }\n}\n', encoding="utf-8")
        build_disconnect_payload("zed", config_path=str(config), write=True)
        text = config.read_text(encoding="utf-8")
        self.assertIn("// editor", text)
        self.assertIn("// keep", text)
        self.assertEqual(list(_jsonc_loads(text)["context_servers"]), ["other"])
