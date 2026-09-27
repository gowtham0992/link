"""Optional contradiction flags from a small local NLI model.

Lexical rules catch contradictions that share words and structure ("uses X"
vs "does not use X anymore", "3.11" vs "3.12"). A natural-language inference
model reads meaning: given two claims it says whether one entails, contradicts
or is neutral to the other. Link uses it only at write time, only against the
handful of stored memories that share a subject word with the new one, and
only to *flag* a possible contradiction for review. It never blocks a save and
never resolves anything on its own, because a probabilistic model should not
overrule the person reviewing their memory.

Model: an int8-quantized three-way DeBERTa-v3 cross-encoder (~87 MB), run on
onnxruntime with the tokenizers library, both already installed with Link's
rerank extra. It is downloaded only by the explicit setup step
(`lnk semantic <dir> --setup --nli`); every other load is offline and returns
None when the model is not present, so the feature costs nothing until a user
opts in. `LINK_NLI=off` disables it.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence

NLI_MODEL_ENV = "LINK_NLI_MODEL"
NLI_DISABLE_ENV = "LINK_NLI"
DEFAULT_NLI_MODEL = "Xenova/nli-deberta-v3-xsmall"
NLI_MODEL_FILE = "onnx/model_quantized.onnx"
# Measured on the claim-update revisions and the recall dataset: at 0.9, with
# pairs restricted to memories whose subject words overlap by 30% or more
# (memory.NLI_MIN_SUBJECT_OVERLAP), 0 of 176 unrelated pairs are flagged and
# 2 revisions the word rules miss are caught. Without that restriction the
# model flagged 63 of the 176: it reads two different project rules as
# contradicting each other. The overlap gate is not optional.
CONTRADICTION_THRESHOLD = 0.9
MAX_PAIR_TOKENS = 256

ContradictionScorer = Callable[[Sequence[tuple[str, str]]], list[float]]

_CACHE: dict[str, object] = {}
_MISSING = object()


def nli_disabled() -> bool:
    return os.environ.get(NLI_DISABLE_ENV, "").strip().lower() in {"0", "off", "false", "no"}


def nli_model_name() -> str:
    return os.environ.get(NLI_MODEL_ENV, "").strip() or DEFAULT_NLI_MODEL


def nli_dependencies_installed() -> bool:
    try:
        import huggingface_hub  # noqa: F401
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401
    except Exception:
        return False
    return True


def _model_files(allow_download: bool) -> tuple[str, str, str]:
    from huggingface_hub import hf_hub_download

    repo = nli_model_name()
    offline = not allow_download
    return (
        hf_hub_download(repo, NLI_MODEL_FILE, local_files_only=offline),
        hf_hub_download(repo, "tokenizer.json", local_files_only=offline),
        hf_hub_download(repo, "config.json", local_files_only=offline),
    )


def _model_cached_locally() -> bool:
    """Cheap check before importing onnxruntime: is the model folder there?

    Every memory write asks for the scorer; users who never set it up should
    not pay an onnxruntime import on each `lnk remember`.
    """
    hub = os.environ.get("HF_HUB_CACHE") or os.path.join(
        os.environ.get("HF_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "huggingface"), "hub"
    )
    folder = "models--" + nli_model_name().replace("/", "--")
    return os.path.isdir(os.path.join(hub, folder))


def load_contradiction_scorer(allow_download: bool = False) -> ContradictionScorer | None:
    """Return a scorer giving P(contradiction) per claim pair, or None.

    None when disabled, when the dependencies are missing, or when the model
    has not been downloaded (offline loads never reach the network).
    """
    if nli_disabled():
        return None
    if not allow_download and not _model_cached_locally():
        return None
    if not nli_dependencies_installed():
        return None
    key = nli_model_name()
    cached = _CACHE.get(key)
    if cached is _MISSING and not allow_download:
        return None
    if cached is not None and cached is not _MISSING:
        return cached  # type: ignore[return-value]
    try:
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_path, tokenizer_path, config_path = _model_files(allow_download)
        session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        tokenizer = Tokenizer.from_file(tokenizer_path)
        tokenizer.enable_truncation(MAX_PAIR_TOKENS)
        tokenizer.enable_padding()
        with open(config_path, encoding="utf-8") as handle:
            labels = {str(value).lower(): int(index) for index, value in json.load(handle)["id2label"].items()}
        contradiction_index = labels["contradiction"]
        input_names = {item.name for item in session.get_inputs()}
    except Exception:
        if not allow_download:
            _CACHE[key] = _MISSING
        return None

    def _probabilities(pairs: Sequence[tuple[str, str]]) -> list[float]:
        encoded = tokenizer.encode_batch([(first, second) for first, second in pairs])
        feed = {
            "input_ids": np.array([item.ids for item in encoded], dtype=np.int64),
            "attention_mask": np.array([item.attention_mask for item in encoded], dtype=np.int64),
        }
        if "token_type_ids" in input_names:
            feed["token_type_ids"] = np.array([item.type_ids for item in encoded], dtype=np.int64)
        logits = session.run(None, feed)[0]
        shifted = np.exp(logits - logits.max(axis=1, keepdims=True))
        probabilities = shifted / shifted.sum(axis=1, keepdims=True)
        return [float(row[contradiction_index]) for row in probabilities]

    def score(pairs: Sequence[tuple[str, str]]) -> list[float]:
        """Symmetric: the larger of the two directions for each pair."""
        if not pairs:
            return []
        forward = _probabilities(pairs)
        backward = _probabilities([(second, first) for first, second in pairs])
        return [max(a, b) for a, b in zip(forward, backward)]

    _CACHE[key] = score
    return score


def nli_status() -> dict[str, object]:
    """Whether the contradiction tier can run here, without loading it."""
    if nli_disabled():
        return {"enabled": False, "reason": f"{NLI_DISABLE_ENV}=off", "model": nli_model_name()}
    if not nli_dependencies_installed():
        return {"enabled": False, "reason": "needs onnxruntime and tokenizers (the rerank extra)", "model": nli_model_name()}
    try:
        _model_files(allow_download=False)
    except Exception:
        return {"enabled": False, "reason": "model not downloaded", "model": nli_model_name()}
    return {"enabled": True, "reason": "", "model": nli_model_name(), "threshold": CONTRADICTION_THRESHOLD}


def setup_nli() -> dict[str, object]:
    """The one explicit, networked step: fetch the model, then load it."""
    if nli_disabled():
        return {"ready": False, "reason": f"{NLI_DISABLE_ENV}=off"}
    if not nli_dependencies_installed():
        return {"ready": False, "reason": "install the rerank extra first (onnxruntime, tokenizers)"}
    _CACHE.pop(nli_model_name(), None)
    scorer = load_contradiction_scorer(allow_download=True)
    return {"ready": scorer is not None, "model": nli_model_name()}
