"""The bash reader: what a command line runs and writes, however it is spelt (the 6.0 review's bypasses)."""
import os
import shlex
import sys
import tempfile
import time
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

    def test_options_in_any_order_or_bundled_meet_the_rule(self):
        cases = {
            "git push -u --force origin feat": "git push --force -u origin feat",
            "git push --no-verify --force": "git push --force --no-verify",
            "git push -uf origin feature": "git push -f -u origin feature",
            "git push -u origin main": "git push origin main -u",
            "git push --set-upstream origin main": "git push origin main --set-upstream",
            "git push -o ci.skip origin main": "git push origin main -o ci.skip",
            "rm -fr build": "rm -rf build",
            "rm -r -f build": "rm -rf build",
            "rm -Rf build": "rm -rf build",
            "rm --recursive --force build": "rm -rf build",
            "rm -v -r -f build": "rm -rfv build",
            "git.exe push -f": "git push -f",
            "npm.cmd publish": "npm publish",
            "GIT.EXE push -f": "git push -f",
        }
        for command, plain in cases.items():
            forms = [" ".join(form) for form in command_forms(command.split())]
            self.assertIn(plain, forms, command)
        # A value stays with its option, and --force-with-lease is not --force.
        forms = [" ".join(form) for form in command_forms("git push -o main origin feat".split())]
        self.assertNotIn("git push origin main", " ".join(forms))
        forms = [" ".join(form) for form in command_forms("git push -u --force-with-lease origin x".split())]
        self.assertFalse(any(form.startswith("git push --force ") for form in forms), forms)

    def test_programs_named_with_a_windows_extension(self):
        self.assertIn("git push -f", _commands("git.exe push -f"))
        self.assertIn("/w", read_shell("git.exe -C /w clean -fdx").trees)

    def test_a_function_body_is_read(self):
        self.assertIn("git push -f", _commands("function gp { git push -f; }; gp"))
        self.assertIn("git push -f", _commands("function gp() { git push -f; }; gp"))

    def test_too_deep_to_read_is_opaque_not_empty(self):
        command = "git push -f"
        for _ in range(4):
            command = f"bash -c {shlex.quote(command)}"
        self.assertFalse(read_shell(command).opaque, "four deep is read")
        self.assertIn("git push -f", _commands(command))
        self.assertTrue(read_shell(f"bash -c {shlex.quote(command)}").opaque, "five deep is not, and says so")
        self.assertTrue(read_shell("$($($($($(git push -f)))))").opaque)
        self.assertTrue(read_shell("find a b -exec find a b -exec find a b -exec rm {} \\; \\; \\;").opaque)
        self.assertFalse(read_shell("find . -name x -exec grep -l y {} \\;").opaque)

    def test_lines_built_to_be_slow_are_read_quickly(self):
        cases = [
            "git push -f; echo $env:X " + "$(" * 95 + "true" + ")" * 95,
            "git push -f; find . " + "-exec find . " * 40 + "\\;",
            "rm " + "{a,b}/" * 5000,
            "rm " + " ".join(f"a{i}" for i in range(12000)),
            "echo " + "a" * 99_000,
            "rm " + "a " * 100_000,
        ]
        for command in cases:
            started = time.perf_counter()
            reading = read_shell(command)
            self.assertLess(time.perf_counter() - started, 3.0, command[:40])
            if len(command) > 100_000 or "{a,b}" in command:
                self.assertTrue(reading.opaque, command[:40])
        self.assertTrue(read_shell("rm a", deadline=time.monotonic() - 1).opaque, "out of time is unreadable")

    def test_in_place_editors_write_their_files(self):
        cases = {
            "sed -Ei 's/a/b/' /w/m/a.md": ["/w/m/a.md"],
            "sed -E -i 's/a/b/' /w/m/a.md": ["/w/m/a.md"],
            "sed --in-place 's/a/b/' /w/m/a.md": ["/w/m/a.md"],
            "sed --in-place=.bak --expression=s/a/b/ /w/m/a.md": ["/w/m/a.md"],
            "perl -0pi -e 's/a/b/' /w/m/a.md": ["/w/m/a.md"],
            "perl -0777pi -e 's/a/b/' /w/m/a.md": ["/w/m/a.md"],
            "gawk -i inplace '{print}' /w/m/a.md": ["/w/m/a.md"],
            "awk --include=inplace '{print}' /w/m/a.md": ["/w/m/a.md"],
            "patch /w/m/a.md < fix.diff": ["/w/m/a.md"],
            "patch -p1 -o /w/m/a.md < fix.diff": ["/w/m/a.md"],
            "sort -o /w/m/a.md x": ["/w/m/a.md"],
        }
        for command, writes in cases.items():
            self.assertEqual([w for w in read_shell(command).writes if w in writes], writes, command)
        self.assertEqual(read_shell("patch -p1 < fix.diff").trees, ["."], "whatever the diff names, from here")
        for command in ("sed -n 's/a/b/p' /w/m/a.md", "sed -E 's/i/x/' /w/m/a.md", "perl -Mlib=x -e 'p' /w/m/a.md",
                        "perl -e 'print 1' /w/m/a.md", "awk '{print}' /w/m/a.md", "sort /w/m/a.md"):
            self.assertEqual(read_shell(command).writes, [], command)

    def test_what_an_archive_or_a_copy_of_contents_lands_on_is_a_tree(self):
        cases = {
            "tar xzf b.tgz -C /w": ["/w"],
            "cd /w && tar xzf /tmp/b.tgz": ["/w/."],
            "bsdtar -xf b.tar -C /w": ["/w"],
            "unzip -o b.zip -d /w": ["/w"],
            "unzip b.zip": ["."],
            "ditto /tmp/wiki /w/wiki": ["/w/wiki"],
            "cpio -idm -D /w": ["/w"],
            "cpio -pdm /w": ["/w"],
            "pax -r -f a.pax": ["."],
            "rsync -a /tmp/backup/ /w/": ["/w/"],
            "cp -r /tmp/backup/wiki/ /w/wiki": ["/w/wiki"],
            "cp -R /tmp/backup/. /w/": ["/w/"],
        }
        for command, trees in cases.items():
            self.assertEqual([t for t in read_shell(command).trees if t in trees], trees, command)
        for command in ("unzip -l b.zip", "tar tzf b.tgz", "tar czf b.tgz src", "cp -r dist /w/x", "rsync a b"):
            self.assertNotIn("/w", read_shell(command).trees, command)
            self.assertNotIn(".", read_shell(command).trees, command)

    def test_git_commands_that_rewrite_the_work_tree(self):
        for command in ("git -C /w stash", "git -C /w stash pop", "git -C /w reset --hard HEAD~1", "git -C /w pull",
                        "git -C /w merge x", "git -C /w rebase main", "git -C /w checkout .", "git -C /w checkout main",
                        "git -C /w switch main", "git -C /w restore .", "git -C /w cherry-pick abc",
                        "git -C /w apply fix.diff"):
            self.assertTrue(any(tree in {"/w", "/w/."} for tree in read_shell(command).trees), command)
        for command in ("git -C /w stash list", "git -C /w status", "git -C /w reset HEAD x", "git -C /w log",
                        "git -C /w checkout -b new", "git -C /w switch -c new", "git -C /w apply --check fix.diff",
                        "git -C /w commit -m x", "git -C /w add -A", "git -C /w fetch"):
            self.assertEqual(read_shell(command).trees, [], command)

    def test_xargs_gives_a_command_arguments_it_cannot_see(self):
        self.assertIn(["lnk", "approve", SUBSTITUTED], read_shell("echo abc | xargs lnk approve").commands)
        self.assertIn(["lnk", "approve", SUBSTITUTED], read_shell("xargs lnk approve < ids").commands)


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
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home),  # ~ on Windows
                                                  "LINK_TEST_ROOT": str(self.ws)})
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
                        "tar -xf x.tar -C ~/proj", "rm -rf ~/tmp", "rm -rf dist", "find . -name '*.pyc' -delete",
                        "echo $HOME", "python3 -c 'print(1)'", "bash -c 'for f in *; do echo $f; done'",
                        "git rm -r --cached build", "curl -sSLo out.tgz https://example.com",
                        "cat files.txt | xargs rm", "cp -r dist ~/link"):
            self.assertFalse(self._held(command), command)

    def test_an_unreadable_command_can_be_let_through_once_and_links_files_cannot(self):
        def decide(command):
            return evaluate_tool_call(self.index, {"tool_name": "Bash", "tool_input": {"command": command}},
                                      context_path=str(self.home / "proj"),
                                      protected=[self.ws / "wiki" / "memories", self.ws / ".link-cache"])
        for command in ('eval "$(ssh-agent -s)"', 'bash -c "$UNKNOWN_CODE"'):
            decision = decide(command)
            self.assertEqual((decision["decision"], decision["approvable"], decision["governance"]),
                             ("ask", True, False), command)
        for command in (f"rm -rf {self.ws.as_posix()}/wiki/memories", 'eval "$X"; rm -rf ~/link/.link-cache'):
            decision = decide(command)
            self.assertEqual((decision["approvable"], decision["governance"]), (False, True), command)

    def test_archives_copies_and_git_above_links_files_are_held(self):
        memory = "~/link/wiki/memories/a.md"
        held = [
            "tar xzf b.tgz -C ~", "tar xzf b.tgz -C ~/link", "cd ~/link && tar xzf /tmp/b.tgz",
            "unzip -o b.zip -d ~/link", "ditto /tmp/wiki ~/link/wiki", "cpio -idm -D ~/link",
            "rsync -a /tmp/backup/ ~/link/", "cp -r /tmp/backup/wiki/ ~/link/wiki", "cd ~/link && git checkout .",
            "git -C ~/link reset --hard HEAD~1", "git -C ~/link stash", "git -C ~/link pull",
            f"sed -Ei 's/deny/ask/' {memory}", f"sed --in-place 's/deny/ask/' {memory}",
            f"perl -0pi -e 's/deny/ask/' {memory}", f"gawk -i inplace '{{print}}' {memory}",
            f"patch {memory} < fix.diff", f"sort -o {memory} x", "function f { rm -rf ~/link; }; f",
            # A path the reader cannot expand never lets the rest of the line through.
            "cat ~x/y; rm -rf ~/link", "cp a ~-/; rm -rf ~/link", "echo hi > ~+/x; rm -rf ~/link",
        ]
        for command in held:
            self.assertTrue(self._held(command), command)

    def test_everyday_git_archives_and_edits_in_a_project_are_not_held(self):
        for command in ("git stash", "git stash pop", "git pull", "git reset --hard", "git checkout main",
                        "git merge feature", "git rebase main", "tar xzf release.tgz", "unzip x.zip",
                        "patch -p1 < x.diff", "sed -i 's/a/b/' src/app.py", "cp -r assets/ public/",
                        "rsync -a src/ build/", "cd ~/link && git status", "git -C ~/link log",
                        "cd ~/link && git add -A && git commit -m wip", "cat ~nobody/x", "ls ~+/x"):
            self.assertFalse(self._held(command), command)

    def test_what_may_be_links_files_can_be_let_through_once_and_what_is_cannot(self):
        def decide(command):
            return evaluate_tool_call(self.index, {"tool_name": "Bash", "tool_input": {"command": command}},
                                      context_path=str(self.home / "proj"),
                                      protected=[self.ws / "wiki" / "memories", self.ws / ".link-cache"])
        # Code that names Link's files, or a path through a variable Link cannot know, may be nothing.
        for command in ("python3 -c \"import json; print(json.load(open('/x/link/.link-cache/hook-index.json')))\"",
                        "node -e \"console.log(require('fs').readdirSync(process.env.HOME + '/link/wiki/memories'))\"",
                        'cp notes.md "$PROJ/wiki/memories/"', "rm -r $BUILD/wiki"):
            decision = decide(command)
            self.assertEqual((decision["decision"], decision["approvable"], decision["governance"]),
                             ("ask", True, False), command)
        for command in ("rm -r ~/link/wiki", "git -C ~/link stash", f"sed -Ei s/a/b/ {self.ws.as_posix()}/wiki/memories/a.md",
                        "rm -r $BUILD/wiki; rm -r ~/link/.link-cache", "lnk approve abc123",
                        "echo abc123 | xargs lnk approve", "lnk enforce x --rule 'ask command: y'"):
            decision = decide(command)
            self.assertEqual((decision["approvable"], decision["governance"]), (False, True), command)
        # Listing what waits, or showing rules, changes nothing.
        for command in ("lnk approve", "lnk approve --json", "lnk enforce x --suggest", "python3 link.py approve"):
            self.assertIsNone(decide(command), command)


if __name__ == "__main__":
    unittest.main()
