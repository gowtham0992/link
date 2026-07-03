#!/usr/bin/env python3
"""Check that Link's public CLI and MCP tool contracts do not drift."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_CLI_COMMANDS = {
    "accept-capture",
    "archive-memory",
    "backup",
    "benchmark",
    "brief",
    "capture-inbox",
    "capture-session",
    "connect",
    "compliance-export",
    "delete-capture",
    "demo",
    "doctor",
    "end",
    "explain-memory",
    "forget-memory",
    "graph-summary",
    "health",
    "import-obsidian",
    "ingest-status",
    "init",
    "memory-audit",
    "memory-inbox",
    "memory-log",
    "wins",
    "migrate",
    "next",
    "onboard",
    "operations",
    "profile",
    "proof",
    "prompts",
    "propose-memories",
    "query",
    "query-link",
    "rebuild-index",
    "rebuild-backlinks",
    "recall",
    "redact-capture",
    "remember",
    "restore-backup",
    "restore-memory",
    "review-memory",
    "serve",
    "set-memory-visibility",
    "session-end",
    "share",
    "snapshot",
    "start",
    "status",
    "team-sync",
    "try",
    "update-memory",
    "validate",
    "version",
    "verify-mcp",
    "welcome",
}

EXPECTED_MCP_TOOLS = {
    "accept_capture",
    "archive_memory",
    "backup_wiki",
    "capture_inbox",
    "capture_session",
    "delete_capture",
    "explain_memory",
    "forget_memory",
    "get_backlinks",
    "get_context",
    "get_graph",
    "get_graph_summary",
    "get_pages",
    "ingest_status",
    "link_operations",
    "link_status",
    "memory_audit",
    "memory_brief",
    "memory_inbox",
    "memory_log",
    "memory_profile",
    "memory_wins",
    "migrate_wiki",
    "propose_memories",
    "query_link",
    "rebuild_index",
    "rebuild_backlinks",
    "recall_memory",
    "redact_capture",
    "remember_memory",
    "restore_memory",
    "review_memory",
    "search_wiki",
    "set_memory_visibility",
    "starter_prompts",
    "update_memory",
    "validate_wiki",
}

EXPECTED_MCP_SLIM_TOOLS = {
    "admin",
    "ingest",
    "recall",
    "remember",
    "review",
    "status",
}

EXPECTED_MCP_PROMPTS = {
    "link_brief",
    "link_ingest",
    "link_remember",
    "link_review",
    "link_session_end",
    "link_start",
}

EXPECTED_MCP_RESOURCES = {
    "link://brief",
    "link://health",
    "link://instructions",
    "link://profile",
    "link://project",
}

DOCS_CLI_COMMANDS = EXPECTED_CLI_COMMANDS - {"end", "query-link"}
CLI_DOC_PATH = Path("docs/cli.html")
MCP_DOC_PATHS = (
    Path("docs/mcp.html"),
    Path("mcp_package/README.md"),
)


def _literal_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _literal_string_list(node: ast.AST) -> list[str]:
    if not isinstance(node, (ast.List, ast.Tuple)):
        return []
    values: list[str] = []
    for item in node.elts:
        value = _literal_string(item)
        if value is not None:
            values.append(value)
    return values


def cli_commands(path: Path = ROOT / "mcp_package/link_core/cli_parser.py") -> set[str]:
    """Return argparse subcommands and aliases declared by Link's CLI parser."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    commands: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "add_parser":
            continue
        if not node.args:
            continue
        command = _literal_string(node.args[0])
        if command:
            commands.add(command)
        for keyword in node.keywords:
            if keyword.arg == "aliases":
                commands.update(_literal_string_list(keyword.value))
    return commands


def _is_mcp_tool_decorator(node: ast.AST) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    return (
        isinstance(target, ast.Attribute)
        and target.attr == "tool"
        and isinstance(target.value, ast.Name)
        and target.value.id == "mcp"
    )


def _is_named_decorator(node: ast.AST, names: set[str]) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    return isinstance(target, ast.Name) and target.id in names


def mcp_tools(path: Path = ROOT / "mcp_package/link_mcp/server.py") -> set[str]:
    """Return full-surface functions exported through MCP."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    tools: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(
            _is_mcp_tool_decorator(decorator) or _is_named_decorator(decorator, {"_full_tool"})
            for decorator in node.decorator_list
        ):
            tools.add(node.name)
    return tools


def mcp_slim_tools(path: Path = ROOT / "mcp_package/link_mcp/server.py") -> set[str]:
    """Return slim-surface functions exported through MCP."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    tools: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(_is_named_decorator(decorator, {"_slim_tool"}) for decorator in node.decorator_list):
            tools.add(node.name)
    return tools


def _decorator_call(decorator: ast.AST, attr: str) -> ast.Call | None:
    if not isinstance(decorator, ast.Call):
        return None
    target = decorator.func
    if (
        isinstance(target, ast.Attribute)
        and target.attr == attr
        and isinstance(target.value, ast.Name)
        and target.value.id == "mcp"
    ):
        return decorator
    return None


def mcp_prompts(path: Path = ROOT / "mcp_package/link_mcp/server.py") -> set[str]:
    """Return prompt names exported through @mcp.prompt()."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    prompts: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            call = _decorator_call(decorator, "prompt")
            if call is None:
                continue
            name = None
            if call.args:
                name = _literal_string(call.args[0])
            for keyword in call.keywords:
                if keyword.arg == "name":
                    name = _literal_string(keyword.value)
            prompts.add(name or node.name)
    return prompts


def mcp_resources(path: Path = ROOT / "mcp_package/link_mcp/server.py") -> set[str]:
    """Return resource URIs exported through @mcp.resource()."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    resources: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            call = _decorator_call(decorator, "resource")
            if call is None or not call.args:
                continue
            uri = _literal_string(call.args[0])
            if uri:
                resources.add(uri)
    return resources


def _missing_terms(path: Path, terms: set[str]) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return sorted(term for term in terms if term not in text)


def _missing_cli_reference(path: Path = ROOT / CLI_DOC_PATH) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    missing: list[str] = []
    for command in sorted(DOCS_CLI_COMMANDS):
        command_tokens = (
            f"`lnk {command}",
            f"`link {command}",
            f"`python3 link.py {command}",
            f"lnk {command}",
            f"link {command}",
            f"python3 link.py {command}",
        )
        if not any(token in text for token in command_tokens):
            missing.append(command)
    return missing


def check_tool_contract(root: Path = ROOT) -> list[str]:
    findings: list[str] = []

    cli_parser_path = root / "mcp_package/link_core/cli_parser.py"
    actual_cli = cli_commands(cli_parser_path)
    missing_cli = sorted(EXPECTED_CLI_COMMANDS - actual_cli)
    extra_cli = sorted(actual_cli - EXPECTED_CLI_COMMANDS)
    if missing_cli:
        findings.append(f"{cli_parser_path.relative_to(root)} is missing CLI commands: {', '.join(missing_cli)}")
    if extra_cli:
        findings.append(f"{cli_parser_path.relative_to(root)} has undocumented CLI commands: {', '.join(extra_cli)}")

    actual_mcp = mcp_tools(root / "mcp_package/link_mcp/server.py")
    missing_mcp = sorted(EXPECTED_MCP_TOOLS - actual_mcp)
    extra_mcp = sorted(actual_mcp - EXPECTED_MCP_TOOLS)
    if missing_mcp:
        findings.append(f"link_mcp.server is missing MCP tools: {', '.join(missing_mcp)}")
    if extra_mcp:
        findings.append(f"link_mcp.server has undocumented MCP tools: {', '.join(extra_mcp)}")

    actual_slim = mcp_slim_tools(root / "mcp_package/link_mcp/server.py")
    missing_slim = sorted(EXPECTED_MCP_SLIM_TOOLS - actual_slim)
    extra_slim = sorted(actual_slim - EXPECTED_MCP_SLIM_TOOLS)
    if missing_slim:
        findings.append(f"link_mcp.server is missing slim MCP tools: {', '.join(missing_slim)}")
    if extra_slim:
        findings.append(f"link_mcp.server has undocumented slim MCP tools: {', '.join(extra_slim)}")

    actual_prompts = mcp_prompts(root / "mcp_package/link_mcp/server.py")
    missing_prompts = sorted(EXPECTED_MCP_PROMPTS - actual_prompts)
    extra_prompts = sorted(actual_prompts - EXPECTED_MCP_PROMPTS)
    if missing_prompts:
        findings.append(f"link_mcp.server is missing MCP prompts: {', '.join(missing_prompts)}")
    if extra_prompts:
        findings.append(f"link_mcp.server has undocumented MCP prompts: {', '.join(extra_prompts)}")

    actual_resources = mcp_resources(root / "mcp_package/link_mcp/server.py")
    missing_resources = sorted(EXPECTED_MCP_RESOURCES - actual_resources)
    extra_resources = sorted(actual_resources - EXPECTED_MCP_RESOURCES)
    if missing_resources:
        findings.append(f"link_mcp.server is missing MCP resources: {', '.join(missing_resources)}")
    if extra_resources:
        findings.append(f"link_mcp.server has undocumented MCP resources: {', '.join(extra_resources)}")

    missing_cli_docs = _missing_cli_reference(root / CLI_DOC_PATH)
    if missing_cli_docs:
        findings.append(f"{CLI_DOC_PATH} command reference is missing: {', '.join(missing_cli_docs)}")

    for relative_path in MCP_DOC_PATHS:
        path = root / relative_path
        missing = _missing_terms(path, EXPECTED_MCP_TOOLS | EXPECTED_MCP_SLIM_TOOLS | EXPECTED_MCP_PROMPTS | EXPECTED_MCP_RESOURCES)
        if missing:
            findings.append(f"{relative_path} is missing MCP tools: {', '.join(missing)}")

    return findings


def main() -> int:
    findings = check_tool_contract()
    if findings:
        print("Tool contract check failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1

    print("Tool contract check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
