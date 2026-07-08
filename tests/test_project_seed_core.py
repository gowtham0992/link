import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.project_seed import (  # noqa: E402
    discover_project_seed_files,
    render_seed_project_text,
    seed_project_context,
)
from link_core.memory import memory_records  # noqa: E402
from link_core.query import query_link  # noqa: E402
from link_core.validation import validate_wiki  # noqa: E402
from link_core.wiki import build_wiki_cache, close_wiki_cache  # noqa: E402


class ProjectSeedCoreTests(unittest.TestCase):
    def test_discovers_allowlisted_project_context_files(self):
        tmp = Path(tempfile.mkdtemp(prefix="link-project-seed-test-"))
        project = tmp / "client-app"
        (project / ".cursor/rules").mkdir(parents=True)
        (project / "README.md").write_text("# Client App\n", encoding="utf-8")
        (project / "AGENTS.md").write_text("Use Link before answering.\n", encoding="utf-8")
        (project / ".cursor/rules/style.mdc").write_text("Keep replies concise.\n", encoding="utf-8")
        (project / ".env").write_text("SHOULD_NOT_BE_SCANNED=true\n", encoding="utf-8")

        files = discover_project_seed_files(project)

        paths = [item["path"] for item in files]
        self.assertEqual(paths, ["README.md", "AGENTS.md", ".cursor/rules/style.mdc"])

    def test_seed_project_writes_source_backed_context_and_rebuilds_indexes(self):
        tmp = Path(tempfile.mkdtemp(prefix="link-project-seed-test-"))
        project = tmp / "client-app"
        target = tmp / "link"
        project.mkdir()
        (project / "README.md").write_text(
            "# Client App\n\nThis project ships payments reporting for internal finance users.\n",
            encoding="utf-8",
        )
        (project / "AGENTS.md").write_text(
            "Before edits, check Link for client-app release context.\n",
            encoding="utf-8",
        )

        payload = seed_project_context(target, project, project_name="Client App")

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["wrote"])
        self.assertTrue((target / payload["raw_path"]).exists())
        self.assertTrue((target / payload["source_page"]).exists())
        self.assertTrue((target / "wiki/index.md").exists())
        self.assertTrue((target / "wiki/_backlinks.json").exists())
        source_text = (target / payload["source_page"]).read_text(encoding="utf-8")
        self.assertIn("> **TLDR:**", source_text)
        self.assertIn("## Summary", source_text)
        self.assertIn("## Raw Source", source_text)
        # The wiki page must carry the actual seeded context, not just file
        # names — recall packets excerpt this page, so this is what makes
        # day-one recall return something useful.
        self.assertIn("payments reporting for internal finance users", source_text)
        self.assertIn("check Link for client-app release context", source_text)

        validation = validate_wiki(target / "wiki")
        self.assertTrue(validation["passed"], validation["findings"])

        cache = build_wiki_cache(target / "wiki")
        try:
            query = query_link(
                target / "wiki",
                "what does client app do?",
                cache,
                memory_records(target / "wiki"),
                budget="small",
            )
        finally:
            close_wiki_cache(cache)
        page_titles = [page["title"] for page in query["wiki"]["pages"]]
        self.assertIn("Project seed: Client App", page_titles)

    def test_seed_project_is_safe_to_rerun_without_overwrite(self):
        tmp = Path(tempfile.mkdtemp(prefix="link-project-seed-test-"))
        project = tmp / "client-app"
        target = tmp / "link"
        project.mkdir()
        (project / "README.md").write_text("# Client App\n\nInitial context.\n", encoding="utf-8")

        first = seed_project_context(target, project, project_name="Client App")
        second = seed_project_context(target, project, project_name="Client App")

        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "already_seeded")
        code, text = render_seed_project_text(second)
        self.assertEqual(code, 0)
        self.assertIn("--overwrite", text)

    def test_seed_project_fails_closed_on_secret_values(self):
        tmp = Path(tempfile.mkdtemp(prefix="link-project-seed-test-"))
        project = tmp / "client-app"
        target = tmp / "link"
        project.mkdir()
        (project / "README.md").write_text("# Client App\n\napi key sk-" + ("a" * 25), encoding="utf-8")

        payload = seed_project_context(target, project, project_name="Client App")

        self.assertEqual(payload["status"], "needs_attention")
        self.assertEqual(payload["blocked_secret_count"], 1)
        self.assertFalse((target / "raw").exists())
        self.assertFalse((target / "wiki").exists())
        code, text = render_seed_project_text(payload)
        self.assertEqual(code, 1)
        self.assertIn("Blocked files:", text)

    def test_seed_project_dry_run_writes_nothing(self):
        tmp = Path(tempfile.mkdtemp(prefix="link-project-seed-test-"))
        project = tmp / "client-app"
        target = tmp / "link"
        project.mkdir()
        (project / "README.md").write_text("# Client App\n\nDry-run context.\n", encoding="utf-8")

        payload = seed_project_context(target, project, project_name="Client App", dry_run=True)

        self.assertEqual(payload["status"], "ok")
        self.assertFalse(payload["wrote"])
        self.assertFalse((target / "raw").exists())
        self.assertFalse((target / "wiki").exists())




class AdrDecisionMiningTests(unittest.TestCase):
    def test_seed_mines_adr_decision_sections_as_proposals(self):
        import tempfile
        project = Path(tempfile.mkdtemp(prefix="link-adr-")).resolve() / "app"
        (project / "docs" / "adr").mkdir(parents=True)
        (project / "README.md").write_text("# App\n", encoding="utf-8")
        (project / "docs/adr/0001-use-postgres.md").write_text(
            "# 1. Use PostgreSQL for persistence\n\n## Status\nAccepted\n\n"
            "## Decision\nWe will use PostgreSQL 16 on RDS; schema changes go through migrations only.\n",
            encoding="utf-8",
        )
        (project / "docs/adr/0002-notes.md").write_text("# 2. Notes\nNo decision section.\n", encoding="utf-8")

        result = seed_project_context(
            Path(tempfile.mkdtemp(prefix="link-adr-root-")).resolve(), project, dry_run=True
        )

        candidates = result["decision_candidates"]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["path"], "docs/adr/0001-use-postgres.md")
        self.assertIn("PostgreSQL 16", candidates[0]["memory"])
        self.assertIn("Use PostgreSQL for persistence", candidates[0]["memory"])
        # Proposal-only: dry run wrote nothing, and mining never writes memories.
        self.assertFalse(result["wrote"])

if __name__ == "__main__":
    unittest.main()
