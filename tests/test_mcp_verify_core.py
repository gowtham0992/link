import shutil
import tempfile
import unittest
from pathlib import Path

from mcp_package.link_core.mcp_verify import (
    build_mcp_verify_status,
    display_command,
    expand_command_prefix,
    mcp_verify_guidance,
    resolve_mcp_python,
    render_mcp_verify_text,
    set_link_command_override,
)


class McpVerifyCoreTests(unittest.TestCase):
    def tearDown(self):
        set_link_command_override(None)

    def test_guidance_reports_missing_sdk_and_version_mismatch(self):
        issues, actions = mcp_verify_guidance(
            target=Path("/tmp/link"),
            init_command=["python3", "link.py", "init", "/tmp/link"],
            expected_version="1.2.0",
            python_cmd="/tmp/Link Python/bin/python",
            import_status={"installed": True, "version": "1.1.0"},
            mcp_sdk_ready=False,
            version_matches=False,
            wiki_exists=True,
        )

        self.assertEqual([issue["code"] for issue in issues], ["mcp_sdk_missing", "version_mismatch"])
        self.assertEqual([action["tool"] for action in actions], ["reinstall_link_mcp", "upgrade_link_mcp"])
        self.assertIn("/tmp/Link Python/bin/python", actions[0]["command_text"])

    def test_render_ready_status(self):
        code, text = render_mcp_verify_text({
            "ready": True,
            "target": "/tmp/link",
            "python": "/tmp/python",
            "expected_version": "1.2.0",
            "version_matches": True,
            "link_mcp": {"installed": True, "version": "1.2.0", "mcp_sdk": True, "error": None},
            "wiki": {"path": "/tmp/link/wiki", "exists": True},
            "config": {"mcpServers": {"link": {"command": "/tmp/python", "args": ["-m", "link_mcp"]}}},
            "next_actions": [],
        })

        self.assertEqual(code, 0)
        self.assertIn("Link MCP verification: /tmp/link", text)
        self.assertIn("link-mcp: installed (1.2.0)", text)
        self.assertIn('"command": "/tmp/python"', text)
        self.assertIn("Result: ready", text)

    def test_render_missing_package_status(self):
        action = {
            "tool": "install_link_mcp",
            "command_text": "/tmp/python -m pip install --upgrade link-mcp",
        }
        code, text = render_mcp_verify_text({
            "ready": False,
            "target": "/tmp/link",
            "python": "/tmp/python",
            "expected_version": "1.2.0",
            "version_matches": False,
            "link_mcp": {"installed": False, "version": None, "mcp_sdk": False, "error": "No module named link_mcp"},
            "wiki": {"path": "/tmp/link/wiki", "exists": True},
            "config": {},
            "next_actions": [action],
        })

        self.assertEqual(code, 1)
        self.assertIn("link-mcp: missing", text)
        self.assertIn("Install: /tmp/python -m pip install --upgrade link-mcp", text)
        self.assertIn("macOS/Homebrew fallback", text)
        self.assertIn("Result: needs attention", text)

    def test_display_command_quotes_paths(self):
        text = display_command(["/tmp/Link Python/bin/python", "-m", "pip"])

        self.assertIn("/tmp/Link Python/bin/python", text)
        self.assertIn("-m", text)
        self.assertIn("pip", text)

    def test_display_command_uses_non_conflicting_default_link_command(self):
        text = display_command(["link", "health", "/tmp/link"])

        self.assertEqual(text, "lnk health /tmp/link")

    def test_display_command_can_use_source_checkout_command(self):
        set_link_command_override(["python3", "/repo/link.py"])

        text = display_command(["link", "health", "/tmp/link"])

        self.assertEqual(text, "python3 /repo/link.py health /tmp/link")

    def test_display_command_rewrites_lnk_when_source_checkout_command_is_set(self):
        set_link_command_override(["python3", "/repo/link.py"])

        text = display_command(["lnk", "doctor", "/tmp/link"])

        self.assertEqual(text, "python3 /repo/link.py doctor /tmp/link")

    def test_expand_command_prefix_preserves_command_path_syntax(self):
        self.assertEqual(expand_command_prefix("/tmp/python"), "/tmp/python")
        self.assertEqual(expand_command_prefix("python"), "python")
        self.assertIn("link-python", expand_command_prefix("~/link-python"))

    def test_resolve_mcp_python_uses_marker(self):
        root = Path(tempfile.mkdtemp(prefix="link-mcp-verify-"))
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        (root / ".link-mcp-python").write_text("/tmp/link-python\n", encoding="utf-8")

        python = resolve_mcp_python(root, root / "wiki", None, default_python="/usr/bin/python")

        self.assertEqual(python, "/tmp/link-python")

    def test_build_status_ready(self):
        target = Path("/tmp/link")
        status = build_mcp_verify_status(
            target=target,
            wiki_dir=Path(__file__).resolve().parents[1],
            expected_version="1.2.0",
            init_command=["python3", "link.py", "init", "/tmp/link"],
            default_python="/tmp/python",
            import_check=lambda _python: {
                "installed": True,
                "version": "1.2.0",
                "mcp_sdk": True,
                "error": None,
            },
        )

        self.assertTrue(status["ready"])
        self.assertEqual(status["python"], "/tmp/python")
        self.assertEqual(status["next_actions"], [])
        self.assertEqual(status["config"]["mcpServers"]["link"]["command"], "/tmp/python")

    def test_build_status_reports_missing_wiki_and_version_mismatch(self):
        status = build_mcp_verify_status(
            target=Path("/tmp/link"),
            wiki_dir=Path("/tmp/link/missing-wiki"),
            expected_version="1.2.0",
            init_command=["python3", "link.py", "init", "/tmp/link"],
            default_python="/tmp/python",
            import_check=lambda _python: {
                "installed": True,
                "version": "1.1.0",
                "mcp_sdk": True,
                "error": None,
            },
        )

        self.assertFalse(status["ready"])
        self.assertEqual([issue["code"] for issue in status["issues"]], ["version_mismatch", "wiki_missing"])
        self.assertEqual([action["tool"] for action in status["next_actions"]], ["upgrade_link_mcp", "init_wiki"])


if __name__ == "__main__":
    unittest.main()
