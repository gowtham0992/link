# Link recall quality benchmark

Link's recall is measured, not asserted. This document holds the current
numbers, exactly how they were produced, and how to reproduce them on your
own machine. There are two tracks:

1. **Link recall benchmark** — our own deterministic, fully auditable
   dataset (checked into this repo; no LLM, no network, no randomness).
2. **LoCoMo third-party track** — the retrieval stage of the long-term
   conversational memory benchmark the hosted-memory industry quotes
   (Maharana et al., ACL 2024, Snap Research), using only its third-party
   questions and evidence annotations.

## Semantic tiers

Lexical recall is always the default and the fallback (zero dependencies).
Two optional local semantic tiers upgrade it — both load offline-only at
recall time, keep embeddings in plain JSON under `.link-cache/`, and use no
vector database or service:

| tier | install | model | load time | best for |
|---|---|---|---|---|
| fast | `pip install "link-mcp[semantic]"` | model2vec potion-base-8M (~30 MB) | ~0.1 s | CLI, session-start hooks |
| quality | `pip install "link-mcp[semantic-quality]"` | all-MiniLM-L6-v2 ONNX (~90 MB) | ~5 s | MCP server, long-lived agents |

The quality tier is preferred automatically when installed
(`LINK_SEMANTIC_PROVIDER` overrides).

## Track 1: Link recall benchmark

Dataset (`scripts/recall_dataset.py`): 62 memories across six domains
including 20 distractors; 1,176 cases (294 authored queries + deterministic
phrasing variants). Queries are grouped by *measured* overlap: a case counts
as `zero-overlap` only if it provably shares no significant stemmed token
with its target memory — pure paraphrases that token matching cannot reach.

Full suite, Apple M4, macOS 26.5.1, Python 3.14, run 2026-07-08, Link
`develop` (post-1.5.0).

### Token-overlap queries (800 cases)

| metric | lexical | fast tier | quality tier |
|---|---|---|---|
| hit@1 | 0.589 | 0.703 | **0.749** |
| hit@3 | 0.729 | 0.833 | **0.886** |
| hit@5 | 0.815 | 0.880 | **0.926** |
| MRR@5 | 0.668 | 0.769 | **0.818** |

### Zero-overlap queries — pure paraphrases (376 cases)

| metric | lexical | fast tier | quality tier |
|---|---|---|---|
| hit@1 | 0.048 | 0.074 | **0.120** (2.5×) |
| hit@3 | 0.064 | 0.136 | **0.255** (4.0×) |
| hit@5 | 0.082 | 0.202 | **0.338** (4.1×) |
| MRR@5 | 0.058 | 0.115 | **0.191** (3.3×) |

### Latency (per recall, 62-memory corpus, model load excluded)

| mode | p50 | mean |
|---|---|---|
| lexical | 1.3 ms | 1.3 ms |
| fast tier | 2.8 ms | 2.8 ms |
| quality tier | 9.3 ms | 10.0 ms |

### Ablations we ran and rejected

- **potion-retrieval-32M** (retrieval-tuned static model) and **multi-view
  embeddings** (title/tldr/body embedded separately, max-similarity): both
  improved token-overlap slightly but did not move zero-overlap paraphrases.
  The zero-overlap ceiling is the static-embedding paradigm itself, which is
  why the quality tier uses a contextual model instead of a bigger static one.
- **potion-base-32M**: marginal over 8M; not worth 4× the size as a default.

## Track 2: LoCoMo third-party retrieval

Every dialog turn of a LoCoMo conversation becomes one memory record; every
evidence-annotated question (adversarial category excluded) becomes a recall
query; we measure whether Link ranks the annotated evidence turns highly.
10 conversations, 5,882 turn-memories (~590 per conversation), 1,536
third-party queries. No LLM anywhere: this isolates the retrieval stage with
third-party queries and third-party gold labels.

| metric | lexical | hybrid (quality tier) |
|---|---|---|
| any-evidence hit@1 | 0.290 | **0.309** |
| any-evidence hit@5 | 0.496 | **0.540** |
| any-evidence hit@10 | 0.578 | **0.685** |
| evidence recall@10 | 0.517 | **0.608** |
| latency p50 / mean | 16 ms | 45 ms / 61 ms |

**Not comparable to published LoCoMo QA scores** (mem0, Zep, etc. report
end-to-end LLM answer quality with server-side pipelines). This track scores
deterministic local ranking only — no answer generation, no LLM judging, no
network. The dataset is CC BY-NC 4.0 © Snap Inc. and is not redistributed
here; the script prints the download command.

## Honest limitations

- **Pure paraphrases are much better, not solved.** The quality tier
  quadruples zero-overlap hit@3/hit@5 over lexical, yet roughly two thirds
  of pure paraphrases still miss the top 5 on our corpus. Link labels every
  semantic-only match (`match: semantic`, capped confidence) so agents
  verify before trusting — we publish the miss rate rather than hiding it.
- **Track 1 is self-authored.** It is deterministic, auditable, and gated
  against regressions in CI, but it was written by the Link project.
  Track 2 exists precisely to complement it with third-party data;
  adversarial case contributions to Track 1 are welcome (five lines per
  intent in `scripts/recall_dataset.py`).
- **The quality tier costs a ~5 s model load**, so short-lived CLI calls
  and session-start hooks default to the fast tier unless you opt in.

## Reproduce

```bash
git clone https://github.com/gowtham0992/link && cd link

# Track 1 (lexical baseline needs nothing):
python3 scripts/eval_recall_quality.py --suite full --mode off
python3 -m venv /tmp/linkbench
/tmp/linkbench/bin/pip install model2vec            # fast tier
/tmp/linkbench/bin/pip install fastembed            # quality tier (preferred when present)
/tmp/linkbench/bin/python scripts/eval_recall_quality.py --suite full --mode real --allow-download

# Track 2 (download the dataset yourself; CC BY-NC 4.0 © Snap Inc.):
curl -L -o /tmp/locomo10.json https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json
python3 scripts/eval_locomo.py /tmp/locomo10.json --mode off
/tmp/linkbench/bin/python scripts/eval_locomo.py /tmp/locomo10.json --mode real
```

`--mode fake` runs a deterministic no-model embedder; CI uses it with a
regression gate: hybrid may never score below lexical on any group metric.
