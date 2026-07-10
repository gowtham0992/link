"""Optional local semantic recall for Link.

Lexical recall stays the default and the fallback. When the optional local
embedding provider is installed (`pip install "link-mcp[semantic]"`) and its
small static-embedding model has been fetched once through the explicit
`lnk semantic --setup` command, memory recall additionally retrieves close
paraphrases ("how do I like my PRs structured" finding a memory phrased
around "commit style") that token matching misses.

Local-first guarantees preserved:
- No network at recall time, ever: model loading is forced offline
  (`HF_HUB_OFFLINE=1`) everywhere except the explicit setup command, so a
  query can never trigger a download.
- No services, no vector database: embeddings live in a plain JSON cache
  under `.link-cache/semantic/`, similarity is brute-force cosine in pure
  Python — personal wikis have hundreds of memories, not millions.
- Deterministic degradation: if the provider, model, or cache is missing or
  broken, every entry point returns empty results and recall behaves exactly
  as before.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

from .files import atomic_write_text

DEFAULT_SEMANTIC_MODEL = "minishlab/potion-base-8M"
SEMANTIC_MODEL_ENV = "LINK_SEMANTIC_MODEL"
SEMANTIC_DISABLE_ENV = "LINK_SEMANTIC"
SEMANTIC_INDEX_VERSION = 1

# Absolute cosine values from small static-embedding models are not
# comparable across queries (a correct match can score 0.25 on one query and
# 0.55 on another), so candidate selection is *standout-based*: a memory
# counts as a semantic match when its similarity stands out from the rest of
# the corpus for this query (z-score), with a small absolute floor to reject
# noise-on-noise. `strength` in [0, 1] expresses how much it stands out.
SEMANTIC_NOISE_FLOOR = 0.15
SEMANTIC_STANDOUT_Z = 1.0
SEMANTIC_MAX_CANDIDATES = 5
SEMANTIC_MODERATE_STRENGTH = 0.5
# Small corpora make standout statistics unstable; fall back to absolute.
SEMANTIC_MIN_CORPUS_FOR_STANDOUT = 5
SEMANTIC_MIN_COSINE = 0.35

Embedder = Callable[[list[str]], list[list[float]]]

_MODEL_CACHE: dict[str, object] = {}

# Two provider tiers, both fully local:
# - "fastembed" (quality): contextual ONNX sentence embeddings. Best recall;
#   ~5 s one-time model load, so it shines in long-lived processes like the
#   MCP server. Preferred automatically when installed.
# - "model2vec" (fast): tiny static embeddings. ~100 ms load, ideal for
#   short-lived CLI calls and session-start hooks.
SEMANTIC_PROVIDER_ENV = "LINK_SEMANTIC_PROVIDER"
# Set by entry points: short-lived CLI commands prefer the instant-load fast
# tier; the long-lived MCP server prefers the quality tier. An explicit
# LINK_SEMANTIC_PROVIDER always wins.
SEMANTIC_SURFACE_ENV = "LINK_SEMANTIC_SURFACE"
DEFAULT_FASTEMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _provider_override() -> str:
    return os.environ.get(SEMANTIC_PROVIDER_ENV, "").strip().lower()


def _fastembed_installed() -> bool:
    try:
        import fastembed  # noqa: F401
    except Exception:
        return False
    return True


def _model2vec_installed() -> bool:
    try:
        import model2vec  # noqa: F401
    except Exception:
        return False
    return True


def semantic_provider() -> str | None:
    """Return the active provider name, or None when nothing is installed."""
    override = _provider_override()
    if override == "fastembed":
        return "fastembed" if _fastembed_installed() else None
    if override == "model2vec":
        return "model2vec" if _model2vec_installed() else None
    surface = os.environ.get(SEMANTIC_SURFACE_ENV, "").strip().lower()
    if surface == "cli" and _model2vec_installed():
        # Interactive commands stay instant; the MCP server still gets the
        # quality tier. LINK_SEMANTIC_PROVIDER overrides this split.
        return "model2vec"
    if _fastembed_installed():
        return "fastembed"
    if _model2vec_installed():
        return "model2vec"
    return None


def semantic_model_name() -> str:
    override = os.environ.get(SEMANTIC_MODEL_ENV, "").strip()
    if override:
        return override
    if semantic_provider() == "fastembed":
        return DEFAULT_FASTEMBED_MODEL
    return DEFAULT_SEMANTIC_MODEL


def semantic_model_key() -> str:
    """Provider-qualified model id; changing provider or model rebuilds the index."""
    return f"{semantic_provider() or 'none'}:{semantic_model_name()}"


def semantic_disabled() -> bool:
    return os.environ.get(SEMANTIC_DISABLE_ENV, "").strip().lower() in {"0", "off", "false", "no"}


def provider_installed() -> bool:
    return semantic_provider() is not None


def _set_offline_guard(allow_download: bool) -> None:
    if not allow_download:
        # Force offline so recall can never silently reach the network.
        os.environ["HF_HUB_OFFLINE"] = "1"
    else:
        os.environ.pop("HF_HUB_OFFLINE", None)


def _load_model(allow_download: bool = False):
    """Load the embedding model; offline unless setup explicitly allows."""
    provider = semantic_provider()
    model_name = semantic_model_name()
    cache_key = f"{provider}:{model_name}"
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached
    _set_offline_guard(allow_download)
    if provider == "fastembed":
        from fastembed import TextEmbedding

        model = TextEmbedding(model_name)
    else:
        from model2vec import StaticModel

        model = StaticModel.from_pretrained(model_name)
    _MODEL_CACHE[cache_key] = model
    return model


def load_embedder(allow_download: bool = False) -> Embedder | None:
    """Return a batch embedding callable, or None when unavailable."""
    provider = semantic_provider()
    if semantic_disabled() or provider is None:
        return None
    try:
        model = _load_model(allow_download=allow_download)
    except Exception:
        return None

    if provider == "fastembed":
        def _embed(texts: list[str]) -> list[list[float]]:
            return [[float(value) for value in vector] for vector in model.embed(texts)]
    else:
        def _embed(texts: list[str]) -> list[list[float]]:
            return [[float(value) for value in vector] for vector in model.encode(texts)]

    return _embed


# ── Rerank tier (optional, local) ──────────────────────────────────────
# A tiny local ONNX cross-encoder re-orders the top recall candidates by
# reading each (query, memory) pair directly. Measured (see
# benchmarks/RESULTS.md): LoCoMo hit@10 0.737 -> 0.794 and bundled
# token-overlap hit@1 0.749 -> 0.839 on the default embedder. The reranker
# score is BLENDED with the retrieval order (reciprocal-rank fusion), never
# substituted: pure reranking collapsed hit@1 0.38 -> 0.18 in ablation.
# Same guarantees as the embedding tiers: loads offline-only (only explicit
# setup may download), disabled by default, applies only to explicit recall
# calls — session hooks and briefs never pay the latency.
RERANK_DISABLE_ENV = "LINK_RERANK"
RERANK_MODEL_ENV = "LINK_RERANK_MODEL"
DEFAULT_RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
RERANK_CANDIDATES = 50
RERANK_RRF_K = 60

Reranker = Callable[[str, list[str]], list[float]]


def rerank_disabled() -> bool:
    return os.environ.get(RERANK_DISABLE_ENV, "").strip().lower() in {"off", "0", "false", "no"}


def rerank_model_name() -> str:
    return os.environ.get(RERANK_MODEL_ENV, "").strip() or DEFAULT_RERANK_MODEL


def load_reranker(allow_download: bool = False) -> Reranker | None:
    """Return a cross-encoder scoring callable, or None when unavailable.

    Never raises and never touches the network unless allow_download=True
    (the explicit one-time setup path).
    """
    if rerank_disabled() or not _fastembed_installed():
        return None
    model_name = rerank_model_name()
    cache_key = f"rerank:{model_name}"
    model = _MODEL_CACHE.get(cache_key)
    if model is None:
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            _set_offline_guard(allow_download)
            model = TextCrossEncoder(model_name)
            _MODEL_CACHE[cache_key] = model
        except Exception:
            return None

    def _score(query: str, documents: list[str]) -> list[float]:
        return [float(value) for value in model.rerank(query, documents)]

    return _score


def rerank_blend(
    query: str,
    results: list[dict[str, object]],
    *,
    limit: int,
    reranker: Reranker | None = None,
) -> list[dict[str, object]]:
    """Re-order recall results by blending retrieval order with a local
    cross-encoder's judgment of each (query, memory) pair.

    Takes the over-fetched candidate list (RERANK_CANDIDATES) in retrieval
    order and returns the top `limit` after reciprocal-rank fusion of the
    two orders. Degrades to the input order when no reranker is available.
    """
    active = reranker or load_reranker(allow_download=False)
    if active is None or len(results) <= 1:
        return results[:limit]
    documents = [
        " ".join([
            str(item.get("title") or ""),
            str(item.get("tldr") or ""),
            str(item.get("snippet") or ""),
            str(item.get("steps") or ""),
        ])[:1000]
        for item in results
    ]
    try:
        scores = active(query, documents)
    except Exception:
        return results[:limit]
    if len(scores) != len(results):
        return results[:limit]
    rerank_order = sorted(range(len(results)), key=lambda i: -scores[i])
    fused: dict[int, float] = {}
    for rank, index in enumerate(rerank_order):
        fused[index] = fused.get(index, 0.0) + 1.0 / (RERANK_RRF_K + rank + 1)
    for rank in range(len(results)):
        fused[rank] = fused.get(rank, 0.0) + 1.0 / (RERANK_RRF_K + rank + 1)
    ordered = sorted(fused, key=lambda index: -fused[index])
    reranked = []
    for index in ordered[:limit]:
        item = dict(results[index])
        item["rerank"] = "blended"
        reranked.append(item)
    return reranked


def rerank_model_available() -> bool:
    """True when the rerank cross-encoder loads offline (installed + cached)."""
    return load_reranker(allow_download=False) is not None


def model_available() -> bool:
    """True when the model is loadable fully offline."""
    return load_embedder(allow_download=False) is not None


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [value / norm for value in vector]


def _cosine(a: list[float], b: list[float]) -> float:
    # Vectors are stored normalized, so cosine is a plain dot product.
    return sum(x * y for x, y in zip(a, b))


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def memory_embedding_text(record: Mapping[str, object]) -> str:
    """The bounded text that represents one memory in the semantic index."""
    tags = " ".join(str(tag) for tag in record.get("tags", []) if str(tag).strip())
    parts = [
        str(record.get("title") or ""),
        str(record.get("tldr") or ""),
        str(record.get("trigger") or ""),
        tags,
        str(record.get("body") or "")[:1000],
        str(record.get("context") or "")[:600],
    ]
    return "\n".join(part for part in parts if part.strip())


def semantic_index_path(root: Path) -> Path:
    return root.expanduser().resolve() / ".link-cache" / "semantic" / "memories.json"


def _load_index(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(payload, dict) or payload.get("version") != SEMANTIC_INDEX_VERSION:
        return {}
    return payload


def _save_index(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(payload))


def refresh_memory_index(
    root: Path,
    records: Iterable[Mapping[str, object]],
    *,
    embedder: Embedder,
    model_name: str | None = None,
) -> dict[str, object]:
    """Embed new or changed memories; prune deleted ones. Returns the index."""
    model = model_name or semantic_model_key()
    path = semantic_index_path(root)
    index = _load_index(path)
    items = index.get("items") if isinstance(index.get("items"), dict) else {}
    if index.get("model") != model:
        items = {}

    wanted: dict[str, str] = {}
    texts_by_name: dict[str, str] = {}
    for record in records:
        name = str(record.get("name") or "").strip()
        if not name:
            continue
        text = memory_embedding_text(record)
        if not text.strip():
            continue
        wanted[name] = _content_hash(text)
        texts_by_name[name] = text

    stale = [
        name for name, digest in wanted.items()
        if not isinstance(items.get(name), dict) or items[name].get("hash") != digest
    ]
    removed = [name for name in list(items) if name not in wanted]
    if stale:
        vectors = embedder([texts_by_name[name] for name in stale])
        for name, vector in zip(stale, vectors):
            items[name] = {
                "hash": wanted[name],
                "vec": [round(value, 5) for value in _normalize(vector)],
            }
    for name in removed:
        items.pop(name, None)

    payload = {"version": SEMANTIC_INDEX_VERSION, "model": model, "items": items}
    if stale or removed or not path.exists():
        _save_index(path, payload)
    return payload


def _candidate_strengths(cosines: dict[str, float]) -> dict[str, dict[str, float]]:
    """Select standout candidates and grade each with a strength in [0, 1]."""
    if not cosines:
        return {}
    values = list(cosines.values())
    if len(values) < SEMANTIC_MIN_CORPUS_FOR_STANDOUT:
        # Too few memories for standout statistics: absolute fallback.
        return {
            name: {
                "cosine": round(value, 4),
                "strength": round(min(1.0, max(0.0, (value - SEMANTIC_MIN_COSINE) / 0.3)), 4),
            }
            for name, value in cosines.items()
            if value >= SEMANTIC_MIN_COSINE
        }
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    std = math.sqrt(variance) or 1e-6
    ranked = sorted(cosines.items(), key=lambda item: item[1], reverse=True)
    candidates: dict[str, dict[str, float]] = {}
    for name, value in ranked[:SEMANTIC_MAX_CANDIDATES]:
        if value < SEMANTIC_NOISE_FLOOR:
            continue
        z = (value - mean) / std
        if z < SEMANTIC_STANDOUT_Z:
            continue
        strength = min(1.0, max(0.0, (z - SEMANTIC_STANDOUT_Z) / 2.5))
        if strength <= 0:
            continue
        candidates[name] = {"cosine": round(value, 4), "strength": round(strength, 4)}
    return candidates


def semantic_memory_scores(
    root: Path,
    query: str,
    records: Iterable[Mapping[str, object]],
    *,
    embedder: Embedder | None = None,
) -> dict[str, dict[str, float]]:
    """Return {memory name: {cosine, strength}} for the query, or {}.

    Never raises and never touches the network: any missing provider, model,
    cache, or unexpected error degrades to lexical-only recall.
    """
    q = query.strip()
    if not q:
        return {}
    try:
        active_embedder = embedder or load_embedder(allow_download=False)
        if active_embedder is None:
            return {}
        index = refresh_memory_index(root, records, embedder=active_embedder)
        items = index.get("items")
        if not isinstance(items, dict) or not items:
            return {}
        query_vector = _normalize(active_embedder([q])[0])
        cosines: dict[str, float] = {}
        for name, entry in items.items():
            vector = entry.get("vec") if isinstance(entry, dict) else None
            if not isinstance(vector, list):
                continue
            cosines[name] = _cosine(query_vector, vector)
        return _candidate_strengths(cosines)
    except Exception:
        return {}


def semantic_match_points(match: Mapping[str, float] | None) -> int:
    """Map a semantic match's strength onto the lexical match-score scale.

    A barely-standout candidate contributes little; a clear standout can
    clear the recall floor on its own but never dominates an exact lexical
    hit (max 10 points vs 20+ for a verbatim title match).
    """
    if not match:
        return 0
    strength = float(match.get("strength") or 0.0)
    return max(0, round(strength * 10))


def semantic_confidence_cap(match: Mapping[str, float] | None) -> str:
    """Honest confidence for a match with no lexical evidence."""
    strength = float(match.get("strength") or 0.0) if match else 0.0
    return "moderate" if strength >= SEMANTIC_MODERATE_STRENGTH else "weak"


def build_semantic_status(
    root: Path,
    *,
    memory_count: int,
    command_target: str | Path = ".",
    python_cmd: str | None = None,
    externally_managed: bool = False,
) -> dict[str, object]:
    """Readiness report for the optional semantic recall layer."""
    provider = semantic_provider()
    installed = provider is not None
    disabled = semantic_disabled()
    ready = False
    index_items = 0
    index = _load_index(semantic_index_path(root))
    items = index.get("items")
    if isinstance(items, dict):
        index_items = len(items)
    if installed and not disabled:
        ready = model_available()

    next_actions: list[str] = []
    if disabled:
        next_actions.append(f"unset {SEMANTIC_DISABLE_ENV} to re-enable semantic recall")
    elif not installed:
        if externally_managed:
            # PEP 668 (Homebrew/Debian pythons): direct pip installs are
            # refused, so --setup provisions Link's managed venv instead.
            next_actions.append(
                f"lnk semantic {command_target} --setup"
                "  # installs the semantic extras into ~/.link-mcp-venv and fetches the models"
            )
        else:
            next_actions.append('pip install "link-mcp[semantic]"  # fast tier (tiny static model)')
            next_actions.append('pip install "link-mcp[semantic-quality]"  # quality tier (contextual model)')
            next_actions.append(f"lnk semantic {command_target} --setup")
    elif not ready:
        next_actions.append(f"lnk semantic {command_target} --setup")
    elif index_items < memory_count:
        next_actions.append(f"lnk semantic {command_target} --rebuild")
    if installed and provider == "model2vec" and not _fastembed_installed() and not externally_managed:
        next_actions.append(
            'optional quality upgrade: pip install "link-mcp[semantic-quality]" then rerun --setup'
        )

    tier = None
    if provider == "fastembed":
        tier = "quality (contextual embeddings; ~5s load, best for the MCP server)"
    elif provider == "model2vec":
        tier = "fast (static embeddings; instant load, best for CLI and hooks)"

    rerank_installed = _fastembed_installed() and not rerank_disabled()
    rerank_ready = rerank_model_available() if rerank_installed else False
    if rerank_disabled():
        rerank_state = f"disabled via {RERANK_DISABLE_ENV}"
    elif rerank_ready:
        rerank_state = "active on explicit recall (hooks and briefs never pay the latency)"
    elif rerank_installed:
        rerank_state = "installed but model not fetched"
        next_actions.append(f"lnk semantic {command_target} --setup  # also fetches the rerank model")
    else:
        rerank_state = "not installed"
        if not externally_managed:
            next_actions.append('optional rerank tier: pip install "link-mcp[rerank]" then rerun --setup')

    return {
        "rerank_ready": rerank_ready,
        "rerank_state": rerank_state,
        "rerank_model": rerank_model_name(),
        "enabled": ready,
        "disabled_by_env": disabled,
        "provider": provider,
        "tier": tier,
        "python": python_cmd,
        "model": semantic_model_name(),
        "model_available_offline": ready,
        "index_path": str(semantic_index_path(root)),
        "indexed_memories": index_items,
        "memory_count": memory_count,
        "mode": "hybrid (lexical + semantic)" if ready else "lexical only",
        "network_policy": (
            "Recall never downloads anything: the model loads offline-only. "
            "Only `lnk semantic --setup` may fetch the model, once, with your approval."
        ),
        "next_actions": next_actions,
    }


def render_semantic_status_text(payload: Mapping[str, object]) -> tuple[int, str]:
    lines = [
        "Link semantic recall",
        "",
        f"Mode: {payload.get('mode')}",
        f"Provider: {payload.get('provider') or 'not installed'}"
        + (f" · {payload.get('tier')}" if payload.get("tier") else ""),
        *( [f"Python: {payload.get('python')}"] if payload.get("python") else [] ),
        f"Model: {payload.get('model')}",
        f"Indexed memories: {payload.get('indexed_memories')} of {payload.get('memory_count')}",
        f"Index: {payload.get('index_path')}",
        f"Rerank tier: {payload.get('rerank_state')}"
        + (f" · {payload.get('rerank_model')}" if payload.get("rerank_ready") else ""),
    ]
    if payload.get("disabled_by_env"):
        lines.append(f"Disabled via {SEMANTIC_DISABLE_ENV} environment variable.")
    actions = payload.get("next_actions")
    if isinstance(actions, list) and actions:
        lines.extend(["", "Next:"])
        lines.extend(f"  {action}" for action in actions)
    lines.extend(["", str(payload.get("network_policy") or "")])
    return 0, "\n".join(lines)
