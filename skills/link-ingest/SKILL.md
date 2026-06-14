---
name: link-ingest
description: Use when a user asks to ingest raw files into Link, refresh stale source pages, propose memories from sources, or validate source-backed wiki updates through the CLI without MCP.
---

# Link Ingest

Use `lnk ingest-status` as the source of truth. In a source checkout, replace `lnk` with `python3 link.py`. The command tells you which raw files need work and which checks must run next.

1. Inspect the ingest plan:
   ```bash
   lnk ingest-status [link-root]
   ```
2. If Link reports secret-looking values, unreadable files, or unsafe paths, stop and ask the user to fix or redact them.
3. Read only the pending raw files named by the ingest plan. Create or update one `wiki/sources/...` page per raw file, and update existing concept/entity/exploration/memory pages before creating thin duplicates.
4. Keep durable memory proposal-only until the user approves it:
   ```bash
   lnk propose-memories raw/<file> [link-root]
   ```
5. After writing wiki pages, rebuild generated indexes and validate:
   ```bash
   lnk rebuild-index [link-root]
   lnk rebuild-backlinks [link-root]
   lnk validate [link-root]
   lnk health [link-root]
   ```

Do not put raw source contents into chat unless needed for the current ingest task. Preserve source paths and provenance on generated pages.
