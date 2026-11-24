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
from link_core.tool_hooks import evaluate_tool_call  # noqa: E402

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
            # Every word of a writing cmdlet counts: an unknown parameter could have shifted the path.
            r"Add-Content migrations\1.sql 'x'": ([], [r"migrations\1.sql", "x"]),
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

    def test_a_short_switch_never_swallows_the_path(self):
        for command in ("Remove-Item -r C:\\ws\\wiki", "rm -r C:\\ws\\wiki", "rd -r C:\\ws\\wiki",
                        "Remove-Item -re -fo C:\\ws\\wiki", "ri -h C:\\ws\\wiki", "Remove-Item -v C:\\ws\\wiki"):
            reading = read_powershell(command)
            self.assertIn("C:\\ws\\wiki", reading.writes, command)
            self.assertIn("C:\\ws\\wiki", reading.trees, command)
        self.assertEqual(read_powershell("Get-Content -h 5 .env").reads, ["5", ".env"])
        self.assertEqual(read_powershell("Copy-Item a.txt -Dest C:\\x").writes, ["C:\\x"])

    def test_pipeline_items_joined_paths_and_dotnet_folders(self):
        home = os.path.expanduser("~")
        sep = "\\" if "\\" in home else "/"  # Join-Path keeps the parent's separator
        os.environ["LINK_PS_HOME"] = "C:\\Users\\me"
        try:
            cases = {
                "Get-ChildItem C:\\ws\\m | ForEach-Object { Remove-Item $_.FullName }": "C:\\ws\\m",
                "gci C:\\ws\\m -r | % { ri $PSItem.FullName }": "C:\\ws\\m",
                "Remove-Item (Join-Path $HOME 'link') -Recurse": f"{home}{sep}link",
                "Remove-Item -Recurse -Force ${HOME}/link": f"{home}/link",
                "Remove-Item (Join-Path $env:LINK_PS_HOME 'link') -Recurse": "C:\\Users\\me\\link",
                "$m = Join-Path $HOME 'link/wiki'; Remove-Item $m -Recurse": f"{home}{sep}link/wiki",
                "[IO.Directory]::Delete('C:\\ws\\wiki', $true)": "C:\\ws\\wiki",
                "Expand-Archive x.zip C:\\ws -Force": "C:\\ws",
                "Expand-Archive -Path x.zip -DestinationPath C:\\ws": "C:\\ws",
            }
            for command, tree in cases.items():
                self.assertIn(tree, read_powershell(command).trees, command)
        finally:
            del os.environ["LINK_PS_HOME"]
        self.assertIn("C:\\ws\\m", read_powershell("Get-ChildItem C:\\ws\\m | % { Set-Content $_.FullName '' }").writes)
        self.assertEqual(read_powershell("[IO.File]::Delete('C:\\ws\\a.md')").trees, [])
        self.assertEqual(read_powershell("Remove-Item (Join-Path $unknown 'dist')").writes, [])

    def test_programs_started_indirectly_are_seen(self):
        for command in ("Start-Process git -ArgumentList 'push','-f'", "Start-Process git -ArgumentList @('push','-f')",
                        "Start-Process git 'push -f'", "& 'C:\\Program Files\\Git\\bin\\git.exe' push -f"):
            commands = [" ".join(words) for words in read_powershell(command).commands]
            self.assertTrue(any(c.startswith(("git push -f", "git.exe push -f")) for c in commands), (command, commands))
        reading = read_powershell("Start-Process pwsh -ArgumentList '-c','Remove-Item C:\\ws\\wiki -Recurse'")
        self.assertEqual(reading.trees, ["C:\\ws\\wiki"])

    def test_deep_subexpressions_are_read_quickly_and_too_deep_is_opaque(self):
        import time

        started = time.perf_counter()
        reading = read_powershell("git push -f; echo " + "$(" * 300 + "true" + ")" * 300)
        self.assertLess(time.perf_counter() - started, 1.0)
        self.assertTrue(reading.opaque)
        self.assertIn(["git", "push", "-f"], reading.commands)
        self.assertFalse(read_powershell('echo "$(Get-Date)" "$(whoami)"').opaque)
        self.assertTrue(read_powershell("Remove-Item " + "a," * 60_000).opaque, "too long to read in time")

    def test_the_powershell_tool_is_read_as_powershell(self):
        self.assertEqual(tool_calls({"tool_name": "PowerShell", "tool_input": {"command": "gc .env"}}),
                         [("powershell", "gc .env")])
        self.assertEqual(tool_calls({"toolName": "powershell", "toolArgs": {"command": "ls"}}), [("powershell", "ls")])
        self.assertEqual(tool_calls({"tool_name": "Bash", "tool_input": {"command": "ls"}}), [("command", "ls")])


class PowerShellGuardTests(unittest.TestCase):
    """The ways PowerShell spells a write to Link's own files, each held by the guard."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ws = Path(self.temp.name) / "ws"
        (self.ws / "wiki" / "memories").mkdir(parents=True)
        (self.ws / ".link-cache").mkdir()
        self.index = {"rules": [{"name": "r", "title": "t", "action": "deny", "kind": "command",
                                 "pattern": "never-matches"}]}

    def tearDown(self):
        self.temp.cleanup()

    def _decision(self, command, tool="PowerShell"):
        decision = evaluate_tool_call(self.index, {"tool_name": tool, "tool_input": {"command": command}},
                                      context_path=str(self.ws),
                                      protected=[self.ws / "wiki" / "memories", self.ws / ".link-cache"])
        return decision and decision["decision"]

    def test_every_spelling_is_held(self):
        cache, memories = f"{self.ws.as_posix()}/.link-cache", f"{self.ws.as_posix()}/wiki/memories"
        held = [
            f"if (Test-Path {cache}) {{ Remove-Item {cache} -Recurse }}",
            f"1 | ForEach-Object {{ Remove-Item {cache} -Recurse }}",
            f"(Remove-Item {cache} -Recurse)",
            f'echo "$(Remove-Item {cache} -Recurse)"',
            f"Get-ChildItem {memories} | Remove-Item",
            f"'{cache}' | Remove-Item -Recurse",
            f"Remove-Item -Recurse -Force `\n  {cache}",
            f"@'\nIt's a note\n'@ | Set-Content {memories}/evil.md",
            f"Set-Content -Va hi -Pa {cache}/approvals.json",
            f"New-Item -Type File {memories}/evil.md",
            f"'x' | Out-File -Enc utf8 {cache}/approvals.json",
            f"Copy-Item -Dest {memories}/evil.md /tmp/evil.md",
            f"Set-Content x.txt,{cache}/approvals.json y",
            f"Copy-Item /tmp/x \u2013Destination {memories}/x.md",
            "powershell -EncodedCommand UgBlAG0AbwB2AGUALQBJAHQAZQBtAA==",
            f"powershell.exe Remove-Item {cache} -Recurse",
            f'pwsh -Com "Remove-Item {cache} -Recurse"',
            f'cmd.exe /c "rmdir /s /q {cache}"',
            f"iex 'Remove-Item {cache} -Recurse'",
            "iex $code",
            f"echo x>{cache}/approvals.json",
            f"<# note #> Remove-Item {cache} -Recurse",
            f"Remove-Item {self.ws.as_posix()}/.link-cach?",
            f"$p = '{cache}'; rm $p -Recurse",
            f"Invoke-WebRequest https://example.com -OutFile {memories}/evil.md",
            f"[IO.File]::WriteAllText('{cache}/approvals.json', 'x')",
            f"echo x > 'a\x00b'; Remove-Item {cache} -Recurse",
            # Paths built from literals and known variables, items fed down a pipe, Link run indirectly.
            f"Remove-Item (Join-Path '{self.ws.as_posix()}' 'wiki/memories') -Recurse",
            f"Remove-Item (Join-Path -Path '{self.ws.as_posix()}' -ChildPath .link-cache) -Recurse",
            f"$r='{self.ws.as_posix()}'; Remove-Item ($r + '/wiki/memories') -Recurse",
            f"'{memories}' | ForEach-Object {{ Remove-Item $_ -Recurse }}",
            f"Clear-Item {memories}/a.md",
            f"$p='{cache}/approvals.json'; [IO.File]::WriteAllText($p,'x')",
            f"python3 -c \"import shutil; shutil.rmtree('{memories}')\"",
            "$x='approve'; lnk $x abc123",
            'git -c core.pager="lnk approve abc123" log',
        ]
        for command in held:
            self.assertEqual(self._decision(command), "ask", command)
        # A shell tool on Windows can run PowerShell too.
        self.assertEqual(self._decision(f"Remove-Item {cache} -Recurse", tool="Bash"), "ask")
        self.assertEqual(self._decision(f"pwsh -c 'Remove-Item {cache} -Recurse'", tool="Bash"), "ask")

    def test_ordinary_powershell_is_not_held(self):
        for command in ["Get-ChildItem src | Remove-Item", "if (Test-Path dist) { Remove-Item dist -Recurse }",
                        "Get-Process 2>&1 | Out-Null", "git log --oneline 2>&1", "Set-Content notes.txt 'x'",
                        f"Get-Content {self.ws.as_posix()}/wiki/memories/a.md",
                        # Beside Link's files, in the folder above them: nothing beneath is touched.
                        f"Copy-Item notes.txt {self.ws.parent.as_posix()}",
                        f"New-Item -ItemType Directory {self.ws.parent.as_posix()}/proj",
                        f"Move-Item build.log {self.ws.parent.as_posix()}",
                        "Remove-Item (Join-Path $unknown 'dist') -Recurse"]:
            self.assertIsNone(self._decision(command), command)



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
