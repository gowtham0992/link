"""Contradiction flags from the optional local NLI tier."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.memory import memory_records, nli_contradiction_flags, write_memory_page  # noqa: E402
from link_core.nli import load_contradiction_scorer, nli_status  # noqa: E402

COMMON = dict(scope="user", tags=None, source="test", log_writer=lambda *a: None, rebuild_backlinks=lambda: True)


def fake_scorer(pairs):
    """Deterministic stand-in: 'never' against its opposite reads as a contradiction."""
    scores = []
    for first, second in pairs:
        a, b = first.lower(), second.lower()
        scores.append(0.98 if ("never" in a) != ("never" in b) else 0.02)
    return scores


class NliFlagTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.wiki = Path(self.temp.name) / "wiki"
        (self.wiki / "memories").mkdir(parents=True)
        (self.wiki / "index.md").write_text("# Index\n", encoding="utf-8")
        write_memory_page(self.wiki, "Deploys go out on Fridays after the release review", "Friday deploys",
                          "decision", timestamp="2026-09-01T00:00:00Z", records=[], contradiction_scorer=None, **COMMON)
        write_memory_page(self.wiki, "The docs site is built with mkdocs", None, "decision",
                          timestamp="2026-09-01T00:00:00Z", records=memory_records(self.wiki),
                          contradiction_scorer=None, **COMMON)

    def tearDown(self):
        self.temp.cleanup()

    def test_only_neighbours_sharing_a_subject_are_scored(self):
        seen = []

        def spy(pairs):
            seen.extend(pairs)
            return [0.0] * len(pairs)

        nli_contradiction_flags(memory_records(self.wiki), "We never deploy on Fridays", None,
                                "decision", "user", "", spy)
        self.assertEqual(len(seen), 1, "the mkdocs memory shares no subject word and must not be scored")

    def test_a_flag_is_a_review_note_not_a_refusal(self):
        result = write_memory_page(self.wiki, "We never deploy on Fridays", None, "decision",
                                   timestamp="2026-09-20T00:00:00Z", records=memory_records(self.wiki),
                                   contradiction_scorer=fake_scorer, allow_conflict=True, **COMMON)
        self.assertTrue(result["created"])
        self.assertEqual([flag["name"] for flag in result["possible_contradictions"]], ["friday-deploys"])
        page = (self.wiki / "memories" / f"{result['name']}.md").read_text(encoding="utf-8")
        self.assertIn("May contradict friday-deploys", page)

    def test_a_failing_model_never_breaks_a_save(self):
        def broken(_pairs):
            raise RuntimeError("model crashed")

        result = write_memory_page(self.wiki, "We never deploy on Fridays", None, "decision",
                                   timestamp="2026-09-20T00:00:00Z", records=memory_records(self.wiki),
                                   contradiction_scorer=broken, allow_conflict=True, **COMMON)
        self.assertTrue(result["created"])
        self.assertEqual(result["possible_contradictions"], [])


class NliOptInTests(unittest.TestCase):
    def test_disabled_means_no_scorer(self):
        os.environ["LINK_NLI"] = "off"
        try:
            self.assertIsNone(load_contradiction_scorer())
            self.assertFalse(nli_status()["enabled"])
        finally:
            del os.environ["LINK_NLI"]

    def test_missing_model_means_no_scorer_and_no_network(self):
        os.environ["HF_HUB_CACHE"] = tempfile.mkdtemp()
        try:
            self.assertIsNone(load_contradiction_scorer())
        finally:
            del os.environ["HF_HUB_CACHE"]



_REAL = load_contradiction_scorer()


@unittest.skipUnless(_REAL, "local NLI model not set up (lnk semantic --setup --nli)")
class RealModelTests(unittest.TestCase):
    def test_a_revision_scores_as_a_contradiction(self):
        (probability,) = _REAL([("Our CI runs on Jenkins.", "Buildkite replaced Jenkins for CI.")])
        self.assertGreaterEqual(probability, 0.9)

    def test_unrelated_rules_never_reach_the_model(self):
        records = [{
            "name": "ruff", "title": "All Python linting goes through Ruff", "memory_type": "decision",
            "scope": "user", "status": "active", "review_status": "reviewed", "tags": [],
            "tldr": "All Python linting goes through Ruff with the repo config.",
        }]
        flags = nli_contradiction_flags(records, "New Python functions carry full type annotations.", None,
                                        "decision", "user", "", _REAL)
        self.assertEqual(flags, [])

class NliMissingRetryTests(unittest.TestCase):
    def test_a_failed_load_is_retried_later(self):
        from unittest import mock

        from link_core import nli

        key = nli.nli_model_name()
        saved = dict(nli._CACHE), dict(nli._MISSING_AT)
        self.addCleanup(lambda: (nli._CACHE.clear(), nli._CACHE.update(saved[0]),
                                 nli._MISSING_AT.clear(), nli._MISSING_AT.update(saved[1])))
        nli._CACHE[key] = nli._MISSING
        nli._MISSING_AT[key] = 0.0  # failed long ago
        with mock.patch.object(nli, "nli_disabled", return_value=False), \
                mock.patch.object(nli, "_model_cached_locally", return_value=True), \
                mock.patch.object(nli, "nli_dependencies_installed", return_value=True), \
                mock.patch.object(nli, "_model_files", side_effect=RuntimeError("still missing")) as files:
            self.assertIsNone(nli.load_contradiction_scorer())
            self.assertEqual(files.call_count, 1, "an old failure is retried")
            self.assertIsNone(nli.load_contradiction_scorer())
            self.assertEqual(files.call_count, 1, "a fresh failure is not retried at once")


if __name__ == "__main__":
    unittest.main()
