# Link recall quality benchmark

Link's recall is measured, not asserted. This document holds the current
numbers, exactly how they were produced, and how to reproduce them on your
own machine. There are three tracks:

1. **Link recall benchmark** — our own deterministic, fully auditable
   dataset (checked into this repo; no LLM, no network, no randomness).
2. **LoCoMo third-party track** — the retrieval stage of the long-term
   conversational memory benchmark the hosted-memory industry quotes
   (Maharana et al., ACL 2024, Snap Research), using only its third-party
   questions and evidence annotations.
3. **Memory hygiene over time** — a multi-month session simulation measuring
   whether the store stays trustworthy: junk rate, contradiction exposure,
   store growth, and temporal accuracy, gated vs ungated.

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
- **Token-level late interaction (MaxSim over static token vectors)**: worse
  than blob embeddings on both groups (zero-overlap hit@5 0.160 vs 0.202) —
  static per-token vectors are too noisy for ColBERT-style matching.
- **Corpus-mined PMI query expansion** (learning the user's vocabulary from
  their own wiki): cannot help zero-overlap queries by construction (there is
  no shared token to expand from) and slightly hurt token-overlap hit@1 by
  pulling in competing memories. Rejected.

## Research context

Two of Link's most-questioned design choices now have independent academic
support. A controlled ablation of memory representations (arXiv:2601.00821)
found verbatim conversation chunks beat LLM-extracted artifacts by 15.9
points on LoCoMo and 22.0 on LongMemEval-S — "retrieval accuracy tracks how
far the representation departs from the source" — with the winning hybrid
being verbatim text supplemented by distilled artifacts, which is Link's
raw-sources-plus-reviewed-memories layout. Separately, a study of
conversational memory retrieval (arXiv:2603.15599) found ranking quality
beats graph structure, consistent with our own rejected entity-graph
ablation below. Neither paper is affiliated with Link.

## Track 2: LoCoMo third-party retrieval

Every dialog turn of a LoCoMo conversation becomes one memory record; every
evidence-annotated question (adversarial category excluded) becomes a recall
query; we measure whether Link ranks the annotated evidence turns highly.
10 conversations, 5,882 turn-memories (~590 per conversation), 1,536
third-party queries. No LLM anywhere: this isolates the retrieval stage with
third-party queries and third-party gold labels.

| metric | lexical | hybrid (quality tier) |
|---|---|---|
| any-evidence hit@1 | 0.266 | **0.329** |
| any-evidence hit@5 | 0.537 | **0.609** |
| any-evidence hit@10 | 0.628 | **0.737** |
| evidence recall@10 | 0.560 | **0.660** |
| latency p50 / mean | 28 ms | 58 ms / 75 ms |

**Context-window records.** Each turn record carries its ±1 dialogue
neighbors in the record's `context` field — retrieval text that is not part
of the memory's claim (echo/duplicate/conflict checks and recall output
never see it). Failure analysis showed the dominant miss was conversational
deixis: a gold turn like "the stories were so inspiring" is only findable by
what it was about, and the surrounding turns give that away for free.
Context-free turn records (the previous rows) scored hybrid hit@10 0.685 /
recall@10 0.608; context lifts that to 0.737 / 0.660 and helps every
category, most strongly single-hop (hit@10 0.713 → 0.816 in the prototype).
Ablation that did not survive: splicing a hit's dialogue neighbors into the
ranked list at recall time *hurt* (hit@10 0.685 → 0.550) — neighbors displace
genuinely ranked turns; context must inform scoring, not bypass it.
Three further challengers to the shipped ranking also measured worse, with
correct primitives and the same protocol: reciprocal rank fusion of the
lexical and semantic rankings (hit@10 0.616), Okapi BM25 replacing Link's
field-weighted lexical scoring inside the fusion (0.627 alone, 0.691 with a
deterministic entity-activation layer), and HippoRAG-style one-step entity
activation over a speaker/proper-noun graph (no measurable lift over its
base fusion). The shipped ranking — field-weighted lexical scoring over
claim + context, merged with standout-based semantic scores — remains the
best configuration measured (0.737). **Rerank tier (opt-in).** A local cross-encoder
(Xenova/ms-marco-MiniLM-L-6-v2, 0.08 GB ONNX) re-orders the top 50 recall
candidates, blended with the retrieval order via reciprocal-rank fusion.
On the default embedder this lifts any-evidence hit@10 0.737 → 0.794,
evidence recall@10 0.660 → 0.717, and multi-hop evidence recall
0.350 → 0.403 — and on the bundled benchmark lifts token-overlap hit@1
0.749 → 0.839 and pure-paraphrase hit@5 0.338 → 0.436, so the gain holds
across both text shapes. Cost: ~0.5 s per recall at 50 candidates, so the
tier applies only to explicit recall calls, never hooks or briefs.
Ablation: using the reranker score alone (no blend) collapsed hit@1
0.380 → 0.182 by promoting topically related non-evidence turns.

**Embedding models are not interchangeable across text shapes.** A sweep of
four modern small local models found the rankings invert between benchmarks:
nomic-embed-text-v1.5-Q wins LoCoMo (hit@10 0.787 vs 0.737 for the default
all-MiniLM-L6-v2) but loses the bundled claim-shaped suite (hit@1 0.713 vs
0.749), with bge-small-en-v1.5 between the two on both. The default stays
all-MiniLM-L6-v2; `LINK_SEMANTIC_MODEL=nomic-ai/nomic-embed-text-v1.5-Q` is
the measured recommendation for conversational-archive workloads.

Remaining known headroom is multi-hop evidence recall (0.403 with the rerank
tier): questions whose gold evidence spans 3+ scattered turns; the honest
answer today is agent-side iterative recall, not memory-layer reasoning.

**Development-set honesty.** The retrieval improvements above (context
records, the rerank tier, and the rejected ablations) were selected by their
scores on this same query set — LoCoMo has no held-out split, and we did not
create one. Treat the deltas as development-set results: directionally real
(each change also had to hold or lift the bundled benchmark, a different
corpus and query style), but the absolute numbers carry selection bias.
Anyone can rerun every configuration from the scripts in this repo.

**Not comparable to published LoCoMo QA scores** (mem0, Zep, etc. report
end-to-end LLM answer quality with server-side pipelines). This track scores
deterministic local ranking only — no answer generation, no LLM judging, no
network. The dataset is CC BY-NC 4.0 © Snap Inc. and is not redistributed
here; the script prints the download command.

## Track 3: Memory hygiene over time

Retrieval benchmarks measure a frozen store. This track measures whether the
store stays *trustworthy* as sessions accumulate — the axis on which
review-gated architecture differs from unsupervised extraction.

`scripts/eval_memory_hygiene.py` drives two pipelines over the same
deterministic stream of 112 authored session events (42 durable facts, 12
mid-stream revisions, plus agent echoes, Link's own injected briefs, and
memory-free noise sessions — every event ground-truth labeled, no LLM):

- **gated** — Link's real pipeline: extraction drops Link-injected output,
  echo containment drops restatements, duplicates are refused, detected
  contradictions resolve by supersession with lineage.
- **ungated** — the same extractor and retrieval with governance off: every
  candidate stored, duplicates and contradictions coexist. This is a
  **governance ablation of Link itself**, not a reimplementation of any
  competitor — though architecturally it mirrors what unsupervised
  LLM-extraction memory does on every message. Maintainers of other systems
  are invited to run the same event stream through their pipelines.

| metric | gated (Link) | ungated |
|---|---|---|
| junk stored (echo / self-brief / noise) | **0** (0.0%) | 16 (23.9%) |
| contradiction exposure@3 after a revision | **0.333** | 0.833 |
| active memories (ground truth: 54) | **40** | 67 |
| as-of temporal accuracy (revised facts) | **1.00** | 1.00 |
| current-truth precision@1 | 0.762 | 0.762 |

The ungated junk rate mirrors what users measure in production LLM-extraction
systems (a public mem0 audit found 97.8% junk after 32 days, over half of it
the system's own prompt text re-ingested). Link's junk rate is zero **by
construction**, and CI enforces it: the hygiene gate fails any change that
stores junk or loses to the ungated baseline.

Honest notes: gated contradiction exposure is 0.333, not zero — Link only
supersedes contradictions its deterministic detector catches (8 of 12
authored revision shapes today), and this benchmark now grades that detector.
Full disclosure: the revision-shape detection rule was developed against this
same authored set (it moved the number from 0.417 during development), so
8/12 is a fit, not a blind score — contributed revision cases the detector
has never seen are the real test, and we welcome them. "Zero junk by
construction" means zero *self-inflicted* junk through automatic capture
(echoes, self-briefs, noise); a user can still approve a bad memory — review
gates shape what is proposed, not what humans decide. Current-truth
precision ties because both pipelines share the same retrieval; the gated
advantage there appears exactly when the outdated version would otherwise
outrank the current one (the exposure metric).

## Track 4: End-to-end QA under mem0's own harness

Tracks 1–3 isolate retrieval and governance. This track runs the full
question-answering pipeline — ingest, retrieve, answer, judge — under
[mem0's open benchmark harness](https://github.com/mem0ai/memory-benchmarks)
with a Link backend, so the numbers are directly comparable to the raw
result files mem0 publishes in that repository. Full provenance notes,
the Link backend adapter, and every judgment live in our benchmark
workspace; config: top-50 memories per answer (single cutoff),
claude-haiku-4-5 as answerer and judge, ~2.7k mean tokens per answer
call, zero LLM calls and zero cost at ingest.

**LoCoMo, full 1,540 questions:**

| system | answerer | judge | accuracy |
|---|---|---|---|
| **Link (local files)** | haiku-4-5 | haiku-4-5 | **84.8%** |
| mem0 v3 platform (cloud) | gpt-5 | haiku-4-5 (same judge) | 83.2% |
| mem0 v3 platform (cloud) | gpt-5 | gpt-5 (their own) | 82.66% |

The middle row is mem0's own published raw answers re-judged with the
identical judge model that scored Link, using the harness's own judge
prompt — so the comparison holds under one referee. The haiku judge
proved slightly stricter than gpt-5 on their answers, and their answers
were written by gpt-5 while Link's came from a budget model: both
asymmetries favor mem0, and Link still leads (multi-hop: 85.1 vs 82.3).
Their 91.6% headline configuration uses top-200 (~7k tokens/call) —
more than twice Link's token budget.

The result also holds under a second, independent judge — Tencent
Hunyuan 3 (295B open weights, unrelated to either lab): **Link 85.5%
vs mem0 platform 83.5%** on the same answers (n=1,538 per side; two
questions per side hit persistent gateway errors and are excluded
identically). Two unrelated judges, same verdict, slightly wider
margin under the neutral one.

**LongMemEval, full 500 questions: 78.0%** (knowledge-update 92.3,
single-session-user 90.0, temporal-reasoning 81.2, preference 76.7,
single-session-assistant 66.1, multi-session 65.4, abstention 22/30).
Not directly comparable to mem0's published 90.4%: every number in
their files uses gpt-5 as both answerer and judge, and LongMemEval is
heavily answerer-reasoning-bound.

We also ran the whole comparison under the neutral Hunyuan 3 judge, in
both directions: mem0's own gpt-5 answers score **91.0%** (so their
published number was not judge-inflated — it holds up under an
unrelated referee, and we say so), Link's haiku answers score **80.6%**,
and swapping Link's answerer from haiku to Hunyuan 3 itself also lands
at **80.6%** (per-category shifts: single-session-user 95.7,
knowledge-update 94.9, temporal 82.7). The ~10-point gap between
answer sets written by gpt-5 and by budget/open models is the
answerer effect the evidence analysis above predicts — on this
benchmark the answering model, not the memory layer, dominates the
score, which is why we publish the retrieval decomposition (evidence
in context for 99.4% of questions) as the memory-layer signal.

What *is* directly measurable without any judge: replaying Link's
deterministic ingest maps every retrieved memory to its source session,
so we can check whether retrieval surfaced the gold evidence. **Link
put evidence sessions in the top-50 context for 99.4% of questions**
(complete evidence: 92.6%); of 102 failures, 3 were retrieval misses
and 79 had the full evidence already in context — the score is
answerer-limited, not memory-limited.

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
