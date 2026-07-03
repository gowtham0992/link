"""Bundled first-run demo wiki content for Link."""
from __future__ import annotations

import shutil
from pathlib import Path

from .files import atomic_write_json, atomic_write_text
from .schema import migrate_wiki
from .wiki import build_backlinks


DEMO_MARKER = ".link-demo"
DEMO_DIRECTORIES = (
    "raw",
    "wiki/sources",
    "wiki/concepts",
    "wiki/entities",
    "wiki/memories",
    "wiki/comparisons",
    "wiki/explorations",
)
RUNTIME_FILES = ("serve.py", "link.py", "LINK.md", ".linkignore")
BRAND_FILES = ("logo.png", "logo.svg")
WORKSPACE_GITIGNORE = """# Link private local source material
raw/*
!raw/.gitkeep

# Link local runtime state
.link-backups/
.link-cache/
.link-mcp-python

# Local/editor noise
.DS_Store
*.swp
*~
__pycache__/
*.pyc
"""


class DemoError(RuntimeError):
    """Raised when a demo workspace cannot be created safely."""


def copy_runtime_files(source_root: Path, target: Path) -> None:
    """Copy the runtime files needed by a standalone Link wiki directory."""
    target.mkdir(parents=True, exist_ok=True)
    for name in RUNTIME_FILES:
        src = source_root / name
        dst = target / name
        if src.exists() and src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
    core_src = source_root / "mcp_package" / "link_core"
    if not core_src.exists():
        core_src = source_root / "link_core"
    if core_src.exists():
        core_target = target / "link_core"
        core_target.mkdir(exist_ok=True)
        for src in core_src.glob("*.py"):
            dst = core_target / src.name
            if src.resolve() != dst.resolve():
                shutil.copy2(src, dst)
    for name in BRAND_FILES:
        src = source_root / name
        dst = target / name
        if src.exists() and src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
    gitignore = target / ".gitignore"
    if not gitignore.exists():
        atomic_write_text(gitignore, WORKSPACE_GITIGNORE)


def create_demo_workspace(target: Path, *, source_root: Path, force: bool = False) -> dict[str, object]:
    """Create a pre-ingested demo workspace and return basic creation metadata."""
    target = target.expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        marker = target / DEMO_MARKER
        if not force:
            raise DemoError(f"{target} already exists. Re-run with --force to replace a Link demo directory.")
        if not marker.exists():
            raise DemoError(f"{target} does not look like a Link demo directory; refusing to overwrite it.")
        shutil.rmtree(target)

    target.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target / DEMO_MARKER, "Link demo directory\n")
    copy_runtime_files(source_root, target)

    for directory in DEMO_DIRECTORIES:
        path = target / directory
        path.mkdir(parents=True, exist_ok=True)
        (path / ".gitkeep").touch()

    for rel, content in DEMO_FILES.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, content.strip() + "\n")

    wiki_dir = target / "wiki"
    backlinks = build_backlinks(wiki_dir, body_only=False)
    atomic_write_json(wiki_dir / "_backlinks.json", backlinks)
    migration = migrate_wiki(wiki_dir)
    return {
        "target": str(target),
        "wiki": str(wiki_dir),
        "file_count": len(DEMO_FILES),
        "migration": migration,
    }


DEMO_FILES: dict[str, str] = {
    "START_HERE.md": """# Link Demo: Start Here

This demo is already ingested. It shows the full loop: source notes, wiki pages,
agent memory, backlinks, graph context, and a compact query packet.

## Try These Agent Prompts

```text
is Link ready?
query Link for why Link helps agents
start with Link before we continue
what does Link remember about local personal memory?
explain why Link remembers local personal memory
```

## Try These CLI Checks

```bash
python3 link.py query "why does Link help agents?" . --budget small
python3 link.py brief "working on agent memory" .
python3 link.py memory-audit .
python3 link.py health .
```

## What To Look For

- The query packet includes both memory and source-backed wiki context.
- The packet is budget-limited, so agents do not need to read the whole wiki.
- The memory entry is inspectable under `wiki/memories/`.
- The graph view shows how sources, concepts, memories, and explorations connect.

Open the local viewer:

```bash
python3 link.py serve .
```

Then visit `http://127.0.0.1:3000`, `http://127.0.0.1:3000/brief`, and
`http://127.0.0.1:3000/graph`.
""",
    "raw/agent-memory-session.md": """---
title: "Agent memory session"
source_type: demo-note
date_captured: 2026-05-02
author: Link demo
tags: [agents, memory, local-first]
---

# Agent memory session

An AI coding agent keeps losing project context between sessions. The team wants durable memory that is local, inspectable, and easy to cite.

Key decisions:

- Keep raw source notes immutable.
- Compile sources into durable wiki pages.
- Use [[agent-memory]] as the interface between past work and future agents.
- Prefer [[local-first-software]] so the knowledge base stays under user control.
- Expose context through MCP so agents can retrieve graph neighborhoods instead of reading every file.
""",
    "raw/transformer-reading-notes.md": """---
title: "Transformer reading notes"
source_type: demo-note
date_captured: 2026-05-02
author: Link demo
tags: [ai, transformers, retrieval]
---

# Transformer reading notes

Transformers made long-context sequence modeling practical by replacing recurrence with attention. Modern LLM systems often pair transformer models with external retrieval.

Connections:

- [[transformers]] provide the model architecture.
- [[retrieval-augmented-generation]] provides fresh or private context.
- [[agent-memory]] gives agents persistent project knowledge outside a single chat.
""",
    "raw/local-release-notes.md": """---
title: "Local release notes"
source_type: demo-note
date_captured: 2026-05-02
author: Link demo
tags: [release, graph, mcp]
---

# Local release notes

The product team ships a local wiki viewer, MCP server, and graph view. The release focuses on making agent memory visible and auditable.

Notable changes:

- [[link]] exposes search, context, backlinks, and graph tools.
- [[knowledge-graph]] shows concepts, sources, and entities as connected pages.
- [[local-first-software]] keeps the source material on disk.
""",
    "wiki/sources/agent-memory-session.md": """---
type: source
title: "Agent memory session"
author: "Link demo"
date_published: "2026-05-02"
date_ingested: "2026-05-02"
source_url: "local demo note"
tags: [agents, memory, local-first]
confidence: high
aliases: ["memory demo note"]
---

# Agent memory session

> **TLDR:** A demo note about turning local project sources into durable context for future agents.

## Summary

The source describes an AI coding workflow where an agent repeatedly loses project context between sessions. It proposes raw source notes, compiled wiki pages, and MCP retrieval as a durable memory layer. *Source: [[agent-memory-session]]* `[confidence: high]`

The note emphasizes local control and inspectability. Raw sources stay immutable, while generated wiki pages become the maintained knowledge layer. *Source: [[agent-memory-session]]* `[confidence: high]`

## Key Claims

- **Agent memory should be durable** so future sessions can recover project context. `[confidence: high]`
- **Raw notes should remain immutable** while wiki pages evolve. `[confidence: high]`
- **MCP makes memory agent-readable** through structured tools instead of ad hoc file scans. `[confidence: high]`

## Connections

- Defines a need for [[agent-memory]].
- Supports [[local-first-software]] as the storage model.
- Connects [[link]] to agent workflows through MCP.

## Raw Source

`raw/agent-memory-session.md`
""",
    "wiki/sources/transformer-reading-notes.md": """---
type: source
title: "Transformer reading notes"
author: "Link demo"
date_published: "2026-05-02"
date_ingested: "2026-05-02"
source_url: "local demo note"
tags: [ai, transformers, retrieval]
confidence: high
aliases: ["transformer demo note"]
---

# Transformer reading notes

> **TLDR:** A demo note linking transformers, retrieval, and persistent agent memory.

## Summary

The source frames [[transformers]] as the architecture behind modern LLM systems and connects them to external retrieval. It treats retrieval and memory as practical complements to model context. *Source: [[transformer-reading-notes]]* `[confidence: high]`

The note links [[retrieval-augmented-generation]] to [[agent-memory]] because both bring outside context into model workflows. *Source: [[transformer-reading-notes]]* `[confidence: high]`

## Key Claims

- **Transformers replaced recurrence with attention** for sequence modeling. `[confidence: high]`
- **External retrieval complements LLM context** when information is fresh, private, or project-specific. `[confidence: high]`
- **Persistent agent memory stores knowledge outside one chat session.** `[confidence: high]`

## Connections

- Explains why [[transformers]] matter to LLM systems.
- Connects [[retrieval-augmented-generation]] to persistent context.
- Supports [[agent-memory]] as a local retrieval layer.

## Raw Source

`raw/transformer-reading-notes.md`
""",
    "wiki/sources/local-release-notes.md": """---
type: source
title: "Local release notes"
author: "Link demo"
date_published: "2026-05-02"
date_ingested: "2026-05-02"
source_url: "local demo note"
tags: [release, graph, mcp]
confidence: high
aliases: ["demo release note"]
---

# Local release notes

> **TLDR:** A demo release note showing Link as a local wiki viewer, graph, and MCP memory server.

## Summary

The source describes a release centered on making agent memory visible and auditable. It identifies a local wiki viewer, MCP server, and graph view as the main product surfaces. *Source: [[local-release-notes]]* `[confidence: high]`

The note connects [[link]] with [[knowledge-graph]] and [[local-first-software]], showing how local markdown can become both a human-readable wiki and agent-readable memory. *Source: [[local-release-notes]]* `[confidence: high]`

## Key Claims

- **Link exposes search, context, backlinks, and graph tools.** `[confidence: high]`
- **Graph views make relationships inspectable.** `[confidence: high]`
- **Local-first storage keeps source material under user control.** `[confidence: high]`

## Connections

- Describes [[link]] product surfaces.
- Connects [[knowledge-graph]] to visible agent memory.
- Supports [[local-first-software]] as the privacy model.

## Raw Source

`raw/local-release-notes.md`
""",
    "wiki/concepts/agent-memory.md": """---
type: concept
title: "Agent memory"
aliases: ["AI memory", "agent context", "durable context"]
date_created: "2026-05-02"
date_updated: "2026-05-02"
source_count: 2
tags: [agents, memory, mcp]
maturity: growing
---

# Agent memory

> **TLDR:** Agent memory is durable, inspectable context that lets AI agents recover prior project knowledge across sessions.

## Overview

Agent memory addresses a common failure mode in AI workflows: each new session starts without the full project history. In Link, memory is stored as markdown wiki pages compiled from immutable raw sources. *Source: [[agent-memory-session]]* `[confidence: high]`

This memory is useful because agents can query a focused topic and receive the primary page plus related graph context. That is more efficient than reading every source file. *Source: [[transformer-reading-notes]]* `[confidence: high]`

## How It Works

1. A user drops source material into `raw/`.
2. An agent compiles durable pages into `wiki/`.
3. Link builds search indexes and backlinks.
4. MCP tools return focused graph context to future agents.

## Key Facts

- **Agent memory should be durable** so future sessions can recover project context. *Source: [[agent-memory-session]]* `[confidence: high]`
- **MCP makes memory agent-readable** through structured tools. *Source: [[agent-memory-session]]* `[confidence: high]`
- **Persistent memory complements LLM context windows** by storing knowledge outside a single chat. *Source: [[transformer-reading-notes]]* `[confidence: high]`

## Open Questions

- Which memories should be promoted from raw notes into stable wiki pages?
- How should agents detect stale project decisions?

## Related

- [[link]] - provides the local wiki and MCP layer.
- [[retrieval-augmented-generation]] - retrieves external context for model workflows.
- [[local-first-software]] - keeps memory under user control.

## Sources

- [[agent-memory-session]]
- [[transformer-reading-notes]]
""",
    "wiki/concepts/retrieval-augmented-generation.md": """---
type: concept
title: "Retrieval-augmented generation"
aliases: ["RAG", "retrieval augmented generation"]
date_created: "2026-05-02"
date_updated: "2026-05-02"
source_count: 1
tags: [ai, retrieval, context]
maturity: seed
---

# Retrieval-augmented generation

> **TLDR:** Retrieval-augmented generation brings external context into model workflows before generation.

## Overview

Retrieval-augmented generation pairs a model with a retrieval layer. Instead of relying only on model weights or the current chat, a system fetches relevant external context first. *Source: [[transformer-reading-notes]]* `[confidence: high]`

In Link, the retrieval layer is a local markdown wiki exposed through search, context, backlinks, and graph tools. This makes [[agent-memory]] inspectable instead of hidden in a proprietary store. *Source: [[transformer-reading-notes]]* `[confidence: high]`

## Key Facts

- **External retrieval complements LLM context** when information is fresh, private, or project-specific. *Source: [[transformer-reading-notes]]* `[confidence: high]`
- **Persistent memory can be modeled as retrieval** over durable local pages. *Source: [[transformer-reading-notes]]* `[confidence: high]`

## Related

- [[agent-memory]] - a local memory use case for retrieval.
- [[transformers]] - the model architecture that often consumes retrieved context.
- [[link]] - provides the local retrieval surface.

## Sources

- [[transformer-reading-notes]]
""",
    "wiki/concepts/transformers.md": """---
type: concept
title: "Transformers"
aliases: ["transformer architecture", "LLM architecture"]
date_created: "2026-05-02"
date_updated: "2026-05-02"
source_count: 1
tags: [ai, models, attention]
maturity: seed
---

# Transformers

> **TLDR:** Transformers are neural architectures that use attention to model relationships across sequences.

## Overview

Transformers are presented in the demo source as the architecture behind many modern LLM systems. They made long-context sequence modeling practical by replacing recurrence with attention. *Source: [[transformer-reading-notes]]* `[confidence: high]`

The source connects transformers to [[retrieval-augmented-generation]] because modern LLM workflows often combine model context with retrieved project or domain knowledge. *Source: [[transformer-reading-notes]]* `[confidence: high]`

## Key Facts

- **Transformers use attention for sequence modeling.** *Source: [[transformer-reading-notes]]* `[confidence: high]`
- **Transformer systems often benefit from retrieved context.** *Source: [[transformer-reading-notes]]* `[confidence: high]`

## Related

- [[retrieval-augmented-generation]] - supplies outside context to model workflows.
- [[agent-memory]] - stores project context for future sessions.

## Sources

- [[transformer-reading-notes]]
""",
    "wiki/concepts/local-first-software.md": """---
type: concept
title: "Local-first software"
aliases: ["local first", "local-first"]
date_created: "2026-05-02"
date_updated: "2026-05-02"
source_count: 2
tags: [privacy, storage, software]
maturity: growing
---

# Local-first software

> **TLDR:** Local-first software keeps user data on disk in formats the user can inspect, back up, and move.

## Overview

Local-first software is a product design choice where the user's data remains directly accessible on their machine. In the demo sources, this matters because [[agent-memory]] can contain project decisions and source notes. *Source: [[agent-memory-session]]* `[confidence: high]`

Link follows this model by storing raw sources and wiki pages as markdown files. The graph and MCP server read those files rather than sending them to a hosted backend. *Source: [[local-release-notes]]* `[confidence: high]`

## Key Facts

- **Raw notes stay immutable** while generated wiki pages evolve. *Source: [[agent-memory-session]]* `[confidence: high]`
- **Local markdown keeps memory inspectable.** *Source: [[local-release-notes]]* `[confidence: high]`

## Related

- [[link]] - implements local-first agent memory.
- [[agent-memory]] - benefits from local, inspectable storage.
- [[knowledge-graph]] - visualizes local wiki relationships.

## Sources

- [[agent-memory-session]]
- [[local-release-notes]]
""",
    "wiki/concepts/knowledge-graph.md": """---
type: concept
title: "Knowledge graph"
aliases: ["graph view", "wiki graph"]
date_created: "2026-05-02"
date_updated: "2026-05-02"
source_count: 1
tags: [graph, wiki, visualization]
maturity: seed
---

# Knowledge graph

> **TLDR:** A knowledge graph shows wiki pages as nodes and wikilinks as relationships.

## Overview

In Link, the knowledge graph makes relationships between sources, concepts, and entities visible. This helps users inspect what an agent has connected and where a claim came from. *Source: [[local-release-notes]]* `[confidence: high]`

The graph supports the same mental model as MCP context retrieval: a topic is not isolated, it lives in a neighborhood of related pages. *Source: [[local-release-notes]]* `[confidence: high]`

## Key Facts

- **Graph views make relationships inspectable.** *Source: [[local-release-notes]]* `[confidence: high]`
- **Wikilinks provide the graph edges.** *Source: [[local-release-notes]]* `[confidence: high]`

## Related

- [[link]] - renders the graph.
- [[agent-memory]] - uses graph context to recover related knowledge.
- [[local-first-software]] - keeps graph data in markdown files.

## Sources

- [[local-release-notes]]
""",
    "wiki/entities/link.md": """---
type: entity
title: "Link"
entity_type: project
aliases: ["Link wiki", "Link MCP"]
date_created: "2026-05-02"
date_updated: "2026-05-02"
tags: [wiki, mcp, agents, local-first]
source_count: 2
maturity: growing
---

# Link

> **TLDR:** Link is a local-first wiki and MCP server that turns source notes into durable memory for AI agents.

## Overview

Link stores source material in `raw/` and compiled wiki pages in `wiki/`. The web viewer makes the wiki readable by humans, while MCP tools make the same knowledge readable by agents. *Source: [[local-release-notes]]* `[confidence: high]`

The demo positions Link as a local [[agent-memory]] layer. It keeps knowledge inspectable through markdown and navigable through a [[knowledge-graph]]. *Source: [[agent-memory-session]]* `[confidence: high]`

## Key Contributions

- Provides search, context, backlinks, and graph tools. *Source: [[local-release-notes]]* `[confidence: high]`
- Keeps source material local and inspectable. *Source: [[local-release-notes]]* `[confidence: high]`
- Gives future agents durable project context. *Source: [[agent-memory-session]]* `[confidence: high]`

## Connections

- Implements [[agent-memory]].
- Uses [[local-first-software]] as the storage model.
- Exposes a [[knowledge-graph]] for human inspection.
- Supports [[retrieval-augmented-generation]] workflows through MCP.

## Sources

- [[agent-memory-session]]
- [[local-release-notes]]
""",
    "wiki/memories/prefer-local-personal-memory.md": """---
type: memory
title: "Prefer local personal memory"
memory_type: preference
scope: user
status: active
date_captured: "2026-05-04T00:00:00Z"
source: "demo"
review_status: pending
tags: [memory, agents, local-first]
aliases: ["local personal memory", "agent personal memory"]
---

# Prefer local personal memory

> **TLDR:** The user wants Link to be local personal memory for agents, with the wiki as the inspectable storage format.

## Memory

The user wants [[link]] to feel like local personal memory for agents rather than only a wiki. Agents should remember user preferences, project context, decisions, and why those memories exist.

## Use This When

- Positioning Link in product copy or onboarding.
- Deciding whether a feature should prioritize [[agent-memory]] workflows over generic note management.
- Explaining why [[local-first-software]] matters for personal agent memory.

## Source

Captured as demo product intent for the first-run wiki.
""",
    "wiki/memories/keep-answers-short-and-cite-wiki-sources.md": """---
type: memory
title: "Keep answers short and cite wiki sources"
memory_type: preference
scope: user
status: active
date_captured: "2026-05-02T00:00:00Z"
source: "demo"
review_status: reviewed
reviewed_at: "2026-05-02T00:00:00Z"
review_note: "Seeded as a reviewed demo preference."
tags: [memory, style, answers]
aliases: ["answer style", "response style"]
---

# Keep answers short and cite wiki sources

> **TLDR:** The user prefers short, direct answers that cite the wiki pages they came from.

## Memory

When answering from Link, keep responses short and point to the [[knowledge-graph]] pages behind each claim instead of repeating whole documents.

## Use This When

- Formatting any answer that uses Link context.
- Deciding how much wiki text to quote in a reply.

## Source

Seeded demo preference for the first-run wiki.
""",
    "wiki/memories/keep-agent-memory-in-local-markdown.md": """---
type: memory
title: "Keep agent memory in local Markdown"
memory_type: decision
scope: project
status: active
date_captured: "2026-05-02T00:00:00Z"
source: "demo"
review_status: reviewed
reviewed_at: "2026-05-02T00:00:00Z"
review_note: "Seeded as a reviewed demo decision."
tags: [memory, decision, local-first]
aliases: ["local markdown decision", "no cloud sync"]
---

# Keep agent memory in local Markdown

> **TLDR:** The project decided agent memory stays in local Markdown files with no cloud sync.

## Memory

This project keeps durable agent memory in plain local Markdown under `wiki/`, following [[local-first-software]]. No cloud sync, no hosted memory profile, no embeddings service.

## Use This When

- An agent or teammate proposes syncing memory to a hosted service.
- Explaining where memory lives and how to audit it.

## Source

Seeded demo decision for the first-run wiki.
""",
    "wiki/memories/local-viewer-runs-on-port-3000.md": """---
type: memory
title: "Local viewer runs on port 3000"
memory_type: fact
scope: project
status: active
date_captured: "2026-05-02T00:00:00Z"
source: "demo"
review_status: reviewed
reviewed_at: "2026-05-02T00:00:00Z"
review_note: "Seeded as a reviewed demo fact."
tags: [memory, viewer, setup]
aliases: ["viewer port", "serve port"]
---

# Local viewer runs on port 3000

> **TLDR:** The local Link viewer serves this wiki at http://127.0.0.1:3000 by default.

## Memory

`lnk serve` binds the read-only local viewer for [[link]] to `127.0.0.1:3000`. It is loopback-only and needs no account or network access.

## Use This When

- Telling the user where to inspect a page, memory, or the graph.
- Debugging why the viewer is unreachable.

## Source

Seeded demo fact for the first-run wiki.
""",
    "wiki/explorations/why-link-helps-agents.md": """---
type: exploration
title: "Why Link helps agents"
date_created: "2026-05-02"
query: "Why does Link help AI agents?"
aliases: ["agent memory demo answer"]
tags: [agents, memory, demo]
---

# Why Link helps agents

> **Query:** Why does Link help AI agents?

## Answer

Link helps agents because it turns past project material into durable, queryable context. Instead of starting each session from a blank chat, an agent can ask for [[agent-memory]] and receive the main page plus related concepts, sources, and entities.

The important part is inspectability. The memory is just markdown, the relationships are just wikilinks, and the graph shows what the agent can retrieve. This fits [[local-first-software]] and makes the memory easier to audit.

## Reasoning

The answer combines [[agent-memory-session]], [[transformer-reading-notes]], and [[local-release-notes]]. Together they show Link as a local retrieval layer for AI workflows: sources become pages, pages form a [[knowledge-graph]], and MCP exposes that graph to agents.

## Sources Consulted

- [[agent-memory]]
- [[link]]
- [[knowledge-graph]]
- [[retrieval-augmented-generation]]
""",
    "wiki/index.md": """# Link Demo Wiki Index

> Last updated: 2026-05-02 | 14 pages | 3 sources

## Categories

### concepts
- [[agent-memory]] - Durable, inspectable context for AI agents. growing - 2 sources - also: AI memory, agent context
- [[retrieval-augmented-generation]] - Retrieves external context before generation. seed - 1 source - also: RAG
- [[transformers]] - Attention-based model architecture behind modern LLM systems. seed - 1 source
- [[local-first-software]] - Keeps user data on disk in inspectable formats. growing - 2 sources
- [[knowledge-graph]] - Shows pages as nodes and wikilinks as edges. seed - 1 source

### entities
- [[link]] - Local-first wiki and MCP memory server for agents. growing - 2 sources - also: Link MCP

### memories
- [[prefer-local-personal-memory]] - User preference that Link should behave as local personal memory for agents. preference · user
- [[keep-answers-short-and-cite-wiki-sources]] - Reviewed style preference for answers built from Link context. preference · user
- [[keep-agent-memory-in-local-markdown]] - Reviewed decision that memory stays in local Markdown with no cloud sync. decision · project
- [[local-viewer-runs-on-port-3000]] - Reviewed fact about where the local viewer serves this wiki. fact · project

### sources
- [[agent-memory-session]] - Demo note on durable project context. high
- [[transformer-reading-notes]] - Demo note connecting transformers, retrieval, and memory. high
- [[local-release-notes]] - Demo note on Link surfaces and graph visibility. high

### explorations
- [[why-link-helps-agents]] - Filed answer explaining Link as durable agent memory.

## Recent

| Date | Operation | Pages Touched |
|------|-----------|---------------|
| 2026-05-02 | demo: create first-run sample wiki | 14 pages |
""",
    "wiki/log.md": """# Link Demo Wiki Log

*Append-only record of demo wiki operations.*

---

## [2026-05-02T00:00:00Z] demo | create first-run sample wiki

- Source: raw/agent-memory-session.md
- Source: raw/transformer-reading-notes.md
- Source: raw/local-release-notes.md
- Created: sources/agent-memory-session.md
- Created: sources/transformer-reading-notes.md
- Created: sources/local-release-notes.md
- Created: concepts/agent-memory.md
- Created: concepts/retrieval-augmented-generation.md
- Created: concepts/transformers.md
- Created: concepts/local-first-software.md
- Created: concepts/knowledge-graph.md
- Created: entities/link.md
- Created: memories/prefer-local-personal-memory.md
- Created: memories/keep-answers-short-and-cite-wiki-sources.md
- Created: memories/keep-agent-memory-in-local-markdown.md
- Created: memories/local-viewer-runs-on-port-3000.md
- Created: explorations/why-link-helps-agents.md
- Rebuilt: wiki/_backlinks.json
- Pages touched: 14

---
""",
}
