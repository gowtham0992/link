#!/usr/bin/env python3
"""Smoke test the generated Link local HTTP viewer over a real localhost socket."""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


class SmokeFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def create_demo(target: Path, python: str) -> None:
    result = subprocess.run(
        [python, str(ROOT / "link.py"), "demo", str(target), "--force"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SmokeFailure(
            "demo creation failed\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


def request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    body = None
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=body,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return int(response.status), dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), dict(exc.headers.items()), exc.read()


def request_json(base_url: str, path: str, **kwargs: Any) -> tuple[int, dict[str, str], dict[str, Any]]:
    status, headers, body = request(base_url, path, **kwargs)
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise SmokeFailure(f"{path} returned invalid JSON: {body[:200]!r}") from exc
    if not isinstance(payload, dict):
        raise SmokeFailure(f"{path} returned {type(payload).__name__}, expected object")
    return status, headers, payload


def wait_until_ready(base_url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=1)
            raise SmokeFailure(
                f"server exited early with {process.returncode}\n"
                f"stdout:\n{stdout}\n"
                f"stderr:\n{stderr}"
            )
        try:
            status, _, _ = request_json(base_url, "/api/status")
            if status == 200:
                return
        except Exception:
            pass
        time.sleep(0.1)
    raise SmokeFailure("server did not become ready within 10 seconds")


def run_smoke(work_dir: Path, python: str) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    demo_target = work_dir / "http-viewer-demo"
    create_demo(demo_target, python)

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [python, "serve.py", "--port", str(port)],
        cwd=demo_target,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_until_ready(base_url, process)

        status, headers, body = request(base_url, "/")
        html = body.decode("utf-8", errors="replace")
        require(status == 200, "home page did not return 200")
        require("Link" in html and "agent memory" in html, "home page did not render Link shell")
        require(headers.get("X-Link-API-Version") == "1", "home page missing API version header")
        require(headers.get("Cache-Control") == "no-store", "home page missing no-store cache policy")
        require("frame-ancestors 'none'" in headers.get("Content-Security-Policy", ""), "home page missing frame CSP")

        status, headers, body = request(base_url, "/graph")
        graph_html = body.decode("utf-8", errors="replace")
        require(status == 200, "graph page did not return 200")
        require("Knowledge Graph" in graph_html, "graph page did not render")
        require("graph-canvas" in graph_html, "graph page did not include the canvas")

        status, _, body = request(base_url, "/health")
        health_html = body.decode("utf-8", errors="replace")
        require(status == 200, "health page did not return 200")
        require("Health" in health_html, "health page did not render")
        require("Repair Commands" in health_html, "health page did not show repair commands")
        require(
            "lnk operations" in health_html or "link.py operations" in health_html,
            "health page did not include operation inspection guidance",
        )

        status, headers, status_payload = request_json(base_url, "/api/status?validate=true")
        require(status == 200, "status API did not return 200")
        require(status_payload.get("ready") is True, "status API did not report ready")
        require(status_payload.get("validation", {}).get("passed") is True, "status API validation did not pass")
        require(headers.get("Content-Type") == "application/json", "status API content type changed")

        status, _, operations = request_json(base_url, "/api/operations")
        require(status == 200, "operations API did not return 200")
        require(operations.get("operation_count") == 0, "demo should not have interrupted operation markers")
        require(operations.get("api_version") == "1", "operations API missing version")

        query = urllib.parse.quote("agent memory")
        status, _, summary = request_json(base_url, f"/api/graph-summary?q={query}&limit=5")
        require(status == 200, "graph-summary API did not return 200")
        require(summary.get("returned_nodes", 0) <= 5, "graph-summary API ignored node limit")

        status, _, denied = request_json(base_url, "/api/rebuild-backlinks", method="POST", payload={})
        require(status == 403, "mutation without local action header did not fail closed")
        require("X-Link-Local-Action" in str(denied.get("error", "")), "mutation guard error was not actionable")

        status, _, rebuilt = request_json(
            base_url,
            "/api/rebuild-backlinks",
            method="POST",
            payload={},
            headers={"X-Link-Local-Action": "true"},
        )
        require(status == 200, "authorized rebuild-backlinks did not return 200")
        require(rebuilt.get("rebuilt") is True, "authorized rebuild-backlinks did not rebuild")

        status, _, options_payload = request_json(base_url, "/api/status", method="OPTIONS")
        require(status == 405, "OPTIONS did not return controlled 405")
        require(options_payload.get("error"), "OPTIONS response did not include JSON error")
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Link's generated local HTTP viewer.")
    parser.add_argument("--work-dir", default="", help="directory for temporary smoke artifacts")
    parser.add_argument("--python", default=sys.executable, help="Python executable used to run Link")
    args = parser.parse_args()
    work_dir = Path(args.work_dir).expanduser().resolve() if args.work_dir else Path(tempfile.mkdtemp(prefix="link-http-viewer-"))
    try:
        run_smoke(work_dir, python=args.python)
    except SmokeFailure as exc:
        print(f"HTTP viewer smoke failed: {exc}", file=sys.stderr)
        return 1
    print(f"HTTP viewer smoke passed in {work_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
