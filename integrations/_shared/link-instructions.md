## Link — Local Agent Memory

Local agent memory lives at `~/link/`. It has raw sources in `~/link/raw/`, compiled wiki pages in `~/link/wiki/`, and direct memories in `~/link/wiki/memories/`.

If you are unsure whether Link is ready, use MCP `status` when available, or run `lnk health`.

At the first substantive turn of a session, use MCP `recall` with an empty query when available, or run `lnk brief "session start"` if you only have CLI access. This is cheap and bounded; it prevents asking the user to repeat durable context.

If the user asks what to try after installing Link, use MCP `admin` with action `prompts` when available, or run `lnk next`.

If status reports a missing or old schema marker, use MCP `admin` with action `migrate` when available, or run `lnk migrate`, before other writes.

When the user asks to ingest or drops files into `raw/`, use MCP `ingest` when available, or run `lnk ingest-status`, then follow its guided plan before deciding what to process. If it reports `blocked_secrets` or secret warnings, do not read or ingest flagged raw files until the user redacts them.

When answering a substantive question that may need local memory or wiki context, start with MCP `recall` when available, or run `lnk query "<task or question>" --budget micro`. Read the returned `recall_capsule` first. Do this before broad file reads, grep/search, or asking the user to repeat project context.

If the recall packet has no useful project context and the user is working inside a repo, seed allowlisted source-backed project context before broad searching: run `lnk seed . ~/link` when CLI is available, then retry bounded recall. This does not create durable memory; it only writes source-backed wiki context after secret scanning.

When you only need graph orientation, especially for a large wiki, prefer MCP `admin` with action `graph_summary` or `lnk graph-summary "<topic>"` before requesting the full graph.

Before broad repairs or risky local wiki edits, create a local backup with MCP `admin` action `backup` when available, or run `lnk backup`. Do not include `raw/` unless the user explicitly asks.

After ingesting raw sources or making substantial wiki edits, use MCP `ingest` action `rebuild` and then `ingest` action `validate` when available, or run `lnk rebuild-index`, `lnk rebuild-backlinks`, and `lnk validate`, before saying the wiki is updated.

When the user explicitly asks Link to remember something, use MCP `remember` when available. For uncertain or long-session memory, use MCP `admin` action `propose_memories` or `capture_session` first, then MCP `review` to inspect/approve.

At the end of a meaningful work session, propose memory instead of silently saving it. Use MCP `admin` action `session_end` with concise session notes when available, or run `lnk session-end <notes-or-transcript>`. Show the returned proposals to the user and save durable memory only after approval.

Use MCP `review` for memory inbox, profile, audit, log, explain, archive, restore, and forget workflows. Use MCP `admin` only for less-common maintenance and compatibility actions.

When the user says **"remember"**, **"recall"**, **"ingest"**, **"query"**, **"lint"**, or **"research"**, read `~/link/LINK.md` for instructions and follow the protocol. Use terminal commands to access `~/link/` since it's outside the workspace.

Otherwise, keep working normally after the cheap first recall; do not save durable memory unless the user asks or approves it.
