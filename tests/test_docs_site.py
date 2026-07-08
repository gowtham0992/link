import re
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DocsSiteTests(unittest.TestCase):
    def docs_pages(self):
        return sorted((ROOT / "docs").glob("*.html"))

    def test_github_pages_site_references_existing_local_assets(self):
        pages = self.docs_pages()
        self.assertGreaterEqual(len(pages), 6)
        self.assertTrue((ROOT / "docs/.nojekyll").exists())

        all_refs = []
        for page in pages:
            html = page.read_text(encoding="utf-8")
            all_refs.extend(re.findall(r'(?:src|href)="(assets/[^"]+)"', html))
            for local_page in re.findall(r'href="([^":#]+\.html)"', html):
                self.assertTrue((ROOT / "docs" / local_page).exists(), f"{page.name} -> {local_page}")

        index_html = (ROOT / "docs/index.html").read_text(encoding="utf-8")
        self.assertIn("Give your agents", index_html)
        self.assertIn("MCP Registry", index_html)
        self.assertIn("scale.html", index_html)
        self.assertGreaterEqual(len(all_refs), 10)
        for ref in all_refs:
            self.assertTrue((ROOT / "docs" / ref).exists(), ref)

        scale_html = (ROOT / "docs/scale.html").read_text(encoding="utf-8")
        self.assertIn("bounded local memory", scale_html)
        self.assertIn("python3 scripts/smoke_large_wiki.py --pages 10000", scale_html)
        self.assertIn("Current Limits", scale_html)

        why_html = (ROOT / "docs/why-link.html").read_text(encoding="utf-8")
        self.assertIn("Compared With Alternatives", why_html)
        for competitor in ("Obsidian", "Mem0", "Letta", "Graphiti", "Built-in agent memory", "Plain RAG"):
            self.assertIn(competitor, why_html)

        ui_html = (ROOT / "docs/ui.html").read_text(encoding="utf-8")
        self.assertIn("http://127.0.0.1:3000/onboard", ui_html)
        self.assertIn("browser version of <code>lnk onboard</code>", ui_html)
        self.assertIn("MCP clients keep working after you close the browser", ui_html)
        self.assertIn("assets/link-ui-tour.gif", ui_html)

        cli_html = (ROOT / "docs/cli.html").read_text(encoding="utf-8")
        self.assertIn("assets/link-cli-tour.gif", cli_html)

        mcp_html = (ROOT / "docs/mcp.html").read_text(encoding="utf-8")
        self.assertIn("assets/link-mcp-agent-chat.gif", mcp_html)

    def test_docs_media_verifier_accepts_checked_in_assets(self):
        spec = importlib.util.spec_from_file_location(
            "generate_docs_media",
            ROOT / "scripts" / "generate_docs_media.py",
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        code, findings = module.validate_docs_media()

        self.assertEqual(code, 0, findings)
        self.assertEqual(findings, [])

    def test_github_pages_site_has_no_external_runtime_dependencies(self):
        index = ROOT / "docs/index.html"
        for page in self.docs_pages():
            html = page.read_text(encoding="utf-8")
            lower = html.lower()

            # The local-first / no-external-call guarantee holds for every page,
            # including the landing page.
            self.assertNotIn("fonts.googleapis.com", html)
            self.assertNotIn("fonts.gstatic.com", html)
            self.assertNotIn("../logo.svg", html)
            self.assertNotIn('<script src="http', lower)
            self.assertNotIn('<link rel="stylesheet" href="http', lower)

            # The landing page is a self-contained pre-rendered bundle with its
            # own inline runtime; the template-uniformity checks below apply to
            # the other pages.
            if page == index:
                continue

            self.assertIn('<script src="assets/site.js" defer></script>', html)
            self.assertNotIn("<script>", lower)

    def test_github_pages_analytics_is_docs_only_and_manual(self):
        site_js = (ROOT / "docs/assets/site.js").read_text(encoding="utf-8")

        self.assertIn("var POSTHOG_PROJECT_KEY =", site_js)
        self.assertNotIn("go/adminOrg", site_js)
        self.assertNotIn("/replay/", site_js)
        self.assertIn('autocapture: false', site_js)
        self.assertIn('capture_pageview: false', site_js)
        self.assertIn('disable_session_recording: true', site_js)
        self.assertIn('disable_persistence: true', site_js)
        self.assertIn('docs_viewed', site_js)
        self.assertIn('install_brew_copied', site_js)
        self.assertIn('install_pypi_copied', site_js)
        self.assertIn('demo_command_copied', site_js)
        self.assertIn('mcp_setup_viewed', site_js)
        self.assertIn('github_clicked', site_js)
        self.assertIn('pypi_clicked', site_js)
        self.assertIn('mcp_registry_clicked', site_js)

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        security = (ROOT / "docs/security.html").read_text(encoding="utf-8")
        self.assertIn("No telemetry in the installed CLI, MCP server, local web UI, or wiki runtime.", readme)
        self.assertIn("does not run inside Link, read local wiki data, or capture source/memory content", security)


if __name__ == "__main__":
    unittest.main()

class FoundingIdentityTests(unittest.TestCase):
    """New releases layer onto Link's founding story; they must never bury it.

    These are the identity claims that made Link through 1.5.0. If a landing
    or README rewrite drops one, this test fails and the author must decide
    deliberately — not by accident of enthusiasm for the newest feature.
    """

    PILLARS = {
        "source-backed": "provenance: memory that can say why it is known",
        "Markdown": "inspectable plain-file storage",
        "approve": "review-gated writes: agents propose, the user decides",
        "your machine": "local-first: no hosted profile",
        "every agent": "one memory shared across agents",
        "proof": "the first-run proof loop (lnk proof)",
    }

    @staticmethod
    def _flat(path):
        # Markdown and templates wrap lines; claims are judged on prose,
        # not line breaks.
        return " ".join((ROOT / path).read_text(encoding="utf-8").split())

    def test_landing_keeps_the_founding_claims(self):
        text = self._flat("docs/index.html")
        for phrase, meaning in self.PILLARS.items():
            self.assertIn(phrase, text, f"landing lost founding claim: {meaning}")

    def test_readme_keeps_the_founding_claims(self):
        text = self._flat("README.md")
        for phrase, meaning in self.PILLARS.items():
            variants = {
                "approve": ("approve", "approval"),
                "every agent": ("every agent", "across multiple agents", "different agents", "across agents"),
            }.get(phrase, (phrase,))
            self.assertTrue(
                any(variant in text for variant in variants),
                f"README lost founding claim: {meaning}",
            )

