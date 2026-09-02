# Deterministic ingest adapters implementation

## Plan

Implemented `plan-deterministic-ingest-adapters.md` on `codex/deterministic-ingest-adapters`.

## Completed phases

- Added the `chezmoi-docs-graph-v1` structured export adapter.
- Added plan-first `lnk ingest` with explicit apply, unmanaged replacement, and pruning gates.
- Added source/output provenance manifests, manual-edit conflicts, staged validation, and rollback.
- Prevented structured documentation exports from becoming automatic personal-memory proposals.
- Documented deterministic and agent-authored ingest as separate product paths.
- Published upstream PR 66 and installed the reviewed branch through Homebrew.
- Migrated the live chezmoi documentation export into adapter ownership.

## Verification

- `uv run --isolated --with pytest --with 'mcp>=1,<2' python -m unittest discover -s tests`: 993 passed.
- Ruff, release hygiene, runtime duplication, tool contract, and `git diff --check`: passed.
- Full-corpus disposable rehearsal: 52 outputs applied; validation passed; immediate rerun reported 52 unchanged and zero conflicts.
- Live apply: 52 outputs adopted; validation passed with zero errors and warnings.
- Fresh CLI rerun: 52 unchanged and zero conflicts.
- Fresh MCP subprocess: initialized server version 2.3.0, listed six slim tools, returned ready status, and retrieved chezmoi documentation.
- Structured documentation memory proposal: zero candidates with an explicit wiki-only reason.

## Deviations

The upstream repositories are read-only for the current GitHub account. The change is live locally from the fork branch while upstream publication waits on maintainer review of PR 66.

## Remaining work

No implementation work remains. Upstream merge and release packaging are controlled by the Link maintainer.
