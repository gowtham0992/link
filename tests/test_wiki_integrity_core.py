"""Is the compiled wiki still standing on its sources? Planted cases, and quiet on a healthy wiki."""
import os
import subprocess
import sys
import tempfile
import time
import unicodedata
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

    def test_a_changed_source_names_the_raw_file_and_claims_only_its_modified_time(self):
        raw = self.ws / "raw" / "agent-memory-session.md"
        later = time.time() + 5
        os.utime(raw, (later, later))  # a touch or a copy: only the time moved, so no more is claimed
        findings = {f["kind"]: f for f in wiki_findings(self.ws)["findings"]}
        for kind in ("source-changed", "cites-changed-source"):
            evidence = str(findings[kind]["evidence"])
            self.assertEqual(findings[kind]["raw"], "raw/agent-memory-session.md")
            self.assertIn("raw/agent-memory-session.md", evidence)
            self.assertIn("newer modified time", evidence)
            self.assertNotIn("changed after", evidence)

    def test_pages_in_hidden_folders_are_not_checked(self):
        concepts = self.ws / "wiki" / "concepts"
        for hidden in (self.ws / "wiki" / ".trash", concepts / ".obsidian"):
            hidden.mkdir()
            (hidden / "agent-memory.md").write_text((concepts / "agent-memory.md").read_text(encoding="utf-8"),
                                                    encoding="utf-8")
            (hidden / "ghost.md").write_text(_page("concept", "Ghost", "A claim. *Source: [[never-ingested]]*"),
                                             encoding="utf-8")
        self.assertEqual(self._kinds(), [], "an Obsidian vault's trash holds no live pages")

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

    def test_a_page_older_than_the_raw_change_stays_flagged_after_its_source_is_refreshed(self):
        raw = self.ws / "raw" / "agent-memory-session.md"
        source = self.ws / "wiki" / "sources" / "agent-memory-session.md"
        later = time.time() + 5
        os.utime(raw, (later, later))
        os.utime(source, (later + 5, later + 5))  # the source page was re-compiled; agent-memory.md was not
        flagged = self._kinds()
        self.assertNotIn(("source-changed", "wiki/sources/agent-memory-session.md"), flagged)
        self.assertIn(("cites-changed-source", "wiki/concepts/agent-memory.md"), flagged)

    def test_a_deleted_raw_file_is_reported(self):
        (self.ws / "raw" / "local-release-notes.md").unlink()
        flagged = self._kinds()
        self.assertIn(("source-raw-missing", "wiki/sources/local-release-notes.md"), flagged)

    def test_a_deleted_raw_file_with_a_space_in_its_name_is_reported(self):
        sources = self.ws / "wiki" / "sources"
        (sources / "meeting-notes.md").write_text(_page("source", "Meeting", "Raw: `raw/Meeting notes.md`"),
                                                  encoding="utf-8")
        flagged = wiki_findings(self.ws)["findings"]
        missing = [f for f in flagged if f["kind"] == "source-raw-missing"]
        self.assertEqual([f["page"] for f in missing], ["wiki/sources/meeting-notes.md"])
        self.assertIn("raw/Meeting notes.md", missing[0]["evidence"])
        (self.ws / "raw" / "Meeting notes.md").write_text("notes\n", encoding="utf-8")
        self.assertNotIn(("source-raw-missing", "wiki/sources/meeting-notes.md"), self._kinds(),
                         "the whole name is checked, not its first word")

    def test_a_missing_raw_file_is_reported_beside_one_still_there(self):
        source = self.ws / "wiki" / "sources" / "agent-memory-session.md"
        source.write_text(source.read_text(encoding="utf-8") + "\nAlso from `raw/follow-up.md`.\n",
                          encoding="utf-8")
        flagged = self._kinds()
        self.assertIn(("source-raw-missing", "wiki/sources/agent-memory-session.md"), flagged)
        self.assertIn(("cites-changed-source", "wiki/concepts/agent-memory.md"), flagged)

    def test_a_citation_by_alias_sees_its_source_change(self):
        (self.ws / "wiki" / "concepts" / "via-alias.md").write_text(
            _page("concept", "Via alias", "A claim. *Source: [[Memory demo note]]*"), encoding="utf-8")
        raw = self.ws / "raw" / "agent-memory-session.md"
        later = time.time() + 5
        os.utime(raw, (later, later))
        self.assertIn(("cites-changed-source", "wiki/concepts/via-alias.md"), self._kinds())

    def test_a_decomposed_file_name_matches_a_composed_link(self):
        sources = self.ws / "wiki" / "sources"
        decomposed = unicodedata.normalize("NFD", "café-notes.md")
        (sources / decomposed).write_text(_page("source", "Café notes", "Notes from the café."), encoding="utf-8")
        (self.ws / "wiki" / "concepts" / "coffee.md").write_text(
            _page("concept", "Coffee", "A claim. *Source: [[" + unicodedata.normalize("NFC", "café-notes") + "]]*"),
            encoding="utf-8")
        self.assertEqual([k for k, p in self._kinds() if p == "wiki/concepts/coffee.md"], [])

    def test_citation_forms_and_targets(self):
        concepts = self.ws / "wiki" / "concepts"
        (concepts / "bold.md").write_text(_page("concept", "Bold", "A claim. **Source:** [[agent-memory-session]]"),
                                          encoding="utf-8")
        (concepts / "resources.md").write_text(_page("concept", "Resources", "Resources: [[nothing-here]]"),
                                               encoding="utf-8")
        (concepts / "from-memory.md").write_text(
            _page("concept", "From memory", "A preference. *Source: [[prefer-local-personal-memory]]*"),
            encoding="utf-8")
        (concepts / "via-alias.md").write_text(  # the demo source page's alias
            _page("concept", "Via alias", "A claim. *Source: [[Memory demo note]]*"), encoding="utf-8")
        flagged = self._kinds()
        for page in ("bold", "resources", "from-memory", "via-alias"):
            self.assertEqual([k for k, p in flagged if p == f"wiki/concepts/{page}.md"], [], page)

    def test_the_same_file_name_in_two_folders_is_two_pages(self):
        entities = self.ws / "wiki" / "entities"
        (entities / "agent-memory.md").write_text(_page("entity", "Agent memory (product)",
                                                        "A product. *Source: [[gone-source]]*"), encoding="utf-8")
        flagged = self._kinds()
        self.assertIn(("cites-missing-source", "wiki/entities/agent-memory.md"), flagged)
        self.assertIn(("possible-duplicate", "wiki/entities/agent-memory.md"), flagged, "one name, two pages")

    def test_titles_in_any_script_and_shared_boilerplate(self):
        concepts = self.ws / "wiki" / "concepts"
        template = ("This page was compiled by the ingest agent from the sources listed below and follows the "
                    "standard layout used across the whole wiki for every concept that gets its own page. ")
        for index, (title, text) in enumerate([("記憶", "ローカルの記憶について。"), ("検索", "検索について。"),
                                               ("Один", "Первая страница."), ("Два", "Вторая страница.")]):
            (concepts / f"page-{index}.md").write_text(
                _page("concept", title, template * 2 + text + " *Source: [[agent-memory-session]]*"),
                encoding="utf-8")
        duplicates = [p for k, p in self._kinds() if k == "possible-duplicate"]
        self.assertEqual(duplicates, [], "distinct non-Latin titles and a shared template are not duplicates")

    def test_findings_make_the_command_exit_1(self):
        (self.ws / "wiki" / "concepts" / "ghost.md").write_text(
            _page("concept", "Ghost", "A claim. *Source: [[never-ingested]]*"), encoding="utf-8")
        result = subprocess.run([*LINK, "stale", str(self.ws), "--wiki"], capture_output=True, text=True,
                                env={**os.environ, "LINK_USAGE": "off"})
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_wiki_and_instructions_together_are_refused_not_half_run(self):
        result = subprocess.run([*LINK, "stale", str(self.ws), "--wiki", "--instructions"], capture_output=True,
                                text=True, env={**os.environ, "LINK_USAGE": "off"})
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("separate checks", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_the_command_reports_and_writes_nothing(self):
        before = {p: p.read_bytes() for p in (self.ws / "wiki").rglob("*.md")}
        out = subprocess.run([*LINK, "stale", str(self.ws), "--wiki"], capture_output=True, text=True, check=True,
                             env={**os.environ, "LINK_USAGE": "off"}).stdout
        self.assertIn("pages", out)
        self.assertEqual(before, {p: p.read_bytes() for p in (self.ws / "wiki").rglob("*.md")})


if __name__ == "__main__":
    unittest.main()
