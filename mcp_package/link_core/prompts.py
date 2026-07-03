"""Shared first-run prompt helpers for Link."""
from __future__ import annotations

from pathlib import Path

from .memory import default_project_for_target, normalize_project
from .mcp_verify import display_command


def _command_target(target: Path) -> Path:
    if target.name == "wiki" and (target / "index.md").exists():
        return target.parent
    return target


def starter_prompt_payload(target: Path, project: str | None = None) -> dict[str, object]:
    """Return natural agent prompts and local checks for a Link user."""
    target = target.expanduser().resolve()
    command_target = str(_command_target(target))
    project_name = normalize_project(project) if project is not None else default_project_for_target(target)
    remember_prompt = (
        "remember that this project uses Link for local agent memory"
        if project_name
        else "remember that I prefer local-first agent memory"
    )
    query_prompt = (
        "what does Link remember about this project?"
        if project_name
        else "what does Link know about me?"
    )
    prompts = [
        {
            "label": "Check readiness",
            "prompt": "is Link ready?",
            "when": "right after install or before troubleshooting",
        },
        {
            "label": "Start with Link",
            "prompt": "start with Link before we continue",
            "when": "at the start of a session or task",
        },
        {
            "label": "Seed project context",
            "prompt": "seed this project into Link",
            "when": "after install inside a repo, before the first real project recall",
        },
        {
            "label": "Save explicit memory",
            "prompt": remember_prompt,
            "when": "when you want future agents to remember a preference, decision, or project fact",
        },
        {
            "label": "Ask with context",
            "prompt": query_prompt,
            "when": "when you want a compact answer-ready packet from memory and wiki context",
        },
        {
            "label": "Ingest a source",
            "prompt": "ingest raw/<file> into Link",
            "when": "after dropping a source file into raw/",
        },
        {
            "label": "Review memory proposals",
            "prompt": "propose memories from raw/<file>",
            "when": "when a source may contain preferences, decisions, or project context",
        },
    ]
    return {
        "target": str(target),
        "project": project_name,
        "shortcut": display_command(["link", "next", command_target]),
        "prompts": prompts,
        "commands": [
            display_command(["link", "seed", ".", command_target]),
            display_command(["link", "health", command_target]),
            display_command(["link", "ingest-status", command_target]),
            display_command(["link", "memory-inbox", command_target]),
            display_command(["link", "benchmark", "agent memory", command_target]),
        ],
    }


def welcome_payload(target: Path, project: str | None = None) -> dict[str, object]:
    """Return a short first-use path for a human trying Link with an agent."""
    starter = starter_prompt_payload(target, project=project)
    command_target = str(_command_target(target.expanduser().resolve()))
    prompts = [
        item for item in starter.get("prompts", [])
        if isinstance(item, dict)
    ]
    proof = [
        "Agent can find Link and check readiness.",
        "Agent can prime itself with compact local memory.",
        "Agent can save explicit memory only when you ask.",
    ]
    steps = []
    for index, item in enumerate(prompts[:3], start=1):
        steps.append({
            "step": index,
            "label": item.get("label", ""),
            "prompt": item.get("prompt", ""),
            "proves": proof[index - 1],
        })
    return {
        "target": starter["target"],
        "project": starter["project"],
        "steps": steps,
        "commands": [
            display_command(["link", "health", command_target]),
            display_command(["link", "serve", command_target]),
            display_command(["link", "ingest-status", command_target]),
            display_command(["link", "prompts", command_target]),
        ],
        "urls": [
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3000/onboard",
            "http://127.0.0.1:3000/health",
            "http://127.0.0.1:3000/graph",
        ],
    }
