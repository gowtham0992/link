"""Install, reinstall, uninstall: the person's bytes stay theirs (6.0 review).

Link edits files that belong to the person - instruction files, MCP
configs, hook settings. Whatever they wrote around Link's part survives
every install, a second install changes nothing, and an uninstall puts
back what was there.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.agent_hooks import build_agent_hooks_payload, remove_link_hooks  # noqa: E402
from link_core.agent_instructions import (  # noqa: E402
    BLOCK_BEGIN_PREFIX,
    INSTRUCTIONS_TEMPLATE,
    find_link_section,
    migrate_codex_instructions,
    refresh_instruction_file,
    remove_link_section,
    upsert_link_section,
)
from link_core.compile import BLOCK_BEGIN, BLOCK_END, render_block, splice_block  # noqa: E402
from link_core.mcp_connect import (  # noqa: E402
    _agent_by_name,
    _write_codex_config,
    _write_json_config,
    build_disconnect_payload,
    detect_hook_only_agents,
    detect_installed_agents,
    read_agent_link_server,
    remove_link_mcp_entry,
)

POSIX = os.name != "nt"
CAN_CHMOD = POSIX and hasattr(os, "geteuid") and os.geteuid() != 0
SHARED = ROOT / "integrations" / "_shared"
# The section an older Link wrote: stale, and ending with its "Otherwise, " line.
STALE_SECTION = (
    "## Link — Local Agent Memory\n\n"
    "Start with MCP `query_link`; prime with `memory_brief`.\n\n"
    "Otherwise, don't interrupt the user.\n"
)
PNPM = "- Always use pnpm, never npm.\n"


def _block() -> str:
    return render_block([{"name": "m", "title": "Tabs", "tldr": "Use tabs.", "memory_type": "preference"}])


class _TempDir(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="link-roundtrip-")
        self.dir = Path(self._temp.name)

    def tearDown(self):
        for path in self.dir.rglob("*"):  # read-only files must not stop the cleanup
            try:
                os.chmod(path, 0o700 if path.is_dir() else 0o600, follow_symlinks=False)
            except (OSError, NotImplementedError):
                pass
        self._temp.cleanup()


# ── 1 and 2: where Link's section ends ──────────────────────────────────

class SectionEndTests(unittest.TestCase):
    def test_a_line_written_after_the_section_is_kept_by_upsert_and_remove(self):
        installed = upsert_link_section("# Mine\n\nhello\n")
        text = installed + "\n" + PNPM
        self.assertEqual(upsert_link_section(text), text, "the current section is already in place")
        self.assertEqual(remove_link_section(text), "# Mine\n\nhello\n\n" + PNPM)
        stale = "# Mine\n\n" + STALE_SECTION + PNPM
        updated = upsert_link_section(stale)
        self.assertTrue(updated.endswith(INSTRUCTIONS_TEMPLATE.rstrip() + "\n" + PNPM), updated[-300:])
        self.assertEqual(upsert_link_section(updated), updated)

    def test_the_compile_block_after_the_section_survives_reinstall_and_remove(self):
        installed = upsert_link_section("# Project\n\nmine\n")
        with_block = splice_block(installed, _block())
        again = upsert_link_section(with_block)
        self.assertEqual(again, with_block, "installing again changes nothing")
        self.assertEqual((again.count(BLOCK_BEGIN), again.count(BLOCK_END)), (1, 1))
        self.assertEqual(splice_block(again, _block()), again, "lnk compile still finds its block")
        stale = splice_block("# Project\n\n" + STALE_SECTION.replace("Otherwise, don't interrupt the user.\n", ""),
                             _block())
        refreshed = upsert_link_section(stale)
        self.assertEqual((refreshed.count(BLOCK_BEGIN), refreshed.count(BLOCK_END)), (1, 1))
        self.assertNotIn("query_link", refreshed)
        removed = remove_link_section(with_block)
        self.assertIsNone(find_link_section(removed))
        self.assertEqual(removed, "# Project\n\nmine\n\n" + _block())

    def test_a_setext_heading_ends_a_section_that_has_no_last_line(self):
        legacy = "## Link — Local Agent Memory\n\nOld text.\n\nMy notes\n========\n\nkeep me\n"
        updated = upsert_link_section(legacy)
        self.assertTrue(updated.endswith("\n\nMy notes\n========\n\nkeep me\n"), updated[-80:])
        self.assertNotIn("Old text.", updated)

    def test_the_block_marker_link_stops_at_is_the_one_compile_writes(self):
        self.assertTrue(BLOCK_BEGIN.startswith(BLOCK_BEGIN_PREFIX))

    def test_the_bash_and_powershell_helpers_use_the_same_ends(self):
        shell = (SHARED / "instructions.sh").read_text(encoding="utf-8")
        powershell = (SHARED / "instructions.ps1").read_text(encoding="utf-8")
        for helper in (shell, powershell):
            self.assertIn("Otherwise, ", helper)
            self.assertIn(BLOCK_BEGIN_PREFIX, helper)
            self.assertIn("(?:=+|-+)", helper)
        self.assertIn("GetUnresolvedProviderPathFromPSPath", powershell)
        self.assertNotIn("[System.IO.Path]::GetFullPath", powershell)


class InstructionFileTests(_TempDir):
    def test_refresh_keeps_a_line_after_the_section(self):
        path = self.dir / ".claude" / "CLAUDE.md"
        path.parent.mkdir()
        path.write_text("# My rules\n\n" + STALE_SECTION + "- Never push to main without asking.\n", encoding="utf-8")
        self.assertTrue(refresh_instruction_file("claude-code", home=self.dir)["refreshed"])
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("\n- Never push to main without asking.\n"), text[-200:])
        self.assertNotIn("query_link", text)

    def test_moving_codex_instructions_keeps_the_persons_lines(self):
        old = self.dir / "AGENTS.md"
        old.write_text("# Home\n\n" + STALE_SECTION + PNPM, encoding="utf-8")
        (self.dir / ".claude").mkdir()
        (self.dir / ".claude" / "CLAUDE.md").write_text(INSTRUCTIONS_TEMPLATE, encoding="utf-8")
        saved = os.environ.pop("CODEX_HOME", None)
        try:
            self.assertTrue(migrate_codex_instructions(self.dir)["moved"])
        finally:
            if saved is not None:
                os.environ["CODEX_HOME"] = saved
        self.assertEqual(old.read_text(encoding="utf-8"), "# Home\n\n" + PNPM)

    @unittest.skipUnless(POSIX, "symlinks")
    def test_a_symlinked_file_stays_a_link_and_its_target_changes(self):
        real = self.dir / "dotfiles" / "CLAUDE.md"
        real.parent.mkdir()
        real.write_text("# Mine\n\n" + STALE_SECTION, encoding="utf-8")
        os.chmod(real, 0o640)
        link = self.dir / ".claude" / "CLAUDE.md"
        link.parent.mkdir()
        link.symlink_to(real)
        self.assertTrue(refresh_instruction_file("claude-code", home=self.dir)["refreshed"])
        self.assertTrue(link.is_symlink())
        self.assertNotIn("query_link", real.read_text(encoding="utf-8"))
        self.assertEqual(stat.S_IMODE(real.stat().st_mode), 0o640)

    @unittest.skipUnless(CAN_CHMOD, "file permissions")
    def test_a_read_only_file_is_refused_not_replaced(self):
        path = self.dir / ".claude" / "CLAUDE.md"
        path.parent.mkdir()
        path.write_text(STALE_SECTION, encoding="utf-8")
        os.chmod(path, 0o444)
        result = refresh_instruction_file("claude-code", home=self.dir)
        self.assertFalse(result["refreshed"])
        self.assertIn("read-only", str(result["error"]))
        self.assertEqual(path.read_text(encoding="utf-8"), STALE_SECTION)


@unittest.skipUnless(POSIX and shutil.which("bash"), "bash helper")
class BashHelperTests(_TempDir):
    """integrations/_shared/instructions.sh, run as the installers run it."""

    def setUp(self):
        super().setUp()
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        (self.bin / "python3").symlink_to(sys.executable)
        self.source = SHARED / "link-instructions.md"

    def _run(self, function: str, *args: str) -> subprocess.CompletedProcess:
        script = f'. "{SHARED}/instructions.sh"; {function} "$@"'
        env = {**os.environ, "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}"}
        return subprocess.run(["bash", "-c", script, "bash", *args], capture_output=True, text=True, env=env,
                              cwd=self.dir, check=False)

    def test_upsert_and_remove_keep_what_the_person_wrote_after_the_section(self):
        for start in ("", "# Mine\n\nhello\n", "# Mine\r\n\r\nhello\r\n"):
            path = self.dir / "AGENTS.md"
            path.write_bytes(start.encode("utf-8"))
            self.assertEqual(self._run("link_upsert_instructions", str(path), str(self.source), "x").returncode, 0)
            newline = "\r\n" if "\r\n" in start else "\n"
            with_mine = path.read_bytes().decode("utf-8") + newline + PNPM.replace("\n", newline)
            path.write_bytes(with_mine.encode("utf-8"))
            self._run("link_upsert_instructions", str(path), str(self.source), "x")
            self.assertEqual(path.read_bytes().decode("utf-8"), with_mine, "installing twice")
            self.assertEqual(upsert_link_section(with_mine), with_mine, "the same answer as link_core")
            self._run("link_remove_instructions", str(path))
            left = path.read_bytes().decode("utf-8")
            self.assertIsNone(find_link_section(left))
            self.assertTrue(left.endswith(PNPM.replace("\n", newline)), repr(left))
            self.assertTrue(left.startswith(start.rstrip("\r\n")), repr(left))

    def test_reinstalling_keeps_the_compile_block(self):
        path = self.dir / "CLAUDE.md"
        project = SHARED / "link-instructions-project.md"
        path.write_text("# Project\n", encoding="utf-8")
        self._run("link_upsert_instructions", str(path), str(project), "x")
        with_block = splice_block(path.read_text(encoding="utf-8"), _block())
        path.write_text(with_block, encoding="utf-8")
        self._run("link_upsert_instructions", str(path), str(project), "x")
        self.assertEqual(path.read_text(encoding="utf-8"), with_block)
        self._run("link_remove_instructions", str(path))
        self.assertEqual(path.read_text(encoding="utf-8"), "# Project\n\n" + _block())

    def test_a_symlink_is_written_through_and_a_read_only_file_refused(self):
        real = self.dir / "dotfiles.md"
        real.write_text("# Mine\n", encoding="utf-8")
        link = self.dir / "CLAUDE.md"
        link.symlink_to(real)
        self._run("link_upsert_instructions", str(link), str(self.source), "x")
        self.assertTrue(link.is_symlink())
        self.assertIsNotNone(find_link_section(real.read_text(encoding="utf-8")))
        if CAN_CHMOD:
            locked = self.dir / "locked.md"
            locked.write_text("# Mine\n", encoding="utf-8")
            os.chmod(locked, 0o444)
            run = self._run("link_upsert_instructions", str(locked), str(self.source), "x")
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("read-only", run.stdout + run.stderr)
            self.assertEqual(locked.read_text(encoding="utf-8"), "# Mine\n")


# ── 3: a project uninstall leaves the global config alone ───────────────

@unittest.skipUnless(POSIX and shutil.which("bash"), "bash installers")
class ProjectUninstallTests(_TempDir):
    def setUp(self):
        super().setUp()
        self.home = self.dir / "home"
        self.project = self.dir / "project"
        self.home.mkdir()
        self.project.mkdir()
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        (self.bin / "python3").symlink_to(sys.executable)
        self.claude_json = self.home / ".claude.json"
        self.claude_json.write_text(json.dumps({"mcpServers": {"link": {"command": "python3", "args": []}}}),
                                    encoding="utf-8")
        settings = self.home / ".claude" / "settings.json"
        settings.parent.mkdir()
        settings.write_text("{}\n", encoding="utf-8")
        build_agent_hooks_payload(target=self.home / "link", agent="claude-code",
                                  runtime_script=self.home / "link" / "link.py", python_cmd="python3",
                                  settings_path=str(settings), write=True)
        self.settings = settings

    def _uninstall(self, agent: str, *args: str) -> None:
        env = {**os.environ, "HOME": str(self.home), "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}"}
        env.pop("CODEX_HOME", None)
        run = subprocess.run(["bash", str(ROOT / "integrations" / agent / "uninstall.sh"), *args],
                             cwd=self.project, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_project_uninstall_keeps_the_global_mcp_entry_and_hooks(self):
        claude_md = self.project / "CLAUDE.md"
        claude_md.write_text("# Project\n\n" + INSTRUCTIONS_TEMPLATE, encoding="utf-8")
        hooks_before = self.settings.read_text(encoding="utf-8")
        self._uninstall("claude-code", "--project")
        self.assertIn("link", json.loads(self.claude_json.read_text(encoding="utf-8"))["mcpServers"])
        self.assertEqual(self.settings.read_text(encoding="utf-8"), hooks_before)
        self.assertEqual(claude_md.read_text(encoding="utf-8"), "# Project\n")
        self._uninstall("claude-code")
        self.assertNotIn("link", json.loads(self.claude_json.read_text(encoding="utf-8"))["mcpServers"])
        self.assertNotIn("hook session-start", self.settings.read_text(encoding="utf-8"))

    def test_every_uninstaller_disconnects_only_in_global_mode(self):
        for script in sorted((ROOT / "integrations").glob("*/uninstall.sh")):
            text = script.read_text(encoding="utf-8")
            agent = script.parent.name
            if agent == "vscode":  # VS Code's only Link config is the project's .vscode/mcp.json
                continue
            disconnect = next(line for line in text.splitlines() if "link_cli disconnect" in line)
            if agent == "copilot":
                self.assertIn("$HOOKS_FLAG", disconnect)
                self.assertIn('if [ "$MODE" != "--global" ]; then HOOKS_FLAG="--no-hooks"; fi', text)
            else:
                guarded = text.split('if [ "$MODE" = "--global" ]; then', 1)[1].split("\nfi", 1)[0]
                self.assertIn(disconnect.strip(), guarded, agent)

    def test_disconnect_without_hooks_leaves_them(self):
        self.claude_json.write_text(json.dumps({"mcpServers": {"link": {"command": "python3"}}}), encoding="utf-8")
        before = self.settings.read_text(encoding="utf-8")
        result = build_disconnect_payload("claude-code", config_path=str(self.claude_json),
                                          hooks_settings=str(self.settings), hooks=False, write=True)
        self.assertTrue(result["mcp"]["removed"])
        self.assertEqual(self.settings.read_text(encoding="utf-8"), before)


# ── 4: Codex's config.toml ───────────────────────────────────────────────

CODEX = (
    'model = "o3"\n\n'
    "[mcp_servers.link]\n"
    'command = "/usr/bin/python3"\n'
    'args = ["-m", "link_mcp", "--wiki", "/old/wiki", "--surface", "slim"]\n'
    "startup_timeout_sec = 60  # mine\n\n"
    "# GitHub MCP, token comes from env -- do not remove\n"
    "[mcp_servers.github]\n"
    'command = "gh-mcp"\n'
)


# Link writes the wiki path as the platform spells it, escaped for a TOML string.
WIKI = str(Path("/x/wiki"))


class CodexConfigTests(_TempDir):
    def setUp(self):
        super().setUp()
        self.path = self.dir / "config.toml"

    def _connect(self, wiki: str = "/x/wiki") -> None:
        _write_codex_config(self.path, "/opt/py", Path(wiki))

    def test_reconnect_changes_only_links_command_and_args(self):
        self.path.write_text(CODEX, encoding="utf-8")
        self._connect()
        self.assertEqual(self.path.read_text(encoding="utf-8"), CODEX.replace(
            'command = "/usr/bin/python3"', 'command = "/opt/py"').replace("/old/wiki", json.dumps(WIKI)[1:-1]))
        once = self.path.read_bytes()
        self._connect()
        self.assertEqual(self.path.read_bytes(), once)

    def test_disconnect_keeps_the_next_tables_comment(self):
        self.path.write_text(CODEX, encoding="utf-8")
        remove_link_mcp_entry(self.path, _agent_by_name("codex"), write=True)
        self.assertEqual(self.path.read_text(encoding="utf-8"),
                         'model = "o3"\n\n# GitHub MCP, token comes from env -- do not remove\n'
                         '[mcp_servers.github]\ncommand = "gh-mcp"\n')

    def test_install_then_uninstall_gives_back_the_same_bytes(self):
        for original in ('model = "o3"\n', 'model = "o3"', "", '[profiles.x]\nmodel = "o3"\n\n'):
            self.path.write_text(original, encoding="utf-8")
            self._connect()
            remove_link_mcp_entry(self.path, _agent_by_name("codex"), write=True)
            self.assertEqual(self.path.read_text(encoding="utf-8").rstrip(), original.rstrip(), repr(original))

    @unittest.skipIf(sys.version_info < (3, 11), "tomllib arrived in Python 3.11")
    def test_quoted_and_indented_headers_are_updated_in_place(self):
        import tomllib
        for header in ('[mcp_servers."link"]', "  [mcp_servers.link]", "[ mcp_servers . link ]  # Link"):
            self.path.write_text(f'{header}\n  command = "a"\n', encoding="utf-8")
            self._connect()
            parsed = tomllib.loads(self.path.read_text(encoding="utf-8"))
            self.assertEqual(parsed["mcp_servers"]["link"]["command"], "/opt/py", header)
            self.assertIn(header, self.path.read_text(encoding="utf-8"))
            server = read_agent_link_server("codex", str(self.path))
            self.assertEqual((server["python"], server["wiki"]), ("/opt/py", WIKI), header)

    @unittest.skipIf(sys.version_info < (3, 11), "without tomllib (3.10) only the table-level check runs")
    def test_forms_link_cannot_edit_and_broken_files_are_refused_unchanged(self):
        for original in ('[mcp_servers]\nlink = { command = "a" }\n', 'mcp_servers.link.command = "a"\n',
                         "[mcp_servers.link\ncommand = \n"):
            self.path.write_text(original, encoding="utf-8")
            with self.assertRaises(ValueError):
                self._connect()
            self.assertEqual(self.path.read_text(encoding="utf-8"), original)
        self.path.write_text('[mcp_servers]\nlink = { command = "a" }\n', encoding="utf-8")
        with self.assertRaises(ValueError):
            remove_link_mcp_entry(self.path, _agent_by_name("codex"), write=True)


# ── 5 and 6: hook settings files ────────────────────────────────────────

def _install(agent: str, path: Path) -> dict:
    return build_agent_hooks_payload(target=Path("/home/x/link"), agent=agent,
                                     runtime_script=Path("/opt/link/link.py"), python_cmd="python3",
                                     settings_path=str(path), write=True)["write"]


class HookFileTests(_TempDir):
    def test_install_keeps_indent_characters_and_mode_and_uninstall_puts_it_back(self):
        path = self.dir / "settings.json"
        original = '{\n    "model": "opus",\n    "env": {\n        "NAME": "Zoë"\n    }\n}\n'
        path.write_text(original, encoding="utf-8")
        os.chmod(path, 0o644)
        self.assertTrue(_install("claude-code", path)["ok"])
        installed = path.read_text(encoding="utf-8")
        self.assertIn('\n    "hooks": {', installed)
        self.assertIn("Zoë", installed)
        self.assertTrue(_install("claude-code", path)["ok"])
        self.assertEqual(path.read_text(encoding="utf-8"), installed, "installing twice")
        remove_link_hooks(path, "claude-code", write=True)
        self.assertEqual(path.read_text(encoding="utf-8"), original)
        if POSIX:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)

    def test_bytes_that_are_not_utf8_are_refused_and_a_bom_and_crlf_kept(self):
        path = self.dir / "hooks.json"
        latin1 = b'{"env": {"GREETING": "caf\xe9"}}\n'
        path.write_bytes(latin1)
        result = _install("cursor", path)
        self.assertFalse(result["ok"])
        self.assertIn("not UTF-8", result["message"])
        self.assertEqual(path.read_bytes(), latin1)
        self.assertIn("not UTF-8", str(remove_link_hooks(path, "cursor", write=True)["error"]))
        path.write_bytes(b'\xef\xbb\xbf{\r\n  "model": "x"\r\n}\r\n')
        self.assertTrue(_install("claude-code", path)["ok"])
        data = path.read_bytes()
        self.assertTrue(data.startswith(b"\xef\xbb\xbf{\r\n"))
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))
        remove_link_hooks(path, "claude-code", write=True)
        self.assertEqual(path.read_bytes(), b'\xef\xbb\xbf{\r\n  "model": "x"\r\n}\r\n')

    def test_files_link_created_are_gone_after_uninstall(self):
        for agent in ("copilot", "cursor", "windsurf", "codex", "kiro", "antigravity"):
            path = self.dir / f"{agent}.json"
            self.assertTrue(_install(agent, path)["ok"], agent)
            remove_link_hooks(path, agent, write=True)
            self.assertFalse(path.exists(), agent)
        # The person's own file stays, without the empty key Link added.
        path = self.dir / "cursor-mine.json"
        path.write_text('{\n  "version": 1,\n  "hooks": {\n    "stop": [{"command": "say done"}]\n  }\n}\n',
                        encoding="utf-8")
        before = path.read_text(encoding="utf-8")
        _install("cursor", path)
        remove_link_hooks(path, "cursor", write=True)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), json.loads(before))
        # Claude Code's settings.json is its whole settings file: emptied, never deleted.
        settings = self.dir / "claude.json"
        _install("claude-code", settings)
        remove_link_hooks(settings, "claude-code", write=True)
        self.assertEqual(json.loads(settings.read_text(encoding="utf-8")), {})

    @unittest.skipUnless(POSIX, "symlinks")
    def test_a_symlinked_settings_file_stays_a_link(self):
        real = self.dir / "dotfiles" / "settings.json"
        real.parent.mkdir()
        real.write_text('{"model": "x"}\n', encoding="utf-8")
        link = self.dir / "settings.json"
        link.symlink_to(real)
        self.assertTrue(_install("claude-code", link)["ok"])
        self.assertTrue(link.is_symlink())
        self.assertIn("hooks", real.read_text(encoding="utf-8"))
        remove_link_hooks(link, "claude-code", write=True)
        self.assertTrue(link.is_symlink())
        self.assertEqual(json.loads(real.read_text(encoding="utf-8")), {"model": "x"})

    @unittest.skipUnless(CAN_CHMOD, "file permissions")
    def test_a_read_only_settings_file_is_refused(self):
        path = self.dir / "settings.json"
        path.write_text('{"model": "x"}\n', encoding="utf-8")
        os.chmod(path, 0o444)
        result = _install("claude-code", path)
        self.assertFalse(result["ok"])
        self.assertIn("read-only", result["message"])
        self.assertEqual(path.read_text(encoding="utf-8"), '{"model": "x"}\n')

    def test_mcp_json_configs_refuse_bytes_that_are_not_utf8(self):
        path = self.dir / "mcp.json"
        latin1 = b'{"note": "caf\xe9", "mcpServers": {}}\n'
        path.write_bytes(latin1)
        with self.assertRaises(ValueError):
            _write_json_config(path, _agent_by_name("cursor"), "python3", Path("/x/wiki"))
        self.assertEqual(path.read_bytes(), latin1)


# ── 9: Zed ───────────────────────────────────────────────────────────────

class ZedRoundTripTests(unittest.TestCase):
    def test_removing_links_permissions_takes_the_agent_setting_link_created(self):
        from link_core.zed_permissions import splice

        permissions = {"tools": {"terminal": {"always_deny": [{"pattern": "^rm$"}]}}}
        for original in ('// my zed\n{\n  "theme": "One Dark", // dark\n}\n', "{}", '{"a": 1}',
                         '{\n  "agent": {},\n  "theme": "a"\n}\n', '{"theme":"a","agent":{"enabled":true}}'):
            written = splice(original, permissions)
            self.assertEqual(splice(written, permissions), written)
            self.assertEqual(splice(written, {}), original)


# ── 10: Copilot in lnk setup ─────────────────────────────────────────────

class CopilotDetectionTests(_TempDir):
    def test_a_copilot_home_is_detected_for_session_hooks_only(self):
        self.assertEqual(detect_hook_only_agents(self.dir), [])
        (self.dir / ".copilot" / "hooks").mkdir(parents=True)
        self.assertEqual(detect_hook_only_agents(self.dir), ["copilot"])
        # Its MCP config is the project's .vscode/mcp.json: setup does not write that.
        self.assertNotIn("copilot", detect_installed_agents(self.dir))

    def test_setup_wires_copilot_hooks(self):
        source = (ROOT / "link.py").read_text(encoding="utf-8")
        setup = source[source.index("def setup("):source.index("def onboard(")]
        self.assertIn("_core_detect_hook_only_agents()", setup)
        self.assertIn("_core_build_agent_hooks_payload(", setup)


if __name__ == "__main__":
    unittest.main()
