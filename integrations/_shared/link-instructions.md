## Link — Local Agent Memory

Local agent memory lives at `~/link/`. It has raw sources in `~/link/raw/`, compiled wiki pages in `~/link/wiki/`, and direct memories in `~/link/wiki/memories/`.

If you are unsure whether Link is ready, use MCP `link_status` when available, or run `lnk health`.

If the user asks what to try after installing Link, use MCP `starter_prompts` when available, or run `lnk next`.

If status reports a missing or old schema marker, use MCP `migrate_wiki` when available, or run `lnk migrate`, before other writes.

When the user asks to ingest or drops files into `raw/`, use MCP `ingest_status` when available, or run `lnk ingest-status`, then follow its guided plan before deciding what to process. If it reports `blocked_secrets` or secret warnings, do not read or ingest flagged raw files until the user redacts them.

When answering a substantive question that may need local memory or wiki context, start with MCP `query_link` when available, or run `lnk query "<task or question>"`.

When you only need graph orientation, especially for a large wiki, prefer MCP `get_graph_summary` or `lnk graph-summary "<topic>"` before requesting the full graph.

When starting personalized or project-specific work, prime yourself with Link first: use MCP `memory_brief` when available, or run `lnk brief "<task or question>"`.

Before broad repairs or risky local wiki edits, create a local backup with MCP `backup_wiki` when available, or run `lnk backup`. Do not include `raw/` unless the user explicitly asks.

After ingesting raw sources or making substantial wiki edits, use MCP `rebuild_index`, `rebuild_backlinks`, and `validate_wiki` when available, or run `lnk rebuild-index`, `lnk rebuild-backlinks`, and `lnk validate`, before saying the wiki is updated.

When the user says **"remember"**, **"recall"**, **"ingest"**, **"query"**, **"lint"**, or **"research"**, read `~/link/LINK.md` for instructions and follow the protocol. Use terminal commands to access `~/link/` since it's outside the workspace.

Otherwise, don't interfere — just be a normal assistant.
