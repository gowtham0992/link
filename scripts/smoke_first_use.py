#!/usr/bin/env python3
"""Exercise Link's first-use path the way a new local user would."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


class SmokeFailure(RuntimeError):
    pass


def run_link(*args: str, python: str = sys.executable) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [python, str(ROOT / "link.py"), *args],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        command = " ".join([python, "link.py", *args])
        raise SmokeFailure(
            f"command failed ({result.returncode}): {command}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def run_json(*args: str, python: str = sys.executable) -> dict[str, Any]:
    result = run_link(*args, python=python)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        command = " ".join([python, "link.py", *args])
        raise SmokeFailure(f"command returned invalid JSON: {command}\n{result.stdout}") from exc
    if not isinstance(payload, dict):
        command = " ".join([python, "link.py", *args])
        raise SmokeFailure(f"command returned {type(payload).__name__}, expected JSON object: {command}")
    return payload


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def run_smoke(work_dir: Path, python: str = sys.executable) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    init_target = work_dir / "new-user-link"
    demo_target = work_dir / "demo-link"

    run_link("init", str(init_target), python=python)
    require((init_target / "link.py").exists(), "init did not copy link.py")
    require((init_target / "serve.py").exists(), "init did not copy serve.py")
    require((init_target / "wiki/_link_schema.json").exists(), "init did not write schema marker")

    init_status = run_json("status", str(init_target), "--validate", "--json", python=python)
    require(init_status.get("ready") is True, "initialized wiki did not report ready")
    require(init_status.get("schema", {}).get("status") == "current", "initialized wiki schema is not current")

    init_prompts = run_json("prompts", str(init_target), "--json", python=python)
    require(len(init_prompts.get("prompts", [])) >= 6, "prompts did not return the first-run prompt set")
    require(
        init_prompts.get("prompts", [{}])[0].get("prompt") == "is Link ready?",
        "prompts did not start with readiness guidance",
    )
    require(
        any("health" in str(command).split() for command in init_prompts.get("commands", [])),
        "prompts did not include readiness command",
    )
    init_welcome = run_json("welcome", str(init_target), "--json", python=python)
    require(len(init_welcome.get("steps", [])) == 3, "welcome did not return the short proof path")
    require(
        init_welcome.get("steps", [{}])[0].get("prompt") == "is Link ready?",
        "welcome did not start with readiness guidance",
    )
    require(
        "http://127.0.0.1:3000/health" in init_welcome.get("urls", []),
        "welcome did not include the local health URL",
    )

    demo_result = run_link("demo", str(demo_target), "--force", python=python)
    require("Try the value loop:" in demo_result.stdout, "demo output did not show the value loop")
    require(
        "query 'why does Link help agents?'" in demo_result.stdout
        or 'query "why does Link help agents?"' in demo_result.stdout,
        "demo output did not show the query proof command",
    )
    require("START_HERE.md" in demo_result.stdout, "demo output did not point to START_HERE.md")
    require((demo_target / "START_HERE.md").exists(), "demo did not create START_HERE.md")
    start_here = (demo_target / "START_HERE.md").read_text(encoding="utf-8")
    require("query Link for why Link helps agents" in start_here, "START_HERE.md did not include agent prompt")
    require("python3 link.py query" in start_here, "START_HERE.md did not include CLI proof command")

    demo_status = run_json("status", str(demo_target), "--validate", "--json", python=python)
    require(demo_status.get("ready") is True, "demo wiki did not report ready")
    require(demo_status.get("validation", {}).get("passed") is True, "demo validation did not pass")
    require(int(demo_status.get("memory_count") or 0) >= 1, "demo did not include a starter memory")

    project_prompts = run_json("prompts", str(demo_target), "--project", "demo", "--json", python=python)
    require(
        "this project uses Link" in project_prompts.get("prompts", [{}, {}, {}])[2].get("prompt", ""),
        "project prompts did not include project memory guidance",
    )

    backup = run_json("backup", str(demo_target), "--label", "first-use-smoke", "--json", python=python)
    require(backup.get("created") is True, "backup did not create an archive")
    require(backup.get("included") == ["wiki"], "backup did not default to wiki-only")
    require((demo_target / ".link-backups" / str(backup["name"])).exists(), "backup archive is missing")

    query = run_json("query", "what is Link agent memory?", str(demo_target), "--budget", "small", "--json", python=python)
    require(query.get("found") is True, "query did not find demo context")
    require(bool(query.get("context_packet")), "query returned an empty context packet")
    require(query.get("budget_report", {}).get("context_packet", {}).get("returned", 0) <= 6, "small query budget was not enforced")

    graph_summary = run_json("graph-summary", "agent memory", str(demo_target), "--limit", "10", "--json", python=python)
    require(graph_summary.get("returned_nodes", 0) >= 1, "graph-summary did not return demo graph context")
    require(graph_summary.get("returned_nodes", 0) <= 10, "graph-summary did not enforce first-use node limit")

    benchmark = run_json("benchmark", "agent memory", str(demo_target), "--budget", "small", "--json", python=python)
    require(benchmark.get("health", {}).get("status") == "pass", "benchmark health did not pass on demo wiki")
    require(benchmark.get("graph_initial", {}).get("mode") in {"full", "summary"}, "benchmark did not report graph initial-load mode")

    brief = run_json("brief", "testing Link as local personal memory", str(demo_target), "--json", python=python)
    require(brief.get("profile", {}).get("memory_count", 0) >= 1, "brief did not include memory profile")
    require("agent_guidance" in brief, "brief did not include agent guidance")

    remembered = run_json(
        "remember",
        "User is testing Link first-use smoke as local personal memory for agents.",
        str(demo_target),
        "--title",
        "First-use smoke memory",
        "--type",
        "note",
        "--source",
        "first-use-smoke",
        "--json",
        python=python,
    )
    require(remembered.get("created") is True, "remember did not create a first-use memory")
    require((demo_target / "wiki/memories/first-use-smoke-memory.md").exists(), "remembered memory page is missing")

    recalled = run_json("recall", "first-use smoke", str(demo_target), "--json", python=python)
    require(recalled.get("count", 0) >= 1, "recall did not find the remembered first-use memory")

    capture_note = work_dir / "session-note.md"
    capture_note.write_text(
        "Remember that first-use smoke keeps memory approval local and explicit.",
        encoding="utf-8",
    )
    captured = run_json("capture-session", str(capture_note), str(demo_target), "--json", python=python)
    require(captured.get("captured") is True, "capture-session did not save the session note")
    require(str(captured.get("path", "")).startswith("raw/memory-captures/"), "capture path was not under raw/memory-captures")

    inbox = run_json("capture-inbox", str(demo_target), "--json", python=python)
    require(inbox.get("count", 0) >= 1, "capture-inbox did not show the saved capture")

    raw_source = demo_target / "raw/new-user-source.md"
    raw_source.write_text("# New user source\n\nA pending raw source for first-use smoke.\n", encoding="utf-8")
    ingest = run_json("ingest-status", str(demo_target), "--json", python=python)
    require(ingest.get("pending_count") == 1, "ingest-status did not report the pending raw source")
    require(ingest.get("guidance", {}).get("agent_prompt"), "ingest-status did not include the next agent prompt")
    require(ingest.get("plan", {}).get("batch"), "ingest-status did not include a guided ingest batch")

    run_link("rebuild-index", str(demo_target), python=python)
    require("[[first-use-smoke-memory]]" in (demo_target / "wiki/index.md").read_text(encoding="utf-8"), "rebuild-index did not catalog the remembered memory")
    run_link("rebuild-backlinks", str(demo_target), python=python)

    validation = run_json("validate", str(demo_target), "--strict", "--json", python=python)
    require(validation.get("passed") is True, "validate --strict did not pass after first-use actions")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Link's first-use local workflow.")
    parser.add_argument("--work-dir", default="", help="directory for temporary smoke artifacts")
    parser.add_argument("--python", default=sys.executable, help="Python executable used to run link.py")
    args = parser.parse_args()

    work_dir = Path(args.work_dir).expanduser().resolve() if args.work_dir else Path(tempfile.mkdtemp(prefix="link-first-use-"))
    try:
        run_smoke(work_dir, python=args.python)
    except SmokeFailure as exc:
        print(f"First-use smoke failed: {exc}", file=sys.stderr)
        return 1

    print(f"First-use smoke passed in {work_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
