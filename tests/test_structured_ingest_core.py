import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.demo import create_demo_workspace  # noqa: E402
from link_core.structured_ingest import (  # noqa: E402
    CHEZMOI_ADAPTER,
    StructuredIngestError,
    apply_structured_ingest,
    plan_structured_ingest,
)
from link_core.validation import validate_wiki  # noqa: E402


def _export(path: Path, *, setup_text: str = "Setup body") -> None:
    records = [
        {
            "record_type": "manifest",
            "schema": "chezmoi-documentation-graph-export/v1",
            "title": "chezmoi docs",
            "description": "Test export.",
            "site_origin": "https://chezmoi.io",
            "source_repository": "https://github.com/twpayne/chezmoi",
            "source_revision": "abc123",
            "published_branch": "gh-pages",
            "published_revision": "def456",
            "generated_at": "2026-08-21T00:00:00Z",
            "page_count": 3,
            "navigation_page_count": 3,
            "relationship_count": 1,
            "external_relationship_count": 0,
            "internal_page_relationship_count": 1,
            "internal_asset_or_route_relationship_count": 0,
            "record_order": ["manifest", "navigation", "page", "relationship"],
        },
        {
            "record_type": "navigation",
            "title": "Navigation",
            "tree": [
                {
                    "type": "section",
                    "title": "User guide",
                    "children": [
                        {"type": "page", "title": "Setup", "page_id": "https://chezmoi.io/user-guide/setup/"}
                    ],
                },
                {
                    "type": "section",
                    "title": "Reference",
                    "children": [
                        {"type": "page", "title": "Commands", "page_id": "https://chezmoi.io/reference/commands/"},
                        {"type": "page", "title": "Release history", "page_id": "https://chezmoi.io/reference/release-history/"},
                    ],
                },
            ],
        },
        {
            "record_type": "page",
            "id": "https://chezmoi.io/user-guide/setup/",
            "title": "Setup",
            "canonical_url": "https://chezmoi.io/user-guide/setup/",
            "markdown": f"# Setup\n\n{setup_text}",
            "source_path": "user-guide/setup.md",
            "navigation_path": ["User guide", "Setup"],
            "outgoing_relationship_count": 1,
        },
        {
            "record_type": "page",
            "id": "https://chezmoi.io/reference/commands/",
            "title": "Commands",
            "canonical_url": "https://chezmoi.io/reference/commands/",
            "markdown": "# Commands\n\nRun commands.",
            "source_path": "reference/commands/index.md",
            "navigation_path": ["Reference", "Commands"],
            "outgoing_relationship_count": 0,
        },
        {
            "record_type": "page",
            "id": "https://chezmoi.io/reference/release-history/",
            "title": "Release history",
            "canonical_url": "https://chezmoi.io/reference/release-history/",
            "markdown": "# Release history\n\nOld releases.",
            "source_path": "reference/release-history.md",
            "navigation_path": ["Reference", "Release history"],
            "outgoing_relationship_count": 0,
        },
        {
            "record_type": "relationship",
            "relationship": "links_to",
            "source_page_id": "https://chezmoi.io/user-guide/setup/",
            "target_kind": "internal_page",
            "target_page_id": "https://chezmoi.io/reference/commands/",
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


class StructuredIngestCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="link-structured-ingest-test-"))
        self.target = self.tmp / "link"
        create_demo_workspace(self.target, source_root=ROOT)
        self.source = self.target / "raw/chezmoi-docs/export.jsonl"
        _export(self.source)

    def test_plan_is_read_only_and_reports_outputs(self):
        plan = plan_structured_ingest(
            self.target,
            Path("raw/chezmoi-docs/export.jsonl"),
            adapter=CHEZMOI_ADAPTER,
            excludes=["Reference / Release history"],
        )

        self.assertTrue(plan["can_apply"])
        self.assertEqual(plan["summary"]["page_count"], 2)
        self.assertEqual(len(plan["outputs"]), 3)
        self.assertFalse((self.target / plan["manifest_path"]).exists())
        self.assertFalse((self.target / "wiki/sources/chezmoi-docs-user-guide-setup.md").exists())

    def test_apply_records_provenance_and_validates(self):
        plan = plan_structured_ingest(
            self.target,
            self.source,
            adapter=CHEZMOI_ADAPTER,
            excludes=["Reference / Release history"],
        )
        result = apply_structured_ingest(plan)

        self.assertTrue(result["applied"])
        self.assertTrue(result["validation"]["passed"])
        manifest = json.loads((self.target / result["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["adapter"], CHEZMOI_ADAPTER)
        self.assertEqual(len(manifest["outputs"]), 3)
        self.assertFalse((self.target / "wiki/sources/chezmoi-docs-reference-release-history.md").exists())
        self.assertTrue(validate_wiki(self.target / "wiki")["passed"])

    def test_manual_change_becomes_conflict(self):
        first = plan_structured_ingest(self.target, self.source, adapter=CHEZMOI_ADAPTER)
        apply_structured_ingest(first)
        page = self.target / "wiki/sources/chezmoi-docs-user-guide-setup.md"
        page.write_text(page.read_text(encoding="utf-8") + "\nmanual edit\n", encoding="utf-8")
        _export(self.source, setup_text="Changed setup body")

        plan = plan_structured_ingest(self.target, self.source, adapter=CHEZMOI_ADAPTER)

        self.assertFalse(plan["can_apply"])
        self.assertEqual(plan["conflicts"][0]["path"], "wiki/sources/chezmoi-docs-user-guide-setup.md")
        with self.assertRaises(StructuredIngestError):
            apply_structured_ingest(plan)

    def test_managed_update_and_prune_are_explicit(self):
        first = plan_structured_ingest(self.target, self.source, adapter=CHEZMOI_ADAPTER)
        apply_structured_ingest(first)
        _export(self.source, setup_text="Changed setup body")
        update = plan_structured_ingest(
            self.target,
            self.source,
            adapter=CHEZMOI_ADAPTER,
            excludes=["Reference / Release history"],
            prune=True,
        )

        actions = {item["path"]: item["action"] for item in update["changes"]}
        self.assertEqual(actions["wiki/sources/chezmoi-docs-user-guide-setup.md"], "update")
        self.assertEqual(actions["wiki/sources/chezmoi-docs-reference-release-history.md"], "delete")
        apply_structured_ingest(update)
        self.assertFalse((self.target / "wiki/sources/chezmoi-docs-reference-release-history.md").exists())
        self.assertIn("Changed setup body", (self.target / "wiki/sources/chezmoi-docs-user-guide-setup.md").read_text(encoding="utf-8"))

    def test_rejects_unknown_schema_and_outside_source(self):
        outside = self.tmp / "outside.jsonl"
        _export(outside)
        with self.assertRaises(StructuredIngestError):
            plan_structured_ingest(self.target, outside, adapter=CHEZMOI_ADAPTER)
        with self.assertRaises(StructuredIngestError):
            plan_structured_ingest(self.target, self.source, adapter="unknown")


if __name__ == "__main__":
    unittest.main()
