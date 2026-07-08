---
name: link-retrieve
description: Use before answering work that may depend on user memory, project history, source-backed notes, or prior decisions; retrieve compact Link context through the CLI without loading the whole wiki or requiring MCP.
---

# Link Retrieve

Use bounded CLI commands so the agent does not dump the whole wiki into context. Load this skill proactively at the first substantive turn of a session, before project/release/debug/design work, or whenever the answer may depend on prior Link memory. In a source checkout, replace `lnk` with `python3 link.py`.

1. If readiness is unclear, start with:
   ```bash
   lnk health [link-root]
   ```
2. If the user is inside a project repo and Link has no project context yet, seed allowlisted source-backed context before broad searching:
   ```bash
   lnk seed . [link-root]
   ```
   This reads project docs/rule files, blocks secret-looking values, and does not create durable memories.
3. For most questions, use a compact query packet:
   ```bash
   lnk query "<question or task>" [link-root] --budget micro
   ```
   Read `recall_capsule` first. Increase to `--budget small`, `--budget medium`, or `--budget large` only when the packet says more context is needed.
4. Before longer work, prime from memory:
   ```bash
   lnk brief "<current task>" [link-root]
   ```
5. For graph context, stay bounded:
   ```bash
   lnk graph-summary "<topic>" [link-root] --limit 40 --depth 1
   ```
6. For performance checks, use:
   ```bash
   lnk benchmark "<topic>" [link-root] --budget small
   ```

Do not enumerate every page, grep raw files, or request the full graph unless the user explicitly asks for an export or exhaustive audit, or the compact packet is insufficient and tells you which follow-up to use.

Recalled memories carry `confidence` labels and, when the optional local semantic tier is installed, a `match` field: `lexical`, `hybrid`, or `semantic`. Treat `semantic` matches (paraphrase similarity, capped confidence) and `weak` matches as hints to verify with the user, not facts to act on.
