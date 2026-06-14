import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HomebrewFormulaTests(unittest.TestCase):
    def test_formula_installs_link_runtime_and_bundled_core(self):
        formula = (ROOT / "packaging/homebrew/Formula/link.rb").read_text(encoding="utf-8")

        self.assertIn('desc "Local Markdown memory for AI agents"', formula)
        self.assertIn('license "MIT"', formula)
        self.assertIn('depends_on "python@3.14"', formula)
        self.assertIn('libexec.install "link.py", "serve.py", "LINK.md", ".linkignore"', formula)
        self.assertIn('(libexec/"mcp_package").install "mcp_package/link_core"', formula)
        self.assertIn('LINK_CLI_COMMAND=lnk exec "#{python3}" "#{libexec}/link.py" "$@"', formula)

    def test_formula_uses_pinned_release_tag_and_revision(self):
        formula = (ROOT / "packaging/homebrew/Formula/link.rb").read_text(encoding="utf-8")

        self.assertRegex(formula, r'tag:\s+"v\d+\.\d+\.\d+"')
        self.assertRegex(formula, r'revision:\s+"[0-9a-f]{40}"')

        tag = re.search(r'tag:\s+"([^"]+)"', formula)
        revision = re.search(r'revision:\s+"([^"]+)"', formula)
        self.assertIsNotNone(tag)
        self.assertIsNotNone(revision)


if __name__ == "__main__":
    unittest.main()
