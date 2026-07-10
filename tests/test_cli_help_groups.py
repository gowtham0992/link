import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.cli_parser import COMMAND_GROUPS, build_cli_parser  # noqa: E402


class GroupedHelpTests(unittest.TestCase):
    def _registered_commands(self) -> set[str]:
        parser = build_cli_parser()
        for action in parser._actions:
            if hasattr(action, "choices") and isinstance(action.choices, dict):
                return set(action.choices)
        raise AssertionError("no subparsers found")

    def test_every_command_appears_in_exactly_one_help_group(self):
        # The grouped epilog replaces argparse's flat listing, so a command
        # missing here is invisible in --help. Aliases are exempt (they
        # resolve to a canonical command that must be listed).
        grouped: list[str] = [name for _, names in COMMAND_GROUPS for name in names]
        self.assertEqual(len(grouped), len(set(grouped)), "duplicate command in help groups")
        registered = self._registered_commands()
        aliases = {"end", "next"}
        missing = (registered - aliases) - set(grouped)
        self.assertFalse(missing, f"commands invisible in --help: {sorted(missing)}")
        ghosts = set(grouped) - registered
        self.assertFalse(ghosts, f"help lists nonexistent commands: {sorted(ghosts)}")

    def test_help_output_is_grouped_not_a_flat_wall(self):
        parser = build_cli_parser()
        text = parser.format_help()
        self.assertIn("Start here:", text)
        self.assertIn("Memory — the core loop:", text)
        # The old brace-wall must be gone from usage.
        self.assertNotIn("{version,init,serve", text)


if __name__ == "__main__":
    unittest.main()
