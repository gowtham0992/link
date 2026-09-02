# Changelog

All notable changes to Link are tracked here.

Release sections use `MAJOR.MINOR.PATCH` versions that match `link-mcp` on PyPI and the MCP Registry. Keep `Unreleased` for work merged after the latest published version.

## [Unreleased]

### Added

- **Recall works outside English.** The tokenizer split on `[^a-z0-9]+`, so
  every non-Latin script produced zero tokens: Japanese, Chinese, Korean,
  Russian, Arabic, and Indic memories were unfindable, and nothing said so -
  recall simply returned nothing. Accented Latin fared little better,
  `über Größe Straße` became `{ber, stra}`, and `déploiement` could not be
  found by typing `deploiement`. Scripts written without spaces are now cut
  into character bigrams, Latin accents are folded (along with `ß`, `ø`, `ı`
  and friends), and the three-character floor - an English heuristic that
  erased shorter words wholesale - applies only to Latin text. Combining
  marks in Indic scripts are vowels rather than accents and are kept:
  stripping them turned `मंगलवार` into `गलव`. ASCII text keeps the original
  path exactly, so no existing memory changes token and no existing ranking
  moves; the LoCoMo track returns all nine published figures unchanged across
  1,536 third-party queries, and the ASCII path is marginally faster than
  before. Wiki page full-text search had the same bug one layer down: its
  query normalizer deleted every non-ASCII character before SQLite ever saw
  it, so `lnk search` for any non-Latin query produced zero terms. Both the
  index and the query side now segment text the same way recall does, and
  the FTS cache moves to v2 so existing indexes rebuild - the first recall
  after upgrading pays that rebuild once. Segmentation follows Lucene's
  CJKAnalyzer: overlapping character bigrams, no dictionary. The fast
  semantic tier's default model is English-trained; measured on a Japanese
  set it neither helped nor hurt (6/6 with and without), so non-English
  recall is lexical-quality by default. The multilingual static model
  (`minishlab/potion-multilingual-128M`, 101 languages) is 512 MB against
  the default's ~30 MB, so it stays opt-in:
  `LINK_SEMANTIC_MODEL=minishlab/potion-multilingual-128M`.
- **`lnk ingest` for structured exports** (#66, contributed by @jakobtfaber).
  A plan-first importer for supported structured sources, starting with the
  `chezmoi-docs-graph-v1` adapter: provenance manifests hashed per output,
  staging through a temporary directory, validation before promotion, and
  explicit `--replace-unmanaged` and `--prune` gates so nothing is
  overwritten or deleted without being asked. Imported documentation lands in
  the wiki, never in memory, and is kept out of automatic personal-memory
  proposals. Review found two things, fixed before release: text-mode
  `--apply` crashed after succeeding, and the proposal guard matched a
  substring so a capture that merely mentioned the feature lost its
  proposals; it now keys off the export's shape.
- **`lnk stale` - notice when a memory outlived the code it describes.** The
  most repeated complaint about agent memory is that nothing can tell when a
  memory stopped being true: a note says a thing lives in `a/b.py`, the file
  is renamed, and the memory keeps being retrieved and believed. Hosted
  memory services cannot fix this because they never see the repository. Run
  `lnk stale` from inside a repository and it lists memories naming files git
  no longer has, with the successor path where git recorded a rename. A
  memory is questioned only when it names a path that is missing now *and*
  that git tracked before - without the second half, an unresolvable path is
  just prose and flagging it is the noise that teaches people to ignore the
  flag. The command changes nothing; findings go to the same review gate as
  everything else. Precision is measured rather than asserted:
  `scripts/eval_staleness.py` reports 0 false flags across 95 path references
  in this repository's own documentation, detects every probed deletion, and
  exits non-zero if either changes.

### Measured and declined

- **Usage-aware ranking.** Four formulations were built and measured -
  additive frequency, tiebreak-only, recency decay in the Generative Agents
  form across the recommended 7-30 day half-life range, and an MMR diversity
  penalty - and none ship. Every one either made memories that had gone
  unread harder to find or did nothing; recency was worst, with the old half
  losing 0.0510 while the fresh half gained 0.0204 at a 30-day half-life. The
  reason is a category difference: those policies suit episodic observation
  streams, and Link stores durable constraints, which do not become less true
  for going unread - that is when they most need surfacing.
  `scripts/eval_salience.py` holds all four closed and fails on any
  regression, so the next attempt has to clear the same bar.

### Fixed

- **Memories with non-Latin titles no longer collide.** Page names came from a
  `[^a-z0-9]` slug, so a Japanese, Hindi, Korean, Arabic or Cyrillic title
  slugged to nothing and every such memory was filed as `memory.md`. The
  second one then matched the duplicate gate's same-slug rule with a perfect
  score and was refused, so a non-English user could save exactly one memory.
  Titles now keep their own script (`東京のデプロイ曜日.md`, `डिप्लॉय-का-दिन.md`),
  Latin accents fold so filenames stay typeable (`zurich-deploy-regel.md`),
  the length cap counts bytes for multibyte scripts, and titles that slug to
  nothing (emoji-only) no longer read as duplicates of each other. ASCII
  titles keep their exact historical slugs; existing pages are untouched.
  The recall packet's ranking key uses the same rules, so non-Latin wiki
  pages no longer share one empty key.
- **LinkBar 1.4.0.** Fixes first: the health probes ran on the main
  actor, so the popover froze for a second or two on every Status refresh;
  they now run concurrently off it, and the five inbox reads run together
  instead of one after another. The review inbox showed five items and
  silently hid the rest; the tab now scrolls and stays on screen on a 13"
  display. Approve, archive, accept and discard confirm what they did, and a
  refused save reports the CLI's actual reason (duplicate, conflict, secret)
  instead of a guess. The live-agent pulse names the repository from the
  transcript's working directory, so `link-pr66` no longer reads as `pr66`.
  `lnk` is found for pipx and venv installs, which a Finder-launched app's
  minimal PATH used to miss. Then the two things people asked for: the
  workspace is chosen in Settings and remembered (a Finder-launched app never
  saw `LINK_WORKSPACE`), and the memory filter matches the way Finder does,
  so typing `zurich` finds `Zürich`.
- **LinkBar shows stale references.** A Status row runs `lnk stale` against
  the repository your most recent agent session is working in and lists the
  memories that name files it no longer has, with a one-click filter on the
  Memory tab and an amber dot in the menu bar. On a CLI older than 3.0 the
  row says so instead of checking forever. The palette gained ↑↓ selection,
  and recall rows mark memories that default recall would hold back.

### Removed

- **The Bar CI investigation integration.** Its Cloudflare side is gone, so
  the collector, summary poller, PR comment writer, their tests, and the
  workflow that drove them come out. The release-hygiene network allowlist is
  back to a single entry, the local viewer smoke test.

### Changed

- **The retrieval benchmark reports precision, not only recall.** Recall is
  the number this category publishes, and it cannot separate a system that
  retrieves cleanly from one that returns everything, because returning
  everything scores 1.0 by construction. On the same 1,536 third-party LoCoMo
  queries, a whole-store dump carries 0.26% signal while Link's top-1 packet
  reaches 0.3086 precision on the fast tier - 117x - and pays a real recall
  cost that is published in the same table. The track now also reports the
  ceiling each cutoff allows (LoCoMo evidence sets average 1.53 turns, so
  precision@10 cannot exceed 0.152 for anyone) and R-precision as the
  k-independent figure to compare across systems.


## [2.3.0] - 2026-08-12

### Fixed

- **LinkBar crashed at launch for everyone but the build host** (#58,
  reported by @SparklesKitchen with a root cause and a verified fix).
  SPM's generated `Bundle.module` accessor calls `fatalError()` when it
  cannot find its resource bundle, and it only looks in two places: the
  app root, and the absolute build directory of the machine that
  compiled the binary. A packaged `.app` has neither - `bundle.sh` put
  the bundle in `Contents/Resources/` - so every cask install since
  1.0.0 died at launch, silently, because an `LSUIElement` app has no
  window to show a crash. It only ever worked on the maintainer's
  machine, where the compiled-in build path resolves. LinkBar no longer
  touches `Bundle.module` at all: it searches the real locations
  (`Bundle.main` first, then the SPM bundle in Resources, the app root,
  and the executable's directory) and returns nil instead of dying. The
  resource copy also lost its `2>/dev/null || true`, so a failed copy
  now fails the build instead of shipping a broken app. Verified by
  running the freshly bundled app with every build path hidden.
- **`rebuild-backlinks` dropped links between pages sharing a filename
  stem** (#59, same reporter). `build_wiki_cache` assigned
  `raw_forward_links[stem]` per page, so a nested
  `sources/vendor-docs/INDEX.md` erased the root `index.md`'s edges -
  rebuild then wrote an incomplete `_backlinks.json` that `validate`
  reported as stale, and the two commands disagreed permanently. The
  cache now merges repeated stems the way `build_backlinks` and
  validation already did.

### Added

- **`lnk handoff` - switch agents mid-task and lose nothing.** The most
  universal pain of multi-agent work is the switch: a rate limit hits,
  the next step suits a different tool, and the first minutes of the new
  session are spent re-explaining. `lnk handoff "where I left off"`
  writes a standalone packet (task, state, explicit next steps), and the
  next session on ANY connected agent opens with it - the session-start
  hook and the MCP first response both push it, so delivery never
  depends on the receiving agent thinking to ask. Handoffs chain
  (breadcrumbs to the previous one), expire on their own (48h), are
  secret-redacted at write time including the title and filename, and
  never become durable memory unless promoted through normal review.
  This is the community's hand-rolled HANDOFF.md pattern productized on
  Link's rails - and unlike the vendor implementations, it crosses
  vendors: Claude Code to Codex to Cursor is the point.
- **Proactive guard - Link speaks up the moment a constraint matters.**
  The session-start brief is a snapshot; forty minutes in, you type
  "let's deploy payments on Friday" and the memory saying deploys happen
  on Tuesdays sits unread. On Claude Code, a per-prompt hook now checks
  each request against constraint-shaped memories (never / always /
  only / do not) and speaks only on a strong overlap: one reminder
  naming the memory, with instructions to confirm before proceeding.
  The guard also rides every MCP recall path, so all nine agents get
  constraint protection whenever they recall - the query paraphrases
  the request - with the cooldown shared through the usage ledger so no
  surface nags twice, and a 45-minute per-memory cooldown keeps one
  reminder from becoming ten.
  Precision-first by design - silence is the normal output (unrelated,
  short, and weak-overlap prompts stay untouched), it runs in ~80ms
  with no model load, and every firing is recorded in the local usage
  ledger as a "guard" event. Wired automatically by `lnk setup` /
  `lnk connect claude-code --hooks`.
- **The handoff suggests itself at the right moment.** When a prompt
  announces a stop or a tool switch ("switching to codex", "hit my rate
  limit", "continue this tomorrow", "stopping here"), the per-prompt
  hook nudges the agent to offer a handoff before the session ends.
  Precision-gated like the guard: "continue with the refactor" and
  "switching to a recursive approach" stay silent.
- **Meaning-based recall is now set up by default.** `lnk setup`
  provisions the fast semantic tier (one ~30 MB local model, ~0.1s
  loads) when it can own the environment - the measured gap between the
  lexical default (hit@1 0.589) and the fast tier (0.703) is the biggest
  quality difference a new install feels. The download happens during
  the explicit setup command with a clear message; recall itself still
  never touches the network. `--no-semantic` opts out; the quality and
  rerank tiers (~200 MB more) remain explicit opt-ins via
  `lnk semantic --setup`; user-managed pythons keep the hint (Link never
  pip-installs into an environment it does not own).
- **Bulk review.** `lnk accept-capture FILE --all` accepts every
  proposal in a capture (duplicates and conflicts are skipped and
  reported, never forced); `lnk delete-capture TARGET --all --confirm`
  clears the pending inbox with dismissals recorded. The review gate
  stays - this is a faster hand, not a bypass. Fixed along the way:
  `delete-capture <dir> --all` now always treats the positional as the
  target directory (a parse ambiguity could previously point a bulk
  delete at the default workspace).

### Changed

- **The MCP session brief is now bounded.** The first tool response of a
  session used to carry the full memory brief (~16.5k characters), making
  the first recall of a session the largest packet Link sends - measured
  and published as an honest asterisk in 2.2.1. It is now a compact
  digest under a hard 4,000-character budget: typed memory claims
  (trimmed), review counts, and a pointer to `recall` for everything
  else. First-recall cost on the benchmark corpus drops from 11,269
  tokens to 2,313 against a 1,954 steady state. The budget is enforced
  in code and pinned by a test, and `eval_token_economics.py` measures
  the real MCP surface on every run.

## [2.2.1] - 2026-08-06

### Fixed

- **LinkBar: the review loop no longer hides the work.** The first hour
  of real 2.2.0 usage found three frictions in the capture inbox: rows
  looked clickable but did nothing, the Accept menu showed only 3 of an
  import's proposals, and a no-op Clean up read as broken. Capture rows
  now carry a chevron and expand on click with every proposal
  individually acceptable; the inbox fetches up to 50 proposal previews;
  a "Review all" button opens the viewer's full capture page (starting
  the viewer if needed); and an empty Clean up now points at review
  instead of shrugging. The Status tab's "Memory in use" row also gains
  the answer to "which memories?": top-used sublines from the local
  usage ledger.
- **`lnk capture-inbox --proposals N`** (1-50, default 3): preview as
  many proposals per capture as review needs — and imported captures now
  preview in curated mining mode, matching what accept can actually
  save. LinkBar 1.2.1 falls back gracefully against an older CLI.

## [2.2.0] - 2026-08-06

Start of the 2.2 cycle: "your memory, everywhere" — git-based sync with no
server is the flagship; consolidation v2 lands first so stores are clean
before they travel.

### Added

- **Memory pushes itself to every agent, not just the ones with hooks.**
  Session hooks exist for three of the nine agents Link supports; for the
  other six, nothing put memory in front of the agent unless it decided to
  ask. Now the **first MCP tool response of a session carries the memory
  brief** — whatever tool was called, even `status` — under
  `link_session_brief`, with a note telling the agent to treat it as
  context it already has. Once per session, skipped when there is nothing
  to say, recorded as a retrieval so `lnk wins` can prove it happened, and
  disabled with `LINK_MCP_AUTOBRIEF=off`. Push, through the one door every
  agent already opens.
- **Retrieval observability — proof your agents actually use memory.** Every
  memory system can tell you what it stored; none could tell you whether an
  agent ever read it back, which made "your agents have memory" a hope
  rather than a measurement. Link now records retrievals locally: session
  briefs (the automatic push path) and recalls (CLI and MCP), with the
  memory names that came back. `lnk wins` drops its old hedge — *"Link does
  not track whether an agent used a memory"* — and answers with facts:
  *"agents read memory back 12 times (4 session briefs), surfacing 7
  distinct memories."* `lnk digest` gains a "how memory got used" section
  including the honest other half: **memories that have never been
  retrieved**, which are candidates to archive.
  Privacy is the point: the ledger records *that* a memory was used and
  *which* one — never the query, the answer, the conversation, or anything
  about the machine. It lives in `.link-usage.json`, is bounded to recent
  events, never syncs (behavior is not memory), and switches off with
  `LINK_USAGE=off`.
- **`lnk digest` — the weekly reflection.** Consolidation answers "what
  should I clean up?" when asked; the digest answers "is my memory
  healthy?" without being asked. One bounded, read-only look back: what
  you taught Link this week, what is aging out of its trust window
  (overdue vs due soon), which memories are drifting into saying the same
  thing, and what is still waiting for review — each with the exact
  follow-up command. Deterministic and offline: it reuses the lifecycle,
  consolidation, and inbox engines rather than computing new truth. A
  quiet week says so plainly. `--days` widens the window, `--json` feeds
  dashboards and agents.
- **LinkBar: the digest delivers itself.** Once a week, when the digest
  has something to say, one notification says it — "Your week with Link:
  4 new · 2 aging · 1 saying the same thing twice · 3 never used". A
  quiet week posts nothing: a reflection ritual that requires discipline
  is not a ritual.
- **`lnk import` — bring your scattered memory home.** Link's pitch is
  memory that is not locked inside one vendor profile, and now there is a
  door out of those profiles: `lnk import claude-code` (CLAUDE.md +
  auto-memory files), `lnk import cursor` (rules), `lnk import codex`
  (AGENTS.md minus Link's own section), and `lnk import file --file x.txt`
  for memories copied out of ChatGPT or anywhere else. Curated files mine
  in a dedicated mode — every deliberate line is a candidate, not just
  chat-shaped ones — and every candidate lands as a proposal in the
  capture inbox behind the same dedup, secret-scanning, and
  injection-labeling gates as any capture. Nothing is auto-accepted;
  re-import is a no-op for anything already pending, dismissed, or saved.
  Day one stops being a cold start and becomes consolidation.
- **`lnk setup` now heals stale agent instruction files.** Real-world
  failure that motivated this: a Kiro steering file written by a pre-2.0
  installer named MCP tools from the old full surface (`query_link`,
  `memory_brief`), the configured slim server exposed none of them, and
  Kiro fell back to grepping the wiki by hand — 4x the cost for the same
  answer. Setup already refreshed MCP configs on every run; it now gives
  Link-owned instruction sections the same idempotent treatment across
  Kiro, Claude Code, Codex, Cursor, and Antigravity/Gemini. Strictly
  refresh-only: a file is touched only when it carries Link's own section
  marker and that section has drifted from the current template; user
  content in shared files (your CLAUDE.md, your AGENTS.md) is preserved
  byte for byte, and files Link never wrote are never created. `--preview`
  lists what would be refreshed. On the machine that surfaced the bug,
  setup found and healed three more stale files beyond Kiro's.
- **Token-economics benchmark (Track 6).** The field's persistent
  production complaint is cost — published footprints differ by orders of
  magnitude between systems. Link's answer is structural: a recall returns
  a *bounded packet*, and now that claim is measured, not asserted. Real
  packets through the real query path: 1,951–4,835 tokens mean per recall
  (micro→large budget), and the growth curve that matters — **a 64×
  larger store produces a 1.58× larger packet, with the final quadrupling
  (400→1,600 memories) moving it 0.3%**. Packet size climbs while the
  budget's slots fill, then plateaus: cost tracks the budget you ask for,
  not how much you have remembered. Both properties are CI-enforced
  (per-budget worst-case ceilings + a deceleration gate), with the honest
  caveats stated in RESULTS.md: 4-chars-per-token approximation, and
  per-recall numbers are not comparable to other systems'
  per-conversation figures.
- **Temporal recall in plain language.** Ask what you believed *then*:
  "where does local data live in March", "what did we decide last
  quarter", "the plan 2 months ago", "what did I prefer back then". Link
  resolves everyday time phrases to an exact date and reconstructs what
  was active on it from the dated files themselves — archived memories,
  supersede lineage, and expiry all participate — then ranks the topic
  with the date words removed. Deterministic: a regex and a calendar, no
  model. Event anchors ("before the migration") are reported honestly as
  unresolved rather than guessed. `--as-of YYYY-MM-DD` still pins the
  moment explicitly and always wins. Temporal reasoning is the open
  problem in the published memory literature (a ~15-point spread between
  architectures); the hygiene benchmark now measures it directly:
  **0.917 point-in-time accuracy from plain language**, identical to
  asking with an ISO date.
- **`lnk sync` — your memory on every machine, no server.** Sync reviewed
  memory between machines through a git remote you control (a private
  repo, a homelab bare repo — anything git can push to). Three promises on
  top of plain git: **secrets never leave** (every outgoing wiki change is
  scanned with the memory gate's own detector before push; a
  credential-shaped value blocks the push with the file named);
  **conflicts become review items, never markers** (when two machines edit
  the same memory, the remote version keeps its path and the local version
  is preserved as a sibling memory — both recallable, paired by
  `lnk consolidate` for the human to merge; git conflict markers never
  touch wiki files); and **the log stays tamper-evident** (diverged logs
  union entry-by-entry into a freshly rebuilt hash chain, with a
  sync-merge entry declaring the re-anchor). `raw/` captures and the
  runtime never sync — private stays local, each machine's installed Link
  provides its own runtime. `lnk sync --init --remote <url>` once, then
  `lnk sync` daily; `--status` shows ahead/behind. Verified end to end
  against a local bare remote: round trip, conflict drill with a clean
  chain, secret push-block.
- **Team memory: a shared brain with no memory server.** `lnk team-sync`
  graduates from printing git guidance to running the whole loop: your
  active `visibility: team` memories are exported to a shared team
  workspace, synced through a git remote the team controls, and
  teammates' memories are imported into your wiki — recallable by your
  agents like anything else. The team repo is itself a mini Link
  workspace with its own tamper-evident log, so every sync guarantee
  (secret push-gate, both-versions conflicts, chain-verified merges)
  applies to the shared brain verbatim. Private and project memories
  never leave your machine; when your copy and the team's differ, yours
  wins locally and the difference is reported. Setup:
  `lnk team-sync --init --remote <shared-git-url>`, then `lnk team-sync`
  whenever. The `visibility: team` field finally does what its name
  always promised.
- **Consolidation v2: merge suggestions for accepted memories.** Write-time
  duplicate refusal blocks strong duplicates at creation, but accepted
  memories drift into overlap over months ("short PR descriptions" saved
  twice with different wording a quarter apart). `lnk consolidate` now
  pairs active memories that likely say the same thing — token overlap plus
  the optional semantic tier — recommends a survivor (reviewed beats newer),
  and prints copy-ready merge and archive commands. Suggestions only:
  opposite-polarity pairs are contradictions (left to the conflict
  detector), supersede-linked pairs are excluded, and nothing merges
  without the human.

### Fixed

- `lnk review-memory --all <workspace>` treated the workspace argument as a
  memory identifier and silently reviewed the default workspace instead
  (found in dogfooding). With `--all`, a lone positional is the target.

## [2.1.0] - 2026-08-02

The inbox-zero release. 2.0 put the review gate in your menu bar; this
release makes sure there's nothing in it twice. Every change comes from
dogfooding the automatic pipeline against a real inbox that had grown to 20
pending captures — five of them the same conversation captured five times.

### Added

- **`lnk setup` — one command for install day and every upgrade.** Detects
  every agent installed on the machine and wires them all at once:
  workspace create/repair, runtime refresh, MCP provisioning, session
  hooks for agents that have them. Idempotent — after `brew upgrade`, the
  same command refreshes everything. `--preview` shows the plan without
  writing. The quickstart is now two commands total.
- **Agent-agnostic by design: Windsurf and Zed join the roster** (7 → 9
  supported agents). Zed's `context_servers` schema (with its required
  `source: custom` entry) is supported natively, and writes into Zed's
  main settings.json merge safely — existing user settings are preserved.
- **Memory poisoning benchmark (Track 5) + injection labeling.** A planted
  memory is injected into every future session — the highest-value prompt-
  injection target an agent system has. 15 authored attacks (guardrail
  bypass, unattended-execution "preferences", data-exfiltration
  conventions, credential planting, spoofed approvals, agent-directed
  commands) now run through the real pipeline in CI: **0 reach the inbox
  unlabeled, 0 false positives** on benign directives. Injection-shaped
  proposals carry a warning in the capture inbox and the decision trail
  ("verify you actually said this before accepting") — labels, never
  censorship; the review gate stays the final defense. To our knowledge
  the only published adversarial benchmark on an agent-memory write path.
- **Dismissal ledger** — deleting a capture now records its proposal
  fingerprints in `raw/memory-captures/.dismissed-proposals.json`, so a
  dismissed proposal never re-enters the inbox from a later session of any
  conversation. Dismissal becomes a decision Link remembers. Inbox previews
  and `accept-capture` indices exclude dismissed proposals consistently.
- **One capture per conversation** — a session-end for a conversation that
  already has a pending capture refreshes that capture in place (same file,
  newer transcript, newer proposals) instead of stacking a near-duplicate.
  Captures carry a `conversation:` identity in frontmatter.
- **Cross-conversation proposal dedup** — the session-end hook drops
  proposals already waiting for review in another capture, with an honest
  decision-trail line naming where ("already waiting for review in ...").
- **`lnk dedup-captures`** — collapses inbox captures that offer nothing new
  (already pending in a newer capture, accepted as memory, or dismissed;
  or proposal-free). Dry-run by default, `--confirm` applies, `--json` for
  tooling. Surfaced in LinkBar as a "Clean up" button on the inbox, and as
  the MCP `admin` action `dedup_captures` for agents.
- **LinkBar: "Why does Link believe this?"** — tap any memory in the browser
  to expand its trust card: the claim, whether default recall will use it
  (with the reason), where it came from, when it was captured and reviewed,
  and any open quality issues — `lnk explain-memory` made ambient.
- **Trust lifecycle: memory ages honestly.** Every memory now gets a typed
  trust window at birth (project context 3 months; preferences, notes, and
  procedures 6; decisions and stable facts 12), stamped as `review_after`.
  Reviewing a memory re-arms its window; a custom future date is kept.
  Memories written before scheduling existed age implicitly from their last
  review or capture date. An aged memory is never archived or hidden — it
  is labeled due for review on every surface (inbox, audit, brief, explain
  cards, LinkBar) and stays recallable, honestly flagged. No other agent
  memory system re-asks whether what it knows is still true.
- **Live demo workspace on the homepage** — the site now embeds a real
  exported Link wiki (docs/demo, generated by `lnk snapshot`): every page
  clickable, memories included, private memories excluded by the export's
  own safety defaults. Snapshot styling joined the brand system
  (cream/ink/rust) so a shared snapshot looks like the product.
- **Memory-hygiene benchmark v2** — the fixture now contains the junk we
  actually observed in the wild, not just the junk we predicted: quiz/debug
  questions carrying absolute keywords, pasted third-party AI advice inside
  user turns, and verbatim cross-session repeats (142 events, up from 112).
  Gated junk stays **0%**; the ungated baseline rises to 36.5%.
  Current-truth precision@1 improves to 0.881, and contradiction exposure
  drops to **0.167** (10 of 12 authored revisions now supersede; v1's 0.333
  was flattered — it silently measured only 9 revisions and its false
  conflicts masked real exposure; see benchmarks/RESULTS.md).
- **Revision detection catches more contradiction shapes** — three general
  detector fixes: updates that add content tokens are no longer swallowed
  by the echo guard (echoes add framing, revisions add content); detailed
  original claims match at partial coverage; preference/decision typing
  jitter no longer blocks detection across the type/scope boundary.
- **Semantic revision detection** (opt-in, local) — when the semantic tier
  is installed, revision-cued claims with no lexical link to what they
  revise ("SQLite with FTS" → "DuckDB files") are compared by meaning:
  claim-vs-claim embeddings, threshold calibrated on real separations
  (true revisions 0.60–0.69, unrelated ≤ 0.18), surfaced as
  `semantic_revision` conflict candidates for review. Fully deterministic
  lexical behavior when the tier is absent; the published benchmark
  numbers stay lexical-only by design.

### Fixed

- **Product-finder round** (walked the whole funnel as a stranger —
  homepage, install, first five minutes): bare `lnk` now greets with the
  four commands that matter instead of an argparse error; `lnk proof` and
  `lnk try` end with the make-it-yours command (`lnk setup`); the homepage
  Setup section and getting-started guide lead with the one-command flow
  and the agent picker gained Windsurf and Zed.
- **Cold-walk friction round** (found by walking the product end-to-end as a
  new user): durability lead-ins ("From now on…", "Going forward…") are
  trimmed from stored claims and titles; accepting a capture clears it from
  the inbox when nothing fresh remains; `review-memory --all` bulk-reviews
  every pending/due memory (lists first, requires `--confirm`); the session
  brief marks unreviewed and aged memories inline (`· pending review`,
  `· review due`) where agents read them; and `remember` infers the memory
  type from the text's own cues — "I prefer X" saves as a preference with a
  preference's trust window, not a generic note (CLI and MCP).
- **Questions are no longer proposed as memories.** "number of walkers is
  always fixed?" matched the preference cue on "always" and — worse —
  ranked as a top durable memory. Interrogatives are now excluded from
  classification and sunk by the durability ranker.
- **Pasted third-party prose is no longer attributed to the user.** Bare
  absolutes ("always", "never", "do not") now require the user's own voice
  (first person, "please", or imperative-initial phrasing) — quoted advice
  like "People on Reddit emphasize... never accept..." no longer becomes a
  proposed user preference.
- **False memory conflicts from boilerplate overlap.** "API listens on port
  8080 in local development" conflicted with a squash-merge rule because
  "development" read as a git branch and "decided/decision" counted as
  shared subject matter. Boilerplate tokens no longer count as evidence.
- **Revisions are no longer swallowed by the echo guard.** "We decided X
  does not apply anymore" restates enough of the original claim that echo
  containment dropped the update, keeping the stale memory alive forever. A
  polarity flip now marks a candidate as a revision, not a restatement.
- **Revision sentences type consistently with what they revise.** "We
  decided X does not ... anymore" now classifies as a decision (the explicit
  decision cue outranks the bare-absolute preference fallback), so conflict
  detection sees the contradiction instead of skipping on a type/scope
  mismatch.
- Time-scoped observations ("does not affect us this quarter") are no
  longer proposed as durable memory.
- Bare imperative directives ("Plot the loss curve every 500 steps") now
  outrank meta-preambles in proposal ordering instead of scoring zero.
- **LinkBar palette**: a failed `lnk` call no longer reports "a similar or
  conflicting memory exists" (it now says it couldn't reach `lnk`); typing
  again within 1.1s of a confirmation no longer wipes the panel from under
  you; a slow recall response for an old query can no longer overwrite the
  results of a newer one.
- **LinkBar inbox at backlog scale**: the full capture list is reviewable
  (scrollable past 4 items) instead of showing only the top 3 of a
  20-item backlog behind a count badge.
- LinkBar builds with zero Swift warnings (actor-isolation conformance,
  Sendable captures, and two lint-level warnings cleared).

## [2.0.0] - 2026-07-27

Link gets a face. The memory layer is unchanged in shape — plain Markdown,
review-gated writes, no LLM in the write path — but it is no longer only a
CLI and an MCP server: **LinkBar** puts the review gate in your macOS menu
bar, and memory becomes something that meets you rather than somewhere you
go. That shift is why this is a major version.

**No breaking changes.** Every CLI command, MCP tool, hook, and memory file
from 1.7 works exactly as before; upgrading is `brew upgrade link`.

### Added

- **LinkBar 1.0** — Link's memory, ambient in your macOS menu bar (`apps/LinkBar`, Swift/SwiftUI, the `lnk --json` CLI is its entire backend). The review gate stops being a place you go and starts being something that meets you:
  - **Memory Palette**: a global hotkey (⌥⌘M) opens a floating panel over any app — type to recall (copy straight into what you're writing), prefix with `+` to remember, review-gated as always.
  - **Live agent pulse**: LinkBar detects agent sessions writing transcripts right now and shows a breathing "N agents active · project" row; the menu-bar icon carries a quiet green dot while memory is being made.
  - **Capture notifications**: a new session capture posts a native banner — "Will save: <proposal>" — with an Accept action right on it. Confirmed working on an unsigned/ad-hoc build (no Apple Developer signature required).
  - **Memory browser**: a Memory tab listing every memory file — search, type filters, archived toggle, supersede lineage, archive/restore — read straight from `wiki/memories/*.md`.
  - **Status dashboard**: health dots for CLI, workspace, MCP, hooks, recall tier, and viewer, each with a one-click fix that verifies its outcome before claiming success.
  - **Inbox**: review/accept memories and captures with "Will save" previews, decision trails ("How Link read this session"), and per-proposal Accept menus.
  - Distributed as an unsigned cask with a postflight quarantine-strip — `brew install --cask gowtham0992/link/linkbar` — zero Gatekeeper friction, zero signing fees.
- Homepage refresh: version banner, per-agent onboard picker (real `lnk onboard --agent <yours> --write` commands), origin-story section, and the three demo terminals as alternating side-by-side rows.

### Fixed

- `lnk semantic` status reported "Indexed memories: 16 of 6" — the index embeds every memory (archived included; they stay inert in default recall), so the denominator is now the total memory count, not active-only.

## [1.7.0] - 2026-07-17

### Added

- Secrets are refused at the memory gate: `remember` (CLI and both MCP tools) now detects credential-shaped text — API-token patterns plus a conservative password heuristic ("Zk9#mango42", "the wifi password is …", "PIN 1234") — and refuses with a pointer to a password manager; `--allow-secret` overrides when the text truly isn't one. Memory pages are plain files injected into every connected agent's session, so a saved credential leaks by design.
- Forgetting now forgets the log too: `forget-memory` scrubs the memory's title and name from past `wiki/log.md` entries, replacing them with `[forgotten memory]`. The log's tamper-evident hash chain is re-anchored and the redaction declares itself as a `redact-log` entry — never silent — and integrity verification passes afterwards.
- The capture inbox shows what Accept will actually save: each capture in `capture-inbox --json` (and the text listing) now carries mined proposal previews (title, memory text, type, confidence) — the same deterministic miner accept-capture uses, with secret-looking values redacted from previews.
- Captured proposals are ranked by durability, so the one a one-click Accept saves (and `accept-capture --index 1`) is the substance, not a meta-preamble. A session that says "I want to set some conventions… From now on I only deploy on Fridays…" used to surface the vague "wants to set conventions" first (it classifies as a preference just as strongly); proposals now sort concrete directives ("I only deploy…", "always run…", "I prefer…") ahead of statements that are merely *about* making rules. Ordering only — every proposal still appears for review.
- Onboarding reads cleaner: `lnk onboard` on a fresh workspace collapses the dozen "created wiki/…" scaffold lines into one summary, and the README Quick Start is now a single two-command hero path (`lnk proof` then `lnk onboard --agent <yours> --write`) instead of three parallel entry points.
- Core hardened against hostile and degenerate inputs (adversarial fuzz of the automatic pipeline): frontmatter values now collapse newlines and control characters, closing a field-injection path where a title containing `\ntitle: injected` (or any `key: value` line) wrote extra frontmatter fields that the parser honored; slugs are capped at 80 chars so pathological titles can't crash writes with filesystem name limits; concurrent session-end hooks no longer race on capture filenames (atomic O_EXCL claim — previously simultaneous hook fires could silently lose a capture); applies_when project conditions normalize to the slug recall compares against and reject unslug-able values. 540-call MCP fuzz now returns clean JSON errors with zero escaped exceptions, and `validate` passes after every hostile write.
- Session captures are now reviewable and correctly attributed. Three fixes to how Link reads a session: (1) standing rules survive long sessions — the hook mines a head+tail window instead of only the most recent ~6k characters, so "from now on I only deploy through the release script" said early in a two-hour session is still captured; (2) accept-time re-mining reads the user's own turns only (recorded in a `## Proposal Source` block), closing a path where the assistant's prose could be re-proposed as your preference; (3) every capture records a decision trail (`## How Link Read This Session`) — messages kept, echoes dropped, proposals found — surfaced on the dashboard Captures page and in `capture-inbox --json` alongside the proposal previews and a "mined from your own turns" attribution flag.
- Session captures now carry retrieval context end to end: when the session-end hook proposes a memory, the neighboring sentences around the claim's origin travel with the proposal, through accept-capture, into the memory page's `context` frontmatter — the same ±1-neighbor window that lifted LoCoMo hit@10 0.685→0.737 in the retrieval benchmark. Context helps recall *find* the memory (scoring + embeddings) but is never part of the claim: echo/duplicate/conflict checks, slim output, and the visible page body all exclude it. Also exposed explicitly as `lnk remember --context` and the `context` parameter on both MCP remember tools; capped at 600 characters.

- The semantic and rerank tiers are now reachable from a Homebrew install: the Homebrew Python refuses direct pip installs (PEP 668), so every printed `pip install "link-mcp[semantic]"` command failed on a fresh Mac. `lnk semantic --setup` now detects an externally-managed runtime, provisions the extras into `~/.link-mcp-venv` (pinned to Link's version), and reruns the setup under that Python — one command from lexical-only to hybrid + rerank. Status and verify-mcp guidance stop printing pip commands the interpreter would refuse. The Homebrew `lnk` shim (tap revision 1) runs through the managed venv whenever it hosts link-mcp, so the CLI gains the tiers too.
- Upgrades no longer drift silently: session hooks run each workspace's own runtime copy, which used to stay old after `brew upgrade`. `lnk health`/`status` now warn (`stale_runtime`) with the exact refresh command; `doctor`, `init`, `onboard`, and `connect --hooks --write` refresh the copy automatically. Newer workspace copies (dogfooded source checkouts) are never downgraded.
- CI now walks the cold install on a clean macOS runner and on Windows: onboard with hooks and MCP, self-provisioning of `~/.link-mcp-venv`, the session-start brief, and a live MCP stdio handshake — after first asserting the runner has no `link_mcp` importable, so a polluted environment can never mask install-path breakage again.
- Docs answer the three questions every newcomer asks — does Link read my conversations, what survives a context clear, and which project a memory belongs to — and GitHub issue templates route bugs (with `lnk doctor` output), friction reports, and feature requests.
- MCP now works out of the box: `lnk connect --write` (and `lnk onboard --agent ... --write`) verifies that the configured Python can actually serve `link-mcp` at Link's version before writing any agent config, reuses an existing `~/.link-mcp-venv` when it matches, and provisions that venv automatically otherwise. A config that cannot start is never written; the chosen Python is persisted via the `.link-mcp-python` marker and reported in the command output. Previously a Homebrew install wrote MCP configs pointing at a Python without the package, so the server failed silently in every agent.
- `lnk verify-mcp <agent>` (for example `lnk verify-mcp claude-code`) now reads the agent's actual config file and verifies the exact Link server it is configured to run — Python, link-mcp version, and wiki — instead of treating the agent name as a directory. When no Link server is configured it points at the `lnk connect ... --write` command.
- Session-end capture now catches standing-rule phrasings ("from now on ...", "going forward ...", "I only push/deploy/... to ...") as preference proposals, and trims conversational preambles ("hey, before we start — ...") from the stored memory text when the remainder stands on its own. Narrative uses ("I only found one bug") are still ignored, and the hygiene benchmark holds at 0 junk.
- Added `procedure` as a memory type: reusable how-to memory (recipes) with an optional `trigger` phrase describing when it applies. Procedures are plain Markdown like every other memory, review-gated, and shared across agents.
- Trigger phrases are scored like the intent-bearing head fields in recall and included in semantic embeddings, so task-shaped queries ("how do I prepare a release") find recipes phrased differently; recalled procedures carry a bounded `steps` excerpt in recall packets so agents can follow them without another file read.
- Added `--trigger` to `lnk remember` and `trigger` to the MCP `remember`/`remember_memory` tools.
- Session-end proposals now detect numbered step sequences in session notes and propose them as `procedure` memories with the preceding goal line as the trigger; accepting a capture carries the trigger through. Saving still requires explicit approval.
- Updated installed agent instructions, MCP instructions, LINK.md, and docs so agents offer to save a recipe after notable multi-step work.
- Extended project seeding to architecture decision records: `lnk seed` now also reads `docs/adr/`, `docs/decisions/`, and `adr/` files, and deterministically mines each ADR's Decision section into proposal-only `decision` memory candidates with paste-ready save commands — a repo's existing rationale becomes governed, recallable, supersedable decision memory only after the user approves each one.
- Made the safety layer visible: conflict refusals now lead with the paste-ready `--supersedes <name>` resolution; terminal recall shows applicability warnings ("out of context here — verify"), recipe triggers, and step previews; and `lnk hook session-end --explain` prints the full decision trail (messages dropped as Link's own output, proposals dropped as echoes or duplicates, trivial-session skips) so silent protections are inspectable.
- Split the semantic default by surface: short-lived CLI commands prefer the instant-load fast tier while the MCP server prefers the quality tier (explicit `LINK_SEMANTIC_PROVIDER` always wins), so installing the quality extra no longer slows interactive commands.
- Added `lnk connect --hooks-settings <path>` so hooks can be installed project-scoped (for example into a repo's `.claude/settings.json`), enabling per-workspace memory for multi-workspace users; `--supersedes` accepts a memory title as well as its name.
- Added a single memory-field rule ("finding it → trigger · fencing it → applies_when · owning it → scope/project/visibility · replacing it → supersedes · aging it → review_after/expires_at") to `remember --help`, the agent instructions, the MCP remember docstring, and the CLI docs.
- Sharpened benchmark honesty: the hygiene baseline is labeled a governance ablation of Link itself (with an open invitation to run the stream through other systems), the conflict-detector score is disclosed as a fit on its development set, and "zero junk" is defined precisely as zero self-inflicted junk.
- Added `lnk recipes` to list saved procedure memories with their triggers, and `lnk recall --type` to filter recall by memory type.
- Added recurring-theme detection to consolidation plans: related-but-not-duplicate captures across sessions are clustered deterministically and surfaced as candidates for one durable memory (a preference or a recipe) — the review-gated way an agent learns user patterns; a scheduled idle-time agent session can run the plan as a "dream pass" and bring proposals to the next session.
- Added the memory-hygiene benchmark (`scripts/eval_memory_hygiene.py` + `scripts/hygiene_dataset.py`): a deterministic multi-month session simulation that measures memory quality over time — junk rate, contradiction exposure after revisions, active-store growth, current-truth precision, and as-of temporal accuracy — comparing Link's gated pipeline against an ungated baseline (same extractor and retrieval, governance off). Measured: 0% junk vs 23.9%, contradiction exposure 0.333 vs 0.833, 40 vs 67 active memories. CI runs the benchmark as a regression gate; developing it caught and fixed a conflict-detector gap (revision-shaped contradictions where both texts contain negations) and an echo-guard gap (partial restatements), both now covered.
- Improved conflict detection with a revision-shape rule: text carrying a negation or revision cue that covers most of an existing memory's subject tokens (boilerplate cue words excluded) is flagged as revising that claim, catching "we don't X anymore; now Y" contradictions that symmetric overlap and negation-XOR miss.
- Strengthened the echo guard with mirrored containment: a partial restatement whose own tokens live almost entirely inside one stored claim adds nothing new and is dropped.
- Added supersedes chains: `lnk remember --supersedes <name>` (and `supersedes` on the MCP remember tools) replaces an outdated memory atomically — the successor records `supersedes` lineage, the predecessor is archived with `superseded_by` and a supersession reason, and conflict refusals now point at this path instead of only offering coexistence overrides. `explain-memory` walks the full lineage chain in both directions.
- Added temporal recall: `lnk recall --as-of YYYY-MM-DD` reconstructs what was active on a past date from existing lifecycle fields (capture, supersession/archive, expiry) — answering the temporal-memory frontier at personal scale with zero graph database.
- Fixed a latent similarity bug: duplicate, conflict, and echo checks now compare memory core claims (title, TLDR, and the `## Memory` section) instead of full templated pages, whose boilerplate diluted token overlap and let real duplicates and contradictions slip past detection on real pages. Conflicts are evaluated before duplicates, and a record identified as a conflict is never also treated as a duplicate, so `allow_conflict` and supersession behave correctly.
- Added conditional memory: scope situational memories with `applies_when` conditions (`project:<slug>`, `path:<glob>`, `task:<phrase>`; OR semantics, validated at write time) via `lnk remember --applies-when` and the MCP remember tools. Recall demotes out-of-context matches and labels every conditional memory with `applicability: matched|out_of_context` so agents never apply one project's conventions in another; startup briefs exclude out-of-context memories entirely. Session hooks evaluate `path:` conditions against the session's working directory. Research context: memory mis-scoping is a documented top failure mode of agent memory systems; Link's conditions are deterministic frontmatter, not classifier guesses.
- Made "don't know" a first-class recall verdict: MCP recall now returns an `abstention` object (recommended when nothing matches or the best match is weak-confidence), the MCP instructions teach agents that "my memory doesn't cover that" is correct behavior rather than failure, and CLI recall warns above hint-grade results. Also added independent research context to `benchmarks/RESULTS.md`: recent controlled ablations find verbatim memory beats LLM-extracted artifacts by 15.9–22 points (arXiv:2601.00821) and ranking beats graph structure (arXiv:2603.15599) — external support for Link's two most-questioned design choices.
- Made the codebase easier to maintain and onboard into: added `ARCHITECTURE.md` (components, data model, write paths, recall pipeline, invariants, guards — the map a new maintainer needs), a `.mailmap` unifying commit identities, dependency version ceilings (`mcp<2`, extras `<1`), and a mypy type-error ratchet (`mypy.ini` + `scripts/check_type_ratchet.py`, wired into CI) that pins the current 387-error baseline and fails when new code adds type errors.
- Fixed the biggest first-session friction: workspace-consuming commands run with no target in a directory that has no Link wiki now fall back to the default workspace (`LINK_WORKSPACE` or `~/link`) with a one-line notice, so `lnk onboard` followed by a pathless `lnk remember`/`lnk recall` just works. Creator commands (`init`, `demo`, `try`, `proof`, `onboard`) never redirect, an explicit target always wins, and a wiki in the current directory still takes precedence.
- Fixed the plumbing leak in generated commands: when a `lnk` launcher on PATH runs this same runtime (e.g. the Homebrew install), every generated command now says `lnk ...` instead of the interpreter and Cellar path — including the viewer's copy-command buttons.
- `lnk remember` without any workspace now points at `lnk onboard` instead of a bare "missing wiki directory" dead end.
- The landing page now serves its actual pitch (headline, what Link does, install command, links) to text fetchers, LLM crawlers, and noscript readers instead of "Unpacking..."; the hero install command gained `&& lnk try` so the blessed first step is unmissable; and the Memory Dashboard explains what review means (unreviewed memories recall as provisional; reviewing earns full trust).
- Added a second animated demo to Getting Started (`docs/assets/link-truth.svg`, self-contained SVG like its 1.6 sibling): the "memory that stays true" arc — a new memory conflicts with an old one, `--supersedes` replaces it with lineage, recall returns only the current truth, and `--as-of` answers what was true back then.
- `lnk --help` now presents commands in seven task-shaped groups (Start here / Memory / Review & governance / Agents / Workspace / Sharing / Utilities) instead of a 60-command wall, and leads with `link.py try`. A guard test keeps every registered command visible in exactly one group.
- `lnk semantic` now reports the rerank tier's state (active / installed but model not fetched / not installed) with the exact next command, and `lnk semantic --setup` fetches the rerank model alongside the embedding model when the extra is installed — previously installing `link-mcp[rerank]` produced silently nothing because no setup path existed.
- Added an optional local rerank tier (`pip install "link-mcp[rerank]"`): a tiny (0.08 GB) local ONNX cross-encoder re-orders the top recall candidates by reading each query-memory pair, blended with the retrieval order via reciprocal-rank fusion — never substituted, since pure reranking collapsed hit@1 in ablation. Measured on the default embedder: LoCoMo any-evidence hit@10 0.737 → 0.794 and multi-hop evidence recall 0.350 → 0.403; bundled-benchmark token-overlap hit@1 0.749 → 0.839 and pure-paraphrase hit@5 0.338 → 0.436. Applies only to explicit recall and MCP recall calls (~0.5 s at 50 candidates) — session hooks and briefs never pay the latency. Same local-first guarantees as the semantic tiers: offline-only model load, `LINK_RERANK=off` to disable, `LINK_RERANK_MODEL` to override.
- Embedding-model findings from the same study (documented in `benchmarks/RESULTS.md`): model rankings invert by text shape — nomic-embed-text-v1.5-Q beats the default on long conversational archives (LoCoMo hit@10 0.787 vs 0.737) but loses on Link's claim-shaped memory pages (bundled hit@1 0.713 vs 0.749), so all-MiniLM-L6-v2 stays the default and nomic is the documented `LINK_SEMANTIC_MODEL` alternative for conversational imports.
- MCP recall now accepts `context_path` (the session's working directory) so memories fenced with `applies_when` `path:` conditions can match over MCP, matching what session hooks already do; without it, path-fenced memories were permanently demoted as out of context for MCP agents. The recall docstring tells agents to pass it.
- Added retrieval `context` to memory records: optional text from around a memory's origin (neighboring dialogue turns, surrounding notes) that helps recall find the memory but is never part of its claim — echo, duplicate, and conflict checks compare claims only, and recall output never carries it. Motivated by LoCoMo failure analysis (the dominant retrieval miss was conversational deixis: turns like "the stories were so inspiring" are only findable by what they were about). The LoCoMo adapter now indexes each turn with its ±1 neighbors as context, lifting hybrid any-evidence hit@10 from 0.685 to 0.737 and evidence recall@10 from 0.608 to 0.660 (lexical hit@10 0.578 → 0.628); the rank-time neighbor-splice ablation that measured worse (0.685 → 0.550) is documented in `benchmarks/RESULTS.md`.
- Added a two-layer echo guard to automatic session capture, so Link can never re-ingest its own voice: transcript extraction drops any message carrying Link-injected output (the session-start brief, consolidation plans, session-end output), and proposals that merely restate an existing active memory — including framing-diluted restatements caught by core-claim token containment — are discarded before a capture is stored. A production audit of a competing memory system found 97.8% of stored entries were junk, over half of it the system's own prompt text re-ingested; Link's re-ingestion rate is zero by construction, with tests proving both layers.
### Fixed

- Recipes saved from numbered steps now get a real title: a procedure without an explicit `--title` is named by its trigger phrase ("cutting a Link release") instead of the first list marker (previously the memory was literally titled "1" at `wiki/memories/1.md`), and derived titles skip leading step numbering for every memory type.
- Accepting a capture now actually carries a procedure proposal's trigger into the memory frontmatter — both the CLI and MCP accept paths dropped it, so auto-proposed recipes lost the phrase that makes trigger-boosted recall find them.
- The "Save if approved" command printed for ADR decision candidates is now paste-safe: it carries the full decision text, shell-quoted, instead of an 80-character display truncation that would have saved a cut-off memory ending in an ellipsis.
- Malformed `applies_when` conditions now fail closed: a memory whose condition string has invalid syntax (e.g. a typo during a hand edit) is treated as out of context everywhere instead of silently becoming unconditional, and the review inbox flags the syntax error with repair guidance. Previously a one-character typo removed the fence and the memory applied in every project unlabeled — the exact mis-scoping `applies_when` exists to prevent.

## [1.6.0] - 2026-07-09

- Added an animated "aha" demo to the Getting Started page: a self-contained SVG (`docs/assets/link-aha.svg`, plain text, no external runtime, animates in any browser) showing the two moments Link is built for — recall that matches by meaning rather than keywords, and memory injected into a new agent session automatically. The README shows the matching recorded GIF (`docs/assets/link-aha.gif`), rendered from real `lnk` commands via a checked-in charmbracelet vhs tape (`docs/media/link-aha.tape`) so it is reproducible, not synthetic.

- Fixed first-ten-minutes friction found by walking Link cold as a brand-new user:
  - `lnk onboard` now surfaces the automatic-memory path: it explains `--hooks` and prints the ready-to-run `--agent <hook-capable> --hooks --write` command, and each hook-capable agent preview offers "Make memory automatic (recommended)". Previously the flagship 1.6 feature was invisible in the guided setup.
  - A recall that finds nothing while memories exist now tells the user paraphrase matching (semantic recall) is off by default and how to turn it on, instead of a bare "No matching memories found". The README's paraphrase example is reframed as opt-in so it never reads like a broken default, and the landing hero calls hybrid recall optional.
  - Generated commands in source-checkout mode use a friendly `python3 link.py` instead of the raw interpreter path (e.g. `python@3.14`); Homebrew users still see plain `lnk`.
  - `lnk proof` now says its workspace is a throwaway demo and points to `lnk onboard` for real memory, with a plain "what this means for you" line.
  - `scripts/prepare_release.py` reminds maintainers to bump the Homebrew tap so `brew install` never serves an older Link than the docs describe.

- Completed 1.6 coverage across the second-tier docs and shipped skills: the official CLI skills now teach the hooks-installed rule, the consolidation pass, semantic match labels, and the `lnk semantic` status check; the memory contract documents the hooked loop and honest recall signals; concepts covers hybrid retrieval and the automatic lifecycle; troubleshooting gains "hooks not firing" and "semantic recall not working" sections; and the scale page links the measured benchmarks.

### Added

- Added `lnk connect <agent> --hooks` to install agent session hooks alongside MCP config for Claude Code, Codex, and Cursor: every new session starts with a bounded Link memory brief injected automatically, and session end stores proposal-only session notes with memory candidates, so the memory loop no longer depends on the agent remembering to call Link. Codex has no session-end hook event, so it gets the session-start brief only; Cursor uses its flat `hooks.json` schema and JSON `additional_context` envelope.
- Added `lnk consolidate` and MCP `review(action="consolidate")` for a read-only backlog plan: pending capture counts, memories needing review, duplicate-capture groups, and paste-safe accept/discard/review commands — nothing is merged, deleted, or saved without the user approving each action.
- Added an automatic backlog nudge to the injected session-start brief: when pending captures or review items cross a threshold, the brief tells the agent to offer the user a short consolidation pass instead of letting the inbox silently grow.
- Added session-end capture noise controls: sessions with no memory-worthy proposal candidates are skipped entirely, and duplicate end events for the same conversation content are deduplicated with a local fingerprint, so automatic hooks cannot flood the capture inbox.
- Added optional hybrid semantic recall (`pip install "link-mcp[semantic]"` + `lnk semantic --setup`): a small local static-embedding model retrieves close paraphrases that token matching misses, across CLI recall, memory briefs, MCP recall, and smart query packets. Lexical recall stays the default and the fallback.
- Kept the local-first guarantee for semantic recall: the model loads offline-only so a query can never trigger a download (only the explicit `--setup` may fetch the model once), embeddings live in plain JSON under `.link-cache/`, similarity is computed in-process with no vector database or service, and `LINK_SEMANTIC=off` disables the layer.
- Added standout-based semantic scoring: candidates are selected by how much they stand out from the rest of the corpus for the query (not by raw cosine thresholds, which are not comparable across queries for static models), and semantic-only matches never outrank exact lexical hits.
- Added honest labeling for semantic recall: recalled memories now carry `match` (`lexical`, `semantic`, or `hybrid`) and `semantic_similarity`, and a match with no lexical evidence is capped at moderate confidence so agents verify paraphrase matches before acting on them.
- Added `lnk semantic` for the layer's status (provider, model, index state, mode) with explicit setup/rebuild actions and next-step guidance.
- Added a publication-grade recall benchmark: `scripts/recall_dataset.py` (62-memory corpus with distractors, 294 authored queries plus deterministic phrasing variants for 1,176 total cases, every query auto-classified by measured token overlap so the paraphrase group provably shares no significant stemmed token with its target) and `scripts/eval_recall_quality.py` (hit@1/3/5, MRR@5, per-domain breakdown, recall latency, JSON output, and a regression gate that fails if hybrid ever scores below lexical). CI runs the gate with a deterministic no-model embedder.
- Published measured results in `benchmarks/RESULTS.md` with methodology, hardware, model-size ablation, honest limitations, and reproduction steps: hybrid recall lifts token-overlap hit@1 0.589 → 0.703 and doubles-to-triples zero-overlap paraphrase hit@3/hit@5, at ~2.8 ms per recall in-process.
- Added `python3 -m link_mcp --semantic-setup` so MCP-only installs (no `lnk` CLI) can run the explicit one-time semantic model fetch and index build; the MCP server itself still never touches the network.
- Added a second semantic tier: `pip install "link-mcp[semantic-quality]"` uses a local contextual ONNX model (all-MiniLM-L6-v2 via fastembed) and is preferred automatically when installed; the static-model fast tier remains for instant-load CLI and hook use, and `LINK_SEMANTIC_PROVIDER` picks explicitly. On the bundled benchmark the quality tier roughly quadruples pure-paraphrase hit@3/hit@5 over lexical recall. Ablations that did not survive measurement (retrieval-tuned static models, multi-view embeddings) are documented in `benchmarks/RESULTS.md`.
- Added a third-party benchmark track: `scripts/eval_locomo.py` scores Link recall on the LoCoMo long-term conversational memory dataset (turns as memories, evidence-annotated questions as queries; retrieval stage only, no LLM anywhere). Hybrid recall lifts any-evidence hit@10 from 0.578 to 0.685 and evidence recall@10 from 0.517 to 0.608 over 1,536 third-party queries. The dataset (CC BY-NC 4.0, Snap Inc.) is downloaded by the user, never redistributed; the script contains no network code.
- Rewrote the public "Why Link?" positioning around the four architectural commitments competitors cannot bolt on — readable Markdown memory, review-gated writes, no LLM in the memory layer, CI-enforced zero network — with named comparisons against Mem0/OpenMemory, Zep/Graphiti, and Letta, and the benchmark as supporting evidence.
- Added `lnk onboard --hooks` so the guided first-run path can install session hooks alongside MCP wiring, and made `connect`/`onboard --hooks --write` refresh workspace runtimes that predate session hooks (preview warns first), preventing broken hooks after upgrades.
- Made the memory-backlog consolidation nudge part of the core brief payload so CLI `start`, MCP briefs, skills, and session hooks all surface it consistently.
- Improved `lnk semantic` diagnostics: status names the Python interpreter being checked, and when the Link MCP Python differs, errors print the exact venv-side setup command; quality-tier setup states the ~5s short-lived-CLI load tradeoff explicitly.
- Made the injected session-start brief compact for empty workspaces (two actionable lines instead of an empty statistics skeleton) and gave every missing-wiki CLI error a concrete next step instead of a dead end.
- Titled automatic session captures with their project, clustered near-duplicate captures in consolidation plans by token overlap instead of exact text, and documented session hooks, semantic recall, and consolidation across the PyPI README, LINK.md, installed agent instructions, MCP instructions resource, and the docs site.
- Added `lnk hook session-start` to print the bounded session-start memory brief (readiness, relevant memories with confidence, pending review and capture state, and retrieval guidance) for agent hook runtimes; it scopes the brief to the hook's working directory project and never fails the agent session.
- Added `lnk hook session-end` to turn an agent transcript into review-gated memory: it extracts bounded user/assistant text (skipping tool calls and outputs), skips trivial sessions, and stores proposal-only session notes through the same duplicate/conflict-safe capture path as `lnk session-end`.
- Added idempotent, non-destructive session-hook writing to `~/.claude/settings.json` that preserves existing user hooks and settings, replaces only Link's own hook entries on rerun, and skips re-injection on session resume.

### Fixed

- `python -m link_mcp --help` now prints usage and the MCP config snippet instead of silently starting the stdio server (which hung in a terminal with no output). The parser still ignores unknown arguments so an agent launch config can never crash the server.
- Automatic session-end capture now mines memory proposals from the user's own turns only, not the assistant's replies. Dogfooding showed the assistant's prose (e.g. a summary line like "you prefer small commits") was being extracted and proposed as the user's own preference. The raw capture still keeps the full transcript for review context; only the proposal candidates are restricted to what the user actually said (`extract_transcript_text(..., roles=("user",))`).

## [1.5.0] - 2026-07-03

### Added

- Added per-memory recall `confidence` labels (`strong`, `moderate`, `weak`) based on significant-token coverage, so agents can tell a real preference match from an incidental shared word before acting on it.
- Added lightweight suffix stemming to memory recall scoring so close paraphrases like "commits" still find memories phrased with "committing", without embeddings or external services.
- Added weak-match guidance to recall packets and CLI recall output: when every matched memory is a weak lexical match, Link now says so and tells the agent to verify with the user instead of presenting it as a known preference.
- Added `lnk session-end` (alias `lnk end`) as the agent-agnostic end-of-session lifecycle command: it stores proposal-only session notes, returns a small set of memory candidates, and refuses to create durable memory without user approval.
- Added MCP `link_session_end` prompt guidance and `admin(action="session_end")` support so MCP clients can run the same proposal-only shutdown loop without adding another default slim tool.
- Updated official skills, installed agent instructions, README, CLI docs, MCP docs, and package README around the portable loop: start with bounded recall, end with review-gated memory proposals.
- Added `lnk seed [project-dir] [target]` to create a source-backed project context page from allowlisted repo files such as `README.md`, `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, and editor rule files, with secret scanning and no silent durable-memory writes.
- Added `lnk onboard --seed-project [dir]` so first-run setup can create the initial source-backed project context page without making users discover a separate command.
- Added benchmark value evidence: `lnk benchmark` now estimates broad wiki body text versus the bounded Link query packet so users can see concrete context-budget savings alongside speed and scale checks.

- Added a slim MCP surface for LLM-native clients so agents can rely on a smaller default set of high-signal tools while the full tool surface remains available for compatibility.
- Added MCP prompt and resource coverage so clients can expose Link recall, remember, ingest, and review workflows as native agent actions instead of requiring users to memorize tool names.
- Added MCP `link_start` and `link://instructions` so clients can attach the portable startup loop: check readiness, run one empty-query recall brief, then use bounded recall before broad context reads.
- Added token-efficient recall capsules with a `micro` budget, rank signals, estimated token counts, and follow-up guidance so agents can retrieve the right memory before expanding context.
- Added `scripts/smoke_recall_quality.py` to exercise recall quality and token-budget behavior across representative memory queries.
- Added `lnk onboard` to create or repair a real `~/link` workspace, check health, optionally seed a first memory, preview or write agent MCP config, and print first prompts in one guided flow.
- Added `lnk proof`, a clean cross-agent continuity demo that creates a local proof workspace, writes one reviewed memory, and recalls it through the same bounded path used by CLI, skills, and MCP.
- Added a local `/onboard` viewer page that turns health, first memory, agent wiring, and starter prompts into one copyable setup checklist.
- Added `/onboard` links to first-run output, starter prompts, the local home page, the health page, HTTP viewer smoke coverage, and large-wiki smoke guidance.
- Added TTY-only CLI styling for human output while keeping JSON and non-TTY output plain for agents and scripts.
- Added audit-log hash-chain entries and doctor verification so silent edits to the local audit trail are detectable.
- Added rollback snapshots for write operations so interrupted multi-file memory/index updates can restore touched files or remove newly created files.
- Added `lnk operations --recover <marker> --confirm` so leftover crash snapshots from interrupted writes can be previewed and applied instead of becoming dead local state.
- Added cross-agent continuity coverage proving a memory written through the CLI can be recalled through the slim MCP surface from the same local wiki.
- Added cache-backed backlink rebuild logic so rebuilds reuse parsed page data while preserving existing body-only/full-link behavior.

### Changed

- Project seed pages now carry bounded, secret-scanned excerpts of the seeded files and recent commit subjects, so day-one recall returns the actual project context instead of a list of file names.

- Redesigned the local web console to the Link design system: cream/ink/rust editorial palette with a warm-dark theme (never pure black), serif headings with mono labels on system font stacks, a tab-strip nav, ledger memory cards, health status cards, and a segment-meter confidence indicator on recalled memories (weak matches carry a 'verify before trusting' note).

- Restored the designed animated landing page on GitHub Pages (live memory-graph hero) and refreshed its content for the slim MCP surface: canonical six tools, `lnk proof`/`lnk try`/`lnk start`/`lnk onboard` commands, and recall confidence labels.
- Tightened the README quick start and moved scale checks into the documentation table; documented recall confidence labels in the agent-facing tool list.

- Seeded the generated demo with four realistic memories (three reviewed, one pending) so the first recall, brief, and viewer walkthrough show a believable memory system and the review loop at the same time.

- Added `lnk start`, a CLI startup loop that combines readiness, validation state, and a local memory brief for agents using skills or shell instead of MCP.
- Updated agent installers and MCP config writers to prefer the slim MCP surface by default, reducing tool-list noise while keeping advanced tools available.
- Made the slim MCP surface the default server surface and aligned README, LINK.md, installed agent instructions, MCP docs, status actions, and query follow-ups around the canonical `status`, `recall`, `remember`, `ingest`, `review`, and `admin` vocabulary.
- Reworded starter prompts around the clearer `start with Link before we continue` flow so first-run users ask for the same startup recall loop exposed by MCP `link_start`.
- Improved query/search ranking for token-efficient recall, including stronger exact/phrase matching, better budget accounting, and clearer recall metadata in query packets, benchmark output, status, and health views.
- Tightened `lnk onboard --write` guidance so config-writing is explicit, repeatable, and clear about which agent files are affected.
- Improved `lnk serve` startup guidance so the terminal points new users to `/onboard`, `/health`, `/graph`, and clearly states that MCP and CLI work without the viewer running.
- Clarified public UI docs around the `/onboard` checklist and viewer-independent CLI, skills, and MCP usage.
- Redesigned the GitHub Pages landing page and refreshed the product brand, logo assets, README header links, and public docs styling around the newer product positioning.
- Replaced older synthetic docs GIFs with real, on-brand product screenshots and figures for UI, CLI, MCP, health, home, and graph flows.
- Reworked the README and docs landing page around one canonical proof path instead of multiple competing quick starts.
- Tightened README and public docs onboarding around a proof-first flow: `lnk proof` for the core memory aha, `lnk try` for the richer demo, and `lnk onboard` for real setup.
- Improved `lnk try` human-readable output so the first-run proof reads like a product moment instead of a debug checklist.
- Updated doctor backlink and isolated-page checks to reuse cached page records instead of rereading the whole wiki independently during health checks.
- Updated team-sync to keep `wiki/log.md` local so Git-based team sharing does not create false audit hash-chain tamper alarms.
- Regenerated dark-mode docs screenshots from deterministic source images before rebuilding the checked-in product GIFs.
- Tightened official skill trigger wording so skill-only agents can proactively retrieve context and propose memory after important user-approved decisions without silently writing.
- Retired the old synthetic docs media generator in favor of a non-destructive verifier for checked-in real product screenshots, GIFs, and diagrams.
- Updated the local `/onboard` checklist to surface project context seeding before first memory and agent wiring, matching the new `lnk onboard --seed-project .` path.
- Updated installed agent instructions so agents recover from empty project recall by seeding allowlisted source-backed repo context before broad searching.
- Updated `lnk start`, MCP `link_start`, and slim MCP `admin` so empty project recall points agents toward source-backed project seeding before broad file reads.
- Updated `lnk start` to include a tiny token-bounded context preview from the same hybrid query packet used by CLI, skills, and MCP once source-backed project context exists.
- Updated status/health next actions so empty initialized workspaces recommend source-backed project seeding before generic ingest prompts.

### Fixed

- Fixed direct `serve.py` argument parsing so a positional target now fails with guidance instead of silently serving the wrong wiki root; use `--root` directly or `lnk serve <target>`.
- Fixed a flaky Windows write-lock path by retrying file-lock acquisition on transient `PermissionError`.
- Fixed docs-site validation so the self-contained landing bundle is allowed while the rest of the public docs keep the local-first/no-external-runtime guarantee.
- Fixed first-run `init` output to print the installed `lnk` command instead of the collision-prone `link` command.

## [1.4.0] - 2026-06-14

### Added

- Added official CLI skills under `skills/` so agents can lazy-load Link workflows without MCP setup.
- Added `lnk try` as a one-command demo proof loop that creates the demo, checks readiness, runs query/brief examples, and prints first agent prompts.
- Added `lnk connect <agent>` to preview or write MCP client config for Codex, Kiro, Claude Code, Cursor, Antigravity, VS Code, and Copilot.
- Added Windows PowerShell installers for Codex, Kiro, Claude Code, Cursor, Antigravity, VS Code, and Copilot.
- Added optional `review_after` dates for durable memories so time-sensitive context can automatically return to the memory inbox for re-checking.
- Added optional `expires_at` dates for durable memories so temporary context automatically leaves default recall after expiry.
- Added `lnk import-obsidian <vault>` to copy Obsidian Markdown notes into `raw/obsidian/` with secret scanning before the normal ingest workflow.
- Added `lnk compliance-export` for redacted readiness, validation, memory-review, operation, and log exports for team or security review.
- Added `lnk restore-backup` to preview and confirm local backup restores with unsafe-tar checks, raw restore opt-in, and pre-restore safety backups.
- Added `lnk team-sync` to print a safe Git sharing plan for reviewed team memory without pushing private raw sources automatically.
- Added `lnk share <page-or-memory>` to print a local viewer permalink and agent prompt for a specific Link page.
- Added `lnk snapshot` to export a static, read-only HTML snapshot for demos or reviews while excluding raw sources, captures, live state, and memory pages by default.
- Added memory `visibility` metadata (`private`, `project`, or `team`) so team sharing can rely on explicit user intent instead of inferring privacy from scope alone.
- Added `lnk set-memory-visibility` and MCP `set_memory_visibility` so existing memories can move between private, project, and team sharing intent after explicit user approval.
- Added `lnk memory-log`, MCP `memory_log`, `/memory-log`, and `/api/memory-log` for recent memory lifecycle changes without exposing raw source or memory bodies.
- Added privacy-safe memory-log change summaries so review, status, and visibility transitions are visible without exposing memory bodies.
- Added `lnk wins`, MCP `memory_wins`, `/wins`, and `/api/wins` for local, non-telemetry proof signals about what Link memory is carrying.
- Added a team security review docs page covering local deployment, data boundaries, memory approval gates, Git sharing, audit exports, and current limits.
- Added a memory contract docs page that explains the stable MCP agent loop, tool groups, write rules, budget behavior, and sharing semantics.
- Added an integration maintainer checklist covering installer invariants, new-agent steps, PowerShell parity, and validation commands.
- Added a scale model docs page covering bounded defaults, benchmark/health checks, large-wiki habits, and current local limits.
- Added `python -m link_mcp --version` so MCP package installs can be verified before a wiki exists.
- Added an Obsidian guide for opening Link's Markdown wiki as a vault and rebuilding indexes after manual edits.
- Added validation and doctor failures for secret-looking values already present in wiki pages so local UI and MCP context do not quietly serve manually introduced secrets.

### Changed

- Broadened local secret detection for common modern provider tokens and credentials before capture, ingest, Obsidian import, and doctor scans.
- Changed the installed CLI command from `link` to `lnk` to avoid the POSIX/macOS `link` utility collision while preserving source-checkout `python3 link.py ...` usage.
- Tightened `lnk team-sync` readiness so unreviewed memories or active `visibility: private` memories block "ready" status before Git sharing.
- Tightened `lnk snapshot --include-memories` so private memories stay excluded unless `--include-private-memories` is explicitly passed.
- Broadened Windows CI from a small portability subset to most non-installer/non-server tests.
- Clarified that the Homebrew formula lives in the separate `gowtham0992/homebrew-link` tap.
- Tightened security reporting guidance to prefer private maintainer contact before public GitHub issues.

## [1.3.0] - 2026-05-22

### Added

- Added copyable agent prompts across page, search, ingest, brief, memory dashboard, profile, audit, capture, and inbox views so browser-first users do not need to memorize Link phrasing.
- Added copy buttons to memory action commands, capture commands, and memory next actions in the local web UI.
- Added empty-wiki home recovery actions that link to ingest and copy the first ingest prompt.
- Added graph empty-state recovery actions that link to ingest and copy the first ingest prompt.
- Added empty memory-brief recovery actions that link to ingest/proposal review and copy a proposal prompt.
- Added empty memory-profile recovery actions that link to ingest/proposal review and copy a remember prompt.
- Added search no-result recovery actions with source-ingest and memory-proposal prompts.
- Added CLI query no-context recovery steps for ingest status, raw source ingest, and rerunning the query.
- Added interactive graph legend chips that filter the graph by page type.
- Added viewer commands and graph/health URLs to the synthetic large-wiki smoke output so local 10k-page checks are easier to inspect.
- Added active navigation highlighting to the local web viewer.
- Added an in-page search refinement form that preserves the current query and page-type filter.
- Added related-page links to wiki page footers using inbound and forward graph context.
- Added threaded local HTTP request handling with locks around shared cache and mutation rate state.
- Added accessible labels to local search inputs.
- Added page-level persistent cache reuse so edited wikis reread changed Markdown pages without rereading unchanged pages.
- Added `link next` as a short alias for starter prompts so first-run users have one memorable next-step command.
- Added the `link next` prompt command to demo output so the first terminal screen points to the agent-first workflow.
- Added the `link next` shortcut to starter prompt payloads and the local prompts page.
- Added persistent-cache reuse details to benchmark JSON and text output.
- Clarified graph controls so large wikis say "load all data" for search/filtering instead of implying the canvas renders every node.
- Added persistent-cache state to status payloads, CLI status output, and the local health page.
- Updated docs to explain persistent-cache reuse in status, benchmark, health, and slow-wiki troubleshooting flows.
- Updated installer and agent-instruction next steps to point at `link next`.
- Simplified quick-start examples around `link next`, with `link welcome` kept as the optional guided proof path.
- Added copy buttons to the home-page starter prompt strip.
- Added a local HTTP request timeout so stalled clients cannot hold server threads indefinitely.
- Added legacy browser hardening headers for frame denial, DNS prefetch control, and cross-domain policy denial.
- Added `/api/health` for a machine-readable readiness packet with validation and interrupted-operation state.
- Added `/api` discovery output with recommended local endpoints and write-action header requirements.
- Added MCP `link_operations` so agents can inspect pending, failed, or interrupted local writes.
- Added `link health` as a single CLI readiness command combining status validation with interrupted-write state.
- Added a `/more` page so direct navigation to advanced local viewer tools no longer lands on Not found.
- Added a graph display cap control so large wikis can trade canvas density for responsiveness without loading every visible node at once.
- Added non-alarmist benchmark scale notes for 1k/10k-page wikis, bounded graph overviews, and SQLite FTS headroom.
- Added `link version` as a discoverable command alias for `link --version`.

### Changed

- Improved the local All Pages view with page-type summary chips and grouped visible results so larger wikis are easier to scan.
- Made All Pages summary chips filter by page type while preserving bounded pagination.
- Grouped local search results by page type and added page-type chips for narrowing result sets.
- Added a Recently Updated section to the local home page so users can resume from fresh wiki pages.
- Refined the local web viewer toward a quieter wiki/document layout with grouped navigation, plainer page metadata, and automatic section outlines on structured wiki pages.
- Changed large-graph canvas seeding to use deterministic category clusters, with higher-degree pages nearer cluster centers, instead of a single global spiral.
- Updated CLI query no-context recovery commands to include the explicit Link root so they work from any terminal directory.
- Updated starter prompt local-check commands to include the explicit Link root so CLI, web, and MCP prompt payloads are paste-safe outside the wiki directory.
- Updated operation recovery commands to include the explicit Link root for interrupted-write repair flows.
- Updated health page repair and next-action commands to include the explicit Link root where the page can infer it.
- Updated starter prompts, installers, ingest post-checks, and quick-start docs to use `link health` as the primary readiness command.
- Updated init and demo next-step commands so setup guidance remains paste-safe outside the current checkout directory.
- Updated ingest guidance commands and post-checks to include the explicit Link root across CLI, JSON, web, and MCP payloads.
- Updated rebuild-index follow-up guidance to include the concrete `link.py` runtime and Link root for the next backlinks repair step.
- Updated ingest UI next-step and validation cards to reuse target-aware commands instead of generic or chained shell snippets.
- Updated `link status` text output to pair MCP-style next actions with concrete local commands for terminal users.
- Updated the health page memory-review fallback to copy a target-aware `link memory-inbox` command.
- Updated `link-mcp` missing-wiki startup guidance to point at `link init`, source checkout init, integration installers, or `--wiki`.
- Updated the CLI product docs with the local large-wiki smoke command and how to inspect the generated fixture.
- Updated public docs to describe the wiki-style home, catalog, and search browsing flows.
- Updated README and UI docs to describe related-page footers and search refinement.
- Clarified large-graph load copy so users know full data enables search/filtering while the canvas remains capped.
- Updated CI to run the full pytest suite rather than the narrower unittest discovery path.

## [1.2.0] - 2026-05-19

### Highlights

- Makes Link easier to install and try as a real product: Homebrew tap support, GitHub Pages docs, cleaner README/product positioning, and visual walkthrough assets.
- Tightens external-user workflows across CLI, MCP, and the local web UI so copied commands work from any terminal directory and agents get explicit Link targets.
- Adds clearer local health and recovery surfaces with `/health`, `link operations`, interrupted-write inspection, and bounded log rotation.
- Improves confidence after the refactor with full user-level acceptance coverage across demo, init, memory lifecycle, capture lifecycle, MCP stdio, HTTP APIs, graph, and large-wiki paths.
- Keeps large local wikis interactive with bounded graph payloads, SQLite FTS search validation, large-wiki smoke coverage, and benchmark/readiness reporting.

### Added

- Added tap-ready Homebrew Formula packaging and maintainer instructions for publishing `gowtham0992/homebrew-link`.
- Added public Homebrew install instructions to README and the product docs.
- Added GitHub Pages product documentation under `docs/`, including focused UI, MCP, CLI, API, security, and contribution pages.
- Added product-facing demo visuals for UI, CLI, and MCP flows so new users can understand Link before installing it.
- Added a local `/health` page for readiness, validation, interrupted operations, warnings, repair actions, and copyable repair commands.
- Added `link operations`, `/api/operations`, and operation markers so interrupted or failed local writes can be inspected before manual cleanup.
- Added bounded `wiki/log.md` rotation so active wikis do not accumulate an indefinitely growing operation log.
- Added external-user acceptance coverage for CLI, MCP stdio, HTTP routes, web mutation APIs, graph rendering, and large-wiki behavior.

### Changed

- Simplified the README architecture section and diagram so the source/wiki/memory/query model is easier to scan.
- Updated generated CLI guidance in memory, capture, web, and MCP payloads to include explicit Link root targets instead of relying on `.`.
- Updated capture inbox, memory inbox, profile, lifecycle, and proposal commands so users can paste commands from any working directory.
- Updated local web audit and capture commands to point at the served Link root.

### Fixed

- Fixed proposal approval commands that could save memories into the caller's current directory when copied from CLI or web output.
- Fixed capture accept/delete/review follow-up commands that assumed the terminal was already inside the Link root.
- Fixed memory review/update/archive/restore/forget follow-up commands that assumed the terminal was already inside the Link root.

## [1.1.0] - 2026-05-08

### Highlights

- Reframes Link as local personal memory for agents, with the Markdown wiki as the inspectable storage layer.
- Adds the first-use path around `link init`, `link serve`, the managed `link` command, demo proof prompts, and readiness checks.
- Adds the memory lifecycle: remember, recall, propose, capture, approve, review, archive, restore, forget, explain, profile, and audit.
- Adds smart query packets so MCP agents can retrieve budgeted memory, ranked wiki context, graph neighborhoods, and follow-up actions without scanning the whole wiki.
- Adds guided ingest/proposal UI, Memory Dashboard, larger graph controls, dark/light/system themes, and clearer local web navigation.
- Adds schema migration, validation gates, release hygiene, MCP contract checks, runtime duplication guardrails, and broader first-use/large-wiki smoke tests.

### Added

- Added Memory Mode foundation with `wiki/memories/`, `link.py remember`, `link.py recall`, and MCP `remember_memory`/`recall_memory` tools.
- Added a first-run demo memory page so Link presents as local agent memory, not only a wiki.
- Added Memory Profile views through `link.py profile`, MCP `memory_profile`, `/profile`, and `/api/memory-profile`.
- Added reversible memory lifecycle controls with `archive-memory`/`restore-memory` and MCP `archive_memory`/`restore_memory`; archived memories are hidden from recall by default.
- Added confirmed permanent memory deletion with `forget-memory` and MCP `forget_memory` for user-requested local forgetting.
- Added low-priority forget actions to memory review/explanation payloads so permanent deletion is discoverable but never the default next step.
- Added memory action commands to web inbox and explanation pages, including review, update, archive, restore, and low-priority forget actions.
- Added Memory Review Inbox with `memory-inbox`, `review-memory`, MCP `memory_inbox`/`review_memory`, `/inbox`, and `/api/memory-inbox`.
- Added Explain Memory views with `explain-memory`, MCP `explain_memory`, `/explain-memory`, and `/api/explain-memory` for provenance, review state, lifecycle, graph links, and recall readiness.
- Added `/propose`, a read-only local UI for turning pasted source/session notes into memory proposals without writing pages.
- Added guarded web approval actions on `/propose` with local-only `remember-memory` and `update-memory` APIs for explicitly saving selected proposals.
- Added a visible review gate to `/propose`, including manual-review states for duplicate/conflict proposals before durable memory writes.
- Kept web approval APIs on the safe path by ignoring duplicate/conflict override flags; use CLI or MCP only after explicit human review.
- Fixed duplicate proposal CLI commands so project-scoped updates preserve the normalized project key.
- Added top-level project reporting to accepted capture payloads so CLI and MCP agents can keep project-scoped memories straight.
- Added raw capture read-warning reporting so unreadable saved captures appear in CLI, MCP, local web inbox, brief, and audit diagnostics instead of disappearing silently.
- Hardened `link.py doctor` secret-content checks so unreadable scannable files fail closed instead of being skipped.
- Hardened local backups so archive failures remove partial `.tar.gz` files and return controlled CLI/MCP errors.
- Added backup-list warnings for unreadable local backup archives instead of failing the whole list operation.
- Hardened wiki validation so unreadable pages become structured `unreadable_page` errors instead of crashing validation.
- Hardened backlink rebuild commands so unreadable pages return controlled CLI, MCP, and local web errors.
- Hardened index rebuild commands so unreadable pages return controlled CLI, MCP, and local web errors.
- Hardened MCP and local web status calls so cache issues produce readiness warnings instead of crashing.
- Made the shared wiki cache skip unreadable pages with `cache_read_warnings` so search/query/graph can continue over readable pages.
- Added shared atomic write helpers and migrated Link state writes for schema markers, memory pages, indexes, backlinks, captures, raw source creation, logs, and demo files.
- Added a root `pyproject.toml` with conservative Ruff correctness checks and a CI lint job for pull requests.
- Optimized ingest status source matching with a reverse raw-path index instead of a raw-file by source-page nested scan.
- Removed a redundant memory index reread from direct memory resolution paths.
- Reused cached forward-link data during context retrieval to avoid an extra primary-page disk read.
- Folded validation backlink comparison into the validation page scan so Markdown pages are read once per validation pass.
- Added MCP `link_status` and `/api/status` for a compact readiness summary with version, wiki path, page/memory counts, optional validation, and safe next actions.
- Added search backend reporting to Link status payloads so agents and users can see whether local search is using SQLite FTS or the token fallback.
- Added `link.py status` so the same readiness summary is available before MCP or the local web server is connected.
- Added `link.py status --validate` to installer next-step output so new users have one readiness command after setup.
- Added `content_page_count` to Link status and first-run guidance for structurally ready but empty wikis.
- Added status warnings so cache or memory-read degradation is visible in CLI, HTTP, and MCP readiness payloads.
- Added shared Markdown renderer coverage under `link_core.markdown` so the local web UI's sanitized Markdown behavior is tested outside the HTTP monolith.
- Added an HTTP viewer smoke test that starts a generated demo server over localhost and verifies pages, JSON APIs, security headers, and local mutation guards.
- Added a GitHub Pages-ready product site under `docs/` with local-agent-memory positioning, demo visuals, quick start, MCP links, and security links.
- Added a `Why Link?` product page that explains where Link fits versus human-first notes apps, hosted memory APIs, stateful-agent runtimes, temporal graph memory systems, and plain file search.
- Clarified the local web viewer safety boundary in README/docs and startup output: the server binds to `127.0.0.1`, has no authentication, and should not be exposed without an added auth layer.
- Moved bundled demo wiki content into `link_core.demo` so the CLI module no longer carries the full demo payload inline.
- Moved the local web UI CSS/JavaScript assets into `link_core.web_assets` so `serve.py` stays focused on routing and rendering.
- Moved memory and raw-capture card rendering into `link_core.web_memory` so memory UI escaping and actions are covered outside the HTTP server.
- Moved the shared local web layout shell into `link_core.web_layout` so header/nav/theme/search behavior is tested outside the HTTP server.
- Moved local HTTP guard parsing and Host validation into `link_core.web_http` with isolated tests.
- Moved local viewer security header policy into `link_core.web_http` so browser hardening stays core-tested outside the HTTP server.
- Moved graph payload, category, and legend helpers into `link_core.web_graph` so graph-scale behavior is tested outside the HTTP monolith.
- Added a managed `~/.local/bin/link` command for global installs so users can run `link status --validate`, `link query`, and `link brief` without remembering wiki paths.
- Added a shared Link runtime version and `link --version`; CLI and local HTTP status now report the same release version as the package.
- Switched MCP status version reporting to the shared Link runtime version so source checkouts and installed packages cannot drift.
- Added `link init` to create or repair a normal Link wiki without loading demo content.
- Added `link serve` to start the local web viewer without remembering `serve.py` paths.
- Made `link verify-mcp` require the installed `link-mcp` version to match the local Link runtime before reporting ready.
- Made `link verify-mcp` print shell-quoted install and upgrade commands using the exact Python executable being verified.
- Made `link verify-mcp` import-check the MCP SDK dependency so broken partial installs no longer report ready.
- Made `link verify-mcp --json` return structured issue codes and repair actions for agent/tooling consumers.
- Improved local server startup errors with bounded port validation in both `link serve` and `serve.py`, plus clear next-port guidance when a port is already in use.
- Added `link benchmark` to measure local cache, search, smart query, and graph timings on a user's current wiki.
- Extended `link benchmark` and large-wiki smoke to prove bounded agent payload timings for graph summaries and page lists.
- Extended `link benchmark` and large-wiki smoke to prove the graph page's initial browser payload stays bounded on huge wikis.
- Added an ignored `.link-cache/` persistent page-record cache so unchanged large wikis can warm search/context indexes without rereading every Markdown page.
- Extended the first-use smoke to run `link graph-summary` and `link benchmark` so the demo value loop is release-gated.
- Made the local graph viewer start with a bounded overview for very large wikis, with an explicit full-graph load control.
- Hardened local write APIs by rejecting browser `Origin`/`Referer` headers that do not point at the local Link viewer.
- Added in-memory rate limiting for local write APIs so runaway local clients get structured JSON `429` responses with `Retry-After`.
- Added explicit local JSON `405` responses for browser preflight requests without granting CORS access.
- Added Content Security Policy headers to the local viewer and a stricter SVG asset policy.
- Added browser isolation and permissions-policy headers, and marked local JSON API responses `Cache-Control: no-store`.
- Marked local HTML pages and served static/raw files `Cache-Control: no-store` so private memory pages and source media are not browser-cached.
- Added shared legacy `Pragma`/`Expires` no-cache headers for local personal-memory responses.
- Returned hardened JSON `405` responses for unsupported local HTTP methods, including `TRACE` and `CONNECT`, instead of default server HTML.
- Hardened `HEAD` handling so local health/static checks return headers without bodies and always reset response state.
- Bounded local HTTP query, search, project, graph-summary, memory lookup, and proposal metadata parameters with the same text normalization used by CLI/MCP inputs.
- Bounded `/propose` page seed query values before rendering source/project form defaults.
- Added an interactive-readiness verdict and threshold warnings to `link benchmark` so larger local wikis are easier to evaluate.
- Added shared benchmark health checks to the large-wiki smoke so user-facing and CI scale verdicts stay aligned.
- Tightened ownership of generated search caches in CLI query and index rebuild paths so in-memory SQLite indexes are closed when short-lived operations finish.
- Hardened smart query budget normalization so unexpected or oversized adapter values safely fall back to `medium`.
- Added an explicit local HTTP API version header and status field for future integration compatibility.
- Added wiki schema markers with safe `link migrate`/MCP `migrate_wiki` migrations for future local format changes.
- Added first-run agent prompts to installer output so new users can immediately try brief, remember, and query workflows.
- Added `link prompts` to print the first-run natural agent prompts and local readiness checks on demand.
- Added `/prompts` and `/api/prompts` so browser-first users get the same starter prompt guidance as the CLI.
- Added MCP `starter_prompts` so MCP-only agents can retrieve the same first-run prompt guidance.
- Updated installed agent instructions and release hygiene so `starter_prompts` remains part of the public agent contract.
- Added guided `link ingest-status` output with structured JSON guidance, exact agent prompts, and follow-up validation commands.
- Added visible post-ingest checks to the CLI and local ingest UI so users see the rebuild/validate/status loop before relying on generated pages.
- Added `/ingest` and `/api/ingest-status` so the local UI shows pending raw files, graph health, and the next agent prompt.
- Added a local `/ingest` Add Raw Source form and `POST /api/raw-source` so browser-first users can paste a source, save it under `raw/`, block secret-looking values, and copy the next ingest prompt without remembering filesystem paths.
- Added ingest completion cards that show which raw files are represented, link to their source pages, and provide copyable memory/query prompts for post-ingest validation.
- Added the same represented-source completion summary to `link ingest-status` for terminal-first users.
- Added MCP `ingest_status` so MCP-only agents can inspect pending raw files and validation guidance.
- Added `link rebuild-index`, MCP `rebuild_index`, and `POST /api/rebuild-index` to regenerate the human-readable wiki catalog from current pages.
- Improved `doctor --fix` so it repairs index drift and rebuilds backlinks afterward.
- Added clearer product framing in the README and local home page for the distinction between source-backed wiki knowledge and explicit agent memory.
- Added a local raw-source picker to `/propose` with secret-aware loading for proposal-only memory workflows.
- Added shared proposal action hints so memory proposals include the safest approval prompt, local command, MCP tool, and arguments.
- Added a wider graph page layout with fullscreen mode so larger wikis can be explored without being squeezed into the reading column.
- Added large-graph controls for node search, type filtering, and selected-node neighborhood depth.
- Added a capped default graph overview for huge wikis so the canvas draws the most connected nodes first while search and selected neighborhoods still pull relevant nodes into view.
- Added bounded graph summaries through CLI, HTTP, and MCP so agents can inspect large graph structure without loading every node and edge into context.
- Made graph edge construction cache-backed so large graph rendering/export avoids rereading every Markdown page after cache warmup.
- Added bounded page-list payloads for MCP and HTTP so agents can inspect page metadata without dumping very large wikis into context.
- Added bounded backlink/page-link payloads for MCP and HTTP so hub pages do not flood agent context.
- Added a short local-server cache poll interval so hot navigation reuses the warmed wiki cache instead of rescanning every page for each request.
- Added duplicate protection for `remember`/`remember_memory`; strong duplicate memories are refused unless explicitly allowed.
- Added memory merge/update workflow with `update-memory` and MCP `update_memory`, including update counts, audit logs, backlink rebuilds, and review reset.
- Added proposal-only memory extraction with `propose-memories` and MCP `propose_memories` for chat/session notes.
- Added agent memory briefs with `link.py brief` and MCP `memory_brief` so agents can prime themselves with relevant local memory before a task.
- Added smart Link query packets with `link.py query`, MCP `query_link`, and `/api/query-link` so agents can retrieve budgeted memory, ranked wiki results, and graph context without reading the whole wiki.
- Added smart query budget reports and follow-up tool actions so agents know when context was truncated and how to continue without scanning the whole wiki.
- Added estimated character/token counts to smart query budget reports so agents can reason about context cost.
- Bounded agent-facing CLI query strings for `query`, `brief`, `graph-summary`, and `benchmark` to match the MCP server's safer input posture.
- Added provenance metadata to smart query memory and wiki packets so agents can explain why Link knows something without loading full pages.
- Added precomputed search word indexes so repeated wiki search and smart query calls avoid rebuilding per-page word sets on larger wikis.
- Added optional in-memory SQLite FTS search acceleration with token-index fallback so large local wikis stay fast without adding a server dependency.
- Improved smart query follow-ups so a truncated large-budget packet does not ask the agent to rerun the same large budget again.
- Added `link.py validate` as an ingest gate for agent-generated wiki pages, covering required frontmatter, type/directory alignment, required sections, dead links, and stale backlinks.
- Added MCP `validate_wiki` and `/api/validate` so agents can run the same ingest gate without shell access.
- Added a runtime duplication guard in CI to block new large copied helper bodies across CLI, web, and MCP runtimes.
- Added a tool contract guard in CI to keep public CLI commands, MCP tools, and README references from drifting.
- Tightened memory mutation adapters so CLI and MCP memory writes share more core behavior with fewer runtime-side exceptions.
- Extracted shared memory audit risk-factor logic into core so CLI, web, and MCP report the same health semantics.
- Extracted shared memory brief capture guidance into core and removed the last allowed large duplicate runtime helper.
- Added raw capture status to CLI and MCP memory briefs so session priming surfaces saved captures and secret-warning captures.
- Added `/brief` and `/api/memory-brief` so the local web UI and HTTP clients can get startup memory context, review warnings, and raw capture status.
- Added `memory-audit` and MCP `memory_audit` for a read-only health report covering memory backlog, raw captures, risk factors, and next actions.
- Added `/audit` and `/api/memory-audit` so the local web UI exposes the same read-only memory audit report.
- Added memory review and raw capture backlog checks to `link.py doctor`, while excluding proposal-only raw captures from ingest-status pending source counts.
- Added conflict detection for memory writes, updates, and proposals; contradictory active memories are surfaced before saving unless explicitly allowed.
- Added shared memory review action plans so inbox and explanation payloads tell agents whether to review, update, archive, restore, or edit metadata next.
- Added project-aware memory boundaries so project-scoped memories can carry a project key and recall/profile/brief keep other explicit projects out of context.
- Improved memory recall ranking so project-matched and reviewed memories win ties while archived/stale memories rank lower when explicitly included.
- Added `link.py capture-session` to save long session notes under `raw/memory-captures/` and return proposal-only memory candidates for human approval.
- Added MCP `capture_session` so agents can preserve long session notes locally before asking which memory proposals to write.
- Added secret-looking content warnings to CLI and MCP session capture results so pasted tokens can be redacted from local raw notes.
- Added `link.py accept-capture` to turn an approved raw-capture proposal into a durable memory through duplicate/conflict-safe writes.
- Added MCP `accept_capture` for approving saved capture proposals through the same duplicate/conflict-safe workflow.
- Added `link.py redact-capture` to replace secret-looking values in saved raw captures while logging only warning labels and counts.
- Added MCP `redact_capture` so agents can redact saved raw captures after user approval.
- Added `link.py delete-capture` with explicit confirmation for removing saved raw captures without logging capture contents.
- Added MCP `delete_capture` with explicit confirmation for removing saved raw captures.
- Added `link.py capture-inbox` to list saved raw captures, secret warnings, and accept/redact/delete commands.
- Added MCP `capture_inbox` to review saved raw captures with redacted snippets before accepting, redacting, or deleting them.
- Added raw capture visibility to `/memory` and `/api/memory-dashboard`, including accept/redact/delete commands and secret-warning counts.
- Added `/captures` and `/api/capture-inbox` for a dedicated local web/API raw capture inbox.
- Added project filtering to `/memory`, `/profile`, `/api/memory-dashboard`, `/api/memory-profile`, and `/api/memory-inbox`.
- Added project filtering to CLI and MCP memory inbox workflows.
- Added read-only web Memory Dashboard at `/memory` and `/api/memory-dashboard` for active memories, review queue, recent updates, archived memories, and next-action commands.
- Added recall readiness metadata to recalled memories so CLI, MCP, and brief payloads expose whether memory is ready, provisional, unsafe, or disabled.
- Added local web review/archive/restore memory actions backed by guarded HTTP POST endpoints; permanent forget remains command/tool-only.
- Added secure proposal-only HTTP endpoint `POST /api/propose-memories`; HTTP memory mutations are limited to local review/archive/restore actions.
- Added a graph node inspector so moving nodes no longer accidentally opens pages; double-click or Open page still navigates.
- Added an explicit `system`/`dark`/`light` theme toggle for the local web UI; dark mode now uses a black page background.
- Added a real MCP stdio smoke test for the built `link-mcp` wheel in CI.
- Added MCP `starter_prompts` coverage to the real stdio smoke test.
- Reused the shared starter prompt payload on the home page so UI, CLI, API, and MCP prompt guidance cannot drift.
- Normalized explicit starter prompt project names so CLI, HTTP, and MCP return consistent project slugs.
- Blocked normal ingest guidance for raw files with secret-looking values so users redact them before any agent reads them into wiki memory.
- Blocked normal ingest guidance for raw files Link cannot read and safety-scan, with explicit CLI, HTTP, and MCP payload diagnostics.
- Blocked normal ingest guidance when source pages cannot be read, because represented/pending raw counts may be incomplete.
- Switched raw-source secret detection to streaming file scans so large source folders do not get loaded into memory during ingest status checks.
- Added an explicit ingest `safety` summary across CLI, HTTP, and MCP payloads so agents do not need to infer whether raw sources are clear, warning-only, or blocked.
- Added copy buttons for guided ingest prompts and post-ingest checks in the local web UI.
- Made proposal source discovery stream secret scans, read only bounded previews, and return explicit source actions for load, redact, or split.
- Made proposal source discovery return explicit fix-access actions for raw files that cannot be read.
- Hardened direct proposal-source loading to reject oversized path inputs and hidden raw files, matching the source picker.
- Added benchmark health summaries and recommendations so `link benchmark` produces clearer proof-of-readiness output.
- Improved benchmark recommendations so slow search, cache, page-list, and graph paths get targeted repair guidance.
- Added README trust-gate guidance for ingest safety, proposal review, validation, benchmark readiness, duplicate/conflict checks, and first-run benchmarking.
- Clarified README guidance for `link verify-mcp`, including version parity, MCP SDK dependency, wiki path, and config checks.
- Clarified README and PyPI docs that status reports content/page/memory counts, not just structural page totals.
- Added a first-use smoke test for init, demo, status, query, brief, remember, capture, ingest-status, and validation workflows.
- Added `link prompts` coverage to the first-use smoke so CI validates the first-run agent prompt path.
- Added `doctor --fix` coverage for schema marker creation so one-command repairs stay release-gated.
- Added large-wiki smoke coverage for smart query budgets and graph generation across hundreds of pages.
- Added timing thresholds to large-wiki smoke coverage so major search/query/graph performance regressions fail early.
- Added release hygiene checks that protect the public agent instruction contract for `query_link`, `validate_wiki`, and `memory_brief`.
- Expanded release hygiene checks so public agent instructions must retain `ingest_status`, `get_graph_summary`, and `backup_wiki` guidance.
- Routed web memory/search limit parsing through the shared bounded-integer helper so local API endpoints handle invalid limits consistently.
- Hardened release hygiene so `server.json` cannot silently lose the `link-mcp` package version entry.
- Added release hygiene checks that block accidental outbound HTTP client code in tracked Python and shell runtimes.
- Expanded outbound-network release hygiene to catch stdlib `http.client` and `urllib` request aliases.
- Expanded outbound-network release hygiene to catch direct stdlib `socket` client imports while allowing the local `socketserver` viewer.
- Updated agent contract checks and installed instructions to include `link_status` for setup/readiness checks.
- Changed CI to run on pull requests and manual dispatch only, preserving GitHub minutes for the develop-branch workflow.
- Added CLI validation to the CI demo health smoke path so PRs catch broken generated wiki templates.
- Updated the PyPI package README with the current MCP tool contract, validation workflow, capture inbox, and permanent-forget guidance.
- Added PyPI package README trust notes for local-first privacy, bounded agent context, SQLite FTS, and graph-summary-first usage.
- Updated package classifiers and PR CI coverage for modern Python, including Python 3.14.
- Added Memory Dashboard next actions so the web UI and API surface the most important memory maintenance step.
- Extracted shared memory proposal logic into `link_core` so CLI, HTTP, and MCP proposal behavior stays aligned.
- Extracted shared raw capture path resolution and notes parsing into `link_core` so CLI and MCP capture operations use the same root-escape guard.
- Extracted shared frontmatter parsing and typed update helpers into `link_core` for safer memory metadata writes.
- Extracted shared memory record loading, review inbox, profile, and recall helpers into `link_core`.
- Extracted shared memory resolution, log lookup, and recall-state helpers into `link_core`.
- Extracted shared memory lifecycle mutations for archive, restore, review, and update workflows into `link_core`.
- Extracted shared memory creation for `remember` and `remember_memory` into `link_core`.
- Extracted shared wiki indexing, search, context, graph, and backlink helpers into `link_core`.
- Extracted shared search ranking and optional SQLite FTS helpers into `link_core.search` so wiki indexing stays separate from search execution.
- Extracted shared memory explanation/audit payloads into `link_core`.

### Fixed

- Tightened README onboarding and release examples around Link's local memory product value.
- Simplified onboarding docs and installed instructions around natural agent prompts and the short `link` command instead of path-heavy maintenance commands.
- Moved the local UI theme control into a compact header utility above search so it no longer wraps awkwardly in the navigation row.
- Reworked the local UI header into a clean brand/tools row with navigation tabs below it.
- Fixed installer MCP setup reporting so failed upgrades no longer masquerade as success by reusing an unrelated older global `link-mcp`.
- Fixed project-mode installer output so MCP wiki paths are absolute and next-step hints point at the project wiki instead of `~/link`.
- Fixed search/context matching for natural queries against hyphenated page slugs, e.g. `local first software` now finds `local-first-software`.
- Fixed missing HTTP context topics to return a controlled 400 JSON error.
- Hardened backlink rebuild over HTTP so local web rebuilds require JSON POST instead of a mutating GET.
- Hardened HTTP rebuild actions so local web index/backlink mutations require the explicit local-action header.
- Hardened local web startup so unsupported host/bind flags fail instead of implying public serving is supported.
- Hardened `/raw/` static serving so the local web viewer only serves supported media/PDF source assets.
- Tightened raw asset path resolution so `/raw/` URLs cannot route through non-raw static allowlists, including encoded parent-directory paths.
- Hardened HTTP memory mutation endpoints with an explicit `X-Link-Local-Action: true` header required by non-UI clients.
- Refreshed the checked-in demo backlink index so `link.py doctor .` reports a healthy graph.

## [1.0.7] - 2026-05-04

### Fixed

- Fixed Codex MCP auto-registration after the venv installer fallback so existing `~/.codex/config.toml` files are updated without a regex crash.
- Fixed `link.py verify-mcp` to use the installer-recorded MCP Python when present.
- Fixed dashboard polish and search keyboard submission in the local web viewer.

## [1.0.6] - 2026-05-04

### Added

- Added `scripts/prepare_release.py` to bump MCP release versions, cut changelog notes, and print publish commands without uploading anything automatically.
- Added versioned changelog tracking for repo, PyPI, and MCP Registry releases.
- Added `link.py ingest-status` to show pending raw sources and stale graph indexes.
- Added `link.py doctor --fix` for safe structure creation and backlink repair.
- Added `link.py verify-mcp` to validate local MCP readiness and print client config.
- Added first 10 minutes onboarding docs.
- Added golden demo snapshot tests and direct MCP contract tests.

### Changed

- Moved raw capture inbox parsing, project filtering, snippet redaction, and command generation into shared `link_core.capture` helpers.
- Polished the graph view with reset, label, and motion controls, keyboard focus, empty-state handling, cursor-centered zoom, and sticky dragged node placement.
- Restructured README.md into a product-doc flow: promise, quick start, first 10 minutes, install paths, then reference and release details.
- Switched release guidance to `release/*` branches and made changelog updates part of the release checklist.
- Refreshed the Link logo.
- Improved first-run and Homebrew/PEP 668 install documentation.
- Narrowed CI trigger noise to pull requests, `main` pushes, and manual dispatch.

### Fixed

- Hardened installers to avoid silently using `--break-system-packages`; they now fall back to `~/.link-mcp-venv` and register MCP with the resolved Python.
- Hardened the local viewer against unsafe graph JSON embedding, path-like wikilink targets, malformed static paths, and local path leakage from static file errors.
- Hardened the local viewer to reject unexpected `Host` headers in addition to binding to `127.0.0.1`.
- Hardened `link-mcp` tool inputs for empty queries/topics and invalid search limits.
- Expanded `doctor` and release hygiene checks for common credential filenames, private keys, and token patterns.

## [1.0.5] - 2026-05-02

### Added

- Added `link.py demo` for a pre-ingested sample wiki.
- Added `link.py doctor` health checks for structure, backlinks, source hygiene, graph integrity, and secret-looking files.
- Added CI release gates for tests, demo health, installer syntax, package build, version consistency, and release hygiene.

### Changed

- Published `link-mcp` 1.0.5 package metadata for PyPI and the MCP Registry.

### Fixed

- Fixed `/api/context` and MCP context handling for the current backlink index shape.
- Fixed markdown rendering so raw HTML and unsafe markdown links cannot execute in the browser.
- Fixed installers so reruns preserve existing user instructions and project installs point MCP at the project wiki.
- Fixed wiki cache invalidation so edits to existing pages refresh search and context.
- Fixed MCP package reinstall behavior so rerunning installers upgrades `link-mcp`.
- Fixed invalid HTTP search limits to return controlled JSON errors.

## Earlier

- `1.0.2` through `1.0.4` were early public MCP packaging and hardening releases. Use `1.0.5` or newer for public installs.
