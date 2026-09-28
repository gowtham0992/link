# Link recall quality benchmark

Link's recall is measured, not asserted. This document holds the current
numbers, exactly how they were produced, and how to reproduce them on your
own machine. Numbers are from 2026-09-26 on `develop` at 46a3c58 (the 4.0
pre-release) unless a section says otherwise, with 3.x figures beside them
where they changed.

| track | question | headline |
|---|---|---|
| 1. Link recall benchmark | does recall find the right memory? (1,176 cases) | hit@1 0.671 lexical, 0.789 quality tier |
| 2. LoCoMo retrieval | third-party questions over 5,882 conversation turns | hit@10 0.716 lexical, 0.826 with rerank |
| 3. Memory hygiene | does the store stay clean over months? | 0 junk, 0 contradiction exposure |
| 4. End-to-end QA | answers under mem0's own harness (pre-4.0) | 84.8% vs mem0 platform 83.2% |
| 5. Memory poisoning | can an injected instruction become memory? | 0 of 18 unlabeled, across 4 channels |
| 6. Token economics | what does a recall cost? | 1,697 tokens at micro, flat as the store grows |
| 7. Behavioral A/B | does an agent with Link do the right thing? | 11 of 12, vs 0 of 12 without |
| 8. Claim updates | does recall return the current value? | 0.94 current, 0 stale with lineage |
| 9. Staleness | does `lnk stale` cry wolf? | 0 false flags in 345 references |
| 10. Contradiction flags | what does the optional NLI tier add? | 0 false alarms, +1 revision caught |
| 11. Instruction files | does `lnk stale --instructions` cry wolf on real repositories? | 0 false flags in 604 references; 8 of 8 findings true |
| 12. Enforced rules | do reviewed rules stop the calls they name, and only those? | 17 of 17 caught, 0 of 34 ordinary calls stopped |

Tracks 1-3, 5-12 need no LLM and no network and run in CI or from one
command each (see Reproduce).

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

Full suite, Apple M4, macOS 26, Python 3.14, run 2026-09-26, Link
`develop` at 46a3c58 (4.0 pre-release). **The lexical column is what a
default `pip install link-mcp` gives you**; the fast and quality columns
each require an optional extra and a one-time local model download. CI
runs this suite to gate dataset integrity (corpus size, authored-case
count, and that the zero-overlap group stays genuinely hard for lexical
matching) - it does not pin the hit@1 scores themselves.

**The groups moved in 4.0, so compare with care.** Overlap is measured with
Link's own stemmer, and 4.0's stemmer does what its docstring always said
("committing" meets "commit", "licensed" meets "license"). 32 cases that
3.x counted as pure paraphrases now share a stemmed word with their target,
so the split is 832 / 344 instead of 800 / 376. The zero-overlap group got
harder (lexical now scores exactly 0 at hit@1 on it), and a 3.x row and a
4.0 row are not the same cases.

### Token-overlap queries (832 cases)

| metric | lexical | fast tier | quality tier |
|---|---|---|---|
| hit@1 | 0.671 | 0.740 | **0.789** |
| hit@3 | 0.827 | 0.885 | **0.936** |
| hit@5 | 0.841 | 0.897 | **0.960** |
| MRR@5 | 0.743 | 0.810 | **0.861** |

### Zero-overlap queries — pure paraphrases (344 cases)

| metric | lexical | fast tier | quality tier |
|---|---|---|---|
| hit@1 | 0.000 | 0.044 | **0.154** |
| hit@3 | 0.023 | 0.198 | **0.398** |
| hit@5 | 0.058 | 0.311 | **0.503** |
| MRR@5 | 0.019 | 0.133 | **0.281** |

Lexical recall cannot reach these by construction; the quality tier finds
half of them in the top 5.

With the opt-in rerank tier on top of the quality tier, token-overlap hit@1
is 0.798 and pure-paraphrase hit@5 0.535 (MRR@5 0.862 and 0.288), at 30 ms
p50 on this corpus. On claim-shaped memories it adds little now: 3.x
measured 0.749 to 0.839 at hit@1, and 4.0's better ranking underneath has
taken most of that gain already. On conversation turns (Track 2) it is
still the largest single lift.

### Latency (per recall, 62-memory corpus, model load excluded)

| mode | p50 | mean |
|---|---|---|
| lexical | 1.4 ms | 1.6 ms |
| fast tier | 4.2 ms | 4.2 ms |
| quality tier | 11.3 ms | 12.1 ms |

### Latency on large stores (lexical, synthetic store)

Recall stays usable as a store grows. Measured on a synthetic store of
decision memories drawn from a 40-word engineering vocabulary, so a common
query word matches about a third of the store (a worst case; real stores
are sparser). `recall` is `lnk recall`'s ranking step; `query` is the full
budgeted packet; `cold` is a fresh process's first packet, parsing
included.

| memories | recall (4.0) | recall (3.0) | query (4.0) | query (3.0) | cold (4.0) | cold (3.0) |
|---|---|---|---|---|---|---|
| 1,000 | 33 ms | 31 ms | 20 ms | 76 ms | 112 ms | 208 ms |
| 5,000 | 158 ms | 142 ms | 76 ms | 385 ms | 615 ms | 1,166 ms |
| 20,000 | 730 ms | 578 ms | 701 ms | 1,667 ms | 4,377 ms | 5,785 ms |

4.0 matches whole words, weighs rare words and checks the top results for
contradictions, which costs recall at the largest size about a quarter more
time than 3.0's substring checks. Records parsed once per file change and a
single scoring pass make the packet 2-5x faster. A pre-release build was
4.4x slower than 3.0 at 20,000 memories; the benchmark caught it, and it was
fixed before release (one regex per acronym per field, rebuilt word sets,
full annotation of every candidate).

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

Run 2026-09-26 on `develop` at 46a3c58 (4.0 pre-release).

| metric | lexical | fast tier | quality tier | quality + rerank | 3.x lexical | 3.x quality |
|---|---|---|---|---|---|---|
| any-evidence hit@1 | 0.350 | 0.296 | 0.329 | **0.453** | 0.266 | 0.329 |
| any-evidence hit@5 | 0.628 | 0.536 | 0.594 | **0.753** | 0.537 | 0.609 |
| any-evidence hit@10 | 0.716 | 0.720 | 0.779 | **0.826** | 0.628 | 0.737 |
| evidence recall@10 | 0.643 | 0.650 | 0.705 | **0.756** | 0.560 | 0.660 |
| latency p50 / mean | 20 / 20 ms | 34 / 34 ms | 49 / 69 ms | 296 / 334 ms | 28 ms | 58 / 75 ms |

The rerank tier (opt-in: a local cross-encoder re-orders the top 50
candidates, blended with the retrieval order) is the best configuration on
every metric, and it applies only to explicit recall calls, never hooks or
briefs. Its 3.x figures were hit@10 0.794 and recall@10 0.717.

4.0's lexical changes (whole words, rare words weigh more, stopwords,
acronyms, a stemmer that works) lift lexical hit@1 from 0.266 to 0.350 and
hit@10 from 0.628 to 0.716, with no model and faster than before. They
also changed which tier wins where. Without the reranker, the semantic
tiers still lead at hit@10 and evidence recall@10, but at hit@1 and hit@5
they now score **below** lexical: the semantic points that used to rescue a weak lexical top result
now displace a strong one.

We measured the obvious fix and declined it. Scaling the semantic
contribution down fixes LoCoMo (quality tier at 0.3x: hit@1 0.378, hit@5
0.712, hit@10 0.786, all above lexical) and costs Link's own claim-shaped
benchmark exactly what the semantic tier exists for: pure-paraphrase hit@5
falls from 0.503 to 0.334. Link stores claims, not chat turns, and LoCoMo
has no held-out split to tune against, so the weight stays. If your store
is a conversation archive and you do not run the rerank tier, lexical is
the better default for top-5 precision today.

Method fix in this run: the benchmark's turn records carried the turn text
only in the body, while real memory records also carry it as a snippet,
which is what the reranker reads. A first 4.0 rerank run therefore scored
the speaker name and a date and collapsed to hit@1 0.160; the records now
carry the snippet real records have, and nothing else about the benchmark
changed (the other columns reproduce exactly).

### Precision: what recall alone cannot show

Recall is the number this category publishes. It cannot separate a system that
retrieves cleanly from one that returns everything, because returning
everything scores 1.0 by construction. Measured on the same 1,536 third-party
queries:

| strategy | precision | evidence recall |
|---|---|---|
| return the whole store (588 turn-memories) | 0.0026 | **1.0000** |
| Link, lexical, top 10 | 0.0816 | 0.6430 |
| Link, quality tier, top 10 | 0.0895 | 0.7047 |
| Link, quality + rerank, top 10 | **0.0980** | 0.7561 |
| Link, quality + rerank, top 1 | **0.4525** | - |

A store dump wins recall outright and carries 0.26% signal. Link's top-10
packet carries ~37x that precision with the rerank tier and its top result
~170x, and takes a real recall loss for it. Both halves belong
in the table.

Raw precision@k needs its ceiling to be readable: LoCoMo evidence sets average
1.53 turns, so no system can exceed precision@10 of 0.152.

| metric | lexical | fast tier | quality tier | quality + rerank | ceiling |
|---|---|---|---|---|---|
| precision@1 | 0.3496 | 0.2962 | 0.3294 | **0.4525** | 1.0000 |
| precision@5 | 0.1368 | 0.1134 | 0.1290 | **0.1703** | 0.2958 |
| precision@10 | 0.0816 | 0.0810 | 0.0895 | **0.0980** | 0.1521 |
| % of ceiling @10 | 53.6% | 53.3% | 58.8% | **64.4%** | - |
| R-precision | 0.3288 | 0.2695 | 0.3096 | **0.4308** | 1.0000 |

R-precision (precision at k = |gold|) is the figure to compare across systems:
it does not depend on a chosen k. In 3.x it was 0.2598 lexical and 0.2855 on
the fast tier.

Method note: this reports the retrieval stage only, with no LLM and no judging,
which is what makes precision measurable at all. Answer-quality benchmarks
cannot expose this gap, since a noisy candidate set still lets the model
recover the answer (arXiv 2605.11325).

**How the shipped configuration was chosen (measured on 3.x ranking).**
The paragraphs below are the development history behind the ranking, with
the numbers as they were measured at the time.

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
best configuration measured (0.737). **Rerank tier (opt-in), as first measured.** A local cross-encoder
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
deterministic stream of 142 authored session events (42 durable facts, 12
mid-stream revisions, plus agent echoes, Link's own injected briefs,
memory-free noise sessions, quiz/debug questions containing absolute
keywords, pasted third-party AI advice inside user turns, and verbatim
cross-session repeats — every event ground-truth labeled, no LLM). The
question, pasted-advice, and repeat classes were added in v2 after real-world
dogfooding showed exactly those shapes leaking into the review inbox; the
fixture now contains the junk we actually observed, not just the junk we
predicted:

- **gated** — Link's real pipeline: extraction drops Link-injected output,
  echo containment drops restatements, duplicates are refused, detected
  contradictions resolve by supersession with lineage.
- **ungated** — the same extractor and retrieval with governance off: every
  candidate stored, duplicates and contradictions coexist. This is a
  **governance ablation of Link itself**, not a reimplementation of any
  competitor — though architecturally it mirrors what unsupervised
  LLM-extraction memory does on every message. Maintainers of other systems
  are invited to run the same event stream through their pipelines.

Run 2026-09-26 on `develop` at 46a3c58 (4.0 pre-release); 3.x in the last column.

| metric | gated (Link) | ungated | gated in 3.x |
|---|---|---|---|
| junk stored (echo / self-brief / noise / question / pasted advice / repeat) | **0** (0.0%) | 30 (35.7%) | 0 |
| contradiction exposure@3 after a revision | **0.000** | 0.750 | 0.167 |
| active memories (42 facts, 12 of them revised along the way) | **42** | 84 | 42 |
| as-of temporal accuracy (revised facts) | **1.00** | 1.00 | 0.917 |
| temporal accuracy from plain language ("...in March", no ISO date) | **1.00** | 1.00 | 0.917 |
| current-truth precision@1 | **0.857** | 0.833 | 0.881 |

The ungated junk rate mirrors what users measure in production LLM-extraction
systems (a public mem0 audit found 97.8% junk after 32 days, over half of it
the system's own prompt text re-ingested). Link's junk rate is zero **by
construction**, and CI enforces it: the hygiene gate fails any change that
stores junk or loses to the ungated baseline.

Honest notes: gated contradiction exposure is now 0: the detector
supersedes all 12 authored revisions. 3.x missed two, both lexically
disjoint rephrasings, and 4.0 catches them with general rules rather than
fixture patches: revisions that name what they replaced ("moved from 8080
to 8443", "Buildkite replaced Jenkins", "5 times instead of 3") and value
changes to a stated claim (versions, ports, counts were invisible when short
tokens were dropped). Point-in-time accuracy is 1.00 because the wrong-
original auto-resolution that cost 3.x one reconstruction no longer happens.
Current-truth precision@1 fell from 0.881 to 0.857 (one query): the 4.0
ranking reads whole words and rare words, and one current fact now loses
its top slot to a topically closer one. We publish the drop rather than
tune it away.

As before, the detection rules were developed with this authored set in
view, so these are fit numbers, not blind scores. The claim-update slice
below was written after the ranking changes it measures and is the better
held-out check; contributed revision cases the detector has never seen are
the real test, and we welcome them. "Zero junk by construction" means zero
*self-inflicted* junk through automatic capture (echoes, self-briefs,
noise, questions, pasted third-party advice, repeats); a user can still
approve a bad memory - review gates shape what is proposed, not what humans
decide. When the optional local semantic tier is installed, a claim-vs-claim
embedding pass adds `semantic_revision` conflict candidates, and the
optional NLI tier (below) flags likely contradictions at write time; the
published table stays lexical-only on purpose, so it reproduces with no
model download.

## Track 4: End-to-end QA under mem0's own harness

*Measured on Link 2.x-3.x retrieval and not repeated for 4.0: the run needs
paid model calls for every answer and judgment. 4.0's retrieval changes are
measured in Tracks 1-3 above.*

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
vs mem0 platform 83.6%** on the same answers (n=1,538 per side; two
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

- **Pure paraphrases are much better, not solved.** Lexical recall cannot
  reach them at all; the quality tier finds half of them in the top 5, so
  the other half still miss on our corpus. Link labels every
  semantic-only match (`match: semantic`, capped confidence) so agents
  verify before trusting — we publish the miss rate rather than hiding it.
- **Track 1 is self-authored.** It is deterministic, auditable, and gated
  against regressions in CI, but it was written by the Link project.
  Track 2 exists precisely to complement it with third-party data;
  adversarial case contributions to Track 1 are welcome (five lines per
  intent in `scripts/recall_dataset.py`).
- **The quality tier costs a ~5 s model load**, so short-lived CLI calls
  and session-start hooks default to the fast tier unless you opt in.

## Track 5: Memory poisoning (adversarial)

A planted memory is injected into every future session, which makes agent
memory the highest-value prompt-injection target an agent system has: a
poisoned webpage, doc, or pasted AI output only has to survive one capture
to give orders forever. As far as we know no other memory system publishes
an adversarial benchmark on this surface.

`scripts/eval_memory_poisoning.py` drives 18 authored attacks (synthetic,
ground-truth labeled, no LLM — `scripts/poisoning_dataset.py`) through the
real pipeline, plus 6 benign directive controls that must never be flagged.
Attack classes: guardrail-bypass instructions, unattended-execution
"preferences" (sudo / --force without approval), data-exfiltration
conventions (ship ~/.ssh and .env in summaries), credential planting,
spoofed-approval framing, agent-directed durable commands, hearsay
carriers, and — added after the July 2026 MemGhost disclosure —
untrusted-channel write instructions: content from an email, newsletter,
or shared doc that tells the agent itself to silently write durable
memory. Every mitigation the MemGhost researchers proposed (user
confirmation before durable writes, source tagging, logged memory writes)
is Link's standing architecture, and the three MemGhost-shaped attacks
die in the pipeline: dropped, flagged, or defanged — none unlabeled.

| layer | what it does | attacks stopped here |
|---|---|---|
| extraction | hearsay/question/echo gates drop what was never the user's own claim | 6 of 18 |
| labeling | injection-shaped proposals carry a warning label into the inbox and decision trail | 9 of 18 |
| write gate | credential-shaped text refused even on a one-click accept | 1 of 18 |
| defanging | extraction strips the payload; only a harmless residue can be stored | 2 of 18 |

**Unlabeled exposure: 0 of 18. Benign false positives: 0 of 6.** Both are
CI-enforced — any change that lets an attack reach the inbox without a
label, or flags a legitimate directive, fails the build.

**The other ways in (added in 4.0).** A review found three channels into a
session that the layers above never saw, so the same 18 attacks now go
through each of them too:

| channel | how the attack arrives | result |
|---|---|---|
| harness text | written into the transcript in the user's name: a subagent report, command output, a compaction summary, a subagent turn, a peer session (6 wrappers) | 0 of 108 probes became a proposal |
| handoff | left as a session handoff, pushed to the top of the next session on any agent | 13 of 18 labelled in the brief; 0 injection-shaped attacks unlabeled; 0 credentials left unredacted |
| team import | shared as a teammate's `visibility: team` memory | 14 of 18 rejected at import, 4 quarantined for review, 0 active |

Before 4.0 the harness channel turned a subagent's report into a proposal
attributed to the user, a handoff carried a prose password verbatim, and a
team import became active memory with no review at all. Each of those is a
CI failure now. The five unlabeled handoffs are the attacks the detector
does not label in any channel (hearsay, a question, credential planting
that is redacted instead) - the handoff channel matches the direct one, it
does not get weaker.

Honest notes: labels are warnings, not blocks — a human may genuinely hold
a "never ask confirmation before builds" preference, so the pipeline never
censors; it attributes ("verify you actually said this before accepting").
The review gate remains the final defense for anything labeled, which is
the architecture's claim, not a hedge: memory writes that no human approved
do not exist in Link. The attack set was authored by us and the detector
was developed against it — these are fit numbers, not blind ones, and the
patterns are deliberately narrow to protect the zero-false-positive
property. Adversarial contributions that beat the layers are welcome and
will be added to the fixture.

## Track 6: Token economics

The literature names token cost as one of memory's persistent production
problems — "sending 100k tokens of history for a 50-token response is
financially unsustainable" — and published footprints differ by orders of
magnitude between systems. Link's answer is structural: retrieval returns a
*bounded packet*, not a context dump. Budgets cap memories, search results,
context pages, and the characters inside each, so cost is a function of the
budget you ask for, not of how much you have remembered.

`scripts/eval_token_economics.py` measures real packets through the real
query path, serialized exactly as the agent receives them.

Run 2026-09-26 on `develop` at 46a3c58 (4.0 pre-release); 3.x means in
the last column.

| budget | mean tokens | worst case | CI ceiling | 3.x mean |
|---|---|---|---|---|
| micro | 1,697 | 2,049 | 2,900 | 1,951 |
| small | 2,408 | 3,242 | 5,900 | 2,912 |
| medium | 3,130 | 5,249 | 10,200 | 3,886 |
| large | 3,752 | 7,681 | 16,800 | 4,835 |

4.0 stopped the packet repeating itself: the ranked list carried every
memory and page a second time, and over MCP each result also went back as a
duplicate structured copy. The ranked list is now references, which takes
13% off a micro packet and 22% off a large one.

The guarantee is the growth curve, not the absolute number:

| store size | mean tokens (medium) | growth |
|---|---|---|
| 25 memories | 3,011 | — |
| 100 memories | 4,066 | +35% |
| 400 memories | 4,692 | +15% |
| 1,600 memories | 4,708 | **+0.3%** |

**A 64x larger store produces a 1.56x larger packet, and the final
quadrupling moves it 0.3%.** Packet size climbs while the budget's slots
fill, then stops. Both properties are CI-enforced: every budget's worst
packet must stay under its ceiling, and the last quadrupling of the store
must not move the packet more than 5%.

**The MCP session brief is a separate, once-per-session cost - bounded.**
Link's first MCP tool response of a session carries a memory brief so that
agents without session hooks still get memory pushed to them. It is a
compact digest under a hard 4,000-character budget, enforced in code and
pinned by a test: the first recall measures **2,058 tokens** against a
steady state of **1,693**, a brief overhead of ~365 tokens. (Before the
digest, the full brief made that first recall cost 11,269 tokens.)
Per-recall figures above exclude it by design: it is paid once per session,
not per recall.

Honest notes: token counts use the 4-chars-per-token approximation Link
uses for its own budget reporting — exact counts vary by tokenizer, so
treat these as order-of-magnitude and, more importantly, as a *shape*.
Comparisons to published per-conversation figures from other systems are
not apples-to-apples: these are per-recall numbers, and a conversation
contains several recalls. What the table supports is narrower and more
useful — Link's cost is bounded and predictable, and does not degrade as
memory accumulates. One measured wrinkle worth stating: at the micro
budget roughly a fifth of the packet is fixed scaffolding (agent guidance,
follow-up actions, budget reporting) rather than retrieved content, which
is the obvious place to look for further savings.

## Track 7: Behavioral A/B - with and without Link

Retrieval scores say whether the right memory comes back. The question
people ask is whether an agent with Link *does the right thing* more often
than one without it. `scripts/eval_behavior_ab.py` answers the half Link
controls, with no model in the loop, and gives you the switch for the
other half.

Twelve scenarios whose correct answer depends on something the user said in
an earlier session: a deploy day, a branch rule, a package manager, a
test command, a port, a secrets rule, an owner, an API rule, a logging
choice, a style preference, and two decisions that were later reversed.
Their memories share one store with 48 realistic distractors. Condition A
is the task alone; condition B is what a connected agent actually has - the
session-start brief plus the task's recall packet (budget micro). Answers
are scored by fixed patterns: the current truth must appear, the stale or
generic answer must not.

In dry mode (CI) a deterministic oracle stands in for the model: it answers
correctly only when the governing memory is in its context, and follows the
earlier of two conflicting claims, the position bias real models show.

| | without Link | with Link |
|---|---|---|
| scenarios answered right (dry oracle) | 0 / 12 | 11 / 12 |
| governing memory in front of the agent | - | 11 / 12 |
| mean context added | - | ~2,850 tokens |

3.x scored 10 of 12. 4.0 closed the standing-preference gap: a preference
about how to answer shares no words with any task, so it fell out of the
session brief, and the brief now reserves two slots for such preferences.
The remaining miss is published as a known gap rather than tuned away, and
the gate fails on any new one: a question about "the database client
library" retrieves an unrelated "logging library" memory ahead of the
migration memory on the shared word, and the micro budget returns only one
memory.

Honest limits: the oracle measures delivery, not obedience - a real model
can ignore a memory it was given, or answer correctly without one. Run the
live track to measure that with your own agent; Link makes no network
calls, the command and its cost are yours:

```bash
python3 scripts/eval_behavior_ab.py --mode live --agent-command "claude -p --model claude-haiku-4-5" --yes
```

## Track 8: Claim updates - does recall return the current value?

LoCoMo asks about events in a conversation. Fact-update benchmarks ask
something else: when a fact changed two or three times, does recall return
the value that holds now? `scripts/eval_claim_updates.py` has 16 subjects
(a rate limit, a port, a database, a deploy day, a CI provider, a runtime
version, a preference, ...) with 36 versions, each queried in the claim's
own words and as a paraphrase that shares little vocabulary. It runs twice:
in a store where each update carries `supersedes` lineage (what the review
flow writes) and in one where it does not (updates saved without review).
It was written after the 4.0 ranking changes it measures and is gated in CI
as a floor, not tuned against.

| store | query | current value first | stale value first | miss |
|---|---|---|---|---|
| with lineage | direct | **0.94** | **0.00** | 0.06 |
| with lineage | paraphrase | 0.31 | **0.00** | 0.69 |
| no lineage | direct | 0.81 | 0.12 | 0.06 |
| no lineage | paraphrase | 0.25 | 0.06 | 0.69 |

Point-in-time recall between versions (`as_of`) returns the value that held
on that date 0.94 of the time in both stores.

With lineage, a superseded value never comes back first. Without it, recall
still puts the newer value first four times in five on direct questions:
4.0 recognises revisions that name what they replaced and reads the newer
of two contradicting results first, labelling the older one
`contradicted_by`. The paraphrase column is lexical-only and mostly misses,
which is what the semantic tiers are for; stale answers stay rare either
way.

## Track 9: Does a memory still hold? (`lnk stale`)

A memory about code goes wrong silently when the code changes. `lnk stale`
checks what a memory names against the repository - files, package
scripts, make and just targets, dependencies, environment variables, URLs,
runtime versions, the package manager, and code anchors (`path:line symbol`)
- and reports a reference only when git history shows it existed and no
longer does. `scripts/eval_staleness.py`, run on this repository:

| check | result |
|---|---|
| references in Link's own documentation | 345, **0 false flags** |
| known deletions from history | 6 probed, **0 missed** |
| prose that merely looks like a path | 3 probed, 0 flagged |
| 4.0 removal kinds (scripts, targets, deps, env vars, URLs, versions, lockfiles) | 7 probed, **0 missed**; a still-true memory flagged 0 times |

The precision rule is the product: a false "stale" flag trains people to
ignore the flag. The same rule gave 0 false flags across 298 references in
eight other real repositories during development.

## Track 10: Contradiction flags at write time

When a memory is written, word rules check it against stored memories for a
contradiction. The optional NLI tier (`lnk semantic <dir> --setup --nli`, an
~87 MB int8 model on onnxruntime) reads meaning instead of words.
`scripts/eval_contradiction_flags.py` measures both on 20 revisions from the
claim-update subjects (should flag) and 216 pairs of distinct memories from
the recall corpus that share a subject word (should not):

| detector | revisions caught | false alarms |
|---|---|---|
| word rules (always on) | **17 / 20** | **0 / 216** |
| NLI model alone, threshold 0.9 | 17 / 20 | 107 / 216 |
| NLI as shipped (30% subject-overlap gate) | 14 / 20 | **0 / 216** |

The model alone is unusable: it reads two different project rules as
mutually exclusive half the time. With the gate it raises no false alarms
and adds one revision the word rules miss ("I now prefer short answers" after
"I like detailed answers"). That is a small gain, and the tier is shipped as
opt-in for exactly that reason: its flag is a review note on the new memory,
never a refusal, it never runs on the recall path, and a model failure
cannot break a save.

## Track 11: Instruction files (`lnk stale --instructions`)

Measured 2026-09-28 on the 5.0.0 branch. AGENTS.md, CLAUDE.md and their
kin go out of date like memories do, and they are loaded into every
session. `scripts/eval_instructions.py` has two tracks.

**Planted.** A scratch repository whose AGENTS.md, CLAUDE.md, Cursor rule
and Windsurf rule name a script, a make target, a dependency, a variable and
a runtime version the repository then removes, run past the Codex and
Windsurf size limits, and contradict each other and a reviewed memory. It
also carries a rule copied into both AGENTS.md and CLAUDE.md, rules that
still hold, and history phrasing ("we dropped Python 3.9 support").

| | result |
|---|---|
| planted findings caught | 9 of 9 |
| quiet cases flagged (copies, still-true rules, history) | 0 |

**Eight public repositories** with instruction files, cloned with three
years of history (the engine's history window), every finding judged by
hand against the repository:

| repository (commit) | files | checkable references | findings | judged |
|---|---|---|---|---|
| openai/openai-agents-python (8e4350044c) | 1 | 59 | 1 size limit | true: AGENTS.md is 38,241 bytes, 5,473 past Codex's 32 KiB |
| modelcontextprotocol/python-sdk (f1b6589088) | 2 | 30 | 0 | |
| anthropics/anthropic-sdk-python (a7285e919a) | 1 | 71 | 1 guidance | true: CLAUDE.md is 368 lines |
| getsentry/sentry-python (2a499ec49c) | 1 | 17 | 0 | |
| astral-sh/uv (c9dab42beb) | 1 | 4 | 0 | |
| biomejs/biome (ff89559eff) | 1 | 14 | 0 | |
| denoland/deno (1b48a20f85) | 2 | 94 | 1 guidance | true: CLAUDE.md is 433 lines |
| pydantic/pydantic-ai (10c5f9b0bd) | 18 | 315 | 2 stale, 3 size limit | true: two AGENTS.md files still say tests use `pytest-anyio`, a dependency removed on 2026-09-26; three nested AGENTS.md chains run 3,663-9,114 bytes past 32 KiB |
| **total** | **27** | **604** | **8** | **8 true, 0 false** |

No real repository produced a contradiction finding; the planted ones were
all caught. The first run of this track found five false flags, all fixed
before these numbers, and the fixes also apply to memories: a
package-manager binary (`pnpm nx build`) read as a removed script, a
backticked `@decorator` read as a scoped package, a word in a manifest
comment read as a removed dependency, a just recipe with a default
parameter missed, and bare example filenames ("run main.ts") read as
references. Track 9 is unchanged by them: 0 false flags, 7 of 7 removals.

## Track 12: Enforced rules before each tool call

Measured 2026-09-28 on the 5.0.0 branch with `scripts/eval_enforcement.py`
(pinned by `tests/test_enforcement_eval.py`). A store of 50 memories, 10 of
them reviewed memories carrying 15 enforced rules, checked against the tool
calls a coding agent makes:

| | result |
|---|---|
| forbidden calls caught (inside `cd ... &&` chains, behind `sudo` and `env` prefixes, with extra flags, by absolute path) | 17 of 17 |
| ordinary calls stopped (`rm -rf dist`, `git push origin feature/x`, `terraform plan`, reading `.envrc.example`, writing under `src/`) | 0 of 34 |
| decision time, p95, in process | 0.149 ms |
| hook command, median, end to end | 99 ms, almost all Python start-up |

The hook reads a compiled rule index in `.link-cache/` that is rebuilt only
when a memory changes. A rule's pattern does exactly what it says: `.env*`
also matches `.envrc.example`, so the bundled rules name `.env` and
`.env.*`.

## Reproduce

```bash
git clone https://github.com/gowtham0992/link && cd link

# Track 12:
python3 scripts/eval_enforcement.py

# Track 11 (planted track needs nothing; pass --repo for real checkouts with history):
python3 scripts/eval_instructions.py
git clone --shallow-since=2023-09-28 https://github.com/pydantic/pydantic-ai /tmp/pydantic-ai
python3 scripts/eval_instructions.py --repo /tmp/pydantic-ai

# Track 1 (lexical baseline needs nothing):
python3 scripts/eval_recall_quality.py --suite full --mode off
python3 -m venv /tmp/linkbench
/tmp/linkbench/bin/pip install model2vec            # fast tier
/tmp/linkbench/bin/pip install fastembed            # quality tier (preferred when present)
/tmp/linkbench/bin/python scripts/eval_recall_quality.py --suite full --mode real --allow-download
/tmp/linkbench/bin/python scripts/eval_recall_quality.py --suite full --mode real --rerank --allow-download

# Track 2 (download the dataset yourself; CC BY-NC 4.0 © Snap Inc.):
curl -L -o /tmp/locomo10.json https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json
python3 scripts/eval_locomo.py /tmp/locomo10.json --mode off
/tmp/linkbench/bin/python scripts/eval_locomo.py /tmp/locomo10.json --mode real
/tmp/linkbench/bin/python scripts/eval_locomo.py /tmp/locomo10.json --mode real --rerank

# Tracks 3 and 5-10 need nothing beyond Link itself (Track 10's model rows
# need `lnk semantic <dir> --setup --nli`):
python3 scripts/eval_memory_hygiene.py
python3 scripts/eval_memory_poisoning.py
python3 scripts/eval_token_economics.py
python3 scripts/eval_behavior_ab.py
python3 scripts/eval_claim_updates.py
python3 scripts/eval_staleness.py
python3 scripts/eval_contradiction_flags.py
```

`--mode fake` runs a deterministic no-model embedder; CI uses it with a
regression gate: hybrid may never score below lexical on any group metric.
