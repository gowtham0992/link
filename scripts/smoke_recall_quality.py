#!/usr/bin/env python3
"""Check that Link retrieves the right memory with tiny token budgets."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.memory import memory_records, recall_memories  # noqa: E402
from link_core.query import query_link  # noqa: E402
from link_core.wiki import build_backlinks, build_wiki_cache, close_wiki_cache  # noqa: E402


class SmokeFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def write_page(wiki: Path, rel: str, text: str) -> None:
    path = wiki / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_quality_wiki(root: Path) -> Path:
    wiki = root / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    write_page(wiki, "index.md", "# Index\n")
    write_page(wiki, "log.md", "# Log\n")
    write_page(
        wiki,
        "concepts/login-flow.md",
        "---\n"
        "type: concept\n"
        "title: Login flow\n"
        "aliases: [auth setup, authentication setup]\n"
        "tags: [authentication, setup]\n"
        "---\n\n"
        "# Login flow\n\n"
        "> **TLDR:** OAuth login setup for the app.\n\n"
        "## Overview\n\nAuthentication setup uses OAuth login configuration.\n",
    )
    write_page(
        wiki,
        "concepts/release-process.md",
        "---\n"
        "type: concept\n"
        "title: Release process\n"
        "tags: [release, publishing]\n"
        "---\n\n"
        "# Release process\n\n"
        "> **TLDR:** Version tags drive package publishing.\n",
    )
    write_page(
        wiki,
        "memories/prefer-oauth-login.md",
        "---\n"
        "type: memory\n"
        "title: Prefer OAuth login\n"
        "memory_type: preference\n"
        "scope: project\n"
        "project: link\n"
        "status: active\n"
        "date_captured: \"2026-05-05T00:00:00Z\"\n"
        "source: wiki/concepts/login-flow.md\n"
        "review_status: reviewed\n"
        "tags: [authentication]\n"
        "---\n\n"
        "# Prefer OAuth login\n\n"
        "> **TLDR:** User prefers OAuth login setup for authentication work.\n\n"
        "## Memory\n\nUser prefers OAuth login setup for authentication work.\n",
    )
    write_page(
        wiki,
        "memories/use-release-tags.md",
        "---\n"
        "type: memory\n"
        "title: Use release tags\n"
        "memory_type: decision\n"
        "scope: project\n"
        "project: link\n"
        "status: active\n"
        "date_captured: \"2026-05-05T00:00:00Z\"\n"
        "source: wiki/concepts/release-process.md\n"
        "review_status: reviewed\n"
        "tags: [release]\n"
        "---\n\n"
        "# Use release tags\n\n"
        "> **TLDR:** Use version tags for package publishing.\n\n"
        "## Memory\n\nUse version tags for package publishing.\n",
    )
    (wiki / "_backlinks.json").write_text(json.dumps(build_backlinks(wiki)), encoding="utf-8")
    return wiki


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="link-recall-quality-"))
    wiki = build_quality_wiki(root)
    cache = build_wiki_cache(wiki)
    try:
        records = memory_records(wiki)
        direct = recall_memories(records, "auth setup", limit=2, project="link")
        require(direct and direct[0]["name"] == "prefer-oauth-login", "auth setup did not recall OAuth login memory first")
        packet = query_link(wiki, "auth setup", cache, records, budget="micro", project="link")
        capsule = packet.get("recall_capsule", {})
        items = capsule.get("items", []) if isinstance(capsule, dict) else []
        require(items and items[0]["name"] == "prefer-oauth-login", "micro capsule did not rank OAuth login first")
        require(int(capsule.get("estimated_tokens") or 0) < 700, "micro capsule exceeded token target")
        release = query_link(wiki, "publishing version", cache, records, budget="micro", project="link")
        release_items = release.get("recall_capsule", {}).get("items", [])
        require(release_items and release_items[0]["name"] == "use-release-tags", "release paraphrase did not recall tag decision first")
    finally:
        close_wiki_cache(cache)
    print(f"Recall quality smoke passed in {root}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SmokeFailure as exc:
        print(f"Recall quality smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
