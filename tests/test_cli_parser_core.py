import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.cli_parser import build_cli_parser, dispatch_cli_command  # noqa: E402


class CliParserCoreTests(unittest.TestCase):
    def test_demo_uses_custom_default_directory(self):
        parser = build_cli_parser(default_demo_dir="custom-demo")

        args = parser.parse_args(["demo"])

        self.assertEqual(args.command, "demo")
        self.assertEqual(args.target, "custom-demo")
        self.assertFalse(args.force)

    def test_query_alias_and_budget_options(self):
        parser = build_cli_parser()

        args = parser.parse_args(["query-link", "agent memory", "/tmp/link", "--budget", "small", "--json"])

        self.assertEqual(args.command, "query-link")
        self.assertEqual(args.query, "agent memory")
        self.assertEqual(args.target, "/tmp/link")
        self.assertEqual(args.budget, "small")
        self.assertTrue(args.json)

    def test_try_command_options(self):
        parser = build_cli_parser(default_demo_dir="custom-demo")

        args = parser.parse_args(["try", "--force", "--serve", "--port", "3456", "--json"])

        self.assertEqual(args.command, "try")
        self.assertEqual(args.target, "custom-demo")
        self.assertTrue(args.force)
        self.assertTrue(args.serve)
        self.assertEqual(args.port, 3456)
        self.assertTrue(args.json)

    def test_proof_command_options(self):
        parser = build_cli_parser()

        args = parser.parse_args(["proof", "/tmp/proof", "--force", "--serve", "--port", "3456", "--json"])

        self.assertEqual(args.command, "proof")
        self.assertEqual(args.target, "/tmp/proof")
        self.assertTrue(args.force)
        self.assertTrue(args.serve)
        self.assertEqual(args.port, 3456)
        self.assertTrue(args.json)

    def test_onboard_command_options(self):
        parser = build_cli_parser()

        args = parser.parse_args([
            "onboard",
            "/tmp/link",
            "--agent",
            "codex",
            "--agent",
            "cursor",
            "--write",
            "--first-memory",
            "I prefer concise updates",
            "--project",
            "link",
            "--port",
            "3456",
            "--json",
        ])

        self.assertEqual(args.command, "onboard")
        self.assertEqual(args.target, "/tmp/link")
        self.assertEqual(args.agent, ["codex", "cursor"])
        self.assertTrue(args.write)
        self.assertEqual(args.first_memory, "I prefer concise updates")
        self.assertEqual(args.project, "link")
        self.assertEqual(args.port, 3456)
        self.assertTrue(args.json)

    def test_operations_limit_and_json_options(self):
        parser = build_cli_parser()

        args = parser.parse_args([
            "operations",
            "/tmp/link",
            "--limit",
            "5",
            "--recover",
            "remember-1.json",
            "--confirm",
            "--json",
        ])

        self.assertEqual(args.command, "operations")
        self.assertEqual(args.target, "/tmp/link")
        self.assertEqual(args.limit, 5)
        self.assertEqual(args.recover, "remember-1.json")
        self.assertTrue(args.confirm)
        self.assertTrue(args.json)

    def test_health_json_option(self):
        parser = build_cli_parser()

        args = parser.parse_args(["health", "/tmp/link", "--json"])

        self.assertEqual(args.command, "health")
        self.assertEqual(args.target, "/tmp/link")
        self.assertTrue(args.json)

    def test_start_command_options(self):
        parser = build_cli_parser()

        args = parser.parse_args([
            "start",
            "/tmp/link",
            "--task",
            "release work",
            "--limit",
            "4",
            "--project",
            "link",
            "--json",
        ])

        self.assertEqual(args.command, "start")
        self.assertEqual(args.target, "/tmp/link")
        self.assertEqual(args.task, "release work")
        self.assertEqual(args.limit, 4)
        self.assertEqual(args.project, "link")
        self.assertTrue(args.json)

    def test_session_end_command_options(self):
        parser = build_cli_parser()

        args = parser.parse_args([
            "session-end",
            "session-notes.md",
            "/tmp/link",
            "--title",
            "Release session",
            "--limit",
            "2",
            "--project",
            "link",
            "--json",
        ])

        self.assertEqual(args.command, "session-end")
        self.assertEqual(args.source_input, "session-notes.md")
        self.assertEqual(args.target, "/tmp/link")
        self.assertEqual(args.title, "Release session")
        self.assertEqual(args.limit, 2)
        self.assertEqual(args.project, "link")
        self.assertTrue(args.json)

        alias = parser.parse_args(["end", "notes.md", "/tmp/link"])
        self.assertEqual(alias.command, "end")
        self.assertEqual(alias.source_input, "notes.md")

    def test_connect_command_options(self):
        parser = build_cli_parser()

        args = parser.parse_args([
            "connect",
            "codex",
            "/tmp/link",
            "--write",
            "--config",
            "/tmp/config.toml",
            "--python",
            "/tmp/python",
            "--json",
        ])

        self.assertEqual(args.command, "connect")
        self.assertEqual(args.agent, "codex")
        self.assertEqual(args.target, "/tmp/link")
        self.assertTrue(args.write)
        self.assertEqual(args.config, "/tmp/config.toml")
        self.assertEqual(args.python, "/tmp/python")
        self.assertTrue(args.json)

    def test_share_command_options(self):
        parser = build_cli_parser()

        args = parser.parse_args([
            "share",
            "Prefer local memory",
            "/tmp/link",
            "--port",
            "3456",
            "--host",
            "localhost",
            "--json",
        ])

        self.assertEqual(args.command, "share")
        self.assertEqual(args.identifier, "Prefer local memory")
        self.assertEqual(args.target, "/tmp/link")
        self.assertEqual(args.port, 3456)
        self.assertEqual(args.host, "localhost")
        self.assertTrue(args.json)

    def test_snapshot_command_options(self):
        parser = build_cli_parser()

        args = parser.parse_args([
            "snapshot",
            "/tmp/link",
            "--output",
            "/tmp/link-snapshot",
            "--include-memories",
            "--include-private-memories",
            "--allow-sensitive",
            "--force",
            "--title",
            "Team Link",
            "--json",
        ])

        self.assertEqual(args.command, "snapshot")
        self.assertEqual(args.target, "/tmp/link")
        self.assertEqual(args.output, "/tmp/link-snapshot")
        self.assertTrue(args.include_memories)
        self.assertTrue(args.include_private_memories)
        self.assertTrue(args.allow_sensitive)
        self.assertTrue(args.force)
        self.assertEqual(args.title, "Team Link")
        self.assertTrue(args.json)

    def test_memory_log_command_options(self):
        parser = build_cli_parser()

        args = parser.parse_args(["memory-log", "/tmp/link", "--limit", "7", "--no-captures", "--json"])

        self.assertEqual(args.command, "memory-log")
        self.assertEqual(args.target, "/tmp/link")
        self.assertEqual(args.limit, 7)
        self.assertTrue(args.no_captures)
        self.assertTrue(args.json)

    def test_wins_command_options(self):
        parser = build_cli_parser()

        args = parser.parse_args(["wins", "/tmp/link", "--limit", "4", "--project", "alpha", "--json"])

        self.assertEqual(args.command, "wins")
        self.assertEqual(args.target, "/tmp/link")
        self.assertEqual(args.limit, 4)
        self.assertEqual(args.project, "alpha")
        self.assertTrue(args.json)

    def test_import_obsidian_command_options(self):
        parser = build_cli_parser()

        args = parser.parse_args([
            "import-obsidian",
            "/tmp/vault",
            "/tmp/link",
            "--overwrite",
            "--dry-run",
            "--limit",
            "12",
            "--json",
        ])

        self.assertEqual(args.command, "import-obsidian")
        self.assertEqual(args.vault, "/tmp/vault")
        self.assertEqual(args.target, "/tmp/link")
        self.assertTrue(args.overwrite)
        self.assertTrue(args.dry_run)
        self.assertEqual(args.limit, 12)
        self.assertTrue(args.json)

    def test_compliance_export_command_options(self):
        parser = build_cli_parser()

        args = parser.parse_args([
            "compliance-export",
            "/tmp/link",
            "--output",
            "/tmp/audit.json",
            "--project",
            "alpha",
            "--limit",
            "25",
            "--json",
        ])

        self.assertEqual(args.command, "compliance-export")
        self.assertEqual(args.target, "/tmp/link")
        self.assertEqual(args.output, "/tmp/audit.json")
        self.assertEqual(args.project, "alpha")
        self.assertEqual(args.limit, 25)
        self.assertTrue(args.json)

    def test_restore_backup_command_options(self):
        parser = build_cli_parser()

        args = parser.parse_args([
            "restore-backup",
            "backup.tar.gz",
            "/tmp/link",
            "--include-raw",
            "--confirm",
            "--no-safety-backup",
            "--json",
        ])

        self.assertEqual(args.command, "restore-backup")
        self.assertEqual(args.backup, "backup.tar.gz")
        self.assertEqual(args.target, "/tmp/link")
        self.assertTrue(args.include_raw)
        self.assertTrue(args.confirm)
        self.assertTrue(args.no_safety_backup)
        self.assertTrue(args.json)

    def test_team_sync_command_options(self):
        parser = build_cli_parser()

        args = parser.parse_args([
            "team-sync",
            "/tmp/link",
            "--remote",
            "git@example.com:team/link-memory.git",
            "--json",
        ])

        self.assertEqual(args.command, "team-sync")
        self.assertEqual(args.target, "/tmp/link")
        self.assertEqual(args.remote, "git@example.com:team/link-memory.git")
        self.assertTrue(args.json)

    def test_version_command_routes_to_handler(self):
        parser = build_cli_parser()

        args = parser.parse_args(["version"])
        code = dispatch_cli_command(args, {"version": lambda: 42})

        self.assertEqual(args.command, "version")
        self.assertEqual(code, 42)

    def test_dispatch_routes_team_sync_arguments(self):
        parser = build_cli_parser()
        calls = []

        args = parser.parse_args(["team-sync", "/tmp/link", "--remote", "git@example.com:team/link.git", "--json"])
        code = dispatch_cli_command(
            args,
            {"team-sync": lambda *args, **kwargs: calls.append((args, kwargs)) or 0},
        )

        self.assertEqual(code, 0)
        self.assertEqual(calls[0][0][0], Path("/tmp/link"))
        self.assertEqual(calls[0][1]["remote"], "git@example.com:team/link.git")
        self.assertTrue(calls[0][1]["json_output"])

    def test_welcome_project_and_json_options(self):
        parser = build_cli_parser()

        args = parser.parse_args(["welcome", "/tmp/link", "--project", "Client Launch", "--json"])

        self.assertEqual(args.command, "welcome")
        self.assertEqual(args.target, "/tmp/link")
        self.assertEqual(args.project, "Client Launch")
        self.assertTrue(args.json)

    def test_next_alias_routes_to_prompts(self):
        parser = build_cli_parser()

        args = parser.parse_args(["next", "/tmp/link", "--project", "Client Launch", "--json"])

        self.assertEqual(args.command, "next")
        self.assertEqual(args.target, "/tmp/link")
        self.assertEqual(args.project, "Client Launch")
        self.assertTrue(args.json)

    def test_memory_choices_are_enforced(self):
        parser = build_cli_parser()

        args = parser.parse_args([
            "remember",
            "prefers concise answers",
            "--type",
            "preference",
            "--scope",
            "user",
            "--visibility",
            "private",
            "--review-after",
            "2026-06-01",
            "--expires-at",
            "2026-07-01",
        ])

        self.assertEqual(args.memory_type, "preference")
        self.assertEqual(args.scope, "user")
        self.assertEqual(args.visibility, "private")
        self.assertEqual(args.review_after, "2026-06-01")
        self.assertEqual(args.expires_at, "2026-07-01")
        with self.assertRaises(SystemExit):
            parser.parse_args(["remember", "bad", "--type", "unsupported"])

    def test_dispatch_routes_query_alias_to_query_handler(self):
        parser = build_cli_parser()
        args = parser.parse_args(["query-link", "agent memory", "/tmp/link", "--budget", "small", "--json"])
        calls = []

        def query_handler(target, query, **kwargs):
            calls.append((target, query, kwargs))
            return 7

        code = dispatch_cli_command(args, {"query": query_handler})

        self.assertEqual(code, 7)
        self.assertEqual(calls[0][0], Path("/tmp/link"))
        self.assertEqual(calls[0][1], "agent memory")
        self.assertEqual(calls[0][2]["budget"], "small")
        self.assertTrue(calls[0][2]["json_output"])

    def test_dispatch_routes_start_to_start_handler(self):
        parser = build_cli_parser()
        args = parser.parse_args([
            "start",
            "/tmp/link",
            "--task",
            "release work",
            "--limit",
            "4",
            "--project",
            "link",
            "--json",
        ])
        calls = []

        def start_handler(target, **kwargs):
            calls.append((target, kwargs))
            return 8

        code = dispatch_cli_command(args, {"start": start_handler})

        self.assertEqual(code, 8)
        self.assertEqual(calls[0][0], Path("/tmp/link"))
        self.assertEqual(calls[0][1]["task"], "release work")
        self.assertEqual(calls[0][1]["limit"], 4)
        self.assertEqual(calls[0][1]["project"], "link")
        self.assertTrue(calls[0][1]["json_output"])

    def test_dispatch_routes_session_end_to_session_end_handler(self):
        parser = build_cli_parser()
        args = parser.parse_args([
            "session-end",
            "session-notes.md",
            "/tmp/link",
            "--title",
            "Release session",
            "--limit",
            "2",
            "--project",
            "link",
            "--json",
        ])
        calls = []

        def session_end_handler(target, source_input, **kwargs):
            calls.append((target, source_input, kwargs))
            return 9

        code = dispatch_cli_command(args, {"session-end": session_end_handler})

        self.assertEqual(code, 9)
        self.assertEqual(calls[0][0], Path("/tmp/link"))
        self.assertEqual(calls[0][1], "session-notes.md")
        self.assertEqual(calls[0][2]["title"], "Release session")
        self.assertEqual(calls[0][2]["limit"], 2)
        self.assertEqual(calls[0][2]["project"], "link")
        self.assertTrue(calls[0][2]["json_output"])

    def test_dispatch_routes_try_arguments(self):
        parser = build_cli_parser()
        args = parser.parse_args(["try", "/tmp/link-demo", "--force", "--serve", "--port", "3456", "--json"])
        calls = []

        def try_handler(target, **kwargs):
            calls.append((target, kwargs))
            return 5

        code = dispatch_cli_command(args, {"try": try_handler})

        self.assertEqual(code, 5)
        self.assertEqual(calls[0][0], Path("/tmp/link-demo"))
        self.assertTrue(calls[0][1]["force"])
        self.assertTrue(calls[0][1]["serve"])
        self.assertEqual(calls[0][1]["port"], 3456)
        self.assertTrue(calls[0][1]["json_output"])

    def test_dispatch_routes_proof_arguments(self):
        parser = build_cli_parser()
        args = parser.parse_args(["proof", "/tmp/proof", "--force", "--serve", "--port", "3456", "--json"])
        calls = []

        def proof_handler(target, **kwargs):
            calls.append((target, kwargs))
            return 9

        code = dispatch_cli_command(args, {"proof": proof_handler})

        self.assertEqual(code, 9)
        self.assertEqual(calls[0][0], Path("/tmp/proof"))
        self.assertTrue(calls[0][1]["force"])
        self.assertTrue(calls[0][1]["serve"])
        self.assertEqual(calls[0][1]["port"], 3456)
        self.assertTrue(calls[0][1]["json_output"])

    def test_dispatch_routes_onboard_arguments(self):
        parser = build_cli_parser()
        args = parser.parse_args([
            "onboard",
            "/tmp/link",
            "--agent",
            "codex",
            "--all-agents",
            "--write",
            "--first-memory",
            "I prefer concise updates",
            "--project",
            "alpha",
            "--port",
            "3456",
            "--json",
        ])
        calls = []

        def onboard_handler(target, **kwargs):
            calls.append((target, kwargs))
            return 2

        code = dispatch_cli_command(args, {"onboard": onboard_handler})

        self.assertEqual(code, 2)
        self.assertEqual(calls[0][0], Path("/tmp/link"))
        self.assertEqual(calls[0][1]["agents"], ["codex"])
        self.assertTrue(calls[0][1]["all_agents"])
        self.assertTrue(calls[0][1]["write"])
        self.assertEqual(calls[0][1]["first_memory"], "I prefer concise updates")
        self.assertEqual(calls[0][1]["project"], "alpha")
        self.assertEqual(calls[0][1]["port"], 3456)
        self.assertTrue(calls[0][1]["json_output"])

    def test_dispatch_routes_operations_arguments(self):
        parser = build_cli_parser()
        args = parser.parse_args(["operations", "/tmp/link", "--limit", "5", "--recover", "remember-1.json", "--confirm", "--json"])
        calls = []

        def operations_handler(target, **kwargs):
            calls.append((target, kwargs))
            return 9

        code = dispatch_cli_command(args, {"operations": operations_handler})

        self.assertEqual(code, 9)
        self.assertEqual(calls[0][0], Path("/tmp/link"))
        self.assertEqual(calls[0][1]["limit"], 5)
        self.assertEqual(calls[0][1]["recover"], "remember-1.json")
        self.assertTrue(calls[0][1]["confirm"])
        self.assertTrue(calls[0][1]["json_output"])

    def test_dispatch_routes_health_arguments(self):
        parser = build_cli_parser()
        args = parser.parse_args(["health", "/tmp/link", "--json"])
        calls = []

        def health_handler(target, **kwargs):
            calls.append((target, kwargs))
            return 6

        code = dispatch_cli_command(args, {"health": health_handler})

        self.assertEqual(code, 6)
        self.assertEqual(calls[0][0], Path("/tmp/link"))
        self.assertTrue(calls[0][1]["json_output"])

    def test_dispatch_routes_connect_arguments(self):
        parser = build_cli_parser()
        args = parser.parse_args([
            "connect",
            "kiro",
            "/tmp/link",
            "--write",
            "--config",
            "/tmp/mcp.json",
            "--python",
            "/tmp/python",
            "--json",
        ])
        calls = []

        def connect_handler(target, agent, **kwargs):
            calls.append((target, agent, kwargs))
            return 4

        code = dispatch_cli_command(args, {"connect": connect_handler})

        self.assertEqual(code, 4)
        self.assertEqual(calls[0][0], Path("/tmp/link"))
        self.assertEqual(calls[0][1], "kiro")
        self.assertTrue(calls[0][2]["write"])
        self.assertEqual(calls[0][2]["config_path"], "/tmp/mcp.json")
        self.assertEqual(calls[0][2]["python_cmd"], "/tmp/python")
        self.assertTrue(calls[0][2]["json_output"])

    def test_dispatch_routes_share_arguments(self):
        parser = build_cli_parser()
        args = parser.parse_args(["share", "Prefer local memory", "/tmp/link", "--port", "3456", "--host", "localhost", "--json"])
        calls = []

        def share_handler(target, identifier, **kwargs):
            calls.append((target, identifier, kwargs))
            return 9

        code = dispatch_cli_command(args, {"share": share_handler})

        self.assertEqual(code, 9)
        self.assertEqual(calls[0][0], Path("/tmp/link"))
        self.assertEqual(calls[0][1], "Prefer local memory")
        self.assertEqual(calls[0][2]["port"], 3456)
        self.assertEqual(calls[0][2]["host"], "localhost")
        self.assertTrue(calls[0][2]["json_output"])

    def test_dispatch_routes_snapshot_arguments(self):
        parser = build_cli_parser()
        args = parser.parse_args([
            "snapshot",
            "/tmp/link",
            "--output",
            "/tmp/snapshot",
            "--include-memories",
            "--include-private-memories",
            "--allow-sensitive",
            "--force",
            "--title",
            "Team Link",
            "--json",
        ])
        calls = []

        def snapshot_handler(target, **kwargs):
            calls.append((target, kwargs))
            return 3

        code = dispatch_cli_command(args, {"snapshot": snapshot_handler})

        self.assertEqual(code, 3)
        self.assertEqual(calls[0][0], Path("/tmp/link"))
        self.assertEqual(calls[0][1]["output"], "/tmp/snapshot")
        self.assertTrue(calls[0][1]["include_memories"])
        self.assertTrue(calls[0][1]["include_private_memories"])
        self.assertTrue(calls[0][1]["allow_sensitive"])
        self.assertTrue(calls[0][1]["force"])
        self.assertEqual(calls[0][1]["title"], "Team Link")
        self.assertTrue(calls[0][1]["json_output"])

    def test_dispatch_routes_import_obsidian_arguments(self):
        parser = build_cli_parser()
        args = parser.parse_args([
            "import-obsidian",
            "/tmp/vault",
            "/tmp/link",
            "--overwrite",
            "--dry-run",
            "--limit",
            "3",
            "--json",
        ])
        calls = []

        def import_obsidian_handler(target, vault, **kwargs):
            calls.append((target, vault, kwargs))
            return 5

        code = dispatch_cli_command(args, {"import-obsidian": import_obsidian_handler})

        self.assertEqual(code, 5)
        self.assertEqual(calls[0][0], Path("/tmp/link"))
        self.assertEqual(calls[0][1], Path("/tmp/vault"))
        self.assertTrue(calls[0][2]["overwrite"])
        self.assertTrue(calls[0][2]["dry_run"])
        self.assertEqual(calls[0][2]["limit"], 3)
        self.assertTrue(calls[0][2]["json_output"])

    def test_dispatch_routes_compliance_export_arguments(self):
        parser = build_cli_parser()
        args = parser.parse_args([
            "compliance-export",
            "/tmp/link",
            "--output",
            "/tmp/audit.json",
            "--project",
            "alpha",
            "--limit",
            "25",
            "--json",
        ])
        calls = []

        def compliance_handler(target, **kwargs):
            calls.append((target, kwargs))
            return 6

        code = dispatch_cli_command(args, {"compliance-export": compliance_handler})

        self.assertEqual(code, 6)
        self.assertEqual(calls[0][0], Path("/tmp/link"))
        self.assertEqual(calls[0][1]["output"], "/tmp/audit.json")
        self.assertEqual(calls[0][1]["project"], "alpha")
        self.assertEqual(calls[0][1]["limit"], 25)
        self.assertTrue(calls[0][1]["json_output"])

    def test_dispatch_routes_welcome_arguments(self):
        parser = build_cli_parser()
        args = parser.parse_args(["welcome", "/tmp/link", "--project", "alpha", "--json"])
        calls = []

        def welcome_handler(target, **kwargs):
            calls.append((target, kwargs))
            return 8

        code = dispatch_cli_command(args, {"welcome": welcome_handler})

        self.assertEqual(code, 8)
        self.assertEqual(calls[0][0], Path("/tmp/link"))
        self.assertEqual(calls[0][1]["project"], "alpha")
        self.assertTrue(calls[0][1]["json_output"])

    def test_dispatch_routes_next_alias_to_prompts_handler(self):
        parser = build_cli_parser()
        args = parser.parse_args(["next", "/tmp/link", "--project", "alpha", "--json"])
        calls = []

        def prompts_handler(target, **kwargs):
            calls.append((target, kwargs))
            return 6

        code = dispatch_cli_command(args, {"prompts": prompts_handler})

        self.assertEqual(code, 6)
        self.assertEqual(calls[0][0], Path("/tmp/link"))
        self.assertEqual(calls[0][1]["project"], "alpha")
        self.assertTrue(calls[0][1]["json_output"])

    def test_dispatch_routes_set_memory_visibility_arguments(self):
        parser = build_cli_parser()
        args = parser.parse_args([
            "set-memory-visibility",
            "prefer-local-memory",
            "team",
            "/tmp/link",
            "--json",
        ])
        calls = []

        def visibility_handler(target, identifier, visibility, **kwargs):
            calls.append((target, identifier, visibility, kwargs))
            return 4

        code = dispatch_cli_command(args, {"set-memory-visibility": visibility_handler})

        self.assertEqual(code, 4)
        self.assertEqual(calls[0][0], Path("/tmp/link"))
        self.assertEqual(calls[0][1], "prefer-local-memory")
        self.assertEqual(calls[0][2], "team")
        self.assertTrue(calls[0][3]["json_output"])

    def test_dispatch_routes_accept_capture_arguments(self):
        parser = build_cli_parser()
        args = parser.parse_args([
            "accept-capture",
            "raw/memory-captures/session.md",
            "/tmp/link",
            "--index",
            "2",
            "--type",
            "decision",
            "--scope",
            "project",
            "--visibility",
            "team",
            "--project",
            "alpha",
            "--allow-conflict",
            "--json",
        ])
        calls = []

        def accept_handler(target, capture, **kwargs):
            calls.append((target, capture, kwargs))
            return 3

        code = dispatch_cli_command(args, {"accept-capture": accept_handler})

        self.assertEqual(code, 3)
        self.assertEqual(calls[0][0], Path("/tmp/link"))
        self.assertEqual(calls[0][1], "raw/memory-captures/session.md")
        self.assertEqual(calls[0][2]["index"], 2)
        self.assertEqual(calls[0][2]["memory_type"], "decision")
        self.assertEqual(calls[0][2]["scope"], "project")
        self.assertEqual(calls[0][2]["visibility"], "team")
        self.assertEqual(calls[0][2]["project"], "alpha")
        self.assertTrue(calls[0][2]["allow_conflict"])
        self.assertTrue(calls[0][2]["json_output"])


if __name__ == "__main__":
    unittest.main()
