# Deterministic ingest adapters

## Objective

Add a real `lnk ingest` interface for structured source exports while preserving Link's agent-authored ingest path for arbitrary sources.

## Phase 1 — Deep ingest module

- [x] Add a schema-specific `chezmoi-docs-graph-v1` adapter.
- [x] Produce a deterministic plan before writes.
- [x] Record source hash, adapter version, options, and output hashes.
- [x] Detect unmanaged or manually changed output conflicts.
- [x] Stage, index, backlink, and validate before committing output.

## Phase 2 — Product interface

- [x] Add `lnk ingest SOURCE TARGET --adapter ...`.
- [x] Make plan mode the default and require `--apply` for writes.
- [x] Support explicit `--replace-unmanaged` and `--prune` gates.
- [x] Document deterministic versus agent-authored ingestion.

## Phase 3 — Verification and rollout

- [x] Add unit and CLI tests for planning, applying, conflicts, updates, and validation.
- [x] Run the repository release gate.
- [ ] Open an upstream pull request.
- [ ] Install the branch through Homebrew and re-ingest the live chezmoi export.
- [ ] Verify the live runtime, provenance manifest, retrieval, and wiki validation.

## Automated verification

```bash
python3 -m ruff check .
python3 -m unittest discover -s tests
python3 scripts/check_release_hygiene.py
python3 scripts/check_runtime_duplication.py
python3 scripts/check_tool_contract.py
git diff --check
```
