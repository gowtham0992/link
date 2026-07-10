import shutil
import tempfile
import unittest
from pathlib import Path

from mcp_package.link_core.mcp_verify import (
    build_mcp_verify_status,
    display_command,
    ensure_link_mcp_runtime,
    expand_command_prefix,
    mcp_verify_guidance,
    provision_link_extras,
    resolve_mcp_python,
    render_mcp_verify_text,
    set_link_command_override,
)


class ProvisionLinkExtrasTests(unittest.TestCase):
    def test_installs_pinned_extras_into_managed_venv(self):
        with tempfile.TemporaryDirectory() as temp:
            venv_dir = Path(temp) / "venv"
            commands = []

            def run(cmd, **kwargs):
                commands.append(cmd)
                class Done:
                    returncode = 0
                    stdout = ""
                    stderr = ""
                return Done()

            result = provision_link_extras(
                "/usr/bin/python3", "1.7.0", venv_dir=venv_dir, run=run,
            )

        self.assertTrue(result["ready"])
        self.assertEqual(commands[0][:3], ["/usr/bin/python3", "-m", "venv"])
        self.assertIn("link-mcp[semantic,semantic-quality,rerank]==1.7.0", commands[1])

    def test_reports_pip_failure_with_the_failing_command(self):
        with tempfile.TemporaryDirectory() as temp:
            venv_dir = Path(temp) / "venv"

            def run(cmd, **kwargs):
                class Failed:
                    returncode = 1
                    stdout = ""
                    stderr = "error: no matching distribution"
                return Failed()

            result = provision_link_extras(
                "/usr/bin/python3", "9.9.9", venv_dir=venv_dir, run=run,
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("no matching distribution" in note for note in result["notes"]))


class EnsureLinkMcpRuntimeTests(unittest.TestCase):
    def test_configured_python_that_matches_wins(self):
        def check(python_cmd):
            return {"installed": True, "version": "1.7.0", "mcp_sdk": True, "error": None}

        result = ensure_link_mcp_runtime("/usr/bin/python3", "1.7.0", import_check=check)

        self.assertTrue(result["ready"])
        self.assertEqual(result["python"], "/usr/bin/python3")
        self.assertFalse(result["provisioned"])

    def test_existing_venv_is_used_when_configured_python_is_stale(self):
        with tempfile.TemporaryDirectory() as temp:
            venv_dir = Path(temp) / "venv"
            (venv_dir / "bin").mkdir(parents=True)
            venv_python = venv_dir / "bin" / "python"
            venv_python.write_text("")

            def check(python_cmd):
                if python_cmd == str(venv_python):
                    return {"installed": True, "version": "1.7.0", "mcp_sdk": True, "error": None}
                return {"installed": True, "version": "1.0.5", "mcp_sdk": True, "error": None}

            result = ensure_link_mcp_runtime(
                "/usr/bin/python3", "1.7.0", import_check=check, venv_dir=venv_dir,
            )

        self.assertTrue(result["ready"])
        self.assertEqual(result["python"], str(venv_python))
        self.assertFalse(result["provisioned"])

    def test_provisioning_creates_venv_and_reports_pip_failures(self):
        with tempfile.TemporaryDirectory() as temp:
            venv_dir = Path(temp) / "venv"
            commands = []

            def check(python_cmd):
                if commands:  # after provisioning steps ran
                    return {"installed": True, "version": "1.7.0", "mcp_sdk": True, "error": None}
                return {"installed": False, "version": None, "mcp_sdk": False, "error": "no module"}

            def run(cmd, **kwargs):
                commands.append(cmd)
                class Done:
                    returncode = 0
                    stdout = ""
                    stderr = ""
                return Done()

            result = ensure_link_mcp_runtime(
                "/usr/bin/python3", "1.7.0",
                provision=True, import_check=check, venv_dir=venv_dir, run=run,
            )

        self.assertTrue(result["ready"])
        self.assertTrue(result["provisioned"])
        self.assertEqual(commands[0][:3], ["/usr/bin/python3", "-m", "venv"])
        self.assertIn("link-mcp==1.7.0", commands[1])

    def test_no_provisioning_without_the_flag(self):
        def check(python_cmd):
            return {"installed": False, "version": None, "mcp_sdk": False, "error": "no module"}

        def run(cmd, **kwargs):
            raise AssertionError("must not run provisioning commands without provision=True")

        result = ensure_link_mcp_runtime("/usr/bin/python3", "1.7.0", import_check=check, run=run)

        self.assertFalse(result["ready"])
        self.assertFalse(result["provisioned"])


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
