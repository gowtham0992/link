## Link — Local Agent Memory

This project has a Link wiki. Raw sources live in `raw/`, compiled wiki pages in `wiki/`, and direct memories in `wiki/memories/`.

If you are unsure whether this project Link wiki is ready, use MCP `status` when available, or run `python3 link.py health`.

At the first substantive turn of a project session, use MCP `recall` with an empty query when available, or run `python3 link.py brief "session start"` if you only have CLI access. This is cheap and bounded; it prevents asking the user to repeat durable project context.

If the user asks what to try after installing Link, use MCP `admin` with action `prompts` when available, or run `python3 link.py next`.

If status reports a missing or old schema marker, use MCP `admin` with action `migrate` when available, or run `python3 link.py migrate`, before other writes.

When the user asks to ingest or drops files into `raw/`, use MCP `ingest` when available, or run `python3 link.py ingest-status`, then follow its guided plan before deciding what to process. If it reports `blocked_secrets` or secret warnings, do not read or ingest flagged raw files until the user redacts them.

When answering a substantive project question, start with MCP `recall` when available, or run `python3 link.py query "<task or question>" --budget micro`. Read the returned `recall_capsule` first. Do this before broad file reads, grep/search, or asking the user to repeat project context.

If the recall packet has no useful project context and this repo has not been seeded yet, seed allowlisted source-backed project context before broad searching: run `python3 link.py seed . .` from the project checkout, then retry bounded recall. This does not create durable memory; it only writes source-backed wiki context after secret scanning.

When you only need graph orientation, especially for a large wiki, prefer MCP `admin` with action `graph_summary` or `python3 link.py graph-summary "<topic>"` before requesting the full graph.

Project installs infer the current repo as the memory project key, so project-scoped memories stay separate from other repos while broad user memories still apply.

Before broad repairs or risky local wiki edits, create a local backup with MCP `admin` action `backup` when available, or run `python3 link.py backup`. Do not include `raw/` unless the user explicitly asks.

For long session notes, use `python3 link.py capture-session "<file-or-text>"` to store a local raw capture and produce memory proposals without writing durable memories.
Use MCP `admin` action `capture_inbox` when available, or `python3 link.py capture-inbox`, to review saved captures, warnings, and next-step commands.
When the human approves a proposal from a capture, use `python3 link.py accept-capture "<raw-capture-path>" --index <n>`.
If a capture reports secret warnings, ask before running `python3 link.py redact-capture "<raw-capture-path>"`.
Only delete a raw capture after explicit confirmation: `python3 link.py delete-capture "<raw-capture-path>" --confirm`.

After ingesting raw sources or making substantial wiki edits, use MCP `ingest` action `rebuild` and then `ingest` action `validate` when available, or run `python3 link.py rebuild-index`, `python3 link.py rebuild-backlinks`, and `python3 link.py validate`, before saying the wiki is updated.

When the user explicitly asks Link to remember something, use MCP `remember` when available. For uncertain or long-session memory, use MCP `admin` action `propose_memories` or `capture_session` first, then MCP `review` to inspect/approve.

Use MCP `review` for memory inbox, profile, audit, log, explain, archive, restore, and forget workflows. Use MCP `admin` only for less-common maintenance and compatibility actions.
If a memory brief reports a memory backlog (pending captures or reviews above threshold), offer the user a short consolidation pass: use MCP `review` with action `consolidate` when available, or run `python3 link.py consolidate`. The plan is read-only; apply its accept/discard/review commands only after the user approves each action.

If Link session hooks are installed for this agent, the session-start memory brief is injected automatically — do not run a second startup recall; go straight to bounded task recall. Recalled memories carry a `match` field: treat `semantic` matches (paraphrase similarity with capped confidence) as hints to verify with the user, not facts to act on.

When the user says **"remember"**, **"recall"**, **"ingest"**, **"query"**, **"lint"**, or **"research"**, read `LINK.md` for instructions and follow the protocol.

When a new memory contradicts an existing one, do not force both to coexist: with the user's approval, save the new memory with `supersedes: <old-name>` (CLI `--supersedes`). The old memory is archived with lineage in both directions, `explain-memory` shows the full chain, and `lnk recall --as-of YYYY-MM-DD` can reconstruct what was true on a past date.

Recalled memories may carry an `applicability` label: `matched` means the memory's declared conditions fit this context; `out_of_context` means they do not — do not apply that memory here without asking the user. When saving a memory that only applies in specific situations, set scoping conditions (for example `applies_when: "project:acme, task:deploying"`).

After completing a notable multi-step task (a release, a tricky deploy, a recovery), offer to save it as a reusable recipe: propose a `procedure` memory with a short `trigger` phrase describing when it applies, and save it only after the user approves. When starting a recurring task, recall first — approved procedures return with their steps.

Otherwise, keep working normally after the cheap first recall; do not save durable memory unless the user asks or approves it.
