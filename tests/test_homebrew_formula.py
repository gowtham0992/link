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
        self.assertIn('libexec.install "link.py", "serve.py", "LINK.md", ".linkignore"', formula)
        self.assertIn('(libexec/"mcp_package").install "mcp_package/link_core"', formula)
        # The shim prefers the managed venv when it hosts link-mcp, so the
        # optional semantic/rerank tiers work under Homebrew's PEP 668 python.
        self.assertIn('LINK_VENV_PY="$HOME/.link-mcp-venv/bin/python"', formula)
        self.assertIn('exec "#{python3}" "#{libexec}/link.py" "$@"', formula)

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
