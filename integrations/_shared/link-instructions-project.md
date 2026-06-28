## Link — Local Agent Memory

This project has a Link wiki. Raw sources live in `raw/`, compiled wiki pages in `wiki/`, and direct memories in `wiki/memories/`.

If you are unsure whether this project Link wiki is ready, use MCP `link_status` when available, or run `python3 link.py health`.

If the user asks what to try after installing Link, use MCP `starter_prompts` when available, or run `python3 link.py next`.

If status reports a missing or old schema marker, use MCP `migrate_wiki` when available, or run `python3 link.py migrate`, before other writes.

When the user asks to ingest or drops files into `raw/`, use MCP `ingest_status` when available, or run `python3 link.py ingest-status`, then follow its guided plan before deciding what to process. If it reports `blocked_secrets` or secret warnings, do not read or ingest flagged raw files until the user redacts them.

When answering a substantive project question, start with MCP `query_link` when available, or run `python3 link.py query "<task or question>" --budget micro`. Read the returned capsule first. Do this before broad file reads, grep/search, or asking the user to repeat project context.

When you only need graph orientation, especially for a large wiki, prefer MCP `get_graph_summary` or `python3 link.py graph-summary "<topic>"` before requesting the full graph.

When starting project-specific work, prime yourself with Link first: use MCP `memory_brief` when available, or run `python3 link.py brief "<task or question>"`. Project installs infer the current repo as the memory project key, so project-scoped memories stay separate from other repos while broad user memories still apply.

Before broad repairs or risky local wiki edits, create a local backup with MCP `backup_wiki` when available, or run `python3 link.py backup`. Do not include `raw/` unless the user explicitly asks.

For long session notes, use `python3 link.py capture-session "<file-or-text>"` to store a local raw capture and produce memory proposals without writing durable memories.
Use MCP `capture_inbox` when available, or `python3 link.py capture-inbox`, to review saved captures, warnings, and next-step commands.
When the human approves a proposal from a capture, use `python3 link.py accept-capture "<raw-capture-path>" --index <n>`.
If a capture reports secret warnings, ask before running `python3 link.py redact-capture "<raw-capture-path>"`.
Only delete a raw capture after explicit confirmation: `python3 link.py delete-capture "<raw-capture-path>" --confirm`.

After ingesting raw sources or making substantial wiki edits, use MCP `rebuild_index`, `rebuild_backlinks`, and `validate_wiki` when available, or run `python3 link.py rebuild-index`, `python3 link.py rebuild-backlinks`, and `python3 link.py validate`, before saying the wiki is updated.

When the user says **"remember"**, **"recall"**, **"ingest"**, **"query"**, **"lint"**, or **"research"**, read `LINK.md` for instructions and follow the protocol.

Otherwise, don't interfere — just be a normal assistant.
