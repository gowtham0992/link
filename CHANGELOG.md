# Changelog

All notable changes to Link are tracked here.

Release sections use `MAJOR.MINOR.PATCH` versions that match `link-mcp` on PyPI and the MCP Registry. Keep `Unreleased` for work merged after the latest published version.

## [Unreleased]

### Added

- Added `link try` as a one-command demo proof loop that creates the demo, checks readiness, runs query/brief examples, and prints first agent prompts.
- Added `link connect <agent>` to preview or write MCP client config for Codex, Kiro, Claude Code, Cursor, Antigravity, VS Code, and Copilot.
- Added optional `review_after` dates for durable memories so time-sensitive context can automatically return to the memory inbox for re-checking.
- Added `python -m link_mcp --version` so MCP package installs can be verified before a wiki exists.
- Added an Obsidian guide for opening Link's Markdown wiki as a vault and rebuilding indexes after manual edits.

### Changed

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
