---
name: link-retrieve
description: Use when a user asks an agent to search, answer from, summarize, brief from, or navigate Link context through the CLI without loading the whole wiki or configuring MCP.
---

# Link Retrieve

Use bounded CLI commands so the agent does not dump the whole wiki into context. In a source checkout, replace `lnk` with `python3 link.py`.

1. If readiness is unclear, start with:
   ```bash
   lnk health [link-root]
   ```
2. For most questions, use a compact query packet:
   ```bash
   lnk query "<question or task>" [link-root] --budget micro
   ```
   Read `recall_capsule` first. Increase to `--budget small`, `--budget medium`, or `--budget large` only when the packet says more context is needed.
3. Before longer work, prime from memory:
   ```bash
   lnk brief "<current task>" [link-root]
   ```
4. For graph context, stay bounded:
   ```bash
   lnk graph-summary "<topic>" [link-root] --limit 40 --depth 1
   ```
5. For performance checks, use:
   ```bash
   lnk benchmark "<topic>" [link-root] --budget small
   ```

Do not enumerate every page, grep raw files, or request the full graph unless the user explicitly asks for an export or exhaustive audit, or the compact packet is insufficient and tells you which follow-up to use.
