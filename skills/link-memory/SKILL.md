---
name: link-memory
description: Use after important user-approved decisions, when durable context should be proposed or reviewed, and for explicit Link memory lifecycle work: remember, recall, review, update, archive, restore, forget, or explain local memories through the CLI without requiring MCP.
---

# Link Memory

Use this skill after important user-approved decisions, preference changes, project conventions, or long work sessions that may deserve durable context. In a source checkout, replace `lnk` with `python3 link.py`. Do not silently save durable memory; propose first unless the user directly asks to remember, approves a proposal, or explicitly confirms an important decision should become durable memory.

If Link session hooks are installed for this agent, the memory brief is injected automatically at session start — skip step 1 and go straight to task-specific recall.

1. Prime before work:
   ```bash
   lnk brief "<current task>" [link-root]
   ```
2. Recall specific memory:
   ```bash
   lnk recall "<topic>" [link-root]
   ```
3. End a session with proposal-only memory candidates:
   ```bash
   lnk session-end <session-notes-or-transcript> [link-root] --limit 3
   ```
   Use `-` as the input when piping a transcript on stdin. Show the proposals to the user; do not save durable memory until the user approves one.
4. Save an explicit memory:
   ```bash
   lnk remember "<user-approved memory>" [link-root] --type note --scope user
   ```
   Use `--project <slug>` for project-scoped memory, `--visibility private|project|team` for sharing intent, `--review-after YYYY-MM-DD` for stale-risk memories, and `--expires-at YYYY-MM-DD` for temporary context. When the user asks Link to stop or check an action, add `--enforce "ask command: git push --force*"` (or `deny write: migrations/**`): with hooks installed the rule is checked before the agent's tool calls, once the user reviews the memory. Never review, clear, archive or update a memory that carries rules yourself; only the user does.
When a brief or recall reports a memory backlog (pending captures or reviews above threshold), offer the user a short consolidation pass:
   ```bash
   lnk consolidate [link-root]
   ```
   The plan is read-only: it groups duplicates and recurring themes and prints accept/discard/review commands. Apply an action only after the user approves it.

5. Review and explain before trusting uncertain memory:
   ```bash
   lnk memory-inbox [link-root]
   lnk explain-memory <name-or-title> [link-root]
   lnk review-memory <name-or-title> [link-root]
   ```
6. Change lifecycle safely:
   ```bash
   lnk update-memory <name-or-title> "<new text>" [link-root]
   lnk archive-memory <name-or-title> [link-root] --reason "<why>"
   lnk restore-memory <name-or-title> [link-root]
   lnk forget-memory <name-or-title> [link-root] --confirm
   ```

7. See what reached the agent, and keep agent files in step:
   ```bash
   lnk receipt [link-root]
   lnk compile [repo] --dry-run
   ```
   The receipt lists each session's memories, whether they arrived whole, and the rule checks. `lnk compile` writes reviewed memory into AGENTS.md, CLAUDE.md and per-agent rule files; show the diff and write only when the user agrees.

When duplicate or conflict warnings appear, prefer updating, reviewing, or archiving existing memory over creating another page.
