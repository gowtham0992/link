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
    "migrate",
    "next",
    "operations",
    "profile",
    "prompts",
    "propose-memories",
    "query",
    "query-link",
    "rebuild-index",
    "rebuild-backlinks",
    "recall",
    "redact-capture",
    "remember",
    "restore-memory",
    "review-memory",
    "serve",
    "share",
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
    "starter_prompts",
    "update_memory",
    "validate_wiki",
}

DOCS_CLI_COMMANDS = EXPECTED_CLI_COMMANDS - {"query-link"}
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


def mcp_tools(path: Path = ROOT / "mcp_package/link_mcp/server.py") -> set[str]:
    """Return functions exported through @mcp.tool()."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    tools: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(_is_mcp_tool_decorator(decorator) for decorator in node.decorator_list):
            tools.add(node.name)
    return tools


def _missing_terms(path: Path, terms: set[str]) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return sorted(term for term in terms if term not in text)


def _missing_cli_reference(path: Path = ROOT / CLI_DOC_PATH) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    missing: list[str] = []
    for command in sorted(DOCS_CLI_COMMANDS):
        command_tokens = (
            f"`link {command}",
            f"`python3 link.py {command}",
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

    missing_cli_docs = _missing_cli_reference(root / CLI_DOC_PATH)
    if missing_cli_docs:
        findings.append(f"{CLI_DOC_PATH} command reference is missing: {', '.join(missing_cli_docs)}")

    for relative_path in MCP_DOC_PATHS:
        path = root / relative_path
        missing = _missing_terms(path, EXPECTED_MCP_TOOLS)
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
