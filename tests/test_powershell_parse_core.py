"""PowerShell commands read as PowerShell: backslashes kept, files named by cmdlets and their aliases."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.shell_parse import read_powershell  # noqa: E402
from link_core.tool_events import tool_calls  # noqa: E402

LINK = [sys.executable, str(ROOT / "link.py")]
HOOK = [sys.executable, str(ROOT / "link_hook.py")]


class ReadPowerShellTests(unittest.TestCase):
    def _rw(self, command):
        reading = read_powershell(command)
        return reading.reads, reading.writes

    def test_backslash_paths_survive(self):
        self.assertEqual(self._rw(r"Get-Content C:\repo\.env"), ([r"C:\repo\.env"], []))
        self.assertEqual(self._rw(r"gc 'C:\a b\.env'"), ([r"C:\a b\.env"], []))
        self.assertEqual(self._rw(r'type "C:\a b\.env"'), ([r"C:\a b\.env"], []))

    def test_cmdlets_and_aliases_name_their_files(self):
        cases = {
            r"Set-Content -Path C:\repo\migrations\1.sql -Value x": ([], [r"C:\repo\migrations\1.sql"]),
            r"Add-Content migrations\1.sql 'x'": ([], [r"migrations\1.sql"]),
            r"Remove-Item -Recurse -Force C:\ws\.link-cache": ([], [r"C:\ws\.link-cache"]),
            r"del a.txt, b.txt": ([], ["a.txt", "b.txt"]),
            r"Copy-Item .env C:\tmp\leak.txt": ([".env"], [r"C:\tmp\leak.txt"]),
            r"Move-Item -Path wiki\memories\a.md -Destination C:\tmp": ([], [r"C:\tmp", r"wiki\memories\a.md"]),
            r"Select-String -Pattern token -Path .env": ([".env"], []),
            r"Select-String token .env": ([".env"], []),
            r"'x' | Out-File -FilePath notes.txt": ([], ["notes.txt"]),
            r"echo x > C:\ws\.link-cache\approvals.json": ([], [r"C:\ws\.link-cache\approvals.json"]),
            r"Get-Content -Path:.env": ([".env"], []),
        }
        for command, expected in cases.items():
            reads, writes = self._rw(command)
            self.assertEqual((reads, sorted(writes)), (expected[0], sorted(expected[1])), command)

    def test_location_and_variables_are_followed(self):
        self.assertEqual(self._rw(r"cd C:\ws; Remove-Item .link-cache -Recurse")[1], [r"C:\ws\.link-cache"])
        self.assertEqual(self._rw(r"Set-Location C:\ws && del .\wiki\memories\x.md")[1],
                         [r"C:\ws\wiki\memories\x.md"])
        os.environ["LINK_PS_TEST"] = r"C:\Users\me"
        try:
            self.assertEqual(self._rw(r"Get-Content $env:LINK_PS_TEST\.ssh\id_rsa")[0], [r"C:\Users\me\.ssh\id_rsa"])
        finally:
            del os.environ["LINK_PS_TEST"]

    def test_commands_for_command_rules(self):
        reading = read_powershell(r'git commit -m "x; y" && git push --force; & "C:\Program Files\Link\lnk.exe" approve abc')
        self.assertEqual(reading.commands, [["git", "commit", "-m", "x; y"], ["git", "push", "--force"],
                                            ["lnk.exe", "approve", "abc"]])
        nested = read_powershell(r'pwsh -NoProfile -Command "Remove-Item C:\ws\wiki -Recurse"')
        self.assertEqual(nested.writes, [r"C:\ws\wiki"])
        self.assertEqual(read_powershell("bash -c 'cat .env'").reads, [".env"], "a POSIX shell inside reads as one")

    def test_the_powershell_tool_is_read_as_powershell(self):
        self.assertEqual(tool_calls({"tool_name": "PowerShell", "tool_input": {"command": "gc .env"}}),
                         [("powershell", "gc .env")])
        self.assertEqual(tool_calls({"toolName": "powershell", "toolArgs": {"command": "ls"}}), [("powershell", "ls")])
        self.assertEqual(tool_calls({"tool_name": "Bash", "tool_input": {"command": "ls"}}), [("command", "ls")])


class PowerShellRulesTests(unittest.TestCase):
    """End to end through the hook: rules on paths and Link's own files hold for PowerShell calls."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ws = Path(self.temp.name) / "ws"
        subprocess.run([*LINK, "demo", str(self.ws), "--force"], check=True, capture_output=True)
        subprocess.run([*LINK, "remember", "Secrets never enter the agent's context", str(self.ws),
                        "--enforce", "ask read: .env", "--enforce", "deny write: migrations/**"],
                       check=True, capture_output=True)
        name = next(p.stem for p in (self.ws / "wiki" / "memories").glob("secrets-never*.md"))
        subprocess.run([*LINK, "review-memory", name, str(self.ws)], check=True, capture_output=True)

    def tearDown(self):
        self.temp.cleanup()

    def _decision(self, command):
        out = subprocess.run([*HOOK, "hook", "pre-tool", str(self.ws)], capture_output=True, text=True, check=True,
                             input=json.dumps({"tool_name": "PowerShell", "tool_input": {"command": command},
                                               "cwd": str(self.ws)})).stdout
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else None

    def test_path_rules_and_the_guard_see_powershell(self):
        self.assertEqual(self._decision(r"Get-Content C:\repo\.env"), "ask")
        self.assertEqual(self._decision(r"Set-Content C:\repo\migrations\0002.sql 'x'"), "deny")
        self.assertEqual(self._decision(f"Remove-Item -Recurse {self.ws.as_posix()}/.link-cache"), "ask")
        self.assertEqual(self._decision(f"cd {self.ws.as_posix()}; del .link-cache/approvals.json"), "ask")
        self.assertIsNone(self._decision(r"Get-Content C:\repo\README.md"))
        self.assertIsNone(self._decision(r"Set-Content C:\repo\src\app.py 'x'"))


if __name__ == "__main__":
    unittest.main()
