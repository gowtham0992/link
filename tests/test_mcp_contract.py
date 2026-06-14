import importlib.util
import json
import sys
import tarfile
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))
from link_core.operations import begin_operation  # noqa: E402

LINK_SPEC = importlib.util.spec_from_file_location("link_cli_for_mcp_tests", ROOT / "link.py")
link_cli = importlib.util.module_from_spec(LINK_SPEC)
assert LINK_SPEC.loader is not None
LINK_SPEC.loader.exec_module(link_cli)


class FakeFastMCP:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def tool(self):
        def decorator(fn):
            return fn

        return decorator

    def run(self, transport: str = "stdio") -> None:
        return None


def install_mcp_stub() -> dict[str, types.ModuleType | None]:
    previous = {
        "mcp": sys.modules.get("mcp"),
        "mcp.server": sys.modules.get("mcp.server"),
        "mcp.server.fastmcp": sys.modules.get("mcp.server.fastmcp"),
    }
    mcp_mod = types.ModuleType("mcp")
    server_mod = types.ModuleType("mcp.server")
    fastmcp_mod = types.ModuleType("mcp.server.fastmcp")
    fastmcp_mod.FastMCP = FakeFastMCP
    server_mod.fastmcp = fastmcp_mod
    mcp_mod.server = server_mod
    sys.modules["mcp"] = mcp_mod
    sys.modules["mcp.server"] = server_mod
    sys.modules["mcp.server.fastmcp"] = fastmcp_mod
    return previous


def restore_mcp_modules(previous: dict[str, types.ModuleType | None]) -> None:
    for name, module in previous.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def create_demo_quiet(target: Path) -> None:
    with redirect_stdout(StringIO()):
        link_cli.create_demo(target, force=False)


def import_mcp_server(wiki_dir: Path):
    previous_modules = install_mcp_stub()
    previous_argv = sys.argv[:]
    module_name = f"link_mcp_server_contract_{id(wiki_dir)}"
    try:
        sys.argv = ["link_mcp.server", "--wiki", str(wiki_dir)]
        spec = importlib.util.spec_from_file_location(module_name, ROOT / "mcp_package/link_mcp/server.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module, previous_modules, previous_argv, module_name
    except BaseException:
        restore_mcp_modules(previous_modules)
        sys.argv = previous_argv
        raise


class McpContractTests(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp(prefix="link-mcp-contract-"))
        self.target = tmp / "demo"
        create_demo_quiet(self.target)
        self.server, self.previous_modules, self.previous_argv, self.module_name = import_mcp_server(self.target / "wiki")

    def tearDown(self):
        if hasattr(self.server, "_clear_cache"):
            self.server._clear_cache()
        sys.modules.pop(self.module_name, None)
        restore_mcp_modules(self.previous_modules)
        sys.argv = self.previous_argv

    def test_search_wiki_contract(self):
        payload = json.loads(self.server.search_wiki("agent memory", limit=5))

        self.assertEqual(payload["query"], "agent memory")
        self.assertGreaterEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["name"], "agent-memory")
        self.assertIn("score", payload["results"][0])
        self.assertIn("snippet", payload["results"][0])

    def test_search_wiki_handles_invalid_limits(self):
        bad_limit = json.loads(self.server.search_wiki("agent memory", limit="bad"))
        negative_limit = json.loads(self.server.search_wiki("agent memory", limit=-10))

        self.assertGreaterEqual(bad_limit["count"], 1)
        self.assertEqual(negative_limit["count"], 1)

    def test_search_wiki_rejects_empty_query(self):
        payload = json.loads(self.server.search_wiki("   ", limit=5))

        self.assertEqual(payload["error"], "query required")
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["results"], [])

    def test_query_link_contract(self):
        payload = json.loads(self.server.query_link("agent memory", budget="small"))

        self.assertTrue(payload["found"])
        self.assertEqual(payload["budget"], "small")
        self.assertIn("memory", payload["strategy"]["mode"])
        self.assertEqual(payload["wiki"]["primary"], "agent-memory")
        self.assertEqual(payload["memory"]["items"][0]["name"], "prefer-local-personal-memory")
        self.assertIn("why_selected", payload["context_packet"][0])
        self.assertIn("budget_report", payload)
        self.assertIn("follow_up", payload)

    def test_link_status_contract(self):
        payload = json.loads(self.server.link_status(include_validation=True))

        self.assertTrue(payload["ready"])
        self.assertEqual(payload["version"], self.server.LINK_VERSION)
        self.assertEqual(payload["page_count"], 13)
        self.assertEqual(payload["content_page_count"], 11)
        self.assertEqual(payload["memory_count"], 1)
        self.assertIn(payload["search_backend"], {"sqlite-fts", "token-index"})
        self.assertEqual(payload["schema"]["status"], "current")
        self.assertTrue(payload["validation"]["passed"])
        self.assertEqual(payload["warnings"], [])
        self.assertEqual(payload["next_actions"][0]["tool"], "query_link")

    def test_mcp_cache_throttles_repeated_mtime_scans(self):
        self.server._clear_cache()
        self.server.CACHE_MTIME_CHECK_INTERVAL_SECONDS = 60.0
        self.server._build_cache()

        with patch.object(self.server, "_wiki_mtime", wraps=self.server._wiki_mtime) as mtime:
            self.server._build_cache()
            self.server._build_cache()

        self.assertEqual(mtime.call_count, 0)

    def test_link_status_contract_reports_cache_warnings(self):
        locked = self.target / "wiki/concepts/locked-page.md"
        locked.write_text("---\ntype: concept\ntitle: Locked\n---\n\n# Locked\n", encoding="utf-8")
        original_read_text = Path.read_text

        def flaky_read_text(path: Path, *args, **kwargs):
            if path.name == "locked-page.md":
                raise OSError("permission denied")
            return original_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", flaky_read_text):
            payload = json.loads(self.server.link_status())

        self.assertFalse(payload["ready"])
        self.assertGreater(payload["page_count"], 0)
        self.assertEqual(payload["warnings"][0]["code"], "cache_read_warnings")

    def test_link_operations_contract(self):
        begin_operation(
            self.target / "wiki",
            "remember",
            "Save memory",
            timestamp="2026-05-17T00:00:00Z",
            paths=["wiki/memories/prefer-local.md"],
        )

        payload = json.loads(self.server.link_operations(limit=5))

        self.assertEqual(payload["operation_count"], 1)
        self.assertEqual(payload["stale_count"], 1)
        self.assertEqual(payload["operations"][0]["operation"], "remember")
        self.assertEqual(payload["operations"][0]["description"], "Save memory")
        self.assertIn("lnk operations", payload["next_actions"][0]["command"])

    def test_starter_prompts_contract(self):
        payload = json.loads(self.server.starter_prompts(project="Client Launch"))

        self.assertEqual(payload["project"], "client-launch")
        self.assertEqual(payload["prompts"][0]["prompt"], "is Link ready?")
        self.assertIn("this project uses Link", payload["prompts"][2]["prompt"])
        self.assertTrue(any(command.startswith("lnk health ") for command in payload["commands"]))

    def test_missing_wiki_message_points_to_current_setup_paths(self):
        previous_argv = sys.argv[:]
        missing = Path(tempfile.mkdtemp(prefix="link-mcp-missing-")) / "missing" / "wiki"
        module_name = f"link_mcp_server_missing_{id(missing)}"
        try:
            sys.argv = ["link_mcp.server", "--wiki", str(missing)]
            spec = importlib.util.spec_from_file_location(module_name, ROOT / "mcp_package/link_mcp/server.py")
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            err = StringIO()
            with redirect_stderr(err), self.assertRaises(SystemExit) as cm:
                spec.loader.exec_module(module)

            self.assertEqual(cm.exception.code, 1)
            text = err.getvalue()
            self.assertIn("Wiki not found", text)
            self.assertIn("lnk init", text)
            self.assertIn("python3 link.py init", text)
            self.assertIn("integrations/*/install.sh", text)
            self.assertIn("--wiki /path/to/wiki", text)
            self.assertNotIn("install.sh first", text)
        finally:
            sys.argv = previous_argv

    def test_version_flag_does_not_require_wiki_or_mcp_sdk(self):
        previous_argv = sys.argv[:]
        missing = Path(tempfile.mkdtemp(prefix="link-mcp-version-")) / "missing" / "wiki"
        module_name = f"link_mcp_server_version_{id(missing)}"
        try:
            sys.argv = ["link_mcp.server", "--wiki", str(missing), "--version"]
            spec = importlib.util.spec_from_file_location(module_name, ROOT / "mcp_package/link_mcp/server.py")
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            out = StringIO()
            err = StringIO()
            with redirect_stdout(out), redirect_stderr(err), self.assertRaises(SystemExit) as cm:
                spec.loader.exec_module(module)

            self.assertEqual(cm.exception.code, 0)
            self.assertIn("link-mcp", out.getvalue())
            self.assertEqual(err.getvalue(), "")
        finally:
            sys.modules.pop(module_name, None)
            sys.argv = previous_argv

    def test_migrate_wiki_contract(self):
        (self.target / "wiki/_link_schema.json").unlink()

        payload = json.loads(self.server.migrate_wiki())

        self.assertTrue(payload["ok"])
        self.assertTrue((self.target / "wiki/_link_schema.json").exists())
        self.assertEqual(payload["previous"]["status"], "missing")
        self.assertEqual(payload["schema"]["status"], "current")

    def test_backup_wiki_contract_excludes_raw_by_default(self):
        (self.target / "raw/private-note.md").write_text("secret source", encoding="utf-8")

        payload = json.loads(self.server.backup_wiki(label="mcp test"))
        listing = json.loads(self.server.backup_wiki(list_only=True))

        self.assertTrue(payload["created"])
        self.assertEqual(payload["included"], ["wiki"])
        self.assertEqual(listing["count"], 1)
        with tarfile.open(payload["path"], "r:gz") as tar:
            names = set(tar.getnames())
        self.assertIn("wiki/index.md", names)
        self.assertNotIn("raw/private-note.md", names)

    def test_backup_wiki_contract_reports_archive_failure(self):
        original_add = tarfile.TarFile.add

        def flaky_add(tar, name, *args, **kwargs):
            if Path(name).name == "agent-memory.md":
                raise OSError("permission denied")
            return original_add(tar, name, *args, **kwargs)

        with patch.object(tarfile.TarFile, "add", flaky_add):
            payload = json.loads(self.server.backup_wiki(label="partial"))

        self.assertFalse(payload["created"])
        self.assertIn("backup failed", payload["error"])
        self.assertEqual(list((self.target / ".link-backups").glob("*.tar.gz")), [])

    def test_backup_wiki_contract_reports_list_warnings(self):
        created = json.loads(self.server.backup_wiki(label="warning source"))
        archive = Path(created["path"])
        original_stat = Path.stat

        def flaky_stat(path: Path, *args, **kwargs):
            if path.name == archive.name:
                raise OSError("permission denied")
            return original_stat(path, *args, **kwargs)

        with patch.object(Path, "stat", flaky_stat):
            payload = json.loads(self.server.backup_wiki(list_only=True))

        self.assertEqual(payload["warning_count"], 1)
        self.assertEqual(payload["warnings"][0]["backup"], archive.name)

    def test_ingest_status_contract(self):
        payload = json.loads(self.server.ingest_status())

        self.assertEqual(payload["guidance"]["state"], "ready")
        self.assertEqual(payload["pending_count"], 0)
        self.assertEqual(payload["source_read_warning_count"], 0)
        self.assertEqual(payload["raw_scan_warning_count"], 0)
        self.assertEqual(payload["backlinks_status"], "current")
        self.assertEqual(payload["plan"]["title"], "Ready for new sources")

    def test_validate_wiki_contract(self):
        payload = json.loads(self.server.validate_wiki())

        self.assertTrue(payload["passed"])
        self.assertEqual(payload["error_count"], 0)
        self.assertEqual(payload["warning_count"], 0)

    def test_validate_wiki_reports_failed_gate(self):
        page = self.target / "wiki/concepts/agent-memory.md"
        page.write_text(
            page.read_text(encoding="utf-8").replace("type: concept", "type: source", 1),
            encoding="utf-8",
        )
        json.loads(self.server.rebuild_backlinks())

        payload = json.loads(self.server.validate_wiki(strict=True))
        codes = {finding["code"] for finding in payload["findings"]}

        self.assertFalse(payload["passed"])
        self.assertIn("type_directory_mismatch", codes)

    def test_get_context_contract(self):
        payload = json.loads(self.server.get_context("agent memory"))
        page_names = [page["name"] for page in payload["pages"]]

        self.assertTrue(payload["found"])
        self.assertEqual(payload["primary"], "agent-memory")
        self.assertEqual(payload["inbound_count"], 10)
        self.assertEqual(payload["forward_count"], 5)
        self.assertEqual(page_names[0], "agent-memory")
        self.assertIn("link", page_names)
        self.assertIn("agent-memory-session", page_names)
        self.assertEqual(payload["pages"][0]["relationship"], "primary")

    def test_get_context_rejects_empty_topic(self):
        payload = json.loads(self.server.get_context(""))

        self.assertFalse(payload["found"])
        self.assertEqual(payload["error"], "topic required")
        self.assertEqual(payload["pages"], [])

    def test_get_pages_filters_contract(self):
        concepts = json.loads(self.server.get_pages(category="concepts"))
        mature = json.loads(self.server.get_pages(maturity="growing"))
        sources = json.loads(self.server.get_pages(page_type="source"))

        self.assertEqual(concepts["count"], 5)
        self.assertEqual(concepts["returned_count"], 5)
        self.assertEqual({page["category"] for page in concepts["pages"]}, {"concepts"})
        self.assertIn("agent-memory", {page["name"] for page in mature["pages"]})
        self.assertEqual(sources["count"], 3)
        self.assertEqual({page["type"] for page in sources["pages"]}, {"source"})

    def test_get_pages_is_bounded_for_large_agent_contexts(self):
        payload = json.loads(self.server.get_pages(limit=2))

        self.assertGreater(payload["count"], 2)
        self.assertEqual(payload["returned_count"], 2)
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["follow_up"][0]["tool"], "get_pages")

    def test_get_pages_normalizes_messy_pagination_args(self):
        payload = json.loads(self.server.get_pages(limit="bad", offset="-20", include_all="true"))

        self.assertGreater(payload["returned_count"], 2)
        self.assertIsNone(payload["limit"])
        self.assertEqual(payload["offset"], 0)
        self.assertFalse(payload["truncated"])

    def test_get_backlinks_contract(self):
        payload = json.loads(self.server.get_backlinks("agent-memory"))

        self.assertEqual(payload["page"], "agent-memory")
        self.assertEqual(payload["inbound_count"], 10)
        self.assertEqual(payload["forward_count"], 5)
        self.assertEqual(len(payload["inbound"]), 10)
        self.assertEqual(len(payload["forward"]), 5)
        self.assertIn("link", payload["inbound"])
        self.assertIn("agent-memory-session", payload["forward"])

    def test_get_backlinks_is_bounded_for_large_agent_contexts(self):
        payload = json.loads(self.server.get_backlinks("agent-memory", limit=3))

        self.assertEqual(payload["inbound_count"], 10)
        self.assertEqual(payload["returned_inbound"], 3)
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["follow_up"][0]["tool"], "get_backlinks")

    def test_get_backlinks_normalizes_messy_pagination_args(self):
        payload = json.loads(self.server.get_backlinks("agent-memory", limit="bad", offset="-5", include_all="yes"))

        self.assertIsNone(payload["limit"])
        self.assertEqual(payload["offset"], 0)
        self.assertEqual(payload["returned_inbound"], payload["inbound_count"])
        self.assertFalse(payload["truncated"])

    def test_get_backlinks_rejects_empty_page_name(self):
        payload = json.loads(self.server.get_backlinks(""))

        self.assertEqual(payload["error"], "page_name required")
        self.assertEqual(payload["inbound"], [])
        self.assertEqual(payload["forward"], [])

    def test_get_graph_contract(self):
        payload = json.loads(self.server.get_graph())
        nodes = {node["id"] for node in payload["nodes"]}
        edges = {(edge["source"], edge["target"]) for edge in payload["edges"]}

        self.assertEqual(len(payload["nodes"]), 13)
        self.assertEqual(len(payload["edges"]), 58)
        self.assertEqual(len(edges), len(payload["edges"]))
        self.assertIn("agent-memory", nodes)
        self.assertIn("prefer-local-personal-memory", nodes)
        self.assertIn(("agent-memory", "link"), edges)
        self.assertIn(("prefer-local-personal-memory", "agent-memory"), edges)
        self.assertIn(("retrieval-augmented-generation", "transformers"), edges)

    def test_get_graph_summary_contract(self):
        payload = json.loads(self.server.get_graph_summary("agent memory", limit=5, depth=1, max_edges=10))
        node_ids = {node["id"] for node in payload["nodes"]}

        self.assertEqual(payload["mode"], "topic-neighborhood")
        self.assertTrue(payload["found"])
        self.assertLessEqual(payload["returned_nodes"], 5)
        self.assertLessEqual(payload["returned_edges"], 10)
        self.assertIn("agent-memory", node_ids)
        self.assertEqual(payload["nodes"][0]["why_selected"], "matched topic")
        self.assertIn("get_context", {item["tool"] for item in payload["follow_up"]})

    def test_recall_memory_contract(self):
        payload = json.loads(self.server.recall_memory("local personal memory"))

        self.assertGreaterEqual(payload["count"], 1)
        self.assertEqual(payload["memories"][0]["name"], "prefer-local-personal-memory")
        self.assertEqual(payload["memories"][0]["memory_type"], "preference")
        self.assertEqual(payload["memories"][0]["recall"]["state"], "needs_review")
        self.assertEqual(payload["memories"][0]["review_issue_count"], 1)

    def test_recall_memory_project_filter_contract(self):
        alpha = json.loads(self.server.remember_memory(
            "Project uses alpha API for imports.",
            title="Alpha API imports",
            memory_type="project",
            scope="project",
            project="alpha",
        ))
        beta = json.loads(self.server.remember_memory(
            "Project uses beta API for imports.",
            title="Beta API imports",
            memory_type="project",
            scope="project",
            project="beta",
        ))
        recalled = json.loads(self.server.recall_memory("API imports", project="alpha"))
        profile = json.loads(self.server.memory_profile(project="alpha"))

        self.assertTrue(alpha["created"])
        self.assertTrue(beta["created"])
        self.assertEqual(alpha["project"], "alpha")
        self.assertEqual(recalled["project"], "alpha")
        self.assertEqual([memory["name"] for memory in recalled["memories"]], ["alpha-api-imports"])
        self.assertEqual(profile["project"], "alpha")
        self.assertIn("alpha", profile["by_project"])
        self.assertNotIn("beta-api-imports", {memory["name"] for memory in profile["recent"]})

    def test_memory_profile_contract(self):
        payload = json.loads(self.server.memory_profile())

        self.assertEqual(payload["memory_count"], 1)
        self.assertEqual(payload["active_count"], 1)
        self.assertEqual(payload["review_count"], 1)
        self.assertEqual(payload["by_type"]["preference"], 1)
        self.assertEqual(payload["by_scope"]["user"], 1)
        self.assertEqual(payload["recent"][0]["name"], "prefer-local-personal-memory")
        self.assertEqual(payload["preferences"][0]["memory_type"], "preference")

    def test_memory_brief_contract(self):
        payload = json.loads(self.server.memory_brief("local personal memory"))

        self.assertEqual(payload["selection"], "query")
        self.assertEqual(payload["query"], "local personal memory")
        self.assertEqual(payload["profile"]["memory_count"], 1)
        self.assertEqual(payload["review"]["count"], 1)
        self.assertEqual(payload["captures"]["count"], 0)
        self.assertEqual(payload["relevant_memories"][0]["name"], "prefer-local-personal-memory")
        self.assertNotIn("body", payload["relevant_memories"][0])
        self.assertIn("agent_guidance", payload)

    def test_memory_brief_surfaces_capture_review_contract(self):
        fake_key = "sk-" + ("F" * 24)
        capture = json.loads(self.server.capture_session(
            f"Remember that MCP brief should surface capture review. Test key {fake_key}",
            title="MCP brief capture",
            project="alpha",
        ))

        raw_payload = self.server.memory_brief("capture review", project="alpha")
        payload = json.loads(raw_payload)

        self.assertTrue(capture["captured"])
        self.assertEqual(payload["captures"]["project"], "alpha")
        self.assertEqual(payload["captures"]["count"], 1)
        self.assertEqual(payload["captures"]["warning_count"], 1)
        self.assertIn("[redacted-secret]", payload["captures"]["items"][0]["snippet"])
        self.assertIn("capture_inbox", payload["captures"]["next_action"])
        self.assertIn("Redact raw captures", "\n".join(payload["agent_guidance"]))
        self.assertNotIn(fake_key, raw_payload)

    def test_memory_audit_contract(self):
        fake_key = "sk-" + ("G" * 24)
        capture = json.loads(self.server.capture_session(
            f"Remember that MCP audit should show capture risk. Test key {fake_key}",
            title="MCP audit capture",
            project="alpha",
        ))

        raw_payload = self.server.memory_audit(project="alpha")
        payload = json.loads(raw_payload)

        self.assertTrue(capture["captured"])
        self.assertEqual(payload["status"], "needs_attention")
        self.assertEqual(payload["project"], "alpha")
        self.assertEqual(payload["captures"]["warning_count"], 1)
        self.assertIn("capture_secret_warnings", [factor["code"] for factor in payload["risk_factors"]])
        self.assertEqual(payload["next_actions"][0]["tool"], "memory_inbox")
        self.assertEqual(payload["next_actions"][1]["tool"], "capture_inbox")
        self.assertNotIn(fake_key, raw_payload)

    def test_capture_session_contract(self):
        before_memories = list((self.target / "wiki/memories").glob("*.md"))
        fake_key = "sk-" + ("A" * 24)

        payload = json.loads(self.server.capture_session(
            f"Remember that the user prefers release branches for Link work. Test key {fake_key}",
            title="Release workflow session",
            project="link",
        ))

        capture_path = self.target / payload["path"]
        after_memories = list((self.target / "wiki/memories").glob("*.md"))
        capture_text = capture_path.read_text(encoding="utf-8")
        log_text = (self.target / "wiki/log.md").read_text(encoding="utf-8")

        self.assertTrue(payload["captured"])
        self.assertEqual(payload["project"], "link")
        self.assertTrue(payload["path"].startswith("raw/memory-captures/"))
        self.assertIn('project: "link"', capture_text)
        self.assertEqual(payload["secret_warnings"], ["OpenAI API key"])
        self.assertGreaterEqual(payload["proposals"]["count"], 1)
        self.assertEqual(len(after_memories), len(before_memories))
        self.assertIn("capture-session", log_text)

    def test_capture_inbox_contract(self):
        fake_key = "sk-" + ("B" * 24)
        alpha = json.loads(self.server.capture_session(
            f"Remember that MCP Alpha captures need review. Test key {fake_key}",
            title="MCP Alpha capture",
            project="alpha",
        ))
        beta = json.loads(self.server.capture_session(
            "Remember that MCP Beta captures stay separate.",
            title="MCP Beta capture",
            project="beta",
        ))

        raw_payload = self.server.capture_inbox(project="alpha")
        payload = json.loads(raw_payload)

        self.assertTrue(alpha["captured"])
        self.assertTrue(beta["captured"])
        self.assertEqual(payload["project"], "alpha")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["warning_count"], 1)
        self.assertEqual(payload["captures"][0]["project"], "alpha")
        self.assertEqual(payload["captures"][0]["secret_warnings"], ["OpenAI API key"])
        self.assertIn("[redacted-secret]", payload["captures"][0]["snippet"])
        self.assertIn("accept_capture", payload["captures"][0]["commands"]["accept"])
        self.assertIn("redact_capture", payload["captures"][0]["commands"]["redact"])
        self.assertIn("delete_capture", payload["captures"][0]["commands"]["delete"])
        self.assertNotIn(fake_key, raw_payload)
        self.assertNotIn("MCP Beta capture", raw_payload)

    def test_capture_inbox_contract_reports_read_warnings(self):
        capture_dir = self.target / "raw" / "memory-captures"
        capture_dir.mkdir(parents=True, exist_ok=True)
        (capture_dir / "locked.md").write_text(
            "---\n"
            "title: MCP locked capture\n"
            "---\n\n"
            "## Notes\n\n"
            "This capture should surface as unreadable.\n",
            encoding="utf-8",
        )
        original_read_text = Path.read_text

        def flaky_read_text(path: Path, *args, **kwargs):
            if path.name == "locked.md":
                raise OSError("permission denied")
            return original_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", flaky_read_text):
            payload = json.loads(self.server.capture_inbox())
            audit = json.loads(self.server.memory_audit())

        self.assertEqual(payload["read_warning_count"], 1)
        self.assertEqual(payload["read_warnings"][0]["capture"], "raw/memory-captures/locked.md")
        self.assertIn("capture_read_warnings", [factor["code"] for factor in audit["risk_factors"]])
        self.assertTrue(audit["next_actions"][1]["recommended"])

    def test_accept_capture_contract(self):
        capture = json.loads(self.server.capture_session(
            "We decided to keep MCP capture approval local and explicit.",
            title="MCP capture approval session",
            project="link",
        ))

        accepted = json.loads(self.server.accept_capture(capture["path"], index=1))
        memory_path = self.target / accepted["result"]["path"]
        memory_text = memory_path.read_text(encoding="utf-8")
        log_text = (self.target / "wiki/log.md").read_text(encoding="utf-8")

        self.assertTrue(accepted["accepted"])
        self.assertEqual(accepted["capture"], capture["path"])
        self.assertEqual(accepted["project"], "link")
        self.assertTrue(accepted["result"]["created"])
        self.assertEqual(accepted["result"]["project"], "link")
        self.assertIn(f'source: "{capture["path"]}"', memory_text)
        self.assertIn('project: "link"', memory_text)
        self.assertIn("MCP capture approval", memory_text)
        self.assertIn("accept-capture", log_text)

        recall = json.loads(self.server.recall_memory("MCP capture approval", project="link"))
        self.assertEqual(recall["memories"][0]["project"], "link")

    def test_redact_capture_contract(self):
        fake_key = "sk-" + ("C" * 24)
        capture = json.loads(self.server.capture_session(
            f"Remember that MCP capture redaction stays local. Test key {fake_key}",
            title="MCP capture redaction session",
        ))

        redacted = json.loads(self.server.redact_capture(capture["path"]))
        capture_text = (self.target / capture["path"]).read_text(encoding="utf-8")
        log_text = (self.target / "wiki/log.md").read_text(encoding="utf-8")

        self.assertTrue(redacted["redacted"])
        self.assertEqual(redacted["labels"], ["OpenAI API key"])
        self.assertNotIn(fake_key, capture_text)
        self.assertIn("[redacted-secret]", capture_text)
        self.assertIn("redact-capture", log_text)
        self.assertNotIn(fake_key, log_text)

    def test_delete_capture_contract(self):
        capture = json.loads(self.server.capture_session(
            "Remember that MCP capture deletion requires confirmation.",
            title="MCP capture deletion session",
        ))
        capture_path = self.target / capture["path"]

        denied = json.loads(self.server.delete_capture(capture["path"]))
        self.assertFalse(denied["deleted"])
        self.assertTrue(denied["confirmation_required"])
        self.assertTrue(capture_path.exists())

        deleted = json.loads(self.server.delete_capture(capture["path"], confirm=True))
        log_text = (self.target / "wiki/log.md").read_text(encoding="utf-8")

        self.assertTrue(deleted["deleted"])
        self.assertFalse(capture_path.exists())
        self.assertIn("delete-capture", log_text)
        self.assertNotIn("MCP capture deletion requires confirmation", log_text)

    def test_memory_inbox_and_review_memory_contract(self):
        inbox = json.loads(self.server.memory_inbox())
        reviewed = json.loads(self.server.review_memory(
            "prefer-local-personal-memory",
            note="confirmed by MCP test",
        ))
        clear = json.loads(self.server.memory_inbox())

        self.assertEqual(inbox["review_count"], 1)
        self.assertEqual(inbox["items"][0]["name"], "prefer-local-personal-memory")
        self.assertEqual(inbox["items"][0]["issues"][0]["code"], "pending_review")
        self.assertEqual(inbox["items"][0]["primary_action"]["kind"], "review")
        self.assertEqual(inbox["items"][0]["primary_action"]["tool"], "review_memory")
        self.assertTrue(reviewed["updated"])
        self.assertEqual(reviewed["review_status"], "reviewed")
        self.assertEqual(reviewed["remaining_issue_count"], 0)
        self.assertEqual(clear["review_count"], 0)

    def test_memory_log_contract(self):
        created = json.loads(self.server.remember_memory(
            "Memory log contract tests should be visible in the lifecycle log.",
            title="Memory log contract",
        ))
        payload = json.loads(self.server.memory_log())

        self.assertTrue(created["created"])
        self.assertEqual(payload["schema"], "link-memory-log-v1")
        self.assertGreaterEqual(payload["count"], 1)
        self.assertEqual(payload["entries"][-1]["operation"], "remember")
        self.assertIn("entries", payload)
        self.assertIn("Memory bodies", payload["privacy_note"])

    def test_memory_wins_contract(self):
        payload = json.loads(self.server.memory_wins())

        self.assertEqual(payload["schema"], "link-memory-wins-v1")
        self.assertGreaterEqual(payload["active_count"], 1)
        self.assertIn("wins", payload)
        self.assertIn("not telemetry", payload["honest_note"])

    def test_memory_inbox_project_filter_contract(self):
        self.server.review_memory("prefer-local-personal-memory")
        alpha = json.loads(self.server.remember_memory(
            "Alpha project stores deployment context in Link.",
            title="Alpha deployment context",
            memory_type="project",
            scope="project",
            project="alpha",
        ))
        beta = json.loads(self.server.remember_memory(
            "Beta project stores design context in Link.",
            title="Beta design context",
            memory_type="project",
            scope="project",
            project="beta",
        ))

        raw_payload = self.server.memory_inbox(project="alpha")
        inbox = json.loads(raw_payload)

        self.assertTrue(alpha["created"])
        self.assertTrue(beta["created"])
        self.assertEqual(inbox["project"], "alpha")
        self.assertEqual([item["project"] for item in inbox["items"]], ["alpha"])
        self.assertNotIn("Beta design context", raw_payload)

    def test_explain_memory_contract(self):
        payload = json.loads(self.server.explain_memory("prefer-local-personal-memory"))

        self.assertTrue(payload["found"])
        self.assertEqual(payload["memory"]["name"], "prefer-local-personal-memory")
        self.assertEqual(payload["provenance"]["source"], "demo")
        self.assertEqual(payload["recall"]["state"], "needs_review")
        self.assertEqual(payload["review"]["issues"][0]["code"], "pending_review")
        self.assertIn("agent-memory", payload["graph"]["forward"])

    def test_explain_memory_after_review_contract(self):
        self.server.review_memory("prefer-local-personal-memory")

        payload = json.loads(self.server.explain_memory("prefer-local-personal-memory"))

        self.assertEqual(payload["recall"]["state"], "ready")
        self.assertEqual(payload["review"]["issue_count"], 0)

    def test_archive_and_restore_memory_contract(self):
        archived = json.loads(self.server.archive_memory(
            "prefer-local-personal-memory",
            reason="unit test stale memory",
        ))
        recall_default = json.loads(self.server.recall_memory("local personal memory"))
        recall_archived = json.loads(self.server.recall_memory("local personal memory", include_archived=True))
        profile = json.loads(self.server.memory_profile())
        restored = json.loads(self.server.restore_memory("Prefer local personal memory"))
        recall_restored = json.loads(self.server.recall_memory("local personal memory"))

        self.assertTrue(archived["updated"])
        self.assertEqual(archived["status"], "archived")
        self.assertEqual(recall_default["count"], 0)
        self.assertEqual(recall_archived["memories"][0]["status"], "archived")
        self.assertEqual(profile["active_count"], 0)
        self.assertEqual(profile["archived"][0]["name"], "prefer-local-personal-memory")
        self.assertTrue(restored["updated"])
        self.assertEqual(restored["status"], "active")
        self.assertEqual(recall_restored["memories"][0]["name"], "prefer-local-personal-memory")

    def test_forget_memory_contract(self):
        memory_path = self.target / "wiki/memories/prefer-local-personal-memory.md"

        denied = json.loads(self.server.forget_memory("prefer-local-personal-memory"))
        forgotten = json.loads(self.server.forget_memory("prefer-local-personal-memory", confirm=True))
        recall = json.loads(self.server.recall_memory("local personal memory", include_archived=True))
        log_text = (self.target / "wiki/log.md").read_text(encoding="utf-8")
        index_text = (self.target / "wiki/index.md").read_text(encoding="utf-8")

        self.assertFalse(denied["forgotten"])
        self.assertTrue(denied["confirmation_required"])
        self.assertTrue(forgotten["forgotten"])
        self.assertTrue(forgotten["backlinks_rebuilt"])
        self.assertFalse(memory_path.exists())
        self.assertEqual(recall["count"], 0)
        self.assertNotIn("[[prefer-local-personal-memory]]", index_text)
        self.assertIn("forget-memory", log_text)
        self.assertNotIn("local personal memory for agents", log_text)

    def test_remember_memory_contract(self):
        payload = json.loads(self.server.remember_memory(
            "User prefers release branches for Link work.",
            title="Prefer release branches",
            memory_type="preference",
            scope="project",
            tags="git, release",
            source="unit test",
            review_after="2026-08-01",
            expires_at="2026-12-01",
        ))
        recall = json.loads(self.server.recall_memory("release branches"))
        memory_text = (self.target / "wiki/memories/prefer-release-branches.md").read_text(encoding="utf-8")

        self.assertTrue(payload["created"])
        self.assertEqual(payload["name"], "prefer-release-branches")
        self.assertEqual(payload["review_after"], "2026-08-01")
        self.assertEqual(payload["expires_at"], "2026-12-01")
        self.assertTrue((self.target / "wiki/memories/prefer-release-branches.md").exists())
        self.assertIn('expires_at: "2026-12-01"', memory_text)
        self.assertEqual(recall["memories"][0]["name"], "prefer-release-branches")

    def test_remember_memory_blocks_strong_duplicate(self):
        first = json.loads(self.server.remember_memory(
            "User prefers release branches for Link work.",
            title="Prefer release branches",
            memory_type="preference",
            scope="project",
        ))
        duplicate = json.loads(self.server.remember_memory(
            "User prefers release branches for Link work.",
            title="Prefer release branches",
            memory_type="preference",
            scope="project",
        ))
        override = json.loads(self.server.remember_memory(
            "User prefers release branches for Link work.",
            title="Prefer release branches",
            memory_type="preference",
            scope="project",
            allow_duplicate=True,
        ))

        self.assertTrue(first["created"])
        self.assertFalse(duplicate["created"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["candidates"][0]["name"], "prefer-release-branches")
        self.assertTrue(override["created"])
        self.assertTrue(override["duplicate_override"])
        self.assertEqual(override["name"], "prefer-release-branches-2")

    def test_remember_memory_blocks_conflict(self):
        conflict = json.loads(self.server.remember_memory(
            "User prefers cloud personal memory for agents.",
            title="Prefer cloud personal memory",
            memory_type="preference",
            scope="user",
        ))
        override = json.loads(self.server.remember_memory(
            "User prefers cloud personal memory for agents.",
            title="Prefer cloud personal memory",
            memory_type="preference",
            scope="user",
            allow_conflict=True,
        ))

        self.assertFalse(conflict["created"])
        self.assertTrue(conflict["conflict"])
        self.assertEqual(conflict["conflict_candidates"][0]["name"], "prefer-local-personal-memory")
        self.assertIn("different_storage_policy", conflict["conflict_candidates"][0]["conflict_reasons"])
        self.assertTrue(override["created"])
        self.assertTrue(override["conflict_override"])

    def test_update_memory_contract(self):
        reviewed = json.loads(self.server.review_memory("prefer-local-personal-memory", note="confirmed"))
        updated = json.loads(self.server.update_memory(
            "prefer-local-personal-memory",
            "Also prefer updating existing memories instead of creating duplicates.",
            source="unit test",
        ))
        explained = json.loads(self.server.explain_memory("prefer-local-personal-memory"))
        memory_text = (self.target / "wiki/memories/prefer-local-personal-memory.md").read_text(encoding="utf-8")
        log_text = (self.target / "wiki/log.md").read_text(encoding="utf-8")

        self.assertEqual(reviewed["review_status"], "reviewed")
        self.assertTrue(updated["updated"])
        self.assertEqual(updated["previous_review_status"], "reviewed")
        self.assertEqual(updated["review_status"], "pending")
        self.assertEqual(updated["update_count"], 1)
        self.assertTrue(updated["backlinks_rebuilt"])
        self.assertEqual(explained["review"]["status"], "pending")
        self.assertEqual(explained["recall"]["state"], "needs_review")
        self.assertIn("instead of creating duplicates", explained["body"])
        self.assertIn("update_count: 1", memory_text)
        self.assertNotIn("reviewed_at:", memory_text)
        self.assertIn("update-memory", log_text)

    def test_set_memory_visibility_contract(self):
        updated = json.loads(self.server.set_memory_visibility("prefer-local-personal-memory", "team"))
        unchanged = json.loads(self.server.set_memory_visibility("prefer-local-personal-memory", "team"))
        rejected = json.loads(self.server.set_memory_visibility("prefer-local-personal-memory", "public"))
        memory_text = (self.target / "wiki/memories/prefer-local-personal-memory.md").read_text(encoding="utf-8")
        log_text = (self.target / "wiki/log.md").read_text(encoding="utf-8")

        self.assertTrue(updated["updated"])
        self.assertEqual(updated["previous_visibility"], "private")
        self.assertEqual(updated["visibility"], "team")
        self.assertFalse(unchanged["updated"])
        self.assertEqual(unchanged["visibility"], "team")
        self.assertFalse(rejected["updated"])
        self.assertIn("visibility must be one of", rejected["error"])
        self.assertIn("visibility: team", memory_text)
        self.assertIn("set-memory-visibility", log_text)

    def test_update_memory_blocks_conflict_with_other_memory(self):
        created = json.loads(self.server.remember_memory(
            "User prefers release branches for Link work.",
            title="Prefer release branches",
            memory_type="preference",
            scope="project",
        ))
        other = json.loads(self.server.remember_memory(
            "User prefers dark mode for Link work.",
            title="Prefer dark mode",
            memory_type="preference",
            scope="project",
        ))
        conflict = json.loads(self.server.update_memory(
            "prefer-dark-mode",
            "User prefers develop branches for Link work.",
            source="unit test",
        ))

        self.assertTrue(created["created"])
        self.assertTrue(other["created"])
        self.assertFalse(conflict["updated"])
        self.assertTrue(conflict["conflict"])
        self.assertEqual(conflict["conflict_candidates"][0]["name"], "prefer-release-branches")

    def test_propose_memories_contract(self):
        created = json.loads(self.server.remember_memory(
            "User prefers release branches for Link work.",
            title="Prefer release branches",
            memory_type="preference",
            scope="project",
        ))
        payload = json.loads(self.server.propose_memories(
            "\n".join([
                "- I prefer release branches for Link work.",
                "- We decided to keep Memory Mode local and source-backed.",
                "- Maybe we could add cloud sync later.",
            ]),
            source="unit test session",
        ))

        self.assertTrue(created["created"])
        self.assertTrue(payload["proposed"])
        self.assertEqual(payload["count"], 2)
        self.assertGreaterEqual(payload["skipped_count"], 1)
        self.assertEqual(payload["proposals"][0]["memory_type"], "preference")
        self.assertEqual(payload["proposals"][0]["suggested_action"], "update-memory")
        self.assertEqual(payload["proposals"][0]["duplicate_candidates"][0]["name"], "prefer-release-branches")
        self.assertEqual(payload["proposals"][1]["memory_type"], "decision")
        self.assertEqual(payload["proposals"][1]["suggested_action"], "remember")

    def test_propose_memories_reports_conflicts(self):
        payload = json.loads(self.server.propose_memories(
            "I prefer cloud personal memory for agents.",
            source="unit test session",
        ))

        self.assertEqual(payload["proposals"][0]["suggested_action"], "review-conflict")
        self.assertEqual(payload["proposals"][0]["conflict_candidates"][0]["name"], "prefer-local-personal-memory")

    def test_rebuild_backlinks_contract(self):
        backlinks_path = self.target / "wiki/_backlinks.json"
        backlinks_path.write_text(json.dumps({"backlinks": {}, "forward": {}}), encoding="utf-8")

        payload = json.loads(self.server.rebuild_backlinks())
        rebuilt = json.loads(backlinks_path.read_text(encoding="utf-8"))

        self.assertTrue(payload["rebuilt"])
        self.assertIn("agent-memory", rebuilt["backlinks"])
        self.assertIn("agent-memory", rebuilt["forward"])
        self.assertIn("link", rebuilt["backlinks"]["agent-memory"])

    def test_rebuild_backlinks_contract_reports_read_errors(self):
        locked = self.target / "wiki/concepts/locked-page.md"
        locked.write_text("---\ntype: concept\ntitle: Locked\n---\n\n[[link]]\n", encoding="utf-8")
        original_read_text = Path.read_text

        def flaky_read_text(path: Path, *args, **kwargs):
            if path.name == "locked-page.md":
                raise OSError("permission denied")
            return original_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", flaky_read_text):
            payload = json.loads(self.server.rebuild_backlinks())

        self.assertFalse(payload["rebuilt"])
        self.assertIn("Could not rebuild backlinks", payload["error"])

    def test_rebuild_index_contract(self):
        index_path = self.target / "wiki/index.md"
        index_path.write_text("# Broken Index\n", encoding="utf-8")

        payload = json.loads(self.server.rebuild_index())
        index_text = index_path.read_text(encoding="utf-8")

        self.assertTrue(payload["rebuilt"])
        self.assertEqual(payload["path"], "wiki/index.md")
        self.assertGreaterEqual(payload["page_count"], 10)
        self.assertEqual(payload["next_actions"][0]["tool"], "rebuild_backlinks")
        self.assertIn("[[agent-memory]]", index_text)
        self.assertIn("[[prefer-local-personal-memory]]", index_text)

    def test_rebuild_index_contract_reports_read_errors(self):
        locked = self.target / "wiki/concepts/locked-page.md"
        locked.write_text("---\ntype: concept\ntitle: Locked\n---\n\n# Locked\n", encoding="utf-8")
        original_read_text = Path.read_text

        def flaky_read_text(path: Path, *args, **kwargs):
            if path.name == "locked-page.md":
                raise OSError("permission denied")
            return original_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", flaky_read_text):
            payload = json.loads(self.server.rebuild_index())

        self.assertFalse(payload["rebuilt"])
        self.assertIn("Could not rebuild index", payload["error"])


if __name__ == "__main__":
    unittest.main()
