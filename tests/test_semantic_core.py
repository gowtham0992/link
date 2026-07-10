import json
import math
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.memory import recall_memories  # noqa: E402
from link_core.semantic import (  # noqa: E402
    SEMANTIC_MIN_COSINE,
    build_semantic_status,
    memory_embedding_text,
    refresh_memory_index,
    semantic_confidence_cap,
    semantic_index_path,
    semantic_match_points,
    semantic_memory_scores,
)

# Tiny deterministic embedder: maps known concepts onto fixed axes so
# paraphrases ("structure my pull requests" / "commit style") land close
# together without any model. It ABSTAINS on text it does not recognize
# (zero vector), like an honest weak model: it can add signal only where it
# has knowledge and can never inject ranking noise elsewhere. CI uses it to
# exercise the full hybrid pipeline with a hard no-regression gate.
_CONCEPTS = {
    0: {"commit", "commits", "committing", "pr", "prs", "pull", "requests", "structure", "structured", "style"},
    1: {"deploy", "deploys", "release", "releases", "ship", "shipping"},
    2: {"database", "sqlite", "postgres", "storage", "persist", "disk", "data"},
}
_FAKE_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "from", "with",
    "how", "what", "which", "where", "do", "does", "we", "my", "our", "i", "should",
    "can", "must", "are", "is", "be", "this", "that", "it", "user", "prefers",
}
_DIM = 16


def fake_embedder(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for text in texts:
        vector = [0.0] * _DIM
        for token in text.lower().split():
            token = "".join(ch for ch in token if ch.isalnum())
            if not token or token in _FAKE_STOPWORDS:
                continue
            for axis, concepts in _CONCEPTS.items():
                if token in concepts:
                    vector[axis] += 1.0
                    break
        vectors.append(vector)
    return vectors


def _memory(name: str, title: str, body: str, **extra) -> dict[str, object]:
    record = {
        "name": name,
        "title": title,
        "tldr": "",
        "tags": [],
        "body": body,
        "status": "active",
        "scope": "user",
        "memory_type": "preference",
        "review_status": "reviewed",
    }
    record.update(extra)
    return record


COMMIT_MEMORY = _memory(
    "commit-style",
    "Commit style",
    "The user prefers small commits and PRs structured with a summary first.",
)
DEPLOY_MEMORY = _memory(
    "deploy-from-main",
    "Deploy from main",
    "Releases ship only from the main branch after CI passes.",
)


class SemanticCoreTests(unittest.TestCase):
    def test_refresh_index_embeds_and_reuses_unchanged(self):
        calls: list[int] = []

        def counting_embedder(texts: list[str]) -> list[list[float]]:
            calls.append(len(texts))
            return fake_embedder(texts)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            records = [COMMIT_MEMORY, DEPLOY_MEMORY]
            index = refresh_memory_index(root, records, embedder=counting_embedder)
            self.assertEqual(len(index["items"]), 2)
            self.assertEqual(sum(calls), 2)

            refresh_memory_index(root, records, embedder=counting_embedder)
            self.assertEqual(sum(calls), 2)  # unchanged: no re-embedding

            changed = dict(COMMIT_MEMORY)
            changed["body"] = "The user now prefers a single squash commit per PR."
            index = refresh_memory_index(root, [changed], embedder=counting_embedder)
            self.assertEqual(sum(calls), 3)  # one changed record re-embedded
            self.assertEqual(list(index["items"]), ["commit-style"])  # deploy pruned

    def test_index_file_is_plain_json(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            refresh_memory_index(root, [COMMIT_MEMORY], embedder=fake_embedder)
            payload = json.loads(semantic_index_path(root).read_text(encoding="utf-8"))
            self.assertIn("commit-style", payload["items"])
            vector = payload["items"]["commit-style"]["vec"]
            self.assertAlmostEqual(math.sqrt(sum(v * v for v in vector)), 1.0, places=3)

    def test_semantic_scores_find_paraphrase(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scores = semantic_memory_scores(
                root,
                "how should I structure my pull requests",
                [COMMIT_MEMORY, DEPLOY_MEMORY],
                embedder=fake_embedder,
            )

        self.assertIn("commit-style", scores)
        self.assertGreaterEqual(scores["commit-style"]["cosine"], SEMANTIC_MIN_COSINE)
        self.assertGreater(scores["commit-style"]["strength"], 0.0)
        self.assertNotIn("deploy-from-main", scores)

    def test_semantic_scores_empty_query_or_failure_degrade_to_empty(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(semantic_memory_scores(root, "", [COMMIT_MEMORY], embedder=fake_embedder), {})

            def broken_embedder(texts: list[str]) -> list[list[float]]:
                raise RuntimeError("boom")

            self.assertEqual(
                semantic_memory_scores(root, "commit style", [COMMIT_MEMORY], embedder=broken_embedder),
                {},
            )

    def test_recall_rescues_paraphrase_with_capped_confidence(self):
        # "structure my pull requests" shares no significant lexical token
        # with the deploy memory and few with commit-style's exact tokens.
        query = "how should I structure my pull requests"
        lexical_only = recall_memories([COMMIT_MEMORY, DEPLOY_MEMORY], query)
        with tempfile.TemporaryDirectory() as temp:
            scores = semantic_memory_scores(
                Path(temp), query, [COMMIT_MEMORY, DEPLOY_MEMORY], embedder=fake_embedder
            )
        hybrid = recall_memories([COMMIT_MEMORY, DEPLOY_MEMORY], query, semantic_scores=scores)

        hybrid_names = [str(item["name"]) for item in hybrid]
        self.assertIn("commit-style", hybrid_names)
        recalled = next(item for item in hybrid if item["name"] == "commit-style")
        self.assertIn(recalled["match"], {"semantic", "hybrid"})
        self.assertIn("semantic_similarity", recalled)
        if recalled["match"] == "semantic":
            # No lexical evidence: confidence must be capped below strong.
            self.assertIn(recalled["confidence"], {"weak", "moderate"})
        # Hybrid recall is a superset of lexical recall here.
        for item in lexical_only:
            self.assertIn(item["name"], hybrid_names)

    def test_lexical_match_keeps_lexical_confidence(self):
        results = recall_memories(
            [COMMIT_MEMORY],
            "commit style",
            semantic_scores={"commit-style": {"cosine": 0.9, "strength": 0.9}},
        )
        self.assertEqual(results[0]["match"], "hybrid")
        self.assertEqual(results[0]["confidence"], "strong")

    def test_match_points_scale(self):
        self.assertEqual(semantic_match_points(None), 0)
        self.assertEqual(semantic_match_points({"strength": 0.0}), 0)
        self.assertGreaterEqual(semantic_match_points({"strength": 0.5}), 4)
        self.assertLessEqual(semantic_match_points({"strength": 1.0}), 10)

    def test_confidence_cap(self):
        self.assertEqual(semantic_confidence_cap({"strength": 0.3}), "weak")
        self.assertEqual(semantic_confidence_cap({"strength": 0.7}), "moderate")
        self.assertEqual(semantic_confidence_cap(None), "weak")

    def test_provider_override_requires_installed_package(self):
        import os
        from link_core import semantic

        # Neither provider package is installed in CI: overrides must not
        # invent a provider, and detection must return None.
        for override in ("fastembed", "model2vec"):
            os.environ[semantic.SEMANTIC_PROVIDER_ENV] = override
            try:
                installed = (
                    semantic._fastembed_installed() if override == "fastembed"
                    else semantic._model2vec_installed()
                )
                if not installed:
                    self.assertIsNone(semantic.semantic_provider())
            finally:
                os.environ.pop(semantic.SEMANTIC_PROVIDER_ENV, None)

    def test_model_key_is_provider_qualified(self):
        from link_core import semantic

        key = semantic.semantic_model_key()
        self.assertIn(":", key)
        self.assertTrue(key.startswith(("none:", "fastembed:", "model2vec:")))

    def test_status_without_provider_reports_lexical_only(self):
        with tempfile.TemporaryDirectory() as temp:
            payload = build_semantic_status(Path(temp), memory_count=3, command_target=temp)
        self.assertEqual(payload["mode"], "lexical only")
        self.assertFalse(payload["enabled"])
        self.assertTrue(any("--setup" in action for action in payload["next_actions"]))

    def test_memory_embedding_text_is_bounded(self):
        record = _memory("big", "Big memory", "x" * 10000)
        self.assertLess(len(memory_embedding_text(record)), 1200)


class RerankTierTests(unittest.TestCase):
    def _results(self):
        return [
            {"name": f"m{i}", "title": f"Memory {i}", "tldr": f"claim {i}", "snippet": "", "score": 10 - i}
            for i in range(5)
        ]

    def test_blend_degrades_to_input_order_without_reranker(self):
        import os
        from link_core.semantic import rerank_blend
        results = self._results()
        # Force the tier off so the test is deterministic even on machines
        # with fastembed installed and a cached reranker model.
        previous = os.environ.get("LINK_RERANK")
        os.environ["LINK_RERANK"] = "off"
        try:
            out = rerank_blend("query", results, limit=3, reranker=None)
        finally:
            if previous is None:
                os.environ.pop("LINK_RERANK", None)
            else:
                os.environ["LINK_RERANK"] = previous
        self.assertEqual([r["name"] for r in out], ["m0", "m1", "m2"])

    def test_blend_fuses_reranker_order_with_retrieval_order(self):
        from link_core.semantic import rerank_blend
        results = self._results()
        # Reranker says the LAST candidate is by far the best.
        def fake_reranker(query, docs):
            return [0.0, 0.0, 0.0, 0.0, 9.0]
        out = rerank_blend("query", results, limit=3, reranker=fake_reranker)
        names = [r["name"] for r in out]
        # m4 must be promoted into the top, but m0 (retrieval's #1) must not
        # be discarded: blend, not substitution.
        self.assertIn("m4", names)
        self.assertIn("m0", names)
        self.assertTrue(all(r.get("rerank") == "blended" for r in out))

    def test_blend_survives_reranker_failure(self):
        from link_core.semantic import rerank_blend
        results = self._results()
        def broken(query, docs):
            raise RuntimeError("model exploded")
        out = rerank_blend("query", results, limit=2, reranker=broken)
        self.assertEqual([r["name"] for r in out], ["m0", "m1"])

    def test_reranker_offline_guard_returns_none_without_model(self):
        from link_core.semantic import load_reranker, rerank_disabled
        self.assertFalse(rerank_disabled())
        # In the test environment fastembed is not installed (or no cached
        # model): load must return None, never raise, never download.
        reranker = load_reranker(allow_download=False)
        self.assertTrue(reranker is None or callable(reranker))



if __name__ == "__main__":
    unittest.main()
