import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.cli_style import style_cli_text, supports_color  # noqa: E402


class _Stream:
    def __init__(self, tty: bool):
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


class CliStyleCoreTests(unittest.TestCase):
    def test_plain_stream_keeps_text_unstyled(self):
        text = "Link health: /tmp/link\nReady: yes\nNext:\n  lnk health /tmp/link"

        self.assertEqual(style_cli_text(text, stream=_Stream(False)), text)

    def test_tty_stream_styles_status_and_commands(self):
        text = "Link health: /tmp/link\nReady: yes\nNext:\nlnk health /tmp/link"

        with patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
            styled = style_cli_text(text, stream=_Stream(True))

        self.assertIn("\033[", styled)
        self.assertIn("Link health", styled)
        self.assertIn("Ready: yes", styled)
        self.assertIn("lnk health", styled)

    def test_no_color_disables_tty_styling(self):
        with patch.dict(os.environ, {"NO_COLOR": "1", "TERM": "xterm-256color"}, clear=True):
            self.assertFalse(supports_color(_Stream(True)))
