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

    def test_operations_limit_and_json_options(self):
        parser = build_cli_parser()

        args = parser.parse_args(["operations", "/tmp/link", "--limit", "5", "--json"])

        self.assertEqual(args.command, "operations")
        self.assertEqual(args.target, "/tmp/link")
        self.assertEqual(args.limit, 5)
        self.assertTrue(args.json)

    def test_health_json_option(self):
        parser = build_cli_parser()

        args = parser.parse_args(["health", "/tmp/link", "--json"])

        self.assertEqual(args.command, "health")
        self.assertEqual(args.target, "/tmp/link")
        self.assertTrue(args.json)

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
            "--review-after",
            "2026-06-01",
            "--expires-at",
            "2026-07-01",
        ])

        self.assertEqual(args.memory_type, "preference")
        self.assertEqual(args.scope, "user")
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

    def test_dispatch_routes_operations_arguments(self):
        parser = build_cli_parser()
        args = parser.parse_args(["operations", "/tmp/link", "--limit", "5", "--json"])
        calls = []

        def operations_handler(target, **kwargs):
            calls.append((target, kwargs))
            return 9

        code = dispatch_cli_command(args, {"operations": operations_handler})

        self.assertEqual(code, 9)
        self.assertEqual(calls[0][0], Path("/tmp/link"))
        self.assertEqual(calls[0][1]["limit"], 5)
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
        self.assertEqual(calls[0][2]["project"], "alpha")
        self.assertTrue(calls[0][2]["allow_conflict"])
        self.assertTrue(calls[0][2]["json_output"])


if __name__ == "__main__":
    unittest.main()
