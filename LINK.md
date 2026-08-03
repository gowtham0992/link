# Link — Local Agent Memory

You are the maintainer of local agent memory called **Link**. Your job is to preserve useful user preferences, project context, decisions, and source-backed knowledge in plain Markdown. The wiki is the storage format; durable local memory is the product.

## Architecture

```
link/
├── LINK.md              ← you are here (the schema — your instructions)
├── raw/                 ← immutable source documents (human adds these)
├── wiki/                ← your domain — structured markdown articles
│   ├── index.md         ← master catalog by category
│   ├── _backlinks.json  ← reverse link index (auto-generated)
│   ├── log.md           ← chronological record of all operations
│   ├── sources/         ← one summary page per ingested source
│   ├── concepts/        ← concept/topic articles
│   ├── entities/        ← people, orgs, projects, tools
│   ├── memories/        ← user preferences, decisions, project facts
│   ├── comparisons/     ← side-by-side analyses
│   └── explorations/    ← filed-back query results
├── serve.py             ← local Wikipedia-style web viewer
└── .linkignore          ← files/patterns to skip during ingest
```

### Three layers

1. **raw/** — The human's curated source collection. Articles, papers, images, notes, PDFs, transcripts. These are immutable — you read from them but NEVER modify them. This is the source of truth.

2. **wiki/** — Your domain. You create pages, update them, maintain cross-references, and keep everything consistent. The human reads it; you write it. Every page follows the templates below.

3. **LINK.md** — This file. The schema that tells you how the wiki works. You and the human co-evolve this over time.

## Page Templates

Every wiki page uses YAML frontmatter + consistent markdown structure. Follow these templates exactly.

### Source Page (`wiki/sources/`)

```markdown
---
type: source
title: "Article Title"
author: "Author Name"
date_published: "2026-01-15"
date_ingested: "2026-04-09"
source_url: "https://..."
tags: [machine-learning, attention]
confidence: high
aliases: ["short name", "abbreviation"]
---

# Article Title

> **TLDR:** One-sentence summary of the key takeaway.

## Summary

2-4 paragraph summary of the source. What does it argue? What evidence does it present? What is novel?

## Key Claims

- **Claim 1** — Description. `[confidence: high]`
- **Claim 2** — Description. `[confidence: medium]`
- **Claim 3** — Description. `[confidence: low]`

## Connections

- Related to [[concept-name]] because...
- Contradicts [[other-source]] on the topic of...
- Supports [[another-concept]] with evidence that...

## Raw Source

`raw/filename.md`
```

### Concept Page (`wiki/concepts/`)

```markdown
---
type: concept
title: "Concept Name"
aliases: ["alternate name", "abbreviation"]
date_created: "2026-04-09"
date_updated: "2026-04-09"
source_count: 3
tags: [category-tag]
maturity: seed | growing | mature | established
---

# Concept Name

> **TLDR:** One-sentence definition accessible to a newcomer.

## Overview

2-4 paragraphs explaining the concept. Write like a Wikipedia article — neutral, clear, comprehensive. Cite sources with [[source-page]] links.

## How It Works

Technical explanation if applicable. Use code blocks, diagrams (mermaid), or step-by-step breakdowns as needed.

## Key Facts

- **Fact 1** — Explanation. *Source: [[source-page]]* `[confidence: high]`
- **Fact 2** — Explanation. *Source: [[source-page]]* `[confidence: medium]`

## Open Questions

- Question that hasn't been answered by current sources
- Contradiction between [[source-a]] and [[source-b]] on this topic

## Related

- [[related-concept-1]] — how they connect
- [[related-concept-2]] — how they connect

## Sources

- [[source-page-1]]
- [[source-page-2]]
```

### Entity Page (`wiki/entities/`)

```markdown
---
type: entity
title: "Entity Name"
entity_type: person | organization | project | tool | dataset
aliases: ["alternate name", "abbreviation"]
date_created: "2026-04-09"
date_updated: "2026-04-09"
tags: [relevant-tags]
source_count: 1
maturity: seed | growing | mature | established
---

# Entity Name

> **TLDR:** One-line description of who/what this is.

## Overview

Who or what is this entity? What are they known for? Why do they matter in this wiki's context?

## Key Contributions

- Contribution 1. *Source: [[source-page]]*
- Contribution 2. *Source: [[source-page]]*

## Connections

- Created [[project-name]]
- Works on [[concept-name]]
- Affiliated with [[org-name]]

## Sources

- [[source-page-1]]
```

### Memory Page (`wiki/memories/`)

Use memory pages for durable user preferences, project decisions, stable facts about the user's work, and context agents should recall across sessions. These are directly captured memories, not neutral encyclopedia articles.

```markdown
---
type: memory
title: "Short Memory Title"
memory_type: preference | decision | project | fact | note
scope: user | project | global
visibility: private | project | team
project: "optional-project-slug"
status: active | stale | archived
date_captured: "2026-04-09T14:30:00Z"
updated_at: ""
update_count: 0
source: "manual | conversation | mcp | raw/source.md"
last_update_source: ""
review_status: pending | reviewed | needs_update
review_after: "optional YYYY-MM-DD date for scheduled re-check"
tags: [memory, relevant-tag]
---

# Short Memory Title

> **TLDR:** One sentence explaining what future agents should remember.

## Memory

The durable memory, written clearly enough for a future agent to use without rereading the original chat.

## Use This When

- Situation where this memory should affect future work.
- Another situation where this memory is relevant.

## Source

Where the memory came from and why it is trustworthy.
```

### Comparison Page (`wiki/comparisons/`)

```markdown
---
type: comparison
title: "X vs Y"
date_created: "2026-04-09"
date_updated: "2026-04-09"
subjects: ["X", "Y"]
aliases: ["alternate name"]
tags: [relevant-tags]
source_count: 1
maturity: seed | growing | mature | established
---

# X vs Y

> **TLDR:** One-sentence verdict or key distinction.

## Overview

Why compare these? What decision or understanding does this comparison serve?

## Comparison

| Dimension | X | Y |
|-----------|---|---|
| Aspect 1  | ... | ... |
| Aspect 2  | ... | ... |

## Analysis

Deeper discussion of trade-offs, contexts where each is better, nuances.

## Verdict

When to use X. When to use Y. Or: why the distinction matters.

## Sources

- [[source-page-1]]
```

### Exploration Page (`wiki/explorations/`)

```markdown
---
type: exploration
title: "Question or Analysis Title"
date_created: "2026-04-09"
query: "The original question asked"
aliases: ["alternate phrasing"]
tags: [relevant-tags]
---

# Question or Analysis Title

> **Query:** The original question that prompted this exploration.

## Answer

The synthesized answer, citing wiki pages.

## Reasoning

How the answer was derived. Which pages were consulted. What connections were made.

## Sources Consulted

- [[wiki-page-1]]
- [[wiki-page-2]]
```

## Operations

### 1. Remember

When the human says to remember something, capture it as local memory. Prefer the built-in command when `link.py` is available:

```bash
python3 link.py remember "User prefers release/* branches for Link work." . --type preference --scope project --tags git,release
```

Rules:
- Only save memories the human explicitly asks to remember or confirms should be remembered.
- Keep memories specific and actionable. "User likes quality" is too vague; "User prefers release/* branches over codex/* branches" is useful.
- Use `memory_type: preference` for user preferences, `decision` for choices made, `project` for project context, `fact` for stable facts, and `note` for everything else.
- Use `scope: user` for broad personal preferences, `project` for the current project, and `global` for agent-wide principles.
- Use `visibility: private` for personal memory, `project` for project-team sharing, and `team` only when the human explicitly wants the memory shared across a team workspace. If omitted, Link treats user/global memories as private and project memories as project-visible.
- For `scope: project`, include a project key when you know it. `link.py` infers this from repo-local installs; otherwise pass `--project <slug>` or MCP `project`.
- At the first substantive turn of a session or substantial task, run `python3 link.py brief "<task or question>" .` or MCP `recall` with an empty query when available. Treat this as the default way to prime yourself with local memory, review warnings, and saved raw capture status.
- For long chat/session notes, prefer `python3 link.py capture-session "<file-or-text>" .` or MCP `admin` action `capture_session`; it stores the raw note locally and returns proposal-only memory candidates. If you do not need to keep the raw note, run `python3 link.py propose-memories "<file-or-text>" .` or MCP `admin` action `propose_memories` instead. Do not write proposals until the human confirms.
- Use `python3 link.py capture-inbox .` or MCP `admin` action `capture_inbox` to review saved raw captures, secret warnings, and the exact accept/redact/delete commands before changing capture state.
- When the human approves a captured proposal, run `python3 link.py accept-capture "<raw-capture-path>" . --index <n>` or MCP `admin` action `accept_capture`. If it reports a duplicate or conflict, stop and ask whether to update/archive the existing memory instead.
- If capture results report `secret_warnings`, ask the human whether to redact the raw capture. Use `python3 link.py redact-capture "<raw-capture-path>" .` or MCP `admin` action `redact_capture`; it replaces secret-looking values and logs labels/counts only.
- If the human asks to remove a raw capture, run `python3 link.py delete-capture "<raw-capture-path>" . --confirm` or MCP `admin` action `delete_capture` with `confirm: true`. Never delete captures without explicit confirmation. Deleting a capture records its proposals as dismissed so the same claims are not re-proposed by later sessions.
- If the capture inbox looks repetitive, run `python3 link.py dedup-captures .` or MCP `admin` action `dedup_captures` to preview which captures offer nothing new (already pending, accepted, or dismissed), then re-run with `--confirm`/`confirm: true` only after the human approves the removal.
- Run `python3 link.py recall "<query>" .` before answering questions that might depend on remembered preferences or project decisions.
- Run `python3 link.py memory-audit .` or MCP `review` action `audit` when the human asks what needs attention in Link memory.
- Run `python3 link.py profile .` when the human asks what Link knows or when you need a quick overview of remembered preferences, decisions, and project context.
- Run `python3 link.py memory-inbox .` or MCP `review` action `inbox` to find pending, stale, invalid, or underspecified memories and follow each item's primary action. Pass `--project <slug>` or MCP `project` when reviewing a specific project.
- If `remember` reports a duplicate candidate, inspect it with `python3 link.py explain-memory "<name-or-title>" .` and merge new information with `python3 link.py update-memory "<name-or-title>" "new detail" .` instead of creating another one. Use `--allow-duplicate` only when the human confirms it should be separate.
- If `remember`, `update-memory`, or `propose-memories` reports conflict candidates, stop and ask the human whether the older memory should be updated, archived, or allowed to coexist. Use `--allow-conflict` only when the human confirms both memories are true in different contexts.
- After updating a memory, review it again with the human because `update-memory` resets `review_status` to `pending`.
- After the human confirms a memory is accurate, run `python3 link.py review-memory "<name-or-title>" .`. Reviewing re-arms the memory's trust window (`review_after`): project context stays trusted for 3 months, preferences/notes/procedures for 6, decisions and stable facts for 12.
- Memories past their trust window are labeled `review_due` in the inbox, audit, and explain output. Treat them as provisional: confirm with the human before relying on one for an important decision, then review it to re-arm the window.
- Run `python3 link.py explain-memory "<name-or-title>" .` when the human asks why an agent knows something or whether a memory is safe to use.
- If a memory is stale or wrong, archive it with `python3 link.py archive-memory "<name-or-title>" . --reason "why"`. Do not delete memory pages unless the human explicitly asks for permanent removal.
- Before broad repair work or risky local wiki edits, create a local backup with `python3 link.py backup .` or MCP `admin` action `backup`. Do not include `raw/` unless the human explicitly asks because raw sources and captures can contain sensitive material.
- If the human explicitly asks Link to permanently forget a memory, use `python3 link.py forget-memory "<name-or-title>" . --confirm` or MCP `review` action `forget` with `confirm: true`. Prefer archive when reversible cleanup is enough, and do not create a backup that preserves the memory unless the human explicitly asks for one.
- Restore an archived memory with `python3 link.py restore-memory "<name-or-title>" .`.

### 2. Ingest

When the human adds a new source to `raw/` and asks you to process it:

0. Run `python3 link.py ingest-status .` when `link.py` is available to see pending raw files, current graph state, and the suggested ingest workflow. If it reports `blocked_secrets` or secret warnings, stop and ask the human to redact the flagged raw file before reading or ingesting it.
1. Read the source completely
2. Discuss key takeaways with the human (brief, 3-5 bullet points)
3. Create a source page in `wiki/sources/` following the template
4. For each significant concept, entity, or claim in the source:
   - If a wiki page exists: UPDATE it with new information, add the source to its Sources section, update `date_updated` and `source_count`
   - If no wiki page exists: CREATE one following the appropriate template, set `maturity: seed`
5. Check for contradictions with existing pages — note them in both pages' Open Questions
6. Update `wiki/index.md` with any new pages
7. Append an entry to `wiki/log.md`

**Ingest rules:**
- Every claim must link back to its source page. No orphan claims.
- Tag confidence on claims: `high` (explicitly stated), `medium` (reasonable inference), `low` (speculative)
- Prefer updating existing pages over creating new ones. A concept page that grows from 3 sources is more valuable than 3 thin pages.
- Update the `maturity` field: seed (1 source) → growing (2-3 sources) → mature (4-6 sources) → established (7+ sources)
- After updating a page, re-read it as a whole. If it no longer reads as a coherent article, restructure it before moving on.
- Watch for page bloat: if a sub-topic is growing past 2-3 paragraphs within an article, it likely deserves its own page. Split proactively.
- Conversely, a new page must have enough substance to stand alone. If you cannot write at least a meaningful TLDR + Overview, fold the information into an existing page instead.
- After ingest completes, rebuild `wiki/index.md` and `wiki/_backlinks.json` so both the human catalog and graph index match the pages.
- After rebuilding index/backlinks, run MCP `ingest` action `validate`, `python3 link.py validate .`, or `GET /api/validate` when available. Treat validation errors as blockers before reporting ingest complete.

**Image ingest rules:**
- Images in `raw/` (png, jpg, webp, gif, svg) are valid sources. Use vision to understand what the image IS.
- Create a source page for the image just like any other source. Describe what you see.
- Embed the image in the source page using: `![description](/raw/filename.png)`
- The web viewer serves supported `raw/` image/PDF assets directly, so image paths just work without exposing every raw file type.
- For screenshots: describe the UI, layout, key elements, purpose.
- For diagrams/charts: extract the concepts, relationships, data, and trends.
- For photos of whiteboards/handwriting: transcribe the content, mark uncertain readings `[confidence: low]`.
- For tweets/posts as images: extract the text, author, and key claims.
- Link extracted concepts to existing wiki pages, same as text sources.

### 3. Query

When the human asks a question:

1. If you are connecting to Link for the first time or troubleshooting setup, call MCP `status`, run `python3 link.py status . --validate`, or call `GET /api/status?validate=true`.
2. At the first substantive turn of a session, call MCP `recall` with an empty query or run `python3 link.py brief "session start" .`. This is cheap and prevents asking the user to repeat durable context.
3. If the human asks what to try after installing Link, call MCP `admin` action `prompts`, run `python3 link.py prompts .`, or call `GET /api/prompts`.
4. If status reports a missing or old schema marker, run MCP `admin` action `migrate` when available or `python3 link.py migrate .` before other writes.
5. If the user asks to ingest or says they dropped files into `raw/`, use MCP `ingest`, `python3 link.py ingest-status .`, or `GET /api/ingest-status` to get pending files, the guided ingest plan, and the next prompt/checks. If the state is `blocked_secrets`, do not read or ingest flagged raw files until the human redacts them.
6. Start with the smart query path when available: MCP `recall`, `python3 link.py query "<question>" .`, or `GET /api/query-link?q=<question>`. This returns a compact context packet with relevant memory, ranked wiki results, graph context, provenance, selection reasons, budget reports, and follow-up tool actions. Use provenance fields to explain why Link knows something. Do not read the whole wiki unless the packet is insufficient; if it is budget-limited, use the returned `follow_up` action first.
7. If the question only needs session priming or personal/project preferences, use `python3 link.py brief "<question>" .` or MCP `recall` with `mode=brief`. Use `profile`/`review(action="profile")` and `recall` afterward only when you need deeper detail.
8. **If you need full source-backed context for one topic:** call `GET /api/context?topic=<question>` or MCP `admin` action `context` — returns the best matching page plus related pages via graph traversal.
9. **If you need graph orientation on a large wiki:** use `python3 link.py graph-summary "<topic>" .`, `GET /api/graph-summary?topic=<topic>`, or MCP `admin` action `graph_summary` before requesting the full graph.
10. **If server/MCP is not available:** read `wiki/index.md` to find relevant pages (check `also:` aliases for matches), then check `wiki/_backlinks.json` for pages that reference the topic.
11. Read only the relevant pages or packet items and synthesize an answer.
12. Cite your sources with [[wiki-links]].
13. Ask the human: "Want me to file this?" Answers that are comparisons should file as comparison pages, not explorations. Match the result to the right page type.
14. If yes, create a page in the appropriate directory following its template.
15. Append to `wiki/log.md`.

### 4. Lint

When the human asks you to health-check the wiki (or periodically on your own):

Start with the built-in checker when `link.py` is available:

```bash
python3 link.py doctor .
```

Use `python3 link.py doctor . --fix` only for safe mechanical repairs: creating missing Link directories/files and rebuilding `_backlinks.json`. Do not use it as a substitute for content review.

Run `python3 link.py validate .` after ingest or large page edits. It is stricter about page shape: required frontmatter, directory/type alignment, required sections, dead wikilinks, and stale backlinks.

Treat doctor errors as blockers. Doctor warnings are quality issues to triage with the human. It checks required structure, dead links, stale backlinks, index drift, TLDR/query summaries, Sources sections, `source_count` consistency, isolated graph pages, raw-source coverage, memory review state, raw capture backlog, and secret-looking filenames or file contents.

Run these checks and report findings:

- **Orphan pages** — pages with no inbound links from other pages
- **Dead links** — [[links]] that point to pages that don't exist
- **Stale claims** — claims citing sources with `date_published` more than 2 years old; flag for review
- **Contradictions** — pages that disagree with each other (check Open Questions sections for flagged contradictions)
- **Thin pages** — concept pages with only 1 source (maturity: seed) that could be enriched
- **Missing pages** — concepts frequently mentioned but lacking their own page
- **Index drift** — pages that exist but aren't listed in index.md
- **Confidence gaps** — claims without `[confidence: high/medium/low]` tags
- **Bloated pages** — articles over 100 lines that should be split into focused sub-pages
- **Misclassified pages** — pages in the wrong directory (e.g., a person in concepts/, a tool in entities/)
- **Unlinked references** — entities or concepts mentioned repeatedly across articles but never given a `[[wikilink]]`
- **Backlink orphans** — pages that link out but are never linked to by anything else

For each finding, suggest a specific action. Then ask the human which ones to execute.

Create a local backup before broad repairs with `python3 link.py backup .` or MCP `admin` action `backup`. Rebuild `wiki/index.md` and `wiki/_backlinks.json` after executing fixes. Prefer `python3 link.py rebuild-index .` and `python3 link.py rebuild-backlinks .` when `link.py` is available, or MCP `ingest` action `rebuild` when using the slim surface; otherwise call `POST /api/rebuild-index` and `POST /api/rebuild-backlinks` with JSON `{}` on the local server or rebuild manually. Append lint results to `wiki/log.md`.


### 5. Research

When the human wants to find or capture new source material for the wiki. Research has three modes based on where the material comes from.

**`research <topic>`** — Web discovery

1. Search the web for the given topic
2. Find 5-8 candidate sources (articles, docs, papers, posts)
3. Present each with: title, URL, 2-3 sentence summary, and relevance to existing wiki pages
4. The human picks which ones to keep
5. For each approved source, save to `raw/` as a markdown file with the content and metadata (title, author, URL, date)
6. Do NOT auto-ingest. The human decides when to run ingest on the new material.

**`research chat`** — Conversation capture

1. Review the current conversation for key insights, decisions, ideas, or knowledge worth preserving
2. Present a summary of what would be captured (bullet points)
3. If the human approves, save as `raw/conversation-{topic}-{date}.md` with frontmatter:
   - `title`: descriptive name for the conversation topic
   - `source_type: conversation`
   - `date_captured`: today's date
   - `participants`: human + AI
4. The file should synthesize the conversation's substance, not dump raw chat logs. Extract the knowledge, not the back-and-forth.
5. Do NOT auto-ingest. Tell the human the file is ready for ingest when they want.

**`research wiki`** — Gap analysis

1. Read `wiki/index.md` and `wiki/_backlinks.json`
2. Identify:
   - Thin pages (maturity: seed) that need more sources
   - Concepts mentioned across multiple pages but lacking depth
   - Topics adjacent to existing pages that the wiki doesn't cover yet
   - Open Questions from existing pages that could be answered with more research
3. Present a prioritized list of suggested research topics, each with:
   - The topic
   - Why it matters (which pages would benefit)
   - Suggested search terms for `research <topic>`
4. The human picks which ones to pursue. Then use `research <topic>` for each.

**Research rules:**
- Research proposes, the human approves. Nothing enters `raw/` without human confirmation.
- Every file saved to `raw/` must have clear attribution: where it came from, when, who wrote it.
- Conversation captures should be substantive. If a chat was just "fix this bug," there's nothing to capture.
- Web sources must include the original URL. No orphan sources.
- Append research operations to `wiki/log.md`.

## Index Structure (`wiki/index.md`)

```markdown
# Link Wiki Index

> Last updated: 2026-04-09 | 42 pages | 15 sources

## Categories

### Category A
- [[example-concept]] — One-line summary of the concept. mature · 6 sources · also: alt-name, abbreviation
- [[another-concept]] — One-line summary. growing · 3 sources · also: alt-name

### Category B
- [[example-person]] — One-line description. growing · 4 sources

### memories
- [[example-preference]] — One-line memory summary. preference · user

### Category C
- [[example-project]] — One-line description. seed · 1 source

## Recent

| Date | Operation | Pages Touched |
|------|-----------|---------------|
| 2026-04-09 | ingest: "Example Source Title" | 8 pages |
| 2026-04-08 | query: "Example question?" | 1 page |
```

Organize by tags/categories. Each entry gets a one-line summary (from the page's TLDR), maturity, and source count. Include `also:` values populated from each page's `aliases` frontmatter field so queries can match alternate names. Include a Recent table showing the last 10 operations.

## Log Structure (`wiki/log.md`)

Append-only. Never rewrite history. Each entry starts with `## [timestamp] operation | description` so the log is parseable with simple tools like `grep "^## \[" log.md | tail -5`.

```markdown
## [2026-04-09T14:30:00Z] ingest | "Example Source Title"

- Source: raw/example-source.md
- Created: sources/example-source.md
- Created: concepts/example-concept.md
- Updated: concepts/another-concept.md (added new section from source)
- Updated: entities/example-entity.md (added contribution from source)
- Updated: index.md
- Pages touched: 6

---

## [2026-04-09T15:00:00Z] query | "Example question about a concept?"

- Pages consulted: concepts/example-concept.md, sources/example-source.md
- Filed as: explorations/example-exploration.md

---

## [2026-04-09T16:00:00Z] lint | health check

- Found: 3 orphan pages, 1 dead link, 2 thin pages
- Actions taken: linked orphans, removed dead link, flagged thin pages for enrichment

---
```

## Conventions

- **File naming:** lowercase, hyphens, no spaces. `example-concept.md` not `Example Concept.md`
- **Wiki links:** use `[[page-name]]` syntax (Obsidian-compatible). Link to the filename without extension.
- **Confidence tags:** `[confidence: high]`, `[confidence: medium]`, `[confidence: low]` — inline after claims
- **Maturity:** tracked in frontmatter. seed → growing → mature → established
- **Dates:** ISO 8601 format. `2026-04-09` for dates, `2026-04-09T14:30:00Z` for timestamps
- **TLDR:** Every page starts with a one-sentence TLDR after the title. This helps both humans scanning and LLMs doing index scans.
- **Aliases:** all page types should include an `aliases` field in frontmatter for alternate names, abbreviations, or common phrasings. These power index matching and query resolution.
- **No hallucination:** If you don't have a source for a claim, don't write it. Use Open Questions for gaps.
- **Idempotent ingest:** Ingesting the same source twice should not duplicate content or corrupt the wiki.
- **Obsidian-compatible:** the wiki is designed to be browsable in Obsidian. `[[wikilinks]]`, YAML frontmatter, and the directory structure all work natively. Graph view shows connections; Dataview can query frontmatter fields. The wiki is also just a git repo of markdown files — version history comes free.

## Writing Standards

Articles should serve understanding, not archival. Write to explain, not to file.

**Voice:**
- Wikipedia-neutral. Flat, factual, encyclopedic. Let the sources carry the weight.
- Paraphrase over block quotes. Use direct quotes only when the original phrasing is the point.
- Concrete language over abstract. "Reduces latency by 40%" over "significantly improves performance."
- Short sentences for claims. Longer sentences for context and connections.
- Active voice. "The system extracts metrics" not "metrics are extracted by the system."

**Avoid:**
- Peacock words: "legendary," "groundbreaking," "visionary," "revolutionary"
- Editorial voice: "interestingly," "importantly," "it should be noted," "notably"
- Rhetorical questions as structure
- Qualifiers that add nothing: "truly," "genuinely," "really," "deeply"
- Progressive narrative: "would go on to," "embarked on a journey," "set out to"
- Hedging without reason: "it seems like," "one could argue" — either state the claim with a confidence tag or put it in Open Questions

**Page balance:**
- A page should be dense enough to be worth reading, but focused enough to have a clear subject. If a page tries to cover two distinct ideas, split it.
- Seed pages are fine — but even a seed should have a real TLDR and a meaningful Overview, not just a stub sentence.
- If a sub-topic within a page grows past 2-3 paragraphs, it probably deserves its own page.
- If you can't write more than a TLDR for something, fold it into the parent page as a mention and create the page later when more material arrives.

## Backlinks (`wiki/_backlinks.json`)

A reverse link index mapping each page to the set of pages that link to it. Also includes forward links. Auto-generated after every ingest and lint operation by scanning all `[[wikilinks]]` across the wiki.

Structure (current format):
```json
{
  "backlinks": {
    "example-concept": ["another-concept", "example-entity", "example-source"]
  },
  "forward": {
    "another-concept": ["example-concept", "related-concept"]
  }
}
```

Used during query to find related pages, and during lint to detect orphans and backlink imbalances.

**Rebuilding:** Run `python3 link.py rebuild-index .` and `python3 link.py rebuild-backlinks .` when `link.py` is available. Otherwise call `POST /api/rebuild-index` and `POST /api/rebuild-backlinks` with JSON `{}` on the local server (if running), or rebuild manually. Always rebuild both after ingest and lint.

## Local Server API

`serve.py` exposes a local HTTP API at `http://127.0.0.1:3000`:

| Endpoint | Description |
|----------|-------------|
| `GET /api/page-list?limit=100&offset=0` | Bounded page metadata list for agents and large wikis, with follow-up pagination actions |
| `GET /api/pages` | Full page metadata list for local UI/export use |
| `GET /api/status?validate=true` | Readiness summary with page/memory counts, optional validation summary, and safe next actions |
| `GET /api/ingest-status` | Raw ingest state with pending files, represented-source completion cards, safety summary, graph health, and next prompts/checks |
| `GET /api/memory-brief?q=<task>&project=<slug>` | Startup memory context: relevant memories, review warnings, capture status, and safe rules |
| `POST /api/raw-source` | Header `X-Link-Local-Action: true`; save pasted source text under `raw/`, reject secret-looking values, and return the next ingest prompt |
| `POST /api/propose-memories` | Propose memories from JSON `{ "text": "..." }` without writing pages |
| `POST /api/review-memory` | Header `X-Link-Local-Action: true`; JSON `{ "memory": "name", "note": "optional" }`; mark a memory reviewed |
| `POST /api/archive-memory` | Header `X-Link-Local-Action: true`; JSON `{ "memory": "name", "reason": "optional" }`; archive a memory from default recall |
| `POST /api/restore-memory` | Header `X-Link-Local-Action: true`; JSON `{ "memory": "name" }`; restore archived memory to active recall |
| `GET /api/capture-inbox?project=<slug>` | Saved raw captures with redacted snippets, warnings, and commands |
| `GET /api/search?q=<query>` | Ranked search — title, alias, tag, fulltext. Returns scores + snippets |
| `GET /api/context?topic=<topic>` | Best matching page + inbound/forward links in one call |
| `GET /api/graph-summary?topic=<topic>&limit=40&depth=1` | Bounded graph overview or topic neighborhood for agents and large wikis |
| `GET /api/graph` | All nodes + edges for graph visualization/export |
| `GET /api/page-links?page=<name>&limit=100&offset=0` | Bounded inbound/forward links for one page, with follow-up pagination actions |
| `GET /api/backlinks` | Reverse link index |
| `POST /api/rebuild-index` | JSON `{}`; regenerate `wiki/index.md` from current pages |
| `POST /api/rebuild-backlinks` | JSON `{}`; rebuild `_backlinks.json` by scanning all wikilinks |
| `GET /api/validate?strict=true` | Validate generated wiki pages; failed gates return HTTP 422 with structured findings |

During query operations, prefer `/api/context?topic=X` over reading files manually — it returns the primary page plus all related pages via graph traversal in one call.

## Scaling

The search and graph infrastructure is built-in and scales without external tools:

- **Search:** in-memory inverted token index built at server startup. O(1) per query. Sub-millisecond at any wiki size. Use `/api/search?q=<query>` instead of reading index.md.
- **Graph traversal:** `/api/context?topic=X` returns a page + its full graph neighborhood in one call. Agents don't need to read the entire index.
- **Backlinks:** `_backlinks.json` stores both reverse and forward links. Rebuilt automatically after ingest and lint.

At very large scale (1000+ pages), consider adding an MCP server wrapper around the API endpoints so agents can call them as native tools without HTTP.

## Getting Started

If the wiki is empty, start here:

1. Human drops first source into `raw/`
2. Human says: "ingest this"
3. You read it, create source page + concept/entity pages, build initial index and log
4. Wiki grows from there — use **query** to ask questions, **lint** to health-check, **research** to find new sources

If the wiki already exists, read `wiki/index.md` and `wiki/log.md` first to understand current state before doing anything.

To verify MCP access, run `python3 link.py verify-mcp .` when `link.py` is available. It checks whether `link_mcp` imports in the configured Python and prints the MCP client config for the current wiki.

## Memory Maintenance

- **Session hooks.** Agents with hook support (Claude Code, Codex, Cursor) can install Link session hooks (`python3 link.py connect <agent> . --hooks --write`): the memory brief is injected automatically at session start and proposal-only session notes are stored at session end. Durable memory always requires review.
- **Consolidation.** When briefs report a memory backlog (pending captures or reviews above threshold), run `python3 link.py consolidate .` (or MCP `review(action="consolidate")`) for a read-only plan with accept/discard/review commands. Apply actions only after the user approves each one.
- **Recipes (procedural memory).** Save reusable how-to memory with `--type procedure` and a `--trigger` phrase describing when it applies (for example: `python3 link.py remember "1. ..." . --type procedure --trigger "cutting a release"`). Recall returns procedures with their steps when a task matches the trigger. Session-end proposals detect numbered step sequences automatically; saving still requires approval.
- **Supersession and temporal recall.** Replace an outdated memory with `python3 link.py remember "<new>" . --supersedes <old-name>`: the predecessor is archived with `superseded_by` lineage, `explain-memory` walks the whole chain, and `recall --as-of YYYY-MM-DD` reconstructs what was active on a past date from lifecycle fields — no graph database.
- **Conditional memory.** Scope situational memories with `applies_when` conditions (`project:<slug>`, `path:<glob>`, `task:<phrase>`; OR semantics). Recall demotes and labels out-of-context matches (`applicability: out_of_context`), and startup briefs exclude them entirely, so one project's conventions never leak into another.
- **Semantic recall (optional, local).** With `link-mcp[semantic]` or `link-mcp[semantic-quality]` installed and a one-time `python3 link.py semantic . --setup`, recall also finds paraphrases. Recalled memories then carry `match: lexical|semantic|hybrid`; treat semantic-only matches as hints to verify, not facts.
