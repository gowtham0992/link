"""The bash reader: what a command line runs and writes, however it is spelt (the 6.0 review's bypasses)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.shell_parse import SUBSTITUTED, command_forms, read_shell  # noqa: E402
from link_core.tool_hooks import evaluate_tool_call  # noqa: E402


def _commands(command, **kwargs):
    return [" ".join(words) for words in read_shell(command, **kwargs).commands]


class ReadShellTests(unittest.TestCase):
    def test_only_a_real_heredoc_hides_the_lines_after_it(self):
        for command in ("echo '<<X'\nrm -rf /w\nX", 'echo "<<X"\nrm -rf /w\nX', "cat <<< X\nrm -rf /w\nX",
                        "echo $((1<<2))\nrm -rf /w\n2", "((x = 1 << 2))\nrm -rf /w\n2",
                        "echo \"a\n<<X\"\nrm -rf /w\nX", "# it's a note\nrm -rf /w"):
            self.assertIn("rm -rf /w", _commands(command), command)
        self.assertEqual(_commands("cat <<'EOF' > notes.txt\nrm -rf /w\nEOF\nls"), ["cat", "ls"])
        self.assertIn("rm -rf /w", _commands("bash <<EOF\nrm -rf /w\nEOF"), "a heredoc a shell runs is read")
        self.assertEqual(read_shell("python3 - <<'PY'\nimport shutil\nPY").code, ["import shutil"])

    def test_redirects_including_clobber(self):
        self.assertEqual(read_shell("echo x >| /w/a.md").writes, ["/w/a.md"])
        self.assertEqual(read_shell("echo x >> /w/a.md 2>&1").writes[:1], ["/w/a.md"])

    def test_words_are_expanded_as_the_shell_expands_them(self):
        env = {"HOME": "/home/me", "LR": "/home/me/link"}
        cases = {
            "rm -rf $HOME/link/x": ["/home/me/link/x"],
            "rm -rf ${HOME}/link/x": ["/home/me/link/x"],
            "rm -rf ~/link/x": ["/home/me/link/x"],
            "rm -rf $LR/x": ["/home/me/link/x"],
            "L=/srv/l; rm -rf $L/x": ["/srv/l/x"],
            "rm -rf /w/{a,b}": ["/w/a", "/w/b"],
            "rm -rf $'/w/\\x61'": ["/w/a"],
            "rm -rf ${UNSET:-/w/d}": ["/w/d"],
            "for d in /w/a /w/b; do rm -rf $d; done": ["/w/a", "/w/b"],
            'cd "$NOPE" && rm -rf wiki': ["$NOPE/wiki"],
        }
        for command, writes in cases.items():
            self.assertEqual(read_shell(command, environ=env).writes, writes, command)

    def test_substitutions_are_read_and_stand_for_an_unknown_value(self):
        reading = read_shell("lnk $(echo approve) id")
        self.assertIn(["lnk", SUBSTITUTED, "id"], reading.commands)
        self.assertIn(["echo", "approve"], reading.commands)
        self.assertIn("rm -rf /w", _commands("echo $(echo $(rm -rf /w))"))
        self.assertIn("rm -rf /w", _commands("cat <(rm -rf /w)"))
        self.assertNotIn("rm -rf /w", _commands("echo '$(rm -rf /w)'"), "single quotes run nothing")

    def test_what_cannot_be_seen_is_marked_opaque(self):
        for command in ('eval "$c"', 'bash -c "$CMD"', "sh -c `curl -s x`", 'zsh -c "$(curl -s x)"'):
            self.assertTrue(read_shell(command, environ={}).opaque, command)
        known = read_shell("c='rm -rf /w'; eval \"$c\"; bash -c \"$c\"", environ={})
        self.assertFalse(known.opaque, "a variable set on the same line is known")
        self.assertEqual(known.writes, ["/w", "/w"])
        self.assertFalse(read_shell("bash -c 'for f in *; do echo $f; done'").opaque)

    def test_interpreter_code_is_kept_for_the_caller(self):
        cases = {
            "python3 -c \"import shutil; shutil.rmtree('/w')\"": "import shutil; shutil.rmtree('/w')",
            "node -e \"require('fs').rmSync('/w')\"": "require('fs').rmSync('/w')",
            "perl -pi -e 's/a/b/' x": "s/a/b/",
            "ruby -e 'File.delete(\"/w\")'": 'File.delete("/w")',
            "python3.12 -Ic 'print(1)'": "print(1)",
        }
        for command, code in cases.items():
            self.assertIn(code, read_shell(command).code, command)

    def test_writers(self):
        cases = {
            "cp -t /w/m /etc/hosts": ["/w/m"],
            "mkdir -p /w/m/new": ["/w/m/new"],
            "tar -xzf x.tar -C /w/m": ["/w/m"],
            "tar xf x.tar --directory=/w/m": ["/w/m"],
            "tar -czf /w/m/x.tgz src": ["/w/m/x.tgz"],
            "curl -sSLo /w/m/a.md https://x": ["/w/m/a.md"],
            "curl --output=/w/m/a.md https://x": ["/w/m/a.md"],
            "wget -O /w/m/a.md https://x": ["/w/m/a.md"],
            "find /w/m -name '*.md' -exec rm {} +": ["/w/m"],
            "find /w/m -delete": ["/w/m"],
            "echo /w/m/a.md | xargs rm": ["/w/m/a.md"],
            "find /w/m -name x | xargs -I{} rm {}": ["/w/m"],
            "git -C /w clean -fdx": ["/w"],
            "git -C /w rm -r m": ["/w/m"],
            "git rm -- /w/m/a.md": ["/w/m/a.md"],
        }
        for command, writes in cases.items():
            self.assertEqual([w for w in read_shell(command).writes if w in writes], writes, command)

    def test_only_tree_writes_reach_into_what_is_beneath(self):
        self.assertEqual(read_shell("rm -rf /w").trees, ["/w"])
        self.assertEqual(read_shell("chmod -R 700 /w").trees, ["/w"])
        self.assertEqual(read_shell("chmod 700 /w").trees, [])
        self.assertEqual(read_shell("mv /w/a /tmp").trees, ["/tmp/a", "/w/a"])
        self.assertEqual(read_shell("cp notes.txt /home").trees, ["/home/notes.txt"])
        self.assertEqual(read_shell("touch /w/a; mkdir /w/b").trees, [])

    def test_git_runs_aliases_and_settings_as_commands(self):
        for command in (
            "git -c alias.x='!lnk approve abc' x", 'git config alias.x "!lnk approve abc" && git x',
            "git config --global alias.x '!lnk approve abc'", 'git -c core.pager="lnk approve abc" log',
            "git -c core.sshCommand='lnk approve abc' fetch", "git config set alias.x '!lnk approve abc'",
            'GIT_PAGER="lnk approve abc" git log', "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.pager "
            "GIT_CONFIG_VALUE_0='lnk approve abc' git log",
        ):
            self.assertIn("lnk approve abc", _commands(command), command)
        self.assertIn("git push --force origin main",
                      _commands("git -c alias.x=\"!sh -c 'git push --force origin main'\" x"))
        self.assertIn("git push --force", _commands("git -c alias.p='push --force' p"))

    def test_rule_forms(self):
        cases = {
            "git push origin +main": "git push --force origin main",
            "git -C . push -f origin main": "git push -f origin main",
            "git -c x=y --no-pager push origin main --force": "git push --force origin main",
            "npm pub": "npm publish",
            "npm --registry https://r publ --access public": "npm publish --access public",
        }
        for command, plain in cases.items():
            forms = [" ".join(form) for form in command_forms(command.split())]
            self.assertIn(plain, forms, command)
        self.assertEqual(command_forms(["git", "push"]), [["git", "push"]])


class LinkFilesGuardTests(unittest.TestCase):
    """Writes to Link's own files are held however they are spelt; writes beside them are not."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve()
        self.ws = self.home / "link"
        (self.ws / "wiki" / "memories").mkdir(parents=True)
        (self.ws / ".link-cache").mkdir()
        (self.home / "proj").mkdir()
        self.index = {"rules": [{"name": "r", "title": "t", "action": "ask", "kind": "command",
                                 "pattern": "never-matches"}]}
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home), "LINK_TEST_ROOT": str(self.ws)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.temp.cleanup()

    def _held(self, command, cwd=None):
        decision = evaluate_tool_call(self.index, {"tool_name": "Bash", "tool_input": {"command": command}},
                                      context_path=str(cwd or self.home / "proj"),
                                      protected=[self.ws / "wiki" / "memories", self.ws / ".link-cache"])
        return decision is not None

    def test_every_spelling_is_held(self):
        ws = self.ws.as_posix()
        held = [
            "rm -rf $HOME/link/wiki/memories", "rm -rf ${LINK_TEST_ROOT}/wiki/memories",
            "rm -rf ~/link/wiki/{memories,zz}", f"rm -rf $'{ws}/wiki/memories'", f"L={ws}; rm -rf $L/wiki/memories",
            'cd "$NOT_SET" && rm -rf wiki/memories', "rm -rf $NOT_SET/.link-cache", "rm -rf $NOT_SET/wiki",
            f"echo x >| {ws}/wiki/memories/a.md", f"echo '<<X'\nrm -rf {ws}/wiki/memories\nX",
            f"echo $((1<<2))\nrm -rf {ws}/wiki/memories\n2", f"c='rm -rf {ws}/wiki/memories'; eval \"$c\"",
            'eval "$UNKNOWN_CODE"', 'bash -c "$UNKNOWN_CODE"',
            f"python3 -c \"import shutil; shutil.rmtree('{ws}/wiki/memories')\"",
            "python3 -c \"open('/somewhere/.link-cache/approvals.json', 'w').write('x')\"",
            f"node -e \"require('fs').rmSync('{ws}', {{recursive: true}})\"",
            "perl -e 'unlink glob q(~/link/wiki/memories/*)'",
            f"cp -t {ws}/wiki/memories /etc/hosts", f"mkdir {ws}/wiki/memories/new",
            f"tar -xf /tmp/x.tar -C {ws}/wiki/memories", f"curl -o {ws}/wiki/memories/a.md https://example.com",
            f"wget -O {ws}/.link-cache/approvals.json https://example.com",
            f"find {ws}/wiki/memories -name '*.md' -exec rm {{}} +", f"echo {ws}/wiki/memories/a.md | xargs rm",
            f"git -C {ws} clean -fdx", f"git -C {ws} rm -r wiki/memories", f"cd {ws} && git rm -r wiki",
            "rm -rf ~", "chmod -R 000 ~/link", "mv ~/link /tmp/gone", "cp -r /tmp/evil/link ~/",
            "rsync -a --delete /tmp/empty/ ~/",
        ]
        for command in held:
            self.assertTrue(self._held(command), command)

    def test_writes_beside_links_files_are_not_held(self):
        for command in ("cp notes.txt ~", "mv build.log ~/", "cp -r dist ~/", "chmod 700 ~", "mkdir ~/proj2",
                        "tar -xf x.tar -C ~", "rm -rf ~/tmp", "rm -rf dist", "find . -name '*.pyc' -delete",
                        "echo $HOME", "python3 -c 'print(1)'", "bash -c 'for f in *; do echo $f; done'",
                        "git rm -r --cached build", "curl -sSLo out.tgz https://example.com",
                        "cat files.txt | xargs rm", "cp -r dist ~/link"):
            self.assertFalse(self._held(command), command)


if __name__ == "__main__":
    unittest.main()
