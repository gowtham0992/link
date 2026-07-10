import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

import link_core.doctor as doctor_module  # noqa: E402
from link_core.doctor import (  # noqa: E402
    DoctorReport,
    apply_doctor_fixes,
    build_doctor_report,
    doctor_validation_errors,
    find_dead_links,
    find_isolated_pages,
    find_pages_missing_source_sections,
    find_pages_missing_summaries,
    find_source_count_mismatches,
    find_unindexed_pages,
    format_validation_error_summary,
    join_limited,
    repair_source_page_validation_shape,
    repair_validation_findings,
    required_paths,
    render_doctor_report,
    raw_source_refs,
    source_section_links,
)
from link_core.log import append_log  # noqa: E402
from link_core.operations import begin_operation  # noqa: E402


class DoctorCoreTests(unittest.TestCase):
    def test_render_healthy_report_with_fixes_and_warnings(self):
        report = DoctorReport("/tmp/link", fix_requested=True)
        report.fixes.append("rebuilt wiki/index.md")
        report.add_ok("OK required wiki structure")
        report.add_warning("memories need review: example")

        text = render_doctor_report(report)

        self.assertIn("Link doctor: /tmp/link", text)
        self.assertIn("Fixes applied:\n- rebuilt wiki/index.md", text)
        self.assertIn("OK required wiki structure", text)
        self.assertIn("Warnings:\n- memories need review: example", text)
        self.assertIn("Result: healthy", text)

    def test_render_error_report(self):
        report = DoctorReport("/tmp/link")
        report.add_error("dead wikilinks: a -> b")

        text = render_doctor_report(report)

        self.assertFalse(report.healthy)
        self.assertIn("Errors:\n- dead wikilinks: a -> b", text)
        self.assertIn("Result: needs attention", text)

    def test_validation_errors_are_filtered_to_doctor_codes(self):
        payload = {
            "findings": [
                {"severity": "error", "code": "missing_required_section", "path": "sources/a.md", "message": "bad"},
                {"severity": "error", "code": "secret_value", "path": "sources/token.md", "message": "redact"},
                {"severity": "error", "code": "dead_wikilink", "path": "concepts/b.md", "message": "missing"},
                {"severity": "warning", "code": "missing_summary", "path": "sources/c.md", "message": "warn"},
            ]
        }

        findings = doctor_validation_errors(payload)
        summary = format_validation_error_summary(findings)

        self.assertEqual(len(findings), 2)
        self.assertIn("sources/a.md [missing_required_section] bad", summary)
        self.assertIn("sources/token.md [secret_value] redact", summary)
        self.assertNotIn("dead_wikilink", summary)

    def test_join_limited_caps_items(self):
        text = join_limited("items: ", [str(index) for index in range(10)], limit=3)

        self.assertEqual(text, "items: 0, 1, 2")

    def test_apply_doctor_fixes_initializes_workspace(self):
        root = Path(tempfile.mkdtemp(prefix="link-doctor-fixes-"))

        fixes = apply_doctor_fixes(root)

        self.assertTrue((root / "raw").is_dir())
        self.assertTrue((root / "wiki/index.md").exists())
        self.assertTrue((root / "wiki/log.md").exists())
        self.assertTrue((root / "wiki/_backlinks.json").exists())
        self.assertTrue((root / "wiki/_link_schema.json").exists())
        self.assertTrue((root / "wiki/sources").is_dir())
        self.assertTrue((root / "wiki/memories").is_dir())
        self.assertIn("created raw", fixes)
        self.assertIn("created wiki/log.md", fixes)
        self.assertIn("created wiki/index.md", fixes)

    def test_apply_doctor_fixes_refreshes_stale_workspace_runtime(self):
        root = Path(tempfile.mkdtemp(prefix="link-doctor-runtime-"))
        (root / "link.py").write_text("# old runtime\n", encoding="utf-8")
        (root / "link_core").mkdir()
        (root / "link_core" / "version.py").write_text(
            'LINK_VERSION = "1.0.0"\n', encoding="utf-8",
        )

        fixes = apply_doctor_fixes(root)

        self.assertTrue(any("refreshed workspace runtime 1.0.0" in fix for fix in fixes))
        refreshed = (root / "link_core" / "version.py").read_text(encoding="utf-8")
        self.assertNotIn('"1.0.0"', refreshed)
        self.assertGreater((root / "link.py").stat().st_size, 100)

    def test_apply_doctor_fixes_leaves_current_runtime_alone(self):
        root = Path(tempfile.mkdtemp(prefix="link-doctor-runtime-"))

        fixes = apply_doctor_fixes(root)  # no runtime copy at all

        self.assertFalse(any("workspace runtime" in fix for fix in fixes))

    def test_required_paths_lists_workspace_shape(self):
        root = Path("/tmp/link")
        paths = [path.relative_to(root).as_posix() for path in required_paths(root)]

        self.assertIn("raw", paths)
        self.assertIn("wiki/index.md", paths)
        self.assertIn("wiki/memories", paths)

    def test_build_doctor_report_uses_shared_health_checks(self):
        root = Path(tempfile.mkdtemp(prefix="link-doctor-report-"))
        apply_doctor_fixes(root)

        report = build_doctor_report(
            root,
            skip_dirs={".git", "__pycache__"},
            secret_name_patterns=(".env", "*.key"),
            skip_suffixes={".png", ".pyc"},
        )

        self.assertTrue(report.healthy)
        self.assertIn("OK required wiki structure", report.ok)
        self.assertIn("OK backlinks are current", report.ok)
        self.assertIn("OK no interrupted Link operations", report.ok)
        self.assertIn("OK no sensitive-looking filenames", report.ok)

    def test_build_doctor_report_uses_cache_backed_backlinks(self):
        root = Path(tempfile.mkdtemp(prefix="link-doctor-report-cache-"))
        apply_doctor_fixes(root)

        with patch.object(
            doctor_module,
            "build_backlinks_from_cache",
            wraps=doctor_module.build_backlinks_from_cache,
        ) as cached_backlinks:
            report = build_doctor_report(root)

        self.assertTrue(report.healthy)
        self.assertGreaterEqual(cached_backlinks.call_count, 2)

    def test_build_doctor_report_fails_on_stale_operation_marker(self):
        root = Path(tempfile.mkdtemp(prefix="link-doctor-report-"))
        apply_doctor_fixes(root)
        begin_operation(root / "wiki", "remember", "Saved memory", timestamp="2000-01-01T00:00:00Z")

        report = build_doctor_report(root)

        self.assertFalse(report.healthy)
        self.assertTrue(any("incomplete Link operations need review" in error for error in report.errors))

    def test_build_doctor_report_fails_on_tampered_audit_log(self):
        root = Path(tempfile.mkdtemp(prefix="link-doctor-report-"))
        apply_doctor_fixes(root)
        wiki_dir = root / "wiki"
        append_log(
            wiki_dir,
            "2026-05-17T00:00:00Z",
            "remember",
            "Prefer local memory",
            ["Created: memories/prefer-local-memory.md", "Scope: user"],
        )
        log_path = wiki_dir / "log.md"
        log_path.write_text(
            log_path.read_text(encoding="utf-8").replace("Scope: user", "Scope: team"),
            encoding="utf-8",
        )

        report = build_doctor_report(root)

        self.assertFalse(report.healthy)
        self.assertTrue(any("audit log hash chain broken" in error for error in report.errors))

    def test_page_health_helpers_find_doctor_findings(self):
        root = Path(tempfile.mkdtemp(prefix="link-doctor-core-"))
        wiki = root / "wiki"
        (wiki / "concepts").mkdir(parents=True)
        (wiki / "sources").mkdir()
        (wiki / "index.md").write_text("# Index\n\n[[agent-memory]]\n", encoding="utf-8")
        (wiki / "log.md").write_text("# Log\n", encoding="utf-8")
        (wiki / "concepts" / "agent-memory.md").write_text(
            "---\n"
            "type: concept\n"
            "title: Agent Memory\n"
            "source_count: 2\n"
            "---\n"
            "# Agent Memory\n\n"
            "> **TLDR:** Durable context.\n\n"
            "Links to [[missing-page]].\n\n"
            "## Sources\n\n"
            "- [[source-one]]\n",
            encoding="utf-8",
        )
        (wiki / "concepts" / "orphan.md").write_text(
            "---\ntype: concept\ntitle: Orphan\n---\n# Orphan\n\nNo summary.\n",
            encoding="utf-8",
        )
        (wiki / "concepts" / "no-sources.md").write_text(
            "---\ntype: concept\ntitle: No Sources\n---\n# No Sources\n\n> **TLDR:** Missing sources.\n",
            encoding="utf-8",
        )
        (wiki / "sources" / "source-one.md").write_text(
            "---\ntype: source\ntitle: Source One\n---\n# Source One\n\n> **TLDR:** Source.\n\n[[agent-memory]]\n",
            encoding="utf-8",
        )

        self.assertEqual(find_dead_links(wiki), ["agent-memory -> missing-page"])
        self.assertEqual(find_unindexed_pages(wiki), ["no-sources", "orphan", "source-one"])
        self.assertEqual(find_pages_missing_summaries(wiki), ["concepts/orphan.md"])
        self.assertEqual(find_pages_missing_source_sections(wiki), ["concepts/no-sources.md", "concepts/orphan.md"])
        self.assertEqual(find_source_count_mismatches(wiki), ["concepts/agent-memory.md source_count=2, sources section has 1"])
        self.assertEqual(find_isolated_pages(wiki), ["concepts/no-sources.md", "concepts/orphan.md"])

    def test_source_section_links_reads_only_sources_section(self):
        links = source_section_links("Intro [[outside]]\n\n## Sources\n\n- [[inside]]\n\n## Next\n\n[[later]]")

        self.assertEqual(links, {"inside"})

    def test_raw_source_refs_finds_inline_and_code_refs(self):
        refs = raw_source_refs("Captured from `raw/one.md` and raw/two.md.")

        self.assertEqual(refs, ["raw/one.md", "raw/two.md"])

    def test_repair_source_page_validation_shape(self):
        root = Path(tempfile.mkdtemp(prefix="link-doctor-repair-"))
        page = root / "source.md"
        page.write_text(
            "---\ntype: source\ntitle: Agent Memory Session\n---\n\n"
            "# Agent Memory Session\n\n"
            "Captured from raw/agent-memory-session.md.\n",
            encoding="utf-8",
        )

        changed = repair_source_page_validation_shape(page, [
            {"code": "missing_summary", "message": "Page should include a TLDR or Query summary."},
            {"code": "missing_required_section", "message": "Missing required section: ## Summary"},
            {"code": "missing_required_section", "message": "Missing required section: ## Raw Source"},
        ])

        text = page.read_text(encoding="utf-8")
        self.assertTrue(changed)
        self.assertIn("> **TLDR:** Agent Memory Session source notes.", text)
        self.assertIn("## Summary", text)
        self.assertIn("## Raw Source", text)
        self.assertIn("`raw/agent-memory-session.md`", text)

    def test_repair_validation_findings_repairs_source_pages_only(self):
        root = Path(tempfile.mkdtemp(prefix="link-doctor-repair-findings-"))
        wiki = root / "wiki"
        (wiki / "sources").mkdir(parents=True)
        (wiki / "sources" / "session.md").write_text(
            "---\ntype: source\ntitle: Session\n---\n\n"
            "# Session\n\nCaptured from raw/session.md.\n",
            encoding="utf-8",
        )

        fixes = repair_validation_findings(wiki)

        self.assertEqual(fixes, ["repaired validation shape for wiki/sources/session.md"])
        repaired = (wiki / "sources" / "session.md").read_text(encoding="utf-8")
        self.assertIn("## Summary", repaired)
        self.assertIn("## Raw Source", repaired)


if __name__ == "__main__":
    unittest.main()
