"""Every path that normalizes memory text must treat all scripts alike.

3.0 made recall work outside English, but the proposal path, the duplicate
gate and negation detection still ran through an ASCII-only compactor. These
tests hold each of those paths, and pin the ASCII behaviour so stored
fingerprints and dismissals stay valid.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.memory import (  # noqa: E402
    compact_memory_text,
    has_negation,
    memory_duplicate_candidates,
    memory_tokens,
    proposal_fingerprint,
    propose_memories_from_text,
)


def _record(name: str, title: str, body: str, memory_type: str = "decision") -> dict[str, object]:
    return {
        "name": name,
        "title": title,
        "memory_type": memory_type,
        "scope": "user",
        "status": "active",
        "review_status": "reviewed",
        "body": f"# {title}\n\n> **TLDR:** {body}\n\n## Memory\n\n{body}\n",
        "tldr": body,
        "snippet": body,
        "tags": [],
    }


class CompactTextTests(unittest.TestCase):
    def test_ascii_fingerprint_is_unchanged(self):
        # Computed with the pre-4.0 algorithm. Dismissed proposals are stored
        # by fingerprint, so this value must never move.
        text = "From now on, deploys happen on Tuesdays - never Fridays!"
        self.assertEqual(proposal_fingerprint(text), "c0745d059d81a0f0")
        self.assertEqual(compact_memory_text(text), "from now on deploys happen on tuesdays never fridays")

    def test_other_scripts_keep_their_letters(self):
        self.assertEqual(compact_memory_text("デプロイは金曜日にしない。"), "デプロイは金曜日にしない")
        self.assertEqual(compact_memory_text("Никогда не деплой в пятницу"), "никогда не деплой в пятницу")
        self.assertEqual(compact_memory_text("Zürich rule"), "zurich rule")

    def test_distinct_claims_get_distinct_fingerprints(self):
        claims = ["デプロイは金曜日にしない", "テストは必ず書く", "कभी शुक्रवार को डिप्लॉय मत करो", "لا تنشر يوم الجمعة"]
        self.assertEqual(len({proposal_fingerprint(claim) for claim in claims}), len(claims))

    def test_curated_non_latin_lines_each_become_a_proposal(self):
        payload = propose_memories_from_text(
            "デプロイは金曜日にしない。\nテストは必ず書く。\nコードレビューは二人で行う。",
            [], source="capture", curated=True,
        )
        self.assertEqual(payload["count"], 3)
        self.assertEqual(payload["skipped_count"], 0)


class KanaSegmentationTests(unittest.TestCase):
    def test_voiced_kana_bigrams_stay_whole(self):
        self.assertEqual(memory_tokens("デプロイ"), {"デプ", "プロ", "ロイ"})

    def test_hangul_and_indic_unchanged(self):
        self.assertIn("배포", memory_tokens("서울 배포 규칙"))
        self.assertIn("मंगलवार", memory_tokens("हम हर मंगलवार को डिप्लॉय करते हैं"))


class NonLatinDuplicateTests(unittest.TestCase):
    def test_reworded_japanese_duplicate_is_caught(self):
        existing = _record("deploy-day-ja", "デプロイの曜日", "東京オフィスでは毎週火曜日の午後にデプロイする")
        candidates = memory_duplicate_candidates(
            [existing],
            "東京オフィスでは毎週火曜日の午後にデプロイします",
            "デプロイする曜日",
            "decision",
            "user",
        )
        self.assertTrue(candidates, "a near-identical Japanese claim should be flagged as a duplicate")
        self.assertIn("high_token_overlap", candidates[0]["duplicate_reasons"])

    def test_unrelated_japanese_claims_are_not_duplicates(self):
        existing = _record("tests-ja", "テスト", "テストは必ず書く")
        self.assertEqual(
            memory_duplicate_candidates([existing], "デプロイは金曜日にしない", None, "decision", "user"),
            [],
        )


class NegationTests(unittest.TestCase):
    def test_negation_across_languages(self):
        negated = [
            "決してmainにpushしない",
            "Wir deployen nie freitags",
            "Nunca despliegues el viernes",
            "Ne déployez pas le vendredi",
            "Никогда не деплой в пятницу",
            "금요일에는 배포하지 않는다",
            "周五不要部署",
        ]
        for text in negated:
            with self.subTest(text=text):
                self.assertTrue(has_negation(text))

    def test_english_words_that_look_foreign_are_not_negations(self):
        for text in ("Use non-blocking IO", "Read the Hindi docs first", "Deploy on Tuesdays", "デプロイは火曜日"):
            with self.subTest(text=text):
                self.assertFalse(has_negation(text))


if __name__ == "__main__":
    unittest.main()
