"""Text rendering helpers for Link memory CLI commands."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from .mcp_verify import display_command


def _shell_words(*parts: object) -> str:
    words = [str(part) for part in parts if str(part) != ""]
    if not words:
        return ""
    if len(words) >= 2 and words[0].startswith("python") and words[1] == "link.py":
        return display_command(["link", *words[2:]])
    return display_command(words)


def _candidate_lines(candidates: object, *, include_reasons: bool = False) -> list[str]:
    lines: list[str] = []
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        return lines
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        title = candidate.get("title", "Untitled memory")
        path = candidate.get("path", "")
        lines.append(f"- {title} ({path})")
        if include_reasons:
            reasons = candidate.get("conflict_reasons")
            if isinstance(reasons, Sequence) and not isinstance(reasons, (str, bytes)):
                reason_text = ", ".join(str(reason) for reason in reasons if reason)
                if reason_text:
                    lines.append(f"  Reasons: {reason_text}")
    return lines


def _first_candidate_name(candidates: object) -> str | None:
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        return None
    for candidate in candidates:
        if isinstance(candidate, Mapping) and candidate.get("name"):
            return str(candidate["name"])
    return None


def format_counts(counts: Mapping[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{name}: {count}" for name, count in counts.items())


def render_remember_text(result: Mapping[str, object], *, target: object = ".") -> tuple[int, str]:
    if not result.get("created"):
        if result.get("secret"):
            return 1, "\n".join([
                "Not saved — this looks like a secret",
                f"Detected: {', '.join(str(w) for w in result.get('secret_warnings', []))}",
                "",
                str(result.get("message") or ""),
            ])
        if result.get("conflict"):
            lines = [
                "Possible conflicting memory found",
                f"Title requested: {result['title']}",
                f"Type: {result['memory_type']}",
                f"Scope: {result['scope']}",
                f"Visibility: {result.get('visibility', 'private')}",
                "",
                "Conflict candidates:",
                *_candidate_lines(result.get("conflict_candidates", []), include_reasons=True),
                "",
                "Next:",
            ]
            first = _first_candidate_name(result.get("conflict_candidates", []))
            if first:
                lines.append(
                    f"  Replace the old memory (archives it with lineage): rerun this remember with --supersedes {first}"
                )
                lines.append(f"  Inspect it first: {_shell_words('python3', 'link.py', 'explain-memory', first, target)}")
            lines.append("  Or update/archive the old memory manually; use --allow-conflict only if both should truly coexist.")
            return 0, "\n".join(lines)

        lines = [
            "Similar memory already exists",
            f"Title requested: {result['title']}",
            f"Type: {result['memory_type']}",
            f"Scope: {result['scope']}",
            f"Visibility: {result.get('visibility', 'private')}",
            "",
            "Existing candidates:",
            *_candidate_lines(result.get("candidates", [])),
            "",
            "Next:",
        ]
        first = _first_candidate_name(result.get("candidates", []))
        if first:
            lines.append(f"  {_shell_words('python3', 'link.py', 'explain-memory', first, target)}")
        lines.append("  Use --allow-duplicate only if this should be a separate memory.")
        return 0, "\n".join(lines)

    lines = [
        "Memory saved",
        f"Title: {result['title']}",
        f"Path: {result['path']}",
        f"Type: {result['memory_type']}",
        f"Scope: {result['scope']}",
        f"Visibility: {result.get('visibility', 'private')}",
    ]
    if result.get("project"):
        lines.append(f"Project: {result['project']}")
    if result.get("supersedes"):
        lines.append(f"Supersedes: {result['supersedes']} (archived with lineage)")
    if result.get("review_after"):
        lines.append(f"Review after: {result['review_after']}")
    if result.get("expires_at"):
        lines.append(f"Expires at: {result['expires_at']}")
    lines.extend([
        "",
        "Next:",
        f"  {_shell_words('python3', 'link.py', 'recall', result['title'], target)}",
    ])
    return 0, "\n".join(lines)


def render_update_memory_text(result: Mapping[str, object], *, target: object = ".") -> tuple[int, str]:
    if not result.get("updated") and result.get("conflict"):
        lines = [
            "Possible conflicting memory found",
            f"Memory being updated: {result['title']} ({result['path']})",
            "",
            "Conflict candidates:",
            *_candidate_lines(result.get("conflict_candidates", []), include_reasons=True),
            "",
            "Next:",
        ]
        first = _first_candidate_name(result.get("conflict_candidates", []))
        if first:
            lines.append(f"  {_shell_words('python3', 'link.py', 'explain-memory', first, target)}")
        lines.append("  Update/archive the conflicting memory, or use --allow-conflict only if both should coexist.")
        return 0, "\n".join(lines)

    return 0, "\n".join([
        "Memory updated",
        f"Title: {result['title']}",
        f"Path: {result['path']}",
        f"Update count: {result['update_count']}",
        f"Review: {result['previous_review_status']} -> {result['review_status']}",
        "",
        "Next:",
        f"  {_shell_words('python3', 'link.py', 'explain-memory', result['name'], target)}",
        f"  {_shell_words('python3', 'link.py', 'review-memory', result['name'], target)}",
    ])


def render_set_memory_visibility_text(result: Mapping[str, object], *, target: object = ".") -> tuple[int, str]:
    headline = "Memory visibility updated" if result.get("updated") else "Memory visibility already set"
    return 0, "\n".join([
        headline,
        f"Title: {result['title']}",
        f"Path: {result['path']}",
        f"Scope: {result['scope']}",
        f"Visibility: {result['previous_visibility']} -> {result['visibility']}",
        f"Review: {result.get('review_status', 'pending')}",
        "",
        "Next:",
        f"  {_shell_words('python3', 'link.py', 'explain-memory', result['name'], target)}",
        f"  {_shell_words('python3', 'link.py', 'team-sync', target)}",
    ])


def render_propose_memories_text(result: Mapping[str, object]) -> tuple[int, str]:
    proposals = result.get("proposals")
    if not isinstance(proposals, Sequence) or isinstance(proposals, (str, bytes)):
        proposals = []

    lines = [
        "Memory proposals",
        f"Source: {result.get('source')}",
    ]
    if result.get("project"):
        lines.append(f"Project: {result.get('project')}")
    lines.append(f"Count: {result.get('count', 0)}")
    if not proposals:
        lines.append("No durable memory candidates found.")
        return 0, "\n".join(lines)

    for index, proposal in enumerate(proposals, start=1):
        if not isinstance(proposal, Mapping):
            continue
        lines.extend([
            "",
            f"{index}. {proposal.get('title')} [{proposal.get('confidence')}]",
            f"   Type: {proposal.get('memory_type')} | Scope: {proposal.get('scope')}",
        ])
        if proposal.get("project"):
            lines.append(f"   Project: {proposal.get('project')}")
        lines.append(f"   Action: {proposal.get('suggested_action')}")
        lines.append(f"   Memory: {proposal.get('memory')}")
        primary_action = proposal.get("primary_action")
        if isinstance(primary_action, Mapping) and primary_action.get("command"):
            lines.append(f"   Command: {primary_action['command']}")
        duplicate_candidates = proposal.get("duplicate_candidates")
        if isinstance(duplicate_candidates, Sequence) and not isinstance(duplicate_candidates, (str, bytes)) and duplicate_candidates:
            first = duplicate_candidates[0]
            if isinstance(first, Mapping):
                lines.append(f"   Duplicate candidate: {first.get('title')} ({first.get('path')})")
    lines.extend([
        "",
        "Next:",
        "  Use remember for new memories, or update-memory for duplicate candidates.",
    ])
    return 0, "\n".join(lines)


def render_recall_text(
    *,
    query: str,
    results: Sequence[Mapping[str, object]],
    include_archived: bool = False,
    project: str | None = None,
    target: object = ".",
    miss_hint: str = "",
) -> tuple[int, str]:
    lines = [f"Link memory recall: {query}"]
    if project:
        lines.append(f"Project: {project}")
    if include_archived:
        lines.append("Including archived/stale memories")
    lines.append("")
    if not results:
        lines.append("No matching memories found.")
        if miss_hint:
            lines.extend(["", miss_hint])
        lines.extend([
            "",
            "Next:",
            f"  Add one: {_shell_words('python3', 'link.py', 'remember', 'Memory to keep', target)}",
        ])
        return 0, "\n".join(lines)

    lines.append(f"{len(results)} memor{'y' if len(results) == 1 else 'ies'}")
    top_confidence = str(results[0].get("confidence") or "")
    if top_confidence in {"", "weak"}:
        lines.append(
            "⚠ Best match is weak — treat as a hint. If asked to answer from memory, "
            "say the memory has nothing reliable on this rather than asserting."
        )
    for record in results:
        lines.append(f"- {record['title']} ({record['memory_type']} · {record['scope']})")
        lines.append(f"  {record['path']}")
        applicability = str(record.get("applicability") or "")
        if applicability == "out_of_context":
            lines.append("  Applies: out of context here — verify with the user before applying this memory.")
        elif applicability == "matched":
            lines.append("  Applies: conditions match this context.")
        trigger = str(record.get("trigger") or "").strip()
        if trigger:
            lines.append(f"  When: {trigger}")
        steps = str(record.get("steps") or "").strip()
        if steps:
            for step_line in steps.splitlines()[:4]:
                lines.append(f"    {step_line}")
            if len(steps.splitlines()) > 4:
                lines.append("    …")
        recall = record.get("recall") if isinstance(record.get("recall"), Mapping) else {}
        confidence = str(record.get("confidence") or "")
        if recall.get("state"):
            state_line = f"  Recall: {recall['state']}"
            if confidence:
                state_line += f" · match: {confidence}"
            lines.append(state_line)
        elif confidence:
            lines.append(f"  Match: {confidence}")
        summary = record.get("tldr") or record.get("snippet")
        if summary:
            lines.append(f"  {summary}")
    if results and all(str(record.get("confidence") or "") == "weak" for record in results):
        lines.extend([
            "",
            "All matches are weak (shared words only). Verify with the user "
            "before relying on them.",
        ])
    return 0, "\n".join(lines)


def render_memory_status_text(result: Mapping[str, object], *, action: str, target: object = ".") -> tuple[int, str]:
    if action == "archive":
        headline = "Memory archived" if result["updated"] else "Memory already archived"
        next_lines = [
            "",
            "Next:",
            f"  Restore: {_shell_words('python3', 'link.py', 'restore-memory', result['name'], target)}",
        ]
    elif action == "restore":
        headline = "Memory restored" if result["updated"] else "Memory already active"
        next_lines = []
    else:
        raise ValueError(f"Unsupported memory status action: {action}")

    return 0, "\n".join([
        headline,
        f"Title: {result['title']}",
        f"Path: {result['path']}",
        f"Previous status: {result['previous_status']}",
        f"Status: {result['status']}",
        *next_lines,
    ])


def render_forget_memory_text(result: Mapping[str, object], *, identifier: str, target: object = ".") -> tuple[int, str]:
    if not result.get("found"):
        return 1, f"Memory not found: {identifier}"
    if result.get("confirmation_required"):
        return 1, "\n".join([
            "Confirmation required.",
            f"Run: {_shell_words('python3', 'link.py', 'forget-memory', result['name'], target, '--confirm')}",
        ])
    return 0, "\n".join([
        "Memory forgotten",
        f"Title: {result['title']}",
        f"Deleted: {result['path']}",
        f"Backlinks rebuilt: {'yes' if result.get('backlinks_rebuilt') else 'no'}",
    ])


def render_review_memory_text(result: Mapping[str, object]) -> tuple[int, str]:
    lines = [
        "Memory reviewed" if result["updated"] else "Memory was already reviewed",
        f"Title: {result['title']}",
        f"Path: {result['path']}",
        f"Previous review status: {result['previous_review_status']}",
        f"Review status: {result['review_status']}",
    ]
    if result["remaining_issue_count"]:
        lines.extend([
            "",
            f"{result['remaining_issue_count']} issue{'s' if result['remaining_issue_count'] != 1 else ''} still need attention:",
        ])
        remaining = result.get("remaining_issues", [])
        if isinstance(remaining, Sequence) and not isinstance(remaining, (str, bytes)):
            for issue in remaining:
                if isinstance(issue, Mapping):
                    lines.append(f"- [{issue['severity']}] {issue['code']}: {issue['message']}")
    return 0, "\n".join(lines)


def render_memory_inbox_text(
    inbox: Mapping[str, object],
    *,
    target: object,
    include_archived: bool = False,
) -> tuple[int, str]:
    lines = [f"Link memory inbox: {target}"]
    if inbox.get("project"):
        lines.append(f"Project: {inbox['project']}")
    if include_archived:
        lines.append("Including archived memories")
    lines.append("")
    review_count = int(inbox.get("review_count") or 0)
    lines.append(f"{review_count} memor{'y' if review_count == 1 else 'ies'} need review")
    counts = inbox.get("counts_by_severity")
    if isinstance(counts, Mapping) and counts:
        lines.append(f"Severity: {format_counts(counts)}")
    lines.append("")
    items = inbox.get("items", [])
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)) or not items:
        lines.append("Inbox is clear.")
        return 0, "\n".join(lines)

    for item in items:
        if not isinstance(item, Mapping):
            continue
        lines.append(f"- {item['title']} ({item['memory_type']} · {item['scope']} · {item['status']})")
        lines.append(f"  {item['path']}")
        issues = item.get("issues", [])
        if isinstance(issues, Sequence) and not isinstance(issues, (str, bytes)):
            for issue in issues:
                if isinstance(issue, Mapping):
                    lines.append(f"  [{issue['severity']}] {issue['code']}: {issue['message']}")
        primary = item.get("primary_action") if isinstance(item.get("primary_action"), Mapping) else {}
        if primary:
            lines.append(f"  Next: {primary['label']} - {primary['description']}")
            lines.append(f"  Command: {primary['command']}")
        actions = []
        raw_actions = item.get("actions", [])
        if isinstance(raw_actions, Sequence) and not isinstance(raw_actions, (str, bytes)):
            primary_kind = primary.get("kind") if primary else None
            actions = [
                action
                for action in raw_actions
                if isinstance(action, Mapping) and action.get("kind") != primary_kind
            ][:3]
        if actions:
            labels = ", ".join(str(action.get("label") or "") for action in actions)
            lines.append(f"  Other actions: {labels}")
    return 0, "\n".join(lines)


def render_memory_log_text(payload: Mapping[str, object], *, target: object) -> tuple[int, str]:
    lines = [
        f"Link memory log: {target}",
        f"{payload.get('count', 0)} recent memory event(s)",
        str(payload.get("privacy_note") or ""),
        "",
    ]
    entries = payload.get("entries", [])
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)) or not entries:
        lines.extend([
            "No memory lifecycle events yet.",
            "",
            "Next:",
            f"  {_shell_words('python3', 'link.py', 'remember', 'a useful preference or decision', target)}",
        ])
        return 0, "\n".join(lines)
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        lines.append(
            f"- {entry.get('timestamp', '')} · {entry.get('operation', '')} · {entry.get('description', '')}"
        )
        summary = str(entry.get("summary") or "").strip()
        if summary:
            lines.append(f"  {summary}")
        impact = str(entry.get("impact") or "").strip()
        if impact:
            lines.append(f"  Impact: {impact}")
        changes = entry.get("changes", [])
        if isinstance(changes, Sequence) and not isinstance(changes, (str, bytes)):
            for change in changes[:4]:
                if isinstance(change, Mapping):
                    lines.append(
                        f"  Change: {change.get('field', '')} {change.get('from', '')} -> {change.get('to', '')}"
                    )
        paths = entry.get("memory_paths", [])
        if isinstance(paths, Sequence) and not isinstance(paths, (str, bytes)) and paths:
            lines.append("  Memories: " + ", ".join(str(path) for path in paths))
        details = entry.get("details", [])
        if isinstance(details, Sequence) and not isinstance(details, (str, bytes)):
            for detail in list(details)[:4]:
                lines.append(f"  - {detail}")
    actions = payload.get("next_actions", [])
    if isinstance(actions, Sequence) and not isinstance(actions, (str, bytes)) and actions:
        lines.extend(["", "Next actions:"])
        for action in actions:
            if isinstance(action, Mapping):
                lines.append(f"- {action.get('label')}: {action.get('command')}")
    return 0, "\n".join(lines)


def render_memory_wins_text(payload: Mapping[str, object], *, target: object) -> tuple[int, str]:
    lines = [
        f"Link memory wins: {target}",
        str(payload.get("honest_note") or ""),
        "",
        (
            f"{payload.get('active_count', 0)} active · "
            f"{payload.get('reviewed_active_count', 0)} reviewed · "
            f"{payload.get('review_count', 0)} need review · "
            f"{payload.get('project_count', 0)} projects"
        ),
        "",
        "Signals:",
    ]
    wins = payload.get("wins", [])
    if isinstance(wins, Sequence) and not isinstance(wins, (str, bytes)):
        for win in wins:
            if not isinstance(win, Mapping):
                continue
            lines.append(f"- {win.get('label')}: {win.get('count')}")
            lines.append(f"  {win.get('description')}")
    recent = payload.get("recent_memories", [])
    if isinstance(recent, Sequence) and not isinstance(recent, (str, bytes)) and recent:
        lines.extend(["", "Recent reusable memories:"])
        for memory in recent[:5]:
            if isinstance(memory, Mapping):
                lines.append(f"- {memory.get('title')} ({memory.get('memory_type')} · {memory.get('scope')})")
                summary = memory.get("tldr") or memory.get("snippet")
                if summary:
                    lines.append(f"  {summary}")
    actions = payload.get("next_actions", [])
    if isinstance(actions, Sequence) and not isinstance(actions, (str, bytes)) and actions:
        lines.extend(["", "Next:"])
        for action in actions:
            if isinstance(action, Mapping):
                lines.append(f"- {action.get('label')}: {action.get('command')}")
    prompts = payload.get("prompts", [])
    if isinstance(prompts, Sequence) and not isinstance(prompts, (str, bytes)) and prompts:
        lines.extend(["", "Useful prompts:"])
        for prompt in prompts[:4]:
            lines.append(f"- {prompt}")
    return 0, "\n".join(lines)


def render_explain_memory_text(explanation: Mapping[str, object]) -> tuple[int, str]:
    memory = explanation["memory"]
    recall_info = explanation["recall"]
    review = explanation["review"]
    provenance = explanation["provenance"]
    lifecycle = explanation["lifecycle"]
    graph = explanation["graph"]
    if not all(isinstance(value, Mapping) for value in (memory, recall_info, review, provenance, lifecycle, graph)):
        raise ValueError("Invalid memory explanation payload")

    lines = [
        f"Link memory explanation: {memory['title']}",
        "",
        f"Path: {memory['path']}",
        f"Type: {memory['memory_type']} · Scope: {memory['scope']} · Visibility: {memory.get('visibility', 'private')} · Status: {lifecycle['status']}",
        f"Source: {provenance['source'] or 'missing'}",
        f"Captured: {provenance['date_captured'] or 'missing'}",
        f"Review: {review['status']} · Issues: {review['issue_count']}",
        f"Recall: {recall_info['state']} ({'enabled' if recall_info['default_enabled'] else 'disabled'} by default)",
        f"Reason: {recall_info['reason']}",
    ]
    summary = memory.get("tldr") or memory.get("snippet")
    if summary:
        lines.extend(["", f"Summary: {summary}"])
    issues = review.get("issues", [])
    if isinstance(issues, Sequence) and not isinstance(issues, (str, bytes)) and issues:
        lines.extend(["", "Review issues:"])
        for issue in issues:
            if isinstance(issue, Mapping):
                lines.append(f"- [{issue['severity']}] {issue['code']}: {issue['message']}")
                lines.append(f"  Action: {issue['suggested_action']}")
    forward = graph.get("forward") if isinstance(graph.get("forward"), Sequence) else []
    inbound = graph.get("inbound") if isinstance(graph.get("inbound"), Sequence) else []
    lines.extend([
        "",
        "Graph:",
        f"- Forward links: {', '.join(str(item) for item in forward) if forward else 'none'}",
        f"- Inbound links: {', '.join(str(item) for item in inbound) if inbound else 'none'}",
    ])
    log_entries = explanation.get("log_entries", [])
    if isinstance(log_entries, Sequence) and not isinstance(log_entries, (str, bytes)) and log_entries:
        lines.extend(["", "Recent lifecycle log:"])
        for entry in log_entries[-3:]:
            first_line = next((line for line in str(entry).splitlines() if line.strip().startswith("## ")), "")
            lines.append(f"- {first_line[3:] if first_line.startswith('## ') else first_line or 'log entry'}")
    return 0, "\n".join(lines)


def render_memory_list(title: str, records: Sequence[Mapping[str, object]], *, empty: str = "none") -> str:
    lines = [title]
    if not records:
        lines.append(f"- {empty}")
        return "\n".join(lines)
    for record in records:
        lines.append(f"- {record['title']} ({record['memory_type']} · {record['scope']})")
        lines.append(f"  {record['path']}")
        summary = record.get("tldr") or record.get("snippet")
        if summary:
            lines.append(f"  {summary}")
    return "\n".join(lines)


def render_brief_text(payload: Mapping[str, object], *, query: str = "", project: str | None = None) -> tuple[int, str]:
    title = "Link memory brief"
    if query:
        title += f": {query}"
    lines = [title]
    if project:
        lines.append(f"Project: {project}")
    lines.append("")
    profile_data = payload["profile"]
    review = payload["review"]
    captures = payload["captures"]
    if not all(isinstance(value, Mapping) for value in (profile_data, review, captures)):
        raise ValueError("Invalid memory brief payload")
    lines.extend([
        (
            f"{profile_data['active_count']} active memories · "
            f"{payload['relevant_count']} relevant · "
            f"{review['count']} need review"
        ),
        f"Types: {format_counts(profile_data['by_type'])}",
        f"Scopes: {format_counts(profile_data['by_scope'])}",
        f"Visibility: {format_counts(profile_data.get('by_visibility', {}))}",
        "",
        render_memory_list("Relevant memories", payload.get("relevant_memories", [])),
    ])
    review_items = review.get("items", [])
    if isinstance(review_items, Sequence) and not isinstance(review_items, (str, bytes)) and review_items:
        lines.extend(["", "Review queue"])
        for item in review_items[:3]:
            if not isinstance(item, Mapping):
                continue
            lines.append(f"- {item['title']} ({item['memory_type']} · {item['scope']})")
            issues = item.get("issues", [])
            if isinstance(issues, Sequence) and not isinstance(issues, (str, bytes)) and issues:
                first_issue = issues[0]
                if isinstance(first_issue, Mapping):
                    lines.append(f"  [{first_issue['severity']}] {first_issue['code']}: {first_issue['message']}")
    capture_items = captures.get("items", [])
    if isinstance(capture_items, Sequence) and not isinstance(capture_items, (str, bytes)) and capture_items:
        lines.extend([
            "",
            "Raw captures",
            f"{captures['count']} saved · {captures['warning_count']} with secret-looking warnings",
        ])
        for capture in capture_items:
            if not isinstance(capture, Mapping):
                continue
            lines.append(f"- {capture['title']} ({capture['path']})")
            warnings = capture.get("secret_warnings", [])
            if isinstance(warnings, Sequence) and not isinstance(warnings, (str, bytes)) and warnings:
                lines.append("  Warnings: " + ", ".join(str(warning) for warning in warnings))
        lines.append(f"  Next: {captures['next_action']}")
    lines.extend(["", "Agent guidance"])
    for item in payload.get("agent_guidance", []):
        lines.append(f"- {item}")
    return 0, "\n".join(lines)


def render_profile_text(
    profile_data: Mapping[str, object],
    *,
    target: object,
    project: str | None = None,
) -> tuple[int, str]:
    lines = [f"Link memory profile: {target}"]
    if project:
        lines.append(f"Project: {project}")
    lines.append("")
    memory_count = int(profile_data["memory_count"])
    active_count = int(profile_data["active_count"])
    review_count = int(profile_data["review_count"])
    lines.extend([
        f"{memory_count} memor{'y' if memory_count == 1 else 'ies'} · {active_count} active · {review_count} need review",
        f"Types: {format_counts(profile_data['by_type'])}",
        f"Scopes: {format_counts(profile_data['by_scope'])}",
        f"Visibility: {format_counts(profile_data.get('by_visibility', {}))}",
    ])
    if profile_data["by_project"]:
        lines.append(f"Projects: {format_counts(profile_data['by_project'])}")
    lines.append(f"Status: {format_counts(profile_data['by_status'])}")
    tags = ", ".join(
        f"{item['tag']} ({item['count']})"
        for item in profile_data["top_tags"]
        if isinstance(item, Mapping)
    )
    if tags:
        lines.append(f"Tags: {tags}")
    lines.append("")

    if memory_count == 0:
        lines.extend([
            "No memories found.",
            "",
            "Next:",
            f"  Add one: {_shell_words('python3', 'link.py', 'remember', 'Memory to keep', target)}",
        ])
        return 0, "\n".join(lines)

    lines.extend([
        render_memory_list("Recent memories", profile_data["recent"]),
        "",
        render_memory_list("Preferences", profile_data["preferences"]),
        "",
        render_memory_list("Decisions", profile_data["decisions"]),
        "",
        render_memory_list("Project context", profile_data["projects"]),
    ])
    if profile_data["archived"]:
        lines.extend(["", render_memory_list("Archived memories", profile_data["archived"])])
    return 0, "\n".join(lines)


def render_memory_audit_text(payload: Mapping[str, object], *, target: object) -> tuple[int, str]:
    lines = [f"Link memory audit: {target}"]
    if payload["project"]:
        lines.append(f"Project: {payload['project']}")
    lines.extend([f"Status: {payload['status']}", ""])
    profile_data = payload["profile"]
    captures = payload["captures"]
    if not isinstance(profile_data, Mapping) or not isinstance(captures, Mapping):
        raise ValueError("Invalid memory audit payload")
    lines.extend([
        (
            f"Memories: {profile_data['memory_count']} total · "
            f"{profile_data['active_count']} active · "
            f"{profile_data['review_count']} need review"
        ),
        (
            f"Raw captures: {captures['count']} saved · "
            f"{captures['warning_count']} with secret-looking warnings · "
            f"{captures.get('read_warning_count', 0)} read warnings"
        ),
    ])
    risk_factors = payload.get("risk_factors", [])
    if isinstance(risk_factors, Sequence) and not isinstance(risk_factors, (str, bytes)) and risk_factors:
        lines.extend(["", "Needs attention"])
        for factor in risk_factors:
            if isinstance(factor, Mapping):
                lines.append(f"- {factor['code']}: {factor['message']}")
    lines.extend(["", "Next actions"])
    next_actions = payload.get("next_actions", [])
    if isinstance(next_actions, Sequence) and not isinstance(next_actions, (str, bytes)):
        for action in next_actions:
            if not isinstance(action, Mapping):
                continue
            marker = "recommended" if action["recommended"] else "optional"
            lines.append(f"- {action['label']} ({marker})")
            lines.append(f"  {action['command']}")
    return 0, "\n".join(lines)
