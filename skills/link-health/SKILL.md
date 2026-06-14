---
name: link-health
description: Use when a user wants to verify Link readiness, troubleshoot a local wiki, inspect interrupted writes, repair generated indexes, or back up Link without setting up MCP.
---

# Link Health

Use the `lnk` CLI. In a source checkout, replace `lnk` with `python3 link.py`. MCP and the local web viewer are optional; `lnk serve` is only for humans to browse the wiki.

1. Check readiness first:
   ```bash
   lnk health [link-root]
   ```
2. If the output mentions interrupted or stale operations, inspect them before repair:
   ```bash
   lnk operations [link-root]
   ```
3. Before broad repairs, migrations, or restore work, create a backup:
   ```bash
   lnk backup [link-root]
   ```
4. Repair only generated or structural state that Link reports as safe:
   ```bash
   lnk doctor --fix [link-root]
   lnk rebuild-index [link-root]
   lnk rebuild-backlinks [link-root]
   ```
5. Validate before saying the wiki is healthy:
   ```bash
   lnk validate [link-root]
   lnk health [link-root]
   ```

If the user asks whether MCP is ready, run `lnk verify-mcp [link-root]`. Do not start `lnk serve` for MCP or CLI work.
