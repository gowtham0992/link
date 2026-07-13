#!/usr/bin/env python3
"""Smoke test a real Link MCP stdio server with the MCP client SDK."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_FULL_TOOLS = {
    "link_status",
    "starter_prompts",
    "migrate_wiki",
    "ingest_status",
    "query_link",
    "validate_wiki",
    "backup_wiki",
    "search_wiki",
    "get_context",
    "get_graph",
    "get_graph_summary",
    "recall_memory",
    "memory_profile",
    "rebuild_index",
    "explain_memory",
}

EXPECTED_SLIM_TOOLS = {
    "admin",
    "ingest",
    "recall",
    "remember",
    "review",
    "status",
}

EXPECTED_PROMPTS = {
    "link_brief",
    "link_ingest",
    "link_remember",
    "link_review",
    "link_session_end",
    "link_start",
}

EXPECTED_RESOURCES = {
    "link://brief",
    "link://health",
    "link://instructions",
    "link://profile",
    "link://project",
}


def _json_text(result: Any, tool_name: str) -> dict[str, Any]:
    is_error = getattr(result, "isError", getattr(result, "is_error", False))
    if is_error:
        raise RuntimeError(f"{tool_name} returned an MCP error result")
    if not result.content:
        raise RuntimeError(f"{tool_name} returned no content")
    text = getattr(result.content[0], "text", "")
    if not text:
        raise RuntimeError(f"{tool_name} returned non-text content")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{tool_name} returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{tool_name} returned JSON {type(payload).__name__}, expected object")
    return payload


async def _assert_prompt_and_resource_contract(session: Any) -> None:
    from pydantic import AnyUrl

    prompts = await session.list_prompts()
    prompt_names = {prompt.name for prompt in prompts.prompts}
    missing_prompts = sorted(EXPECTED_PROMPTS - prompt_names)
    if missing_prompts:
        raise RuntimeError(f"missing MCP prompts: {', '.join(missing_prompts)}")

    prompt = await session.get_prompt("link_brief", {"task": "agent memory"})
    prompt_text = getattr(prompt.messages[0].content, "text", "") if prompt.messages else ""
    if "recall(query='agent memory'" not in prompt_text:
        raise RuntimeError("link_brief prompt did not render recall guidance")
    start_prompt = await session.get_prompt("link_start", {"task": "release work"})
    start_text = getattr(start_prompt.messages[0].content, "text", "") if start_prompt.messages else ""
    if "recall(query='', mode='brief'" not in start_text or "recall_capsule" not in start_text:
        raise RuntimeError("link_start prompt did not render startup recall guidance")
    end_prompt = await session.get_prompt("link_session_end", {"summary": "we decided to keep memory review-gated"})
    end_text = getattr(end_prompt.messages[0].content, "text", "") if end_prompt.messages else ""
    if "admin(action='session_end'" not in end_text or "without silently saving durable memory" not in end_text:
        raise RuntimeError("link_session_end prompt did not render proposal-only guidance")

    resources = await session.list_resources()
    resource_uris = {str(resource.uri) for resource in resources.resources}
    missing_resources = sorted(EXPECTED_RESOURCES - resource_uris)
    if missing_resources:
        raise RuntimeError(f"missing MCP resources: {', '.join(missing_resources)}")

    resource = await session.read_resource(AnyUrl("link://health"))
    resource_text = getattr(resource.contents[0], "text", "") if resource.contents else ""
    try:
        health = json.loads(resource_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"link://health returned invalid JSON: {exc}") from exc
    if health.get("ready") is not True:
        raise RuntimeError("link://health did not report a ready demo wiki")
    instructions = await session.read_resource(AnyUrl("link://instructions"))
    instructions_text = getattr(instructions.contents[0], "text", "") if instructions.contents else ""
    if "recall(query=\"\", mode=\"brief\"" not in instructions_text or "Never silently save durable memory" not in instructions_text:
        raise RuntimeError("link://instructions did not render the portable agent loop")


async def _run_full_smoke(session: Any) -> None:
    listed = await session.list_tools()
    tool_names = {tool.name for tool in listed.tools}
    missing = sorted(EXPECTED_FULL_TOOLS - tool_names)
    if missing:
        raise RuntimeError(f"missing MCP tools: {', '.join(missing)}")

    status = _json_text(
        await session.call_tool(
            "link_status",
            {"include_validation": True},
            read_timeout_seconds=timedelta(seconds=10),
        ),
        "link_status",
    )
    if not status.get("ready") or status.get("validation", {}).get("passed") is not True:
        raise RuntimeError("link_status did not report the demo wiki as ready")

    prompts = _json_text(
        await session.call_tool(
            "starter_prompts",
            {"project": "mcp-smoke"},
            read_timeout_seconds=timedelta(seconds=10),
        ),
        "starter_prompts",
    )
    if prompts.get("project") != "mcp-smoke" or prompts.get("prompts", [{}])[0].get("prompt") != "is Link ready?":
        raise RuntimeError("starter_prompts did not return the expected first-run guidance")

    search = _json_text(
        await session.call_tool(
            "search_wiki",
            {"query": "agent memory", "limit": 3},
            read_timeout_seconds=timedelta(seconds=10),
        ),
        "search_wiki",
    )
    result_names = [r.get("name") for r in search.get("results", []) if isinstance(r, dict)]
    if search.get("count", 0) < 1 or "agent-memory" not in result_names:
        raise RuntimeError(
            f"search_wiki did not surface the demo page; got {result_names}"
        )

    packet = _json_text(
        await session.call_tool(
            "query_link",
            {"query": "agent memory", "budget": "small"},
            read_timeout_seconds=timedelta(seconds=10),
        ),
        "query_link",
    )
    wiki = packet.get("wiki") if isinstance(packet.get("wiki"), dict) else {}
    page_names = [p.get("name") for p in (wiki.get("pages") or []) if isinstance(p, dict)]
    if not packet.get("found") or "agent-memory" not in page_names:
        raise RuntimeError(
            "query_link did not surface the demo page; "
            f"found={packet.get('found')} primary={wiki.get('primary')} pages={page_names[:5]}"
        )
    if not packet.get("context_packet"):
        raise RuntimeError("query_link returned an empty context packet")

    validation = _json_text(
        await session.call_tool(
            "validate_wiki",
            {},
            read_timeout_seconds=timedelta(seconds=10),
        ),
        "validate_wiki",
    )
    if not validation.get("passed") or validation.get("error_count") != 0:
        raise RuntimeError("validate_wiki did not accept the demo wiki")

    backup = _json_text(
        await session.call_tool(
            "backup_wiki",
            {"label": "mcp-smoke"},
            read_timeout_seconds=timedelta(seconds=10),
        ),
        "backup_wiki",
    )
    if not backup.get("created") or "wiki" not in backup.get("included", []):
        raise RuntimeError("backup_wiki did not create a wiki backup")

    context = _json_text(
        await session.call_tool(
            "get_context",
            {"topic": "agent memory"},
            read_timeout_seconds=timedelta(seconds=10),
        ),
        "get_context",
    )
    if not context.get("found") or context.get("primary") != "agent-memory":
        raise RuntimeError("get_context did not return the expected primary page")

    graph_summary = _json_text(
        await session.call_tool(
            "get_graph_summary",
            {"topic": "agent memory", "limit": 5, "depth": 1},
            read_timeout_seconds=timedelta(seconds=10),
        ),
        "get_graph_summary",
    )
    if graph_summary.get("returned_nodes", 0) > 5:
        raise RuntimeError("get_graph_summary ignored the node limit")
    if not graph_summary.get("nodes"):
        raise RuntimeError("get_graph_summary did not return any nodes")

    profile = _json_text(
        await session.call_tool(
            "memory_profile",
            {},
            read_timeout_seconds=timedelta(seconds=10),
        ),
        "memory_profile",
    )
    if profile.get("memory_count", 0) < 1:
        raise RuntimeError("memory_profile did not see the demo memory")

    rebuilt_index = _json_text(
        await session.call_tool(
            "rebuild_index",
            {},
            read_timeout_seconds=timedelta(seconds=10),
        ),
        "rebuild_index",
    )
    if not rebuilt_index.get("rebuilt") or rebuilt_index.get("page_count", 0) < 1:
        raise RuntimeError("rebuild_index did not rebuild the demo catalog")

    rebuilt_backlinks = _json_text(
        await session.call_tool(
            "rebuild_backlinks",
            {},
            read_timeout_seconds=timedelta(seconds=10),
        ),
        "rebuild_backlinks",
    )
    if not rebuilt_backlinks.get("rebuilt"):
        raise RuntimeError("rebuild_backlinks did not repair the demo graph")


async def _run_slim_smoke(session: Any) -> None:
    listed = await session.list_tools()
    tool_names = {tool.name for tool in listed.tools}
    missing = sorted(EXPECTED_SLIM_TOOLS - tool_names)
    if missing:
        raise RuntimeError(f"missing slim MCP tools: {', '.join(missing)}")
    full_only = sorted(EXPECTED_FULL_TOOLS & tool_names)
    if full_only:
        raise RuntimeError(f"slim surface exposed full MCP tools: {', '.join(full_only)}")

    status = _json_text(
        await session.call_tool(
            "status",
            {"include_validation": True},
            read_timeout_seconds=timedelta(seconds=10),
        ),
        "status",
    )
    if not status.get("ready") or status.get("validation", {}).get("passed") is not True:
        raise RuntimeError("slim status did not report the demo wiki as ready")

    packet = _json_text(
        await session.call_tool(
            "recall",
            {"query": "agent memory", "budget": "small"},
            read_timeout_seconds=timedelta(seconds=10),
        ),
        "recall",
    )
    wiki = packet.get("wiki") if isinstance(packet.get("wiki"), dict) else {}
    page_names = [p.get("name") for p in (wiki.get("pages") or []) if isinstance(p, dict)]
    if not packet.get("found") or "agent-memory" not in page_names:
        # Report the server's own page/search counts so we can tell an
        # empty-wiki problem (0 content pages) from a search problem
        # (pages present, recall returns none).
        raise RuntimeError(
            "slim recall did not surface the demo page; "
            f"found={packet.get('found')} primary={wiki.get('primary')} pages={page_names[:5]} "
            f"| status.content_pages={status.get('content_page_count')} "
            f"status.pages={status.get('page_count')} "
            f"wiki.search_count={wiki.get('search_count')} "
            f"strategy={packet.get('strategy')}"
        )

    brief = _json_text(
        await session.call_tool(
            "recall",
            {"mode": "brief"},
            read_timeout_seconds=timedelta(seconds=10),
        ),
        "recall",
    )
    if brief.get("mode") != "brief" or brief.get("brief", {}).get("relevant_count", 0) < 1:
        raise RuntimeError("slim recall brief did not include demo memory")

    ingest = _json_text(
        await session.call_tool(
            "ingest",
            {},
            read_timeout_seconds=timedelta(seconds=10),
        ),
        "ingest",
    )
    if ingest.get("pending_count") != 0:
        raise RuntimeError("slim ingest did not report the demo as fully represented")

    review = _json_text(
        await session.call_tool(
            "review",
            {"action": "profile"},
            read_timeout_seconds=timedelta(seconds=10),
        ),
        "review",
    )
    if review.get("memory_count", 0) < 1:
        raise RuntimeError("slim review profile did not see demo memory")

    admin = _json_text(
        await session.call_tool(
            "admin",
            {"action": "validate", "arguments": "{\"strict\": true}"},
            read_timeout_seconds=timedelta(seconds=10),
        ),
        "admin",
    )
    if not admin.get("passed"):
        raise RuntimeError("slim admin validate did not accept the demo wiki")


async def _run_smoke(wiki_dir: Path, python: str, surface: str) -> None:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    env = os.environ.copy()
    local_package = str(ROOT / "mcp_package")
    env["PYTHONPATH"] = (
        local_package
        if not env.get("PYTHONPATH")
        else local_package + os.pathsep + str(env["PYTHONPATH"])
    )
    server_args = ["-m", "link_mcp", "--wiki", str(wiki_dir)]
    expected_surface = "slim" if surface == "default" else surface
    if surface != "default":
        server_args.extend(["--surface", surface])
    server = StdioServerParameters(command=python, args=server_args, env=env)
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            await _assert_prompt_and_resource_contract(session)
            if expected_surface == "slim":
                await _run_slim_smoke(session)
            else:
                await _run_full_smoke(session)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Link MCP over stdio.")
    parser.add_argument("wiki", help="path to a Link wiki directory")
    parser.add_argument("--python", default=sys.executable, help="Python executable used to run -m link_mcp")
    parser.add_argument("--surface", choices=("default", "full", "slim"), default="default")
    args = parser.parse_args()

    wiki_dir = Path(args.wiki).expanduser().resolve()
    if not (wiki_dir / "index.md").exists():
        print(f"MCP smoke failed: {wiki_dir} does not look like a Link wiki", file=sys.stderr)
        return 1

    try:
        import anyio

        anyio.run(_run_smoke, wiki_dir, args.python, args.surface)
    except BaseException as exc:  # noqa: BLE001 - surface the real cause
        # The MCP session wraps handler failures in anyio TaskGroups, so a
        # plain str(exc) is just "unhandled errors in a TaskGroup". Unwrap
        # nested ExceptionGroups to the leaf so CI shows what actually broke.
        def _leaves(err: BaseException) -> list[str]:
            subs = getattr(err, "exceptions", None)
            if not subs:
                return [f"{type(err).__name__}: {err}"]
            out: list[str] = []
            for sub in subs:
                out.extend(_leaves(sub))
            return out

        for leaf in _leaves(exc):
            print(f"MCP smoke failed: {leaf}", file=sys.stderr)
        return 1

    print(f"MCP stdio smoke passed for {wiki_dir} ({args.surface} surface)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
