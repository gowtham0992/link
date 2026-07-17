# Link Architecture

The map a new maintainer needs before touching anything. For what Link *is*,
read the [README](README.md); this is how it works and where things live.

## The one-paragraph version

Link is a local memory layer for AI agents. A **workspace** (default
`~/link`) holds immutable raw sources (`raw/`), an agent-compiled Markdown
wiki (`wiki/`), and reviewed **memory pages** (`wiki/memories/*.md` — plain
Markdown with YAML frontmatter). Four surfaces read and write it through one
shared core: the CLI (`link.py`), the MCP server (`mcp_package/link_mcp/`),
agent session hooks, and a local read-only web viewer (`serve.py`). Nothing
durable is written without user approval, no LLM runs inside the memory
layer, and the runtime never touches the network.

## Components

```
link.py                     CLI shell: arg wiring, output rendering, hooks entry
serve.py                    local web viewer (127.0.0.1 only; --host refused)
mcp_package/
  link_core/                ALL shared logic lives here
    memory.py               memory model: write path, recall ranking, review,
                            conflicts/duplicates/echo, supersedes, applies_when
    semantic.py             optional local embeddings + rerank tier (offline-only)
    capture.py              raw session captures + proposal accept flow
    agent_hooks.py          session-hook config writing + transcript extraction
    consolidate.py          read-only backlog plans, duplicate/theme clustering
    project_seed.py         source-backed project seeding, ADR decision mining
    cli_parser.py           argparse tree + grouped help + dispatch
    cli_memory.py, cli_runtime.py   CLI rendering helpers
    web_*.py                viewer page builders (server-rendered HTML strings)
    mcp_verify.py           MCP config generation + `lnk`-vs-path command display
  link_mcp/server.py        MCP tool surface (slim = canonical, full = compat)
scripts/                    benchmarks (recall, LoCoMo, hygiene), release prep,
                            CI guards (see Guards below)
docs/                       public site, served from main branch by GitHub Pages
```

`link.py` and `serve.py` are intentionally standalone-runnable (a workspace
carries copies so `python3 link.py` works with zero installs); the
`check_runtime_duplication.py` guard keeps root and package logic from
drifting apart.

## The data model

A memory page's frontmatter is the whole schema — there is no database:

- `memory_type` (preference | decision | project | fact | note | procedure),
  `scope` (user | project | global), `visibility` (private | project | team)
- lifecycle: `status` (active | archived | stale), `date_captured`,
  `review_status`/`reviewed_at`, `review_after`, `expires_at`,
  `archived_at` + `archive_reason`
- 1.7 fields, one rule of thumb: **finding it** → `trigger` (recipes),
  **fencing it** → `applies_when` (`project:` / `path:` / `task:`,
  OR semantics, fail-closed on bad syntax), **replacing it** →
  `supersedes`/`superseded_by` (lineage chain), plus retrieval `context`
  (text that helps recall find a memory but is never part of its claim)

`raw/` is user-owned and immutable; `wiki/` pages are agent-compiled and
source-linked; `.link-cache/` holds derived state only (semantic index as
plain JSON, hook dedup fingerprints) and is always safe to delete.

## The two write paths (both review-gated)

1. **Explicit** — `remember` (CLI or MCP): conflict detection runs first
   (negation-XOR, option groups, revision-shape rule on head-claim tokens),
   then duplicate detection; a conflicting write is refused with a
   paste-ready `--supersedes` resolution; supersession archives the
   predecessor with lineage inside one operation journal entry.
2. **Automatic** — session-end hooks: transcript text is extracted with
   Link's own injected output dropped (echo guard layer 1), proposals are
   mined **from user turns only**, proposals restating existing memories are
   dropped (echo layer 2, core-claim containment), trivial and duplicate
   sessions are skipped, and everything lands as a *proposal-only capture*
   awaiting `accept-capture`. Nothing durable happens without approval.

## The recall pipeline

Query → field-weighted lexical scoring (title/tldr+trigger/tags/body+context)
→ optional semantic similarity from a local embedding model, merged by
*standout* (z-score vs the corpus, never raw cosine thresholds; semantic-only
matches capped at moderate confidence) → rank boosts (project affinity,
temporal, applicability match) with out-of-context conditional memories
demoted and labeled → optional rerank tier (local cross-encoder blended via
reciprocal-rank fusion over the top 50; explicit recall only, hooks never pay
the latency). Results carry honest labels: `match` (lexical/semantic/hybrid),
`confidence`, `applicability`, `rerank`. `--as-of DATE` reconstructs what was
active on a past date from lifecycle fields alone.

Measured behavior lives in `benchmarks/RESULTS.md` — including the
experiments that failed. Keep it that way.

## Invariants (the things you must not break)

1. **Review-gated writes**: no code path may create durable memory without
   explicit user approval. Automatic paths produce proposals only.
2. **No LLM in the memory layer**: extraction, recall, dedup, conflicts are
   deterministic. LLMs are consumers, never components.
3. **Offline runtime**: models load with the offline guard; only explicit
   `--setup` may download. CI greps the runtime for outbound-network code
   and the tests must pass with sockets blocked.
4. **Claims stay clean**: echo/duplicate/conflict checks compare
   `memory_claim_text` (title + TLDR + Memory section) — never retrieval
   `context`, never template boilerplate.
5. **Plain files**: every state change must remain legible as a Markdown
   diff. If a feature needs a database, redesign the feature.

## Guards and gates (run before every push)

```
python3 -m pytest tests -q                    # includes benchmark regression gates
python3 scripts/check_release_hygiene.py      # secrets + outbound-network scan
python3 scripts/check_runtime_duplication.py  # root vs package drift
python3 scripts/check_tool_contract.py        # MCP surface contract
uvx ruff check .
```

CI (`.github/workflows/ci.yml`) runs on pull requests: Linux 3.10/3.12/3.14,
Windows, package build + twine + wheel install + MCP stdio smoke, installer
syntax, large-wiki smoke.

## Adding things

- **New CLI command**: subparser in `cli_parser.py`, handler in `link.py`,
  dispatch entry in `main()`, a group in `COMMAND_GROUPS` (guard test fails
  if you forget), tests in `tests/test_link_cli.py`.
- **New memory field**: frontmatter write in `write_memory_page`, read in
  `memory_record_from_page`, decide its role against the field rule above,
  keep it out of `memory_claim_text` unless it *is* claim.
- **New MCP tool/param**: `server.py` slim surface first;
  `check_tool_contract.py` must stay green; document in the instructions
  resource.
- **Release**: `scripts/prepare_release.py <version>` on develop → PR to
  main → tag → PyPI → mcp-publisher → Homebrew tap bump
  (gowtham0992/homebrew-link). The script prints the full runbook.
