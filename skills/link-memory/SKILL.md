---
name: link-memory
description: Use for explicit Link memory lifecycle work and after important user-approved decisions: remember, recall, review, update, archive, restore, forget, or explain local memories through the CLI without requiring MCP.
---

# Link Memory

Use explicit memory operations. In a source checkout, replace `lnk` with `python3 link.py`. Do not silently save durable memory; only remember when the user asks, approves a proposal, or explicitly confirms an important decision should become durable memory.

1. Prime before work:
   ```bash
   lnk brief "<current task>" [link-root]
   ```
2. Recall specific memory:
   ```bash
   lnk recall "<topic>" [link-root]
   ```
3. Save an explicit memory:
   ```bash
   lnk remember "<user-approved memory>" [link-root] --type note --scope user
   ```
   Use `--project <slug>` for project-scoped memory, `--visibility private|project|team` for sharing intent, `--review-after YYYY-MM-DD` for stale-risk memories, and `--expires-at YYYY-MM-DD` for temporary context.
4. Review and explain before trusting uncertain memory:
   ```bash
   lnk memory-inbox [link-root]
   lnk explain-memory <name-or-title> [link-root]
   lnk review-memory <name-or-title> [link-root]
   ```
5. Change lifecycle safely:
   ```bash
   lnk update-memory <name-or-title> "<new text>" [link-root]
   lnk archive-memory <name-or-title> [link-root] --reason "<why>"
   lnk restore-memory <name-or-title> [link-root]
   lnk forget-memory <name-or-title> [link-root] --confirm
   ```

When duplicate or conflict warnings appear, prefer updating, reviewing, or archiving existing memory over creating another page.
