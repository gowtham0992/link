# Link recall quality benchmark

Link's recall is measured, not asserted. This document holds the current
numbers, exactly how they were produced, and how to reproduce them on your
own machine. The benchmark is deterministic and fully local: no LLM calls,
no network, no randomness — every memory and query is authored text checked
into this repository.

## What is measured

Given a personal-memory corpus and a query, Link's `recall` ranks memories.
We measure whether the correct memory appears at rank 1 / top 3 / top 5
(hit@1, hit@3, hit@5) and the mean reciprocal rank (MRR@5), comparing:

- **lexical-only** — Link's default recall: token matching with stemming,
  synonym groups, and rank boosts. Zero dependencies.
- **hybrid** — lexical plus the optional local semantic layer
  (`pip install "link-mcp[semantic]"`, model2vec `potion-base-8M`,
  ~30 MB static embeddings, loaded offline-only).

## Dataset

`scripts/recall_dataset.py`:

- **62 memories** across six domains (tooling, process, infra, data,
  preferences, project facts), including 20 distractor memories with no
  queries, so ranking competes against realistic noise. This corpus size
  reflects real personal agent memory (dozens to hundreds of memories, not
  millions of documents).
- **1,176 cases** in the full suite: 294 authored queries (7 per intent,
  mixing natural token-matching phrasings and true paraphrases) plus 882
  deterministic phrasing variants ("quick question: …", "remind me: …") that
  test framing robustness. The small suite (294 authored cases) is what CI
  runs.
- **Honest grouping**: queries are classified by *measured* overlap, not by
  authorship. A query counts as `zero-overlap` only if it provably shares no
  significant stemmed token with any text of its target memory — i.e. pure
  paraphrases that token matching cannot reach directly.

## Results

Full suite (1,176 cases), model2vec potion-base-8M, Apple M4, macOS 26.5.1,
Python 3.14. Run date: 2026-07-07, Link `develop` (post-1.5.0).

### Token-overlap queries (800 cases)

| metric | lexical-only | hybrid | change |
|---|---|---|---|
| hit@1 | 0.589 | **0.703** | +11.4 pp |
| hit@3 | 0.729 | **0.833** | +10.4 pp |
| hit@5 | 0.815 | **0.880** | +6.5 pp |
| MRR@5 | 0.668 | **0.769** | +0.101 |

Semantic evidence helps even when tokens match: it disambiguates between
several memories that share words with the query.

### Zero-overlap queries — pure paraphrases (376 cases)

| metric | lexical-only | hybrid | change |
|---|---|---|---|
| hit@1 | 0.048 | **0.074** | 1.5× |
| hit@3 | 0.064 | **0.136** | 2.1× |
| hit@5 | 0.082 | **0.202** | 2.5× |
| MRR@5 | 0.058 | **0.115** | 2.0× |

### Latency (per recall over the 62-memory corpus)

| mode | p50 | p95 | mean |
|---|---|---|---|
| lexical-only | 1.33 ms | 1.85 ms | 1.32 ms |
| hybrid | 2.76 ms | 3.31 ms | 2.79 ms |

In-process, no service, no vector database. The one-time model load
(~100 ms) is excluded; embedding-index refresh is incremental and
content-hash keyed.

### Model size ablation (authored 294-case suite)

| model | size | zero-overlap hit@3 | hit@5 | hybrid mean latency |
|---|---|---|---|---|
| none (lexical) | 0 | 0.064 | 0.074 | 1.15 ms |
| potion-base-8M (default) | ~30 MB | 0.149 | 0.234 | 2.62 ms |
| potion-base-32M | ~120 MB | 0.160 | 0.266 | 3.73 ms |

The 32M model buys little over 8M on this task, which is why 8M is the
default (`LINK_SEMANTIC_MODEL` overrides it).

## Honest limitations

- **Pure paraphrases remain hard.** Hybrid recall doubles-to-triples
  zero-overlap performance, but the majority of pure paraphrases still miss
  the top 5 at this corpus size with a 30 MB static model. Link labels
  every semantic-only match (`match: semantic`, capped confidence) so agents
  verify before trusting — we consider honest uncertainty a feature, and we
  publish the miss rate rather than hiding it.
- **The dataset is authored by the Link project.** It was written before
  tuning was finalized and the scoring gate fails the build if hybrid ever
  regresses lexical, but it is not an independent third-party benchmark.
  Contributions of adversarial cases are welcome — the format is five lines
  per intent in `scripts/recall_dataset.py`.
- **Not comparable to hosted-memory benchmark numbers** (e.g. DMR/LoCoMo
  scores from cloud systems): those measure LLM answer quality with
  server-side embeddings or knowledge graphs and per-ingestion LLM calls.
  Link's benchmark measures deterministic local ranking with zero network
  and zero LLM involvement — a different, stricter privacy contract.

## Reproduce

```bash
git clone https://github.com/gowtham0992/link && cd link
python3 -m venv /tmp/linkbench && /tmp/linkbench/bin/pip install model2vec
/tmp/linkbench/bin/python scripts/eval_recall_quality.py --suite full --mode real --allow-download
# lexical baseline only (no dependencies):
python3 scripts/eval_recall_quality.py --suite full --mode off
```

`--mode fake` runs a deterministic no-model embedder; CI uses it with a
regression gate: hybrid may never score below lexical on any group metric.
