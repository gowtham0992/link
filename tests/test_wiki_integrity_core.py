"""Is the compiled wiki still standing on its sources? Planted cases, and quiet on a healthy wiki."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.wiki_integrity import wiki_findings  # noqa: E402

LINK = [sys.executable, str(ROOT / "link.py")]


def _page(kind, title, body, aliases=()):
    alias_line = f"aliases: [{', '.join(repr(a) for a in aliases)}]\n" if aliases else ""
    return f"---\ntype: {kind}\ntitle: \"{title}\"\n{alias_line}---\n\n# {title}\n\n{body}\n"


class WikiIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ws = Path(self.temp.name) / "ws"
        subprocess.run([*LINK, "demo", str(self.ws), "--force"], check=True, capture_output=True,
                       env={**os.environ, "LINK_USAGE": "off"})

    def tearDown(self):
        self.temp.cleanup()

    def _kinds(self):
        return sorted((f["kind"], f["page"]) for f in wiki_findings(self.ws)["findings"])

    def test_the_demo_wiki_is_quiet(self):
        self.assertEqual(self._kinds(), [])

    def test_a_changed_raw_source_flags_every_page_built_on_it(self):
        raw = self.ws / "raw" / "agent-memory-session.md"
        later = time.time() + 5
        raw.write_text(raw.read_text(encoding="utf-8") + "\nMemory should now expire after 30 days.\n", encoding="utf-8")
        os.utime(raw, (later, later))
        flagged = self._kinds()
        self.assertIn(("source-changed", "wiki/sources/agent-memory-session.md"), flagged)
        cited_by = {page for kind, page in flagged if kind == "cites-changed-source"}
        self.assertIn("wiki/concepts/agent-memory.md", cited_by)
        self.assertNotIn("wiki/concepts/transformers.md", cited_by, "pages not built on it stay quiet")

    def test_citations_to_nothing_and_to_the_wiki_alone(self):
        concepts = self.ws / "wiki" / "concepts"
        (concepts / "ghost.md").write_text(_page("concept", "Ghost", "A claim. *Source: [[never-ingested]]*"),
                                           encoding="utf-8")
        (concepts / "echo.md").write_text(_page("concept", "Echo", "A claim. *Source: [[agent-memory]]*"),
                                          encoding="utf-8")
        flagged = self._kinds()
        self.assertIn(("cites-missing-source", "wiki/concepts/ghost.md"), flagged)
        self.assertIn(("wiki-only-support", "wiki/concepts/echo.md"), flagged)

    def test_two_pages_for_one_concept(self):
        concepts = self.ws / "wiki" / "concepts"
        body = (concepts / "agent-memory.md").read_text(encoding="utf-8").split("---", 2)[2]
        (concepts / "ai-memory.md").write_text(_page("concept", "AI memory", body), encoding="utf-8")
        (concepts / "local-first.md").write_text(
            _page("concept", "Local first", "*Source: [[local-release-notes]]*", aliases=["Local-first software"]),
            encoding="utf-8")
        duplicates = {page for kind, page in self._kinds() if kind == "possible-duplicate"}
        self.assertTrue({"wiki/concepts/ai-memory.md", "wiki/concepts/agent-memory.md"} & duplicates,
                        "the same text under a second name")
        self.assertTrue({"wiki/concepts/local-first.md", "wiki/concepts/local-first-software.md"} & duplicates,
                        "an alias that names another page")

    def test_the_command_reports_and_writes_nothing(self):
        before = {p: p.read_bytes() for p in (self.ws / "wiki").rglob("*.md")}
        out = subprocess.run([*LINK, "stale", str(self.ws), "--wiki"], capture_output=True, text=True, check=True,
                             env={**os.environ, "LINK_USAGE": "off"}).stdout
        self.assertIn("pages", out)
        self.assertEqual(before, {p: p.read_bytes() for p in (self.ws / "wiki").rglob("*.md")})


if __name__ == "__main__":
    unittest.main()
