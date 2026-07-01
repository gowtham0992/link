import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.schema import CURRENT_SCHEMA_VERSION, migrate_wiki, schema_status, write_schema  # noqa: E402


class SchemaCoreTests(unittest.TestCase):
    def test_missing_schema_needs_migration(self):
        wiki = Path(tempfile.mkdtemp(prefix="link-schema-core-")) / "wiki"

        status = schema_status(wiki)

        self.assertEqual(status["status"], "missing")
        self.assertTrue(status["needs_migration"])
        self.assertEqual(status["current_version"], CURRENT_SCHEMA_VERSION)

    def test_migrate_wiki_writes_marker_and_directories(self):
        wiki = Path(tempfile.mkdtemp(prefix="link-schema-core-")) / "wiki"

        result = migrate_wiki(wiki)

        self.assertTrue(result["ok"])
        self.assertTrue(result["migrated"])
        self.assertIn("wrote _link_schema.json", result["changes"])
        self.assertTrue((wiki / "memories").is_dir())
        self.assertEqual(schema_status(wiki)["status"], "current")

    def test_migrate_aged_schema_fixture_preserves_existing_pages(self):
        wiki = Path(tempfile.mkdtemp(prefix="link-schema-aged-")) / "wiki"
        (wiki / "sources").mkdir(parents=True)
        (wiki / "concepts").mkdir()
        (wiki / "sources" / "release-notes.md").write_text(
            "---\ntype: source\ntitle: Release notes\n---\n"
            "# Release notes\n\n> **TLDR:** Older source page.\n",
            encoding="utf-8",
        )
        (wiki / "concepts" / "agent-memory.md").write_text(
            "---\ntype: concept\ntitle: Agent memory\n---\n"
            "# Agent memory\n\n> **TLDR:** Existing concept.\n",
            encoding="utf-8",
        )
        old_marker = {"schema": "link-wiki", "version": 0, "updated_at": "2026-01-01T00:00:00Z"}
        (wiki / "_link_schema.json").write_text(json.dumps(old_marker), encoding="utf-8")

        result = migrate_wiki(wiki)

        self.assertTrue(result["ok"])
        self.assertTrue(result["migrated"])
        self.assertEqual(result["previous"]["status"], "old")
        self.assertIn("wrote _link_schema.json", result["changes"])
        self.assertTrue((wiki / "memories").is_dir())
        self.assertTrue((wiki / "comparisons").is_dir())
        self.assertIn("Older source page", (wiki / "sources" / "release-notes.md").read_text(encoding="utf-8"))
        self.assertIn("Existing concept", (wiki / "concepts" / "agent-memory.md").read_text(encoding="utf-8"))
        self.assertEqual(schema_status(wiki)["status"], "current")

    def test_migrate_wiki_is_idempotent(self):
        wiki = Path(tempfile.mkdtemp(prefix="link-schema-core-")) / "wiki"
        migrate_wiki(wiki)

        result = migrate_wiki(wiki)

        self.assertTrue(result["ok"])
        self.assertFalse(result["migrated"])
        self.assertEqual(result["changes"], [])

    def test_migrate_wiki_refuses_newer_schema(self):
        wiki = Path(tempfile.mkdtemp(prefix="link-schema-core-")) / "wiki"
        wiki.mkdir()
        (wiki / "_link_schema.json").write_text(
            json.dumps({"schema": "link-wiki", "version": CURRENT_SCHEMA_VERSION + 1}),
            encoding="utf-8",
        )

        result = migrate_wiki(wiki)

        self.assertFalse(result["ok"])
        self.assertFalse(result["migrated"])
        self.assertEqual(result["schema"]["status"], "newer")
        self.assertIn("newer than this runtime", result["error"])

    def test_migrate_wiki_refuses_invalid_schema(self):
        wiki = Path(tempfile.mkdtemp(prefix="link-schema-core-")) / "wiki"
        wiki.mkdir()
        (wiki / "_link_schema.json").write_text("{not-json", encoding="utf-8")

        result = migrate_wiki(wiki)

        self.assertFalse(result["ok"])
        self.assertFalse(result["migrated"])
        self.assertEqual(result["schema"]["status"], "invalid")
        self.assertIn("invalid schema marker", result["error"])

    def test_schema_status_rejects_wrong_schema_name(self):
        wiki = Path(tempfile.mkdtemp(prefix="link-schema-core-")) / "wiki"
        wiki.mkdir()
        (wiki / "_link_schema.json").write_text(
            json.dumps({"schema": "other-wiki", "version": CURRENT_SCHEMA_VERSION}),
            encoding="utf-8",
        )

        status = schema_status(wiki)

        self.assertEqual(status["status"], "invalid")
        self.assertIn("schema must be", status["error"])

    def test_write_schema_records_current_version(self):
        wiki = Path(tempfile.mkdtemp(prefix="link-schema-core-")) / "wiki"

        payload = write_schema(wiki)

        self.assertEqual(payload["schema"], "link-wiki")
        self.assertEqual(payload["version"], CURRENT_SCHEMA_VERSION)
        self.assertTrue((wiki / "_link_schema.json").exists())


if __name__ == "__main__":
    unittest.main()
