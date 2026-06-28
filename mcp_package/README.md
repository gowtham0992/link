# link-mcp

<!-- mcp-name: io.github.gowtham0992/link -->

MCP server for [Link](https://github.com/gowtham0992/link), local personal memory for agents. Exposes memories and wiki context as MCP tools so agents can recall preferences, decisions, project context, sources, and graph neighborhoods without reading files directly.

Listed on the [official MCP Registry](https://registry.modelcontextprotocol.io) as `io.github.gowtham0992/link`.

Release notes: [CHANGELOG.md](https://github.com/gowtham0992/link/blob/main/CHANGELOG.md)

## What You Need

`link-mcp` is the MCP server. It needs a Link wiki to read from. The normal
wiki location is `~/link/wiki`, created by the main Link installers.

Recommended setup:

```bash
git clone https://github.com/gowtham0992/link.git
bash link/integrations/codex/install.sh   # or claude-code, cursor, kiro, vscode
```

The installer scaffolds `~/link/`, installs or upgrades `link-mcp`, writes agent
instructions, and prints the exact MCP config for your machine.

If Link is already installed and you only need to wire MCP into an agent, use
the CLI helper from the main Link package:

```bash
link connect codex ~/link
link connect codex ~/link --write
link verify-mcp ~/link
```

After install, ask your agent:

```text
is Link ready?
brief me from Link before we continue
query Link for what you know about this project
```

## MCP-Only Install

Use this when you already have a Link wiki and only need the MCP package.

```bash
python3 -m pip install --upgrade link-mcp
```

If macOS/Homebrew Python reports `externally-managed-environment`, use a
dedicated venv:

```bash
python3 -m venv ~/.link-mcp-venv
~/.link-mcp-venv/bin/python -m pip install --upgrade pip link-mcp
```

On Windows, use a venv and configure your MCP client with that Python:

```powershell
py -m venv .link-mcp-venv
.\.link-mcp-venv\Scripts\python -m pip install --upgrade pip link-mcp
```

Then add the server to your MCP client config. Use an absolute wiki path:

```json
{
  "mcpServers": {
    "link": {
      "command": "python3",
      "args": ["-m", "link_mcp", "--wiki", "/Users/YOU/link/wiki", "--surface", "slim"]
    }
  }
}
```

If you installed into the venv, use the venv Python:

```json
{
  "mcpServers": {
    "link": {
      "command": "/Users/YOU/.link-mcp-venv/bin/python",
      "args": ["-m", "link_mcp", "--wiki", "/Users/YOU/link/wiki", "--surface", "slim"]
    }
  }
}
```

Replace `/Users/YOU` with your absolute home path. The default wiki is
`~/link/wiki/`; override with `--wiki /path/to/wiki`. `--surface slim` is the
recommended LLM-native surface for most agents. Use `--surface full` only when
an older integration or a power-user workflow needs every individual tool.

## Agent Workflow

### Slim Surface

New MCP configs should expose Link through six model-facing tools:

1. `status(include_validation?)` checks readiness and safe next actions.
2. `recall(query, budget?, project?, mode?, limit?)` is the one read tool for
   briefs, answer-ready context packets, wiki search, and graph context.
3. `remember(text, ...)` writes only explicit user-approved durable memories.
4. `ingest(action?, strict?)` checks or validates raw-source ingest work.
5. `review(action?, ...)` handles memory inbox, profile, audit, log, explain,
   archive, restore, forget, and visibility review workflows.
6. `admin(action, arguments?)` is the escape hatch for backup, migrate,
   validate, graph export, pages, captures, rebuilds, and advanced updates.

Link also exposes MCP prompts `link_brief`, `link_remember`, `link_ingest`, and
`link_review`, plus resources `link://health`, `link://brief`,
`link://profile`, and `link://project` for clients that support prompt/resource
attachment.

### Full Compatibility Surface

Most agents should call:

1. `link_status(include_validation=true)` when connecting or troubleshooting.
2. `link_operations()` if status reports pending, failed, or interrupted writes.
3. `starter_prompts()` when the user asks what to try after install.
4. `memory_brief(query="<current task>")` before personalized or project work.
5. `query_link(query="<question>", budget="small")` for compact answer-ready context.
6. `ingest_status()` when the user drops files into `raw/`.
7. `validate_wiki(strict=true)` after ingest or large edits.

Use `remember_memory` only when the user explicitly approves saving durable
memory. Add `review_after` for memories that should return to the review inbox
after a date, or `expires_at` for temporary context that should leave default
recall after a date. Use `propose_memories` or `capture_session` for proposal-only review.
For local CLI setup checks, `link verify-mcp --json` returns structured
`issues` and `next_actions` that agents and scripts can consume without parsing
terminal text.
In the local web proposal picker, unreadable raw files are surfaced as
`Fix access` instead of being loaded as empty proposal text.

## Privacy and Scale

- Local-first: `link-mcp` reads the wiki path you configure and does not call
  external APIs, send telemetry, or require API keys.
- Bounded by default: `query_link`, `get_pages`, `get_backlinks`, and
  `get_graph_summary` are designed for agent context budgets so large wikis do
  not have to be dumped into a chat.
- Large-wiki search uses in-memory SQLite FTS when Python provides it, with a
  token-index fallback when FTS is unavailable.
- Use `get_graph_summary` before `get_graph` unless the user explicitly needs a
  full graph export.

## Tools

| Tool | Description |
|------|-------------|
| `link_status(include_validation?)` | Readiness summary with package version, wiki path, content/page/memory counts, optional validation summary, warnings, and safe next actions. |
| `link_operations(limit?)` | Inspect pending, failed, or interrupted local Link write operations with safe next actions. |
| `starter_prompts(project?)` | First-run natural agent prompts plus local readiness/check commands. |
| `migrate_wiki()` | Apply safe, idempotent wiki schema migrations when `link_status` reports a missing or old schema marker. |
| `ingest_status()` | Raw source ingest state with pending files, graph health, raw safety/access diagnostics, the next agent prompt, guided plan, and follow-up checks. |
| `query_link(query, budget?, project?)` | Build a compact answer-ready packet from local memory, ranked wiki search, graph-neighborhood context, provenance, budget reports with estimated packet size, and follow-up actions. |
| `validate_wiki(strict?)` | Validate agent-generated wiki pages after ingest or large edits: frontmatter, type/directory alignment, required sections, dead links, and backlink freshness. |
| `backup_wiki(label?, include_raw?, list_only?)` | Create or list local `.link-backups/` archives before broad repairs or risky wiki edits; raw sources are excluded by default. |
| `memory_brief(query?, limit?, project?)` | Prime the agent before answering or coding with profile counts, relevant memories, review warnings, and safe memory rules. |
| `memory_audit(limit?, project?)` | Read-only health report for memory review backlog, saved raw captures, risk factors, and next actions. |
| `memory_profile(limit?, project?)` | Summarize what Link remembers by type, scope, status, recency, preferences, decisions, and project context. |
| `memory_inbox(limit?, include_archived?)` | List memories that need user review, cleanup, or stronger metadata with primary actions and tool-call hints. |
| `memory_log(limit?, include_captures?)` | List recent memory lifecycle changes from `wiki/log.md` without raw source or memory bodies. |
| `memory_wins(limit?, project?)` | Summarize local proof signals for what Link memory is carrying without telemetry. |
| `review_memory(identifier, note?)` | Mark a confirmed memory as reviewed. |
| `explain_memory(identifier)` | Explain provenance, lifecycle, graph links, review issues, and recall readiness for one memory. |
| `recall_memory(query, limit?, include_archived?, project?)` | Search durable local memories for preferences, decisions, and project context. |
| `remember_memory(memory, title?, memory_type?, scope?, tags?, source?, allow_duplicate?, allow_conflict?, project?, visibility?, review_after?, expires_at?)` | Save an explicit user-approved local memory under `wiki/memories/`; strong duplicates and likely conflicts require explicit override. `visibility` accepts `private`, `project`, or `team` sharing intent. `review_after` accepts `YYYY-MM-DD` for scheduled re-checks; `expires_at` accepts `YYYY-MM-DD` for temporary memories that should leave default recall. |
| `propose_memories(text, source?, limit?, project?)` | Propose durable memories from chat/session notes without writing them. |
| `capture_session(text, title?, source?, limit?, project?)` | Save long chat/session notes under `raw/memory-captures/` and return proposal-only memory candidates plus secret-looking content warnings. |
| `capture_inbox(limit?, project?)` | Review saved raw captures with redacted snippets, secret-warning labels, and accept/redact/delete commands. |
| `accept_capture(capture, index?, title?, memory_type?, scope?, visibility?, tags?, project?, allow_duplicate?, allow_conflict?)` | Accept one proposal from a saved raw capture using duplicate/conflict-safe memory writes. |
| `redact_capture(capture, replacement?)` | Redact secret-looking values from a saved raw capture after user approval. |
| `delete_capture(capture, confirm?)` | Delete a saved raw capture after explicit confirmation. |
| `update_memory(identifier, memory, source?, allow_conflict?, project?)` | Merge new information into an existing memory, blocking likely conflicts with other active memories by default. |
| `set_memory_visibility(identifier, visibility)` | Change a memory's sharing intent between `private`, `project`, and `team` after explicit user approval. |
| `archive_memory(identifier, reason?)` | Archive stale or wrong memory without deleting the Markdown page. |
| `restore_memory(identifier)` | Restore archived memory to active status. |
| `forget_memory(identifier, confirm?)` | Permanently delete a memory only after explicit user confirmation; prefer archive for reversible cleanup. |
| `search_wiki(query, limit?)` | Ranked search — title (20pts), alias (8pts), tag (5pts), fulltext (2pts). Returns scores + snippets. |
| `get_context(topic)` | **Primary tool.** Best matching page (full content) + inbound/forward graph links in one call. |
| `get_pages(category?, type?, maturity?, limit?, offset?, include_all?)` | Bounded page metadata list with filters and follow-up pagination actions; set `include_all=true` only for explicit full metadata export. |
| `get_backlinks(page_name, limit?, offset?, include_all?)` | Bounded inbound + forward links for a page, with total counts and follow-up pagination actions. |
| `get_graph_summary(topic?, limit?, depth?, max_edges?)` | Bounded graph overview or topic neighborhood for large wikis and agent context budgets. |
| `get_graph()` | Full graph export with all nodes + edges; prefer `get_graph_summary` first on large wikis. |
| `rebuild_index()` | Regenerate `wiki/index.md` from current pages so the human-readable catalog stays complete. |
| `rebuild_backlinks()` | Rebuild `_backlinks.json` after ingest or lint. |

Use `link_status` when connecting to Link or troubleshooting setup; if status reports pending, failed, or interrupted writes, call `link_operations` before attempting repair. If the user asks what to try after install, call `starter_prompts`. If status reports a missing or old schema marker, call `migrate_wiki` before other writes. Use `ingest_status` when the user drops files into `raw/` or asks what still needs ingest; if it returns `blocked_secrets`, `blocked_raw_access`, `blocked_source_access`, scan warnings, or secret warnings, do not read or ingest flagged raw files until the user redacts them, fixes local file access, or repairs unreadable source pages. Start with `query_link` for substantive questions that may need both local memory and wiki context. Use each item provenance to explain why Link knows something; if `budget_report` says context was truncated, use the returned `follow_up` action before scanning files manually. Use `memory_brief`, passing the user's task as `query` when available, at session start or before personalized/project work. Pass `project` for repo-specific work so Link returns broad user/global memory plus that project's memory, while keeping other explicit projects out of recall and duplicate/conflict checks. After ingesting sources or substantially editing wiki pages, call `rebuild_index`, `rebuild_backlinks`, then `validate_wiki`, before saying the wiki is updated. Use `backup_wiki` before broad repairs or risky local wiki edits; raw sources are excluded unless the user explicitly asks to include them. Use `memory_profile` to inspect the user/project memory shape, `memory_audit` to see review/capture risks, `memory_inbox` to find memories needing human review and the primary action for each item, `memory_log` to see recent memory lifecycle changes without raw bodies, `memory_wins` to summarize local proof signals without telemetry, `explain_memory` to audit why a memory exists, then `recall_memory` for focused preferences, decisions, and project context. Use `capture_session` for long chat/session notes that should be preserved locally before approval; use `propose_memories` when no raw capture is needed. Both return candidates only. Use `capture_inbox` to review saved captures before accepting, redacting, or deleting them. If `capture_session` reports secret warnings, ask before calling `redact_capture`. Use `accept_capture` only after the user approves one captured proposal. Use `delete_capture` only after explicit user confirmation. If `remember_memory` or `accept_capture` returns duplicate candidates, use `update_memory` on the existing memory unless the user confirms a separate memory. If it returns conflict candidates, ask the user whether to update or archive the older memory before forcing a conflict. Use `archive_memory`, not deletion, when a memory is stale or wrong. Use `forget_memory` only when the user explicitly asks for permanent deletion. Use `get_context` when you need the full primary source page after `query_link` shows it is relevant. Use `get_graph_summary` before `get_graph` when the wiki may be large or the agent only needs graph orientation.
Web approval APIs keep the safe path only: duplicate/conflict overrides should
go through CLI or MCP after explicit human review.

## Wiki location

Default: `~/link/wiki/`. Override with `--wiki /path/to/wiki`.

## Requirements

- Python 3.10+
- A Link wiki (scaffolded by `install.sh`)
