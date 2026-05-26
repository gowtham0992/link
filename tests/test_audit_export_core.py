import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.audit_export import build_compliance_export, log_entries, write_compliance_export  # noqa: E402
from link_core.log import append_log  # noqa: E402
from link_core.schema import migrate_wiki  # noqa: E402
from link_core.wiki import build_backlinks  # noqa: E402


class AuditExportCoreTests(unittest.TestCase):
    def make_wiki(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="link-audit-export-"))
        wiki = root / "wiki"
        migrate_wiki(wiki)
        (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
        (wiki / "log.md").write_text("# Link Wiki Log\n\n", encoding="utf-8")
        memory = (
            "---\n"
            "type: memory\n"
            "title: Prefer Local Memory\n"
            "memory_type: preference\n"
            "scope: user\n"
            "status: active\n"
            "date_captured: \"2026-05-25T00:00:00Z\"\n"
            "source: unit test\n"
            "review_status: reviewed\n"
            "---\n\n"
            "# Prefer Local Memory\n\n"
            "> **TLDR:** User prefers local memory.\n\n"
            "## Memory\n\nUser prefers local memory.\n\n"
            "## Source\n\nunit test\n"
        )
        (wiki / "memories/prefer-local-memory.md").write_text(memory, encoding="utf-8")
        (wiki / "_backlinks.json").write_text(json.dumps(build_backlinks(wiki, body_only=False)), encoding="utf-8")
        append_log(wiki, "2026-05-25T00:00:00Z", "remember", "Prefer Local Memory", ["Created memory page"])
        return wiki

    def test_log_entries_parse_recent_operations(self):
        wiki = self.make_wiki()

        entries = log_entries(wiki)

        self.assertEqual(entries[-1]["operation"], "remember")
        self.assertEqual(entries[-1]["description"], "Prefer Local Memory")
        self.assertEqual(entries[-1]["details"], ["Created memory page"])

    def test_build_compliance_export_excludes_memory_body(self):
        wiki = self.make_wiki()

        payload = build_compliance_export(wiki, version="1.3.0")

        self.assertEqual(payload["schema"], "link-compliance-export-v1")
        self.assertEqual(payload["status"]["version"], "1.3.0")
        self.assertEqual(payload["memory_profile"]["memory_count"], 1)
        self.assertNotIn("body", payload["memories"][0])
        self.assertIn("Raw source contents", payload["privacy_note"])

    def test_write_compliance_export_writes_json(self):
        wiki = self.make_wiki()
        payload = build_compliance_export(wiki, version="1.3.0")
        output = wiki.parent / "audit.json"

        write_compliance_export(output, payload)

        data = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], "link-compliance-export-v1")


if __name__ == "__main__":
    unittest.main()
