import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HomebrewFormulaTests(unittest.TestCase):
    """The in-repo template must mirror what the live tap actually ships."""

    def _formula(self) -> str:
        return (ROOT / "packaging/homebrew/Formula/link.rb").read_text(encoding="utf-8")

    def test_formula_installs_link_runtime_and_bundled_core(self):
        formula = self._formula()

        self.assertIn('desc "Local Markdown memory for AI agents"', formula)
        self.assertIn('license "MIT"', formula)
        self.assertIn('depends_on "python@3.14"', formula)
        self.assertIn('libexec.install "link.py", "link_hook.py", "serve.py", "LINK.md", ".linkignore"', formula)
        self.assertIn('(libexec/"mcp_package").install "mcp_package/link_core"', formula)
        # The shim prefers the managed venv when it hosts link-mcp, so the
        # optional semantic/rerank tiers work under Homebrew's PEP 668 python.
        self.assertIn('LINK_VENV_PY="$HOME/.link-mcp-venv/bin/python"', formula)
        self.assertIn('exec "#{python3}" "#{libexec}/link.py" "$@"', formula)

    def test_formula_installs_every_file_a_workspace_runtime_copies(self):
        # `lnk setup` copies the runtime from where Homebrew put it; a file the
        # formula leaves out never reaches a workspace (6.0.0 shipped without
        # link_hook.py, so tool hooks never took the fast path under Homebrew).
        import sys  # noqa: PLC0415

        sys.path.insert(0, str(ROOT / "mcp_package"))
        from link_core.demo import RUNTIME_FILES  # noqa: PLC0415

        install = re.search(r'libexec\.install ("[^\n]+)', self._formula())
        self.assertIsNotNone(install)
        for name in RUNTIME_FILES:
            self.assertIn(f'"{name}"', install.group(1), name)

    def test_the_release_renders_the_tap_formula_from_this_template(self):
        import sys  # noqa: PLC0415

        sys.path.insert(0, str(ROOT / "scripts"))
        import prepare_release  # noqa: PLC0415

        formula = self._formula()
        self.assertIn('url "https://github.com/gowtham0992/link/archive/refs/tags/vX.Y.Z.tar.gz"', formula)
        self.assertIn('sha256 "REPLACE_WITH_RELEASE_TARBALL_SHA256"', formula)
        render = prepare_release.tap_commands("6.0.1", None)[1]
        self.assertIn("packaging/homebrew/Formula/link.rb > ", render)
        self.assertIn("refs/tags/v6.0.1.tar.gz", render)

    def test_formula_pins_release_tarball(self):
        formula = self._formula()
        self.assertRegex(formula, r'url "https://github\.com/gowtham0992/link/archive/refs/tags/v.+\.tar\.gz"')
        self.assertIn("sha256 ", formula)

    def test_caveats_teach_the_current_product(self):
        formula = self._formula()
        caveats = re.search(r"<<~EOS\n(.*?)\n\s*EOS", formula, re.DOTALL)
        self.assertIsNotNone(caveats)
        text = caveats.group(1)
        self.assertIn("lnk proof", text)
        self.assertIn("lnk setup", text)
        self.assertIn("linkbar", text)
        # The pre-2.1 per-agent onboarding must not be the post-install story.
        self.assertNotIn("onboard --agent", text)


if __name__ == "__main__":
    unittest.main()
