"""Claim provenance: memories about code carry line anchors that are re-verified."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.provenance import (  # noqa: E402
    add_anchors_to_page,
    find_anchors,
    page_anchors,
    symbol_candidates,
    verify_anchors,
)
from link_core.staleness import StalenessChecker  # noqa: E402

SOURCE = '''import yaml


def parse_config(path):
    return yaml.safe_load(open(path))


class RetryPolicy:
    max_attempts = 5
'''


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True, text=True, env={
        **os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}).stdout


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="link-provenance-")
        self.repo = Path(self.temp.name)
        _git(self.repo, "init", "-q", "--initial-branch", "main")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "app.py").write_text(SOURCE, encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "seed")
        self.rid = _git(self.repo, "rev-list", "--max-parents=0", "HEAD").strip()[:12]

    def tearDown(self):
        self.temp.cleanup()

    def test_symbols_are_recognised(self):
        self.assertEqual(symbol_candidates("`parse_config` and RetryPolicy, not Tuesday or deploy"),
                         ["parse_config", "RetryPolicy"])

    def test_file_plus_symbol_gets_a_line_anchor(self):
        anchors = find_anchors("`parse_config` in src/app.py loads YAML; RetryPolicy caps attempts.", self.repo)
        self.assertEqual(anchors, [f"src/app.py:4 parse_config @{self.rid}", f"src/app.py:8 RetryPolicy @{self.rid}"])

    def test_ordinary_memories_get_no_anchor(self):
        for text in ("We deploy on Tuesdays.", "The app lives in src/app.py.", "Use `parse_config` for YAML."):
            self.assertEqual(find_anchors(text, self.repo), [], text)

    def test_anchor_holds_moves_and_goes(self):
        anchors = find_anchors("`parse_config` in src/app.py loads YAML.", self.repo)
        self.assertEqual(verify_anchors(anchors, self.repo)[0]["state"], "holds")
        (self.repo / "src" / "app.py").write_text("# header\n# more\n" + SOURCE, encoding="utf-8")
        moved = verify_anchors(anchors, self.repo)[0]
        self.assertEqual((moved["state"], moved["line"]), ("moved", 6))
        (self.repo / "src" / "app.py").write_text(SOURCE.replace("parse_config", "load_settings"), encoding="utf-8")
        self.assertEqual(verify_anchors(anchors, self.repo)[0]["state"], "gone")
        (self.repo / "src" / "app.py").unlink()
        self.assertEqual(verify_anchors(anchors, self.repo)[0]["state"], "gone")

    def test_page_stamping_and_opt_out(self):
        page = '---\ntype: memory\ntitle: "x"\n---\n\n# x\n'
        stamped = add_anchors_to_page(page, "`parse_config` in src/app.py loads YAML.", repo_root=self.repo)
        self.assertEqual(page_anchors(stamped), [f"src/app.py:4 parse_config @{self.rid}"])
        self.assertEqual(add_anchors_to_page(page, "We deploy on Tuesdays.", repo_root=self.repo), page)
        os.environ["LINK_ANCHORS"] = "off"
        try:
            self.assertEqual(add_anchors_to_page(page, "`parse_config` in src/app.py", repo_root=self.repo), page)
        finally:
            del os.environ["LINK_ANCHORS"]

    def test_written_memory_carries_anchors_and_the_verdict_checks_them(self):
        from link_core.memory import memory_records, write_memory_page
        wiki = self.repo / "notes-wiki"
        (wiki / "memories").mkdir(parents=True)
        cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            result = write_memory_page(
                wiki, "`parse_config` in src/app.py must stay side-effect free.", title=None,
                memory_type="decision", scope="project", tags=None, source="test",
                timestamp="2026-09-26T00:00:00Z", records=[], project="app",
                log_writer=lambda *a: None, rebuild_backlinks=lambda: True)
        finally:
            os.chdir(cwd)
        page = (wiki / "memories" / f"{result['name']}.md").read_text(encoding="utf-8")
        anchors = page_anchors(page)
        self.assertEqual(anchors, [f"src/app.py:4 parse_config @{self.rid}"])
        checker = StalenessChecker(self.repo)
        text = str(memory_records(wiki)[0].get("body") or "")
        self.assertEqual(checker.verdict(text, anchors=anchors)["verdict"], "verified")
        (self.repo / "src" / "app.py").write_text(SOURCE.replace("parse_config", "load_settings"), encoding="utf-8")
        verdict = StalenessChecker(self.repo).verdict(text, anchors=anchors)
        self.assertEqual(verdict["verdict"], "stale")
        self.assertIn("parse_config is no longer in src/app.py", verdict["findings"][-1]["evidence"])


class AnchorRepositoryTests(unittest.TestCase):
    """Anchors are checked only in the repository they were written in."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="link-anchor-repo-")
        base = Path(self.temp.name)
        self.repo = base / "project"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "docs").mkdir()
        (self.repo / "src" / "app.py").write_text(SOURCE, encoding="utf-8")
        (self.repo / "docs" / "index.md").write_text("# docs\n", encoding="utf-8")
        _git(self.repo, "init", "-q", "--initial-branch", "main")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "seed")
        self.text = "`parse_config` in src/app.py loads YAML."
        self.anchors = find_anchors(self.text, self.repo)
        self.assertEqual(len(self.anchors), 1)
        self.other = base / "other"
        (self.other / "src").mkdir(parents=True)
        (self.other / "src" / "app.py").write_text("print('unrelated')\n", encoding="utf-8")
        _git(self.other, "init", "-q", "--initial-branch", "main")
        _git(self.other, "add", "-A")
        _git(self.other, "commit", "-q", "-m", "other project")
        self.empty = base / "empty"
        self.empty.mkdir()
        _git(self.empty, "init", "-q", "--initial-branch", "main")

    def tearDown(self):
        self.temp.cleanup()

    def test_another_repository_never_sees_the_anchor_as_stale(self):
        for place in (self.other, self.empty):
            states = [r["state"] for r in verify_anchors(self.anchors, place)]
            self.assertEqual(states, ["skipped"], place)
            verdict = StalenessChecker(place).verdict(self.text, anchors=self.anchors)
            self.assertNotEqual(verdict["verdict"], "stale", place)
            self.assertEqual(StalenessChecker(place).anchor_findings(self.anchors), [], place)

    def test_a_subdirectory_of_the_same_repository_still_checks_it(self):
        verdict = StalenessChecker(self.repo / "docs").verdict(self.text, anchors=self.anchors)
        self.assertEqual(verdict["verdict"], "verified")

    def test_a_symbol_that_only_moved_is_not_stale(self):
        (self.repo / "src" / "app.py").write_text("# a new header line\n" + SOURCE, encoding="utf-8")
        self.assertEqual(verify_anchors(self.anchors, self.repo)[0]["state"], "moved")
        self.assertEqual(StalenessChecker(self.repo).anchor_findings(self.anchors), [])
        self.assertEqual(StalenessChecker(self.repo).verdict(self.text, anchors=self.anchors)["verdict"], "verified")

    def test_anchors_from_before_repository_identity_are_not_checked(self):
        legacy = [anchor.rsplit(" @", 1)[0] for anchor in self.anchors]
        (self.repo / "src" / "app.py").unlink()
        self.assertEqual([r["state"] for r in verify_anchors(legacy, self.repo)], ["skipped"])

    def test_no_repository_identity_means_no_anchors(self):
        (self.empty / "src").mkdir()
        (self.empty / "src" / "app.py").write_text(SOURCE, encoding="utf-8")
        self.assertEqual(find_anchors(self.text, self.empty), [])

    def test_anchors_never_read_outside_the_checkout(self):
        secret = self.repo.parent / "secrets"
        secret.mkdir()
        (secret / "prod.env").write_text("parse_config=1\n", encoding="utf-8")
        self.assertEqual(find_anchors("`parse_config` lives in ../secrets/prod.env", self.repo), [])
        rid = self.anchors[0].rsplit("@", 1)[1]
        crafted = [f"/etc/hosts:1 localhost @{rid}", f"../secrets/prod.env:1 parse_config @{rid}"]
        self.assertEqual(verify_anchors(crafted, self.repo), [])

    def test_a_file_too_large_to_read_is_skipped_not_gone(self):
        from link_core import provenance
        original = provenance.MAX_FILE_BYTES
        provenance.MAX_FILE_BYTES = 10
        try:
            self.assertEqual(verify_anchors(self.anchors, self.repo)[0]["state"], "skipped")
            self.assertEqual(StalenessChecker(self.repo).anchor_findings(self.anchors), [])
        finally:
            provenance.MAX_FILE_BYTES = original


if __name__ == "__main__":
    unittest.main()
