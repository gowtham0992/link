import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.agent_hooks import (  # noqa: E402
    build_agent_hooks_payload,
    extract_transcript_text,
    hook_supported_agents,
    supports_agent_hooks,
)


def _transcript_line(role: str, content: object) -> str:
    return json.dumps({"type": role, "message": {"role": role, "content": content}})


class AgentHooksCoreTests(unittest.TestCase):
    def test_hook_supported_agents_include_claude_code(self):
        self.assertIn("claude-code", hook_supported_agents())

    def test_supports_agent_hooks_accepts_aliases_and_rejects_others(self):
        self.assertTrue(supports_agent_hooks("claude-code"))
        self.assertTrue(supports_agent_hooks("claude"))
        self.assertFalse(supports_agent_hooks("codex"))
        self.assertFalse(supports_agent_hooks("cursor"))

    def test_build_payload_rejects_unsupported_agent(self):
        with self.assertRaises(ValueError):
            build_agent_hooks_payload(
                target=Path("/tmp/link"),
                agent="codex",
                runtime_script=Path("/tmp/link/link.py"),
                python_cmd="python3",
            )

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
        # Paths with spaces must stay shell-safe in the written command.
        self.assertIn("'/tmp/my link/link.py'", str(events["SessionStart"]))
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

    def test_extract_transcript_handles_missing_file(self):
        self.assertEqual(extract_transcript_text(Path("/nonexistent/transcript.jsonl")), "")


if __name__ == "__main__":
    unittest.main()
