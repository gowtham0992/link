"""Suggested next commands must run on a pip install, which ships link_cli.py, not link.py."""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))
SPEC = importlib.util.spec_from_file_location("link_cli_hints", ROOT / "link.py")
link = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(link)


class PipShimTests(unittest.TestCase):
    def _with_lnk(self, text):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        shim = Path(temp.name) / "lnk"
        shim.write_text(text, encoding="utf-8")
        shim.chmod(0o755)
        return mock.patch.dict(os.environ, {"PATH": temp.name})

    @unittest.skipIf(os.name == "nt", "Windows installs lnk.exe; an extensionless script is not on PATH there")
    def test_pip_console_script_for_this_interpreter_counts(self):
        with self._with_lnk(f"#!{sys.executable}\nfrom link_cli import main\nmain()\n"):
            self.assertTrue(link._lnk_on_path_runs_this_runtime())

    def test_another_interpreters_lnk_does_not(self):
        with self._with_lnk("#!/nonexistent/python\nfrom link_cli import main\nmain()\n"):
            self.assertFalse(link._lnk_on_path_runs_this_runtime())

    def test_fallback_names_the_file_that_is_running(self):
        import link_core.mcp_verify as verify

        saved = verify._link_command_override
        self.addCleanup(verify.set_link_command_override, saved)
        with mock.patch.dict(os.environ, {"PATH": "", "LINK_CLI_COMMAND": ""}):
            link._configure_link_command_display()
            rendered = link._display_command(["link", "recall", "x"])
        self.assertIn(str(Path(link.__file__).resolve()), rendered)


if __name__ == "__main__":
    unittest.main()
