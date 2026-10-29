import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.agent_hooks import (  # noqa: E402
    _is_link_hook_command,
    build_agent_hooks_payload,
    extract_transcript_text,
    hook_supported_agents,
    supports_agent_hooks,
)


def _transcript_line(role: str, content: object) -> str:
    return json.dumps({"type": role, "message": {"role": role, "content": content}})


class AgentHooksCoreTests(unittest.TestCase):
    def test_hook_supported_agents_include_hook_capable_agents(self):
        agents = hook_supported_agents()
        for agent in ("claude-code", "codex", "cursor", "gemini", "antigravity", "copilot", "windsurf"):
            self.assertIn(agent, agents)

    def test_supports_agent_hooks_accepts_aliases_and_rejects_others(self):
        self.assertTrue(supports_agent_hooks("claude-code"))
        self.assertTrue(supports_agent_hooks("claude"))
        self.assertTrue(supports_agent_hooks("codex"))
        self.assertTrue(supports_agent_hooks("cursor"))
        self.assertTrue(supports_agent_hooks("gemini-cli"))
        self.assertFalse(supports_agent_hooks("zed"))
        self.assertFalse(supports_agent_hooks("vscode"))

    def test_build_payload_rejects_unsupported_agent(self):
        with self.assertRaises(ValueError):
            build_agent_hooks_payload(
                target=Path("/tmp/link"),
                agent="zed",
                runtime_script=Path("/tmp/link/link.py"),
                python_cmd="python3",
            )

    def test_codex_gets_session_start_and_rule_checks(self):
        payload = build_agent_hooks_payload(
            target=Path("/tmp/link"),
            agent="codex",
            runtime_script=Path("/tmp/link/link.py"),
            python_cmd="python3",
        )

        self.assertIn("SessionStart", payload["events"])
        self.assertNotIn("SessionEnd", payload["events"])
        self.assertIn("hooks.json", str(payload["settings_path"]))
        self.assertIn(".codex", str(payload["settings_path"]))
        snippet = json.loads(str(payload["snippet"]))
        self.assertEqual(list(snippet["hooks"].keys()), ["SessionStart", "PreToolUse"])
        self.assertEqual(snippet["hooks"]["PreToolUse"][0]["matcher"], "Bash|apply_patch")
        self.assertIn("--emit codex", str(payload["events"]["PreToolUse"]))
        self.assertTrue(any("no session-end hook event" in item for item in payload["behavior"]))
        self.assertTrue(any("lnk approve" in item for item in payload["behavior"]), "Codex cannot ask")

    def test_every_agent_with_a_pre_tool_seam_gets_rule_checks(self):
        expected = {
            # agent: (settings file, events with their matchers, emit)
            "cursor": ("~/.cursor/hooks.json",
                       {"beforeShellExecution": None, "beforeReadFile": None, "preToolUse": "Write|Delete"}, "cursor"),
            "gemini": ("~/.gemini/settings.json",
                       {"BeforeTool": "run_shell_command|read_file|read_many_files|write_file|replace"}, "gemini"),
            "copilot": ("~/.copilot/hooks/link.json", {"preToolUse": "bash|powershell|view|create|edit"}, "copilot"),
            "windsurf": ("~/.codeium/windsurf/hooks.json",
                         {"pre_run_command": None, "pre_read_code": None, "pre_write_code": None}, "windsurf"),
        }
        for agent, (settings, events, emit) in expected.items():
            payload = build_agent_hooks_payload(target=Path("/tmp/link"), agent=agent,
                                                runtime_script=Path("/tmp/link/link.py"), python_cmd="python3")
            self.assertEqual(payload["settings_path"], str(Path(settings).expanduser()), agent)
            snippet = json.loads(str(payload["snippet"]))
            for event_name, matcher in events.items():
                self.assertIn(f"--emit {emit}", str(payload["events"][event_name]), (agent, event_name))
                entry = snippet["hooks"][event_name][0]
                found = entry.get("matcher") if "matcher" in entry else None
                self.assertEqual(found, matcher, (agent, event_name))

    def test_powershell_calls_are_checked_too(self):
        claude = json.loads(str(build_agent_hooks_payload(target=Path("/tmp/link"), agent="claude-code",
                                                          runtime_script=Path("/tmp/link/link.py"),
                                                          python_cmd="python3")["snippet"]))
        self.assertIn("PowerShell", claude["hooks"]["PreToolUse"][0]["matcher"].split("|"))
        copilot = json.loads(str(build_agent_hooks_payload(target=Path("/tmp/link"), agent="copilot",
                                                           runtime_script=Path("/tmp/link/link.py"),
                                                           python_cmd="python3")["snippet"]))
        self.assertIn("powershell", copilot["hooks"]["preToolUse"][0]["matcher"].split("|"))

    def test_disconnecting_antigravity_or_gemini_removes_both_hook_sets(self):
        from link_core.mcp_connect import build_disconnect_payload  # noqa: PLC0415

        for name in ("antigravity", "gemini"):
            with tempfile.TemporaryDirectory() as temp:
                home = Path(temp)
                old_home = dict(os.environ)
                os.environ.update(HOME=str(home), USERPROFILE=str(home))
                try:
                    build_agent_hooks_payload(target=home / "link", agent="antigravity",
                                              runtime_script=home / "link" / "link.py", python_cmd="python3",
                                              write=True)
                    result = build_disconnect_payload(agent=name, write=True)
                finally:
                    os.environ.clear()
                    os.environ.update(old_home)
                self.assertTrue(result["hooks"]["removed"], name)
                for settings in (home / ".gemini" / "settings.json", home / ".gemini" / "config" / "hooks.json"):
                    self.assertNotIn("hook pre-tool", settings.read_text(encoding="utf-8"), (name, settings))

    def test_gemini_counts_milliseconds_and_copilot_names_its_timeout(self):
        gemini = json.loads(str(build_agent_hooks_payload(
            target=Path("/tmp/link"), agent="gemini", runtime_script=Path("/tmp/link/link.py"),
            python_cmd="python3")["snippet"]))
        self.assertEqual(gemini["hooks"]["BeforeTool"][0]["hooks"][0]["timeout"], 10_000)
        copilot = json.loads(str(build_agent_hooks_payload(
            target=Path("/tmp/link"), agent="copilot", runtime_script=Path("/tmp/link/link.py"),
            python_cmd="python3")["snippet"]))
        entry = copilot["hooks"]["preToolUse"][0]
        self.assertEqual((copilot["version"], entry["type"], entry["timeoutSec"]), (1, "command", 10))
        windsurf = json.loads(str(build_agent_hooks_payload(
            target=Path("/tmp/link"), agent="windsurf", runtime_script=Path("/tmp/link/link.py"),
            python_cmd="python3")["snippet"]))
        self.assertNotIn("SessionStart", windsurf["hooks"], "Windsurf has no session-start event")
        self.assertNotIn("timeout", windsurf["hooks"]["pre_run_command"][0])

    def test_kiro_gets_a_v3_hooks_file_and_an_agent_profile_and_loses_both_on_disconnect(self):
        from link_core.mcp_connect import build_disconnect_payload  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            v3 = home / ".kiro" / "hooks" / "link.json"
            profile = home / ".kiro" / "agents" / "link.json"
            profile.parent.mkdir(parents=True)
            profile.write_text(json.dumps({"name": "link", "tools": ["@builtin"], "hooks": {
                "stop": [{"command": "say done"}]}}), encoding="utf-8")
            old_home = dict(os.environ)
            os.environ.update(HOME=str(home), USERPROFILE=str(home))
            try:
                for _ in range(2):  # a second connect replaces, never duplicates
                    payload = build_agent_hooks_payload(target=home / "link", agent="kiro",
                                                        runtime_script=home / "link" / "link.py",
                                                        python_cmd="python3", write=True)
                hooks = json.loads(v3.read_text(encoding="utf-8"))
                agent = json.loads(profile.read_text(encoding="utf-8"))
                result = build_disconnect_payload(agent="kiro", write=True)
                after = json.loads(profile.read_text(encoding="utf-8"))
            finally:
                os.environ.clear()
                os.environ.update(old_home)
        self.assertTrue(payload["write"]["ok"], payload["write"])
        self.assertEqual(hooks["version"], "v1")
        self.assertEqual([(h["trigger"], h.get("matcher")) for h in hooks["hooks"]],
                         [("SessionStart", None), ("PreToolUse", None)], "every tool, as in the profile")
        self.assertIn("--emit kiro", hooks["hooks"][1]["action"]["command"])
        self.assertEqual(hooks["hooks"][1]["timeout"], 10)
        self.assertEqual(agent["tools"], ["@builtin"], "a profile the person already has keeps its own settings")
        self.assertEqual(agent["hooks"]["stop"], [{"command": "say done"}])
        self.assertEqual(len(agent["hooks"]["agentSpawn"]), 1)
        self.assertEqual(agent["hooks"]["preToolUse"][0]["timeout_ms"], 10_000)
        self.assertNotIn("matcher", agent["hooks"]["preToolUse"][0], "every tool: Link decides what matters")
        self.assertIn("--emit kiro-agent", agent["hooks"]["preToolUse"][0]["command"], "told apart from V3's hook")
        self.assertTrue(result["hooks"]["removed"])
        self.assertFalse(v3.exists(), "Link's own hooks file goes when nothing else is in it")
        self.assertEqual(after["hooks"], {"stop": [{"command": "say done"}]})

    def test_a_profile_link_created_goes_on_disconnect_and_list_hooks_are_never_replaced(self):
        from link_core.agent_hooks import remove_link_hooks  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "link.json"
            kwargs = dict(target=Path("/tmp/link"), agent="kiro-agent", runtime_script=Path("/tmp/link/link.py"),
                          python_cmd="python3", settings_path=str(path))
            build_agent_hooks_payload(**kwargs, write=True)
            remove_link_hooks(path, "kiro-agent", write=True)
            self.assertFalse(path.exists(), "the profile Link made, with nothing of the person's in it")

            # A profile Kiro migrated to its list form: Link's entries come out, the person's stay.
            mine = {"name": "mine", "trigger": "Stop", "action": {"type": "command", "command": "say done"}}
            link = {"name": "Link", "trigger": "PreToolUse",
                    "action": {"type": "command", "command": "python3 /tmp/link/link.py hook pre-tool /tmp/link"}}
            path.write_text(json.dumps({"name": "link", "hooks": [mine, link]}), encoding="utf-8")
            result = build_agent_hooks_payload(**kwargs, write=True)
            self.assertFalse(result["write"]["ok"], "never replaces hooks it cannot read as its own kind")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["hooks"], [mine, link])
            self.assertEqual(remove_link_hooks(path, "kiro-agent", write=True)["found"], ["PreToolUse"])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["hooks"], [mine])
            path.write_text("{not json", encoding="utf-8")
            self.assertIn("not valid JSON", remove_link_hooks(path, "kiro-agent", write=True)["error"])

    def test_a_new_kiro_profile_has_every_tool_and_the_mcp_servers(self):
        snippet = json.loads(str(build_agent_hooks_payload(
            target=Path("/tmp/link"), agent="kiro-agent", runtime_script=Path("/tmp/link/link.py"),
            python_cmd="python3")["snippet"]))
        self.assertIn("agentSpawn", snippet["hooks"])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "link.json"
            build_agent_hooks_payload(target=Path("/tmp/link"), agent="kiro-agent",
                                      runtime_script=Path("/tmp/link/link.py"), python_cmd="python3",
                                      settings_path=str(path), write=True)
            profile = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual((profile["name"], profile["tools"], profile["includeMcpJson"]), ("link", ["*"], True))

    def test_antigravity_writes_its_own_file_and_gemini_clis(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            antigravity = home / ".gemini" / "config" / "hooks.json"
            antigravity.parent.mkdir(parents=True)
            antigravity.write_text(json.dumps({"mine": {"PreToolUse": []}}), encoding="utf-8")
            old_home = dict(os.environ)
            os.environ.update(HOME=str(home), USERPROFILE=str(home))
            try:
                payload = build_agent_hooks_payload(target=home / "link", agent="antigravity",
                                                    runtime_script=home / "link" / "link.py",
                                                    python_cmd="python3", write=True)
            finally:
                os.environ.clear()
                os.environ.update(old_home)
            self.assertTrue(payload["write"]["ok"], payload["write"])
            written = json.loads(antigravity.read_text(encoding="utf-8"))
            self.assertIn("mine", written, "another hook set in the same file is kept")
            self.assertEqual(written["link"]["PreToolUse"][0]["matcher"].split("|")[0], "run_command")
            self.assertIn("command", written["link"]["SessionStart"][0], "lifecycle events take handlers directly")
            self.assertEqual(written["link"]["SessionStart"][0]["type"], "command")
            [gemini] = payload["companions"]
            self.assertTrue(gemini["write"]["ok"], gemini["write"])
            self.assertIn("BeforeTool", json.loads((home / ".gemini" / "settings.json").read_text(encoding="utf-8"))["hooks"])

    def test_cursor_uses_flat_schema_and_cursor_emit(self):
        payload = build_agent_hooks_payload(
            target=Path("/tmp/link"),
            agent="cursor",
            runtime_script=Path("/tmp/link/link.py"),
            python_cmd="python3",
        )

        self.assertIn("--emit cursor", str(payload["events"]["sessionStart"]))
        self.assertNotIn("--emit", str(payload["events"]["sessionEnd"]))
        snippet = json.loads(str(payload["snippet"]))
        self.assertEqual(snippet["version"], 1)
        # Flat schema: entries directly in the event array, no matcher groups.
        self.assertIn("command", snippet["hooks"]["sessionStart"][0])
        self.assertNotIn("hooks", snippet["hooks"]["sessionStart"][0])

    def test_cursor_write_preserves_version_and_foreign_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = Path(temp) / "hooks.json"
            settings.write_text(
                json.dumps({
                    "version": 1,
                    "hooks": {
                        "sessionStart": [{"command": "./my-hook.sh"}],
                        "stop": [{"command": "./on-stop.sh"}],
                    },
                }),
                encoding="utf-8",
            )

            for _ in range(2):
                payload = build_agent_hooks_payload(
                    target=Path(temp),
                    agent="cursor",
                    runtime_script=Path(temp) / "link.py",
                    python_cmd="python3",
                    settings_path=str(settings),
                    write=True,
                )
                self.assertTrue(payload["write"]["ok"], payload["write"])

            data = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(data["version"], 1)
            self.assertEqual(data["hooks"]["stop"], [{"command": "./on-stop.sh"}])
            starts = data["hooks"]["sessionStart"]
            self.assertEqual(starts[0], {"command": "./my-hook.sh"})
            link_entries = [e for e in starts if "hook session-start" in e.get("command", "")]
            self.assertEqual(len(link_entries), 1)
            self.assertEqual(len(data["hooks"]["sessionEnd"]), 1)

    def test_tool_hooks_run_the_small_entry_point_when_it_is_installed(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            (runtime / "link.py").write_text("", encoding="utf-8")
            payload = build_agent_hooks_payload(target=runtime, agent="claude-code",
                                                runtime_script=runtime / "link.py", python_cmd="/usr/bin/python3")
            self.assertNotIn("link_hook.py", json.dumps(payload["events"]), "no small entry point, no change")
            (runtime / "link_hook.py").write_text("", encoding="utf-8")
            payload = build_agent_hooks_payload(target=runtime, agent="claude-code",
                                                runtime_script=runtime / "link.py", python_cmd="/usr/bin/python3")
            events = payload["events"]
            for name, event in (("PreToolUse", "pre-tool"), ("PostToolUse", "post-tool")):
                command = json.dumps(events[name])
                self.assertIn("link_hook.py", command)
                self.assertIn(f" hook {event} ", command)
                self.assertTrue(_is_link_hook_command(
                    f"/usr/bin/python3 {runtime / 'link_hook.py'} hook {event} {runtime}", event))
            self.assertNotIn("link_hook.py", json.dumps(events["SessionStart"]), "session hooks keep the CLI")

    def test_build_preview_includes_both_events_and_commands(self):
        payload = build_agent_hooks_payload(
            target=Path("/tmp/my link"),
            agent="claude-code",
            runtime_script=Path("/tmp/my link/link.py"),
            python_cmd="/usr/bin/python3",
        )

        self.assertEqual(payload["agent"], "claude-code")
        self.assertFalse(payload["write"]["ok"])
        events = payload["events"]
        self.assertIn(" hook session-start ", str(events["SessionStart"]))
        self.assertIn(" hook session-end ", str(events["SessionEnd"]))
        # Paths with spaces must stay shell-safe in the written command:
        # shlex single quotes on POSIX, list2cmdline double quotes on Windows.
        script = str(Path("/tmp/my link/link.py"))
        quoted = f'"{script}"' if os.name == "nt" else f"'{script}'"
        self.assertIn(quoted, str(events["SessionStart"]))
        snippet = json.loads(str(payload["snippet"]))
        self.assertIn("SessionStart", snippet["hooks"])
        self.assertIn("SessionEnd", snippet["hooks"])
        self.assertEqual(snippet["hooks"]["SessionStart"][0]["matcher"], "startup|clear|compact")

    def test_write_preserves_existing_settings_and_hooks(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = Path(temp) / "settings.json"
            settings.write_text(
                json.dumps({
                    "model": "opus",
                    "hooks": {
                        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "my-guard"}]}],
                        "SessionStart": [{"hooks": [{"type": "command", "command": "echo user-hook"}]}],
                    },
                }),
                encoding="utf-8",
            )

            payload = build_agent_hooks_payload(
                target=Path(temp),
                agent="claude-code",
                runtime_script=Path(temp) / "link.py",
                python_cmd="python3",
                settings_path=str(settings),
                write=True,
            )

            self.assertTrue(payload["write"]["ok"], payload["write"])
            data = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(data["model"], "opus")
            self.assertEqual(data["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "my-guard")
            self.assertEqual(data["hooks"]["SessionStart"][0]["hooks"][0]["command"], "echo user-hook")
            start_groups = data["hooks"]["SessionStart"]
            self.assertEqual(len(start_groups), 2)
            self.assertEqual(start_groups[1]["matcher"], "startup|clear|compact")
            self.assertEqual(len(data["hooks"]["SessionEnd"]), 1)

    def test_rewrite_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = Path(temp) / "settings.json"
            for _ in range(2):
                payload = build_agent_hooks_payload(
                    target=Path(temp),
                    agent="claude-code",
                    runtime_script=Path(temp) / "link.py",
                    python_cmd="python3",
                    settings_path=str(settings),
                    write=True,
                )
                self.assertTrue(payload["write"]["ok"], payload["write"])

            data = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(len(data["hooks"]["SessionStart"]), 1)
            self.assertEqual(len(data["hooks"]["SessionStart"][0]["hooks"]), 1)
            self.assertEqual(len(data["hooks"]["SessionEnd"]), 1)
            self.assertEqual(len(data["hooks"]["SessionEnd"][0]["hooks"]), 1)

    def test_write_refuses_non_object_settings_file(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = Path(temp) / "settings.json"
            settings.write_text("[]", encoding="utf-8")

            payload = build_agent_hooks_payload(
                target=Path(temp),
                agent="claude-code",
                runtime_script=Path(temp) / "link.py",
                python_cmd="python3",
                settings_path=str(settings),
                write=True,
            )

            self.assertFalse(payload["write"]["ok"])
            self.assertEqual(settings.read_text(encoding="utf-8"), "[]")

    def test_extract_transcript_keeps_text_and_skips_tool_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            transcript = Path(temp) / "transcript.jsonl"
            transcript.write_text(
                "\n".join([
                    _transcript_line("user", "We decided to use SQLite FTS."),
                    _transcript_line("assistant", [
                        {"type": "text", "text": "Noted the SQLite FTS decision."},
                        {"type": "tool_use", "id": "x", "name": "Bash", "input": {"command": "secret-tool-call"}},
                    ]),
                    _transcript_line("user", [
                        {"type": "tool_result", "tool_use_id": "x", "content": "tool output noise"},
                    ]),
                    json.dumps({"type": "summary", "summary": "meta line"}),
                    "not json at all",
                ]),
                encoding="utf-8",
            )

            text = extract_transcript_text(transcript)

        self.assertIn("User: We decided to use SQLite FTS.", text)
        self.assertIn("Assistant: Noted the SQLite FTS decision.", text)
        self.assertNotIn("secret-tool-call", text)
        self.assertNotIn("tool output noise", text)
        self.assertNotIn("meta line", text)

    def test_extract_transcript_bounds_output_to_most_recent_messages(self):
        with tempfile.TemporaryDirectory() as temp:
            transcript = Path(temp) / "transcript.jsonl"
            lines = [_transcript_line("user", f"message {index}: " + ("x" * 400)) for index in range(50)]
            transcript.write_text("\n".join(lines), encoding="utf-8")

            text = extract_transcript_text(transcript, max_chars=2000)

        self.assertLessEqual(len(text), 2200)
        self.assertIn("message 49", text)
        self.assertNotIn("message 0:", text)

    def test_keep_head_preserves_opening_turns_in_a_long_session(self):
        with tempfile.TemporaryDirectory() as temp:
            transcript = Path(temp) / "transcript.jsonl"
            lines = [_transcript_line("user", "OPENING RULE: only deploy through the release script.")]
            lines += [_transcript_line("user", f"filler step {i}: " + ("x" * 400)) for i in range(50)]
            transcript.write_text("\n".join(lines), encoding="utf-8")

            # Recency-only drops the opening; keep_head preserves it.
            recency = extract_transcript_text(transcript, max_chars=2000)
            headed = extract_transcript_text(transcript, max_chars=2000, keep_head=True)

        self.assertNotIn("OPENING RULE", recency)
        self.assertIn("OPENING RULE", headed)
        self.assertIn("filler step 49", headed)

    def test_extract_transcript_drops_link_injected_content(self):
        with tempfile.TemporaryDirectory() as temp:
            transcript = Path(temp) / "transcript.jsonl"
            transcript.write_text(
                "\n".join([
                    # The session-start hook's injected brief, echoed in context
                    _transcript_line("user", "Link memory (local, source-backed) · project demo\n"
                                             "Relevant memories\n- Prefer small commits (preference · user)"),
                    _transcript_line("assistant", "Link consolidation plan (read-only)\nPending captures: 3"),
                    _transcript_line("user", "We decided to adopt trunk-based development."),
                ]),
                encoding="utf-8",
            )

            text = extract_transcript_text(transcript)

        self.assertIn("trunk-based development", text)
        self.assertNotIn("Relevant memories", text)
        self.assertNotIn("Pending captures", text)
        self.assertNotIn("Prefer small commits", text)

    def test_extract_transcript_can_keep_user_turns_only(self):
        # Memory proposals must come from the user's words, not the assistant's
        # prose (which dogfooding showed gets mis-attributed as user preferences).
        with tempfile.TemporaryDirectory() as temp:
            transcript = Path(temp) / "transcript.jsonl"
            transcript.write_text(
                "\n".join([
                    _transcript_line("user", "ok go ahead"),
                    _transcript_line("assistant", [{"type": "text",
                        "text": "Tests pass on broken things; eyes don't. I prefer small commits."}]),
                    _transcript_line("user", "We decided to require signed commits on every branch."),
                ]),
                encoding="utf-8",
            )

            both = extract_transcript_text(transcript)
            user_only = extract_transcript_text(transcript, roles=("user",))

        self.assertIn("Tests pass on broken things", both)
        self.assertNotIn("Tests pass on broken things", user_only)
        self.assertNotIn("I prefer small commits", user_only)
        self.assertIn("signed commits", user_only)
        self.assertIn("ok go ahead", user_only)

    def test_extract_transcript_handles_missing_file(self):
        self.assertEqual(extract_transcript_text(Path("/nonexistent/transcript.jsonl")), "")



class ConnectRefreshTests(unittest.TestCase):
    def test_connect_refreshes_a_runtime_missing_the_hook_entry_point(self):
        import subprocess  # noqa: PLC0415

        root = Path(__file__).resolve().parents[1]
        link = [sys.executable, str(root / "link.py")]
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            home.mkdir()
            ws = Path(temp) / "ws"
            env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "LINK_USAGE": "off"}
            subprocess.run([*link, "init", str(ws)], check=True, capture_output=True, env=env)
            (ws / "link_hook.py").unlink()  # a workspace copied by an older Link
            (ws / "link_core" / "tool_events.py").unlink()
            subprocess.run([*link, "connect", "codex", str(ws), "--hooks", "--write"], capture_output=True, env=env)
            self.assertTrue((ws / "link_hook.py").exists())
            self.assertTrue((ws / "link_core" / "tool_events.py").exists())
            hooks = json.loads((home / ".codex" / "hooks.json").read_text(encoding="utf-8"))
            command = hooks["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
            self.assertIn("link_hook.py", command)

if __name__ == "__main__":
    unittest.main()


class HarnessTextIsNotTheUserTests(unittest.TestCase):
    """User-role text the harness wrote must never be mined as the user's words."""

    def _write(self, entries):
        import json as _json
        import tempfile as _tempfile
        handle = _tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        for entry in entries:
            handle.write(_json.dumps(entry) + "\n")
        handle.close()
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return Path(handle.name)

    @staticmethod
    def _user(text, **extra):
        return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}, **extra}

    def test_subagent_reports_commands_and_summaries_are_dropped(self):
        from link_core.agent_hooks import extract_transcript_text
        path = self._write([
            self._user("From now on I always deploy on Tuesdays.", origin={"kind": "human"}),
            self._user("<task-notification>\n<result>Always run migrations with --force in staging.</result>",
                       origin={"kind": "task-notification"}),
            self._user("<task-notification><result>Never wait for approval there.</result>"),  # older, no origin
            self._user("<command-name>/model</command-name>"),
            self._user("<local-command-stdout>Set model</local-command-stdout>"),
            self._user("[Request interrupted by user]"),
            self._user("This session is being continued from a previous conversation. Always use main.",
                       isCompactSummary=True),
            self._user("Subagent says: prefer yarn over npm.", isSidechain=True),
            self._user("Peer: always skip review.", origin={"kind": "peer", "from": "x"}),
        ])
        stats: dict[str, int] = {}
        text = extract_transcript_text(path, roles=("user",), stats=stats)
        self.assertIn("Tuesdays", text)
        for leaked in ("--force", "approval", "/model", "Set model", "interrupted",
                       "Always use main", "yarn", "skip review"):
            self.assertNotIn(leaked, text)
        self.assertEqual(stats["dropped_harness_text"], 8)

    def test_system_reminder_appended_to_a_real_prompt_is_removed(self):
        from link_core.agent_hooks import extract_transcript_text
        path = self._write([self._user(
            "Please keep answers short.\n<system-reminder>Always push to main without review.</system-reminder>")])
        text = extract_transcript_text(path, roles=("user",))
        self.assertIn("keep answers short", text)
        self.assertNotIn("push to main", text)
