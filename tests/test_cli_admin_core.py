import unittest
from pathlib import Path

from mcp_package.link_core.cli_admin import (
    render_backup_created_text,
    render_backup_list_text,
    render_backup_restore_text,
    render_migrate_text,
    render_rebuild_backlinks_text,
    render_rebuild_index_text,
    render_status_text,
    render_validate_text,
)
from mcp_package.link_core.mcp_verify import display_command


class CliAdminCoreTests(unittest.TestCase):
    def test_render_validate_passed(self):
        code, text = render_validate_text({
            "passed": True,
            "findings": [],
            "error_count": 0,
            "warning_count": 0,
        }, wiki_dir="/tmp/link/wiki")

        self.assertEqual(code, 0)
        self.assertIn("OK wiki pages satisfy the ingest validation gate", text)
        self.assertIn("Result: passed (0 errors, 0 warnings)", text)

    def test_render_validate_failed(self):
        code, text = render_validate_text({
            "passed": False,
            "findings": [{
                "severity": "error",
                "path": "sources/source.md",
                "code": "missing_summary",
                "message": "Missing summary.",
            }],
            "error_count": 1,
            "warning_count": 0,
        }, wiki_dir="/tmp/link/wiki")

        self.assertEqual(code, 1)
        self.assertIn("ERROR sources/source.md [missing_summary] Missing summary.", text)

    def test_render_migrate_current(self):
        code, text = render_migrate_text({
            "ok": True,
            "previous": {"status": "missing"},
            "schema": {"status": "current", "version": 1},
            "changes": ["created schema marker"],
        }, wiki_dir="/tmp/link/wiki")

        self.assertEqual(code, 0)
        self.assertIn("Previous schema: missing", text)
        self.assertIn("Result: current", text)

    def test_render_status_not_ready(self):
        code, text = render_status_text({
            "version": "1.1.0",
            "ready": False,
            "page_count": 1,
            "content_page_count": 0,
            "memory_count": 0,
            "active_memory_count": 0,
            "needs_review_count": 0,
            "search_backend": "sqlite-fts",
            "schema": {"status": "missing"},
            "missing": ["wiki/index.md"],
            "validation": {"checked": False},
            "warnings": [{"code": "missing_schema", "message": "Schema marker missing."}],
            "next_actions": [{"tool": "migrate_wiki", "label": "migrate schema", "arguments": {}}],
        }, wiki_dir="/tmp/link/wiki", version="1.1.0")

        self.assertEqual(code, 1)
        self.assertIn("Ready: no", text)
        self.assertIn("Missing: wiki/index.md", text)
        self.assertIn("migrate_wiki: migrate schema", text)
        self.assertIn(f"Run: lnk migrate {Path('/tmp/link/wiki').parent}", text)

    def test_render_status_ready_includes_human_query_command(self):
        code, text = render_status_text({
            "version": "1.1.0",
            "ready": True,
            "page_count": 3,
            "content_page_count": 2,
            "memory_count": 1,
            "active_memory_count": 1,
            "needs_review_count": 0,
            "search_backend": "sqlite-fts",
            "schema": {"status": "current", "version": 1},
            "missing": [],
            "validation": {"checked": True, "passed": True, "error_count": 0, "warning_count": 0},
            "warnings": [],
            "next_actions": [{"tool": "query_link", "label": "answer with compact local context", "arguments": {"query": "<user task>"}}],
        }, wiki_dir="/tmp/link/wiki", version="1.1.0")

        self.assertEqual(code, 0)
        self.assertIn("query_link: answer with compact local context", text)
        self.assertIn("Run: lnk query", text)
        self.assertIn("what should I know before continuing?", text)
        self.assertIn("/tmp/link", text)

    def test_render_backup_list(self):
        code, text = render_backup_list_text({
            "backup_dir": "/tmp/link/.link-backups",
            "warnings": [{"backup": "bad.tar.gz", "error": "corrupt"}],
            "backups": [{"name": "link-20260516.tar.gz", "bytes": 12}],
        })

        self.assertEqual(code, 0)
        self.assertIn("Warning: could not read backup bad.tar.gz: corrupt", text)
        self.assertIn("link-20260516.tar.gz (12 bytes)", text)

    def test_render_backup_created(self):
        code, text = render_backup_created_text({
            "path": "/tmp/link/.link-backups/link.tar.gz",
            "included": ["wiki", "LINK.md"],
            "file_count": 2,
            "bytes": 100,
            "pruned": ["old.tar.gz"],
        })

        self.assertEqual(code, 0)
        self.assertIn("Included: wiki, LINK.md", text)
        self.assertIn("raw/ was excluded", text)
        self.assertIn("Pruned old backups: old.tar.gz", text)

    def test_render_backup_restore_includes_integrity_result(self):
        code, text = render_backup_restore_text({
            "name": "link.tar.gz",
            "backup": "/tmp/link/.link-backups/link.tar.gz",
            "restore_roots": ["wiki"],
            "skipped_roots": [],
            "file_count": 3,
            "restored": True,
            "safety_backup": {"path": "/tmp/link/.link-backups/pre-restore.tar.gz"},
            "integrity": {
                "checked": True,
                "passed": True,
                "error_count": 0,
                "warning_count": 0,
            },
        }, target="/tmp/link")

        self.assertEqual(code, 0)
        self.assertIn("Safety backup:", text)
        self.assertIn("Integrity: passed (0 errors, 0 warnings)", text)
        self.assertIn("Result: restored", text)

    def test_render_rebuild_outputs(self):
        backlinks_code, backlinks_text = render_rebuild_backlinks_text(
            out_path="/tmp/link/wiki/_backlinks.json",
            page_count=2,
            edge_count=3,
        )
        index_code, index_text = render_rebuild_index_text({
            "page_count": 2,
            "source_count": 1,
            "memory_count": 1,
        }, index_path="/tmp/link/wiki/index.md")

        self.assertEqual(backlinks_code, 0)
        self.assertIn("Edges: 3", backlinks_text)
        self.assertEqual(index_code, 0)
        root = Path("/tmp/link/wiki").parent
        rebuild_command = display_command(["python3", str(root / "link.py"), "rebuild-backlinks", str(root)])
        self.assertIn(f"Next: run {rebuild_command} before validation", index_text)


if __name__ == "__main__":
    unittest.main()
