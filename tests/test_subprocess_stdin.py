"""Every subprocess Link's package spawns closes or feeds stdin explicitly.

The MCP server talks to its client over stdin/stdout. A child process that
inherits that stdin hangs on Windows until its timeout; one `git rev-parse`
in the recall path made every MCP recall time out on Windows CI. link_core
and link_mcp run inside that server, so each spawn there must pass `stdin=`
or `input=`. (The CLI copy the package build drops beside them is not
scanned: interactive CLI spawns may inherit the terminal on purpose.)
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_PACKAGES = (ROOT / "mcp_package" / "link_core", ROOT / "mcp_package" / "link_mcp")
SPAWN_RE = re.compile(r"\bsubprocess\.(?:run|Popen|check_output|check_call|call)\(")


def spawn_calls(text: str):
    for match in SPAWN_RE.finditer(text):
        depth, index = 1, match.end()
        while depth and index < len(text):
            depth += {"(": 1, ")": -1}.get(text[index], 0)
            index += 1
        yield text.count("\n", 0, match.start()) + 1, text[match.start():index]


class SubprocessStdinTests(unittest.TestCase):
    def test_package_spawns_never_inherit_stdin(self):
        offenders = []
        checked = 0
        for path in sorted(path for package in SERVER_PACKAGES for path in package.rglob("*.py")):
            for line, call in spawn_calls(path.read_text(encoding="utf-8")):
                checked += 1
                if "stdin=" not in call and "input=" not in call:
                    offenders.append(f"{path.relative_to(ROOT)}:{line}")
        self.assertGreater(checked, 0)
        self.assertEqual(offenders, [], "pass stdin=subprocess.DEVNULL (or input=) to these spawns")

    def test_scanner_catches_an_inheriting_spawn(self):
        calls = list(spawn_calls('subprocess.run(\n    ["git", "status"],\n    capture_output=True,\n)\n'))
        self.assertEqual(len(calls), 1)
        self.assertNotIn("stdin=", calls[0][1])


if __name__ == "__main__":
    unittest.main()
