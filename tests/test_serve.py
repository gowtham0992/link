import json
import os
import socketserver
import tempfile
import time
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import serve
from link_core.operations import begin_operation
from link_core.schema import write_schema


def reset_wiki(wiki_dir: Path) -> None:
    close = getattr(getattr(serve, "_fts_index", None), "close", None)
    if callable(close):
        close()
    serve.WIKI_DIR = wiki_dir
    serve.RAW_DIR = wiki_dir.parent / "raw"
    serve._pages_cache = None
    serve._pages_cache_mtime = 0.0
    serve._pages_cache_checked_at = 0.0
    serve.CACHE_MTIME_CHECK_INTERVAL_SECONDS = 0.0
    serve._page_index = {}
    serve._fulltext_index = {}
    serve._normalized_fulltext_index = {}
    serve._text_words_index = {}
    serve._meta_words_index = {}
    serve._snippet_index = {}
    serve._token_index = {}
    serve._page_map = {}
    serve._meta_token_index = {}
    serve._forward_links_index = {}
    serve._fts_index = None
    serve._search_backend = "token-index"
    serve._cache_read_warnings = []
    serve._mutation_rate_limiter = serve._CoreLocalRateLimiter(
        max_events=serve.MUTATION_RATE_LIMIT,
        window_seconds=serve.MUTATION_RATE_WINDOW_SECONDS,
    )


def write_page(wiki_dir: Path, rel: str, text: str) -> Path:
    path = wiki_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def run_handler(method: str, path: str, body: bytes = b"", headers: dict[str, str] | None = None):
    status, payload, _ = run_handler_with_headers(method, path, body, headers)
    return status, payload


def run_handler_with_headers(method: str, path: str, body: bytes = b"", headers: dict[str, str] | None = None):
    handler = object.__new__(serve.Handler)
    handler.command = method
    handler.path = path
    handler.request_version = "HTTP/1.1"
    handler.requestline = f"{method} {path} HTTP/1.1"
    handler.client_address = ("127.0.0.1", 0)
    handler.server = None
    request_headers = {"Host": "127.0.0.1"}
    request_headers.update(headers or {})
    handler.headers = request_headers
    handler.rfile = BytesIO(body)
    handler.wfile = BytesIO()
    if method == "POST":
        handler.do_POST()
    elif method == "GET":
        handler.do_GET()
    elif method == "OPTIONS":
        handler.do_OPTIONS()
    elif method == "PUT":
        handler.do_PUT()
    elif method == "PATCH":
        handler.do_PATCH()
    elif method == "DELETE":
        handler.do_DELETE()
    elif method == "TRACE":
        handler.do_TRACE()
    elif method == "CONNECT":
        handler.do_CONNECT()
    else:
        raise ValueError(method)
    raw = handler.wfile.getvalue()
    header_bytes, _, body_bytes = raw.partition(b"\r\n\r\n")
    header_lines = header_bytes.splitlines()
    status_line = header_lines[0].decode("ascii")
    status = int(status_line.split()[1])
    response_headers = {}
    for line in header_lines[1:]:
        key, _, value = line.decode("ascii").partition(":")
        if key:
            response_headers[key.strip()] = value.strip()
    payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else None
    return status, payload, response_headers


def run_handler_raw(method: str, path: str, body: bytes = b"", headers: dict[str, str] | None = None):
    handler = object.__new__(serve.Handler)
    handler.command = method
    handler.path = path
    handler.request_version = "HTTP/1.1"
    handler.requestline = f"{method} {path} HTTP/1.1"
    handler.client_address = ("127.0.0.1", 0)
    handler.server = None
    request_headers = {"Host": "127.0.0.1"}
    request_headers.update(headers or {})
    handler.headers = request_headers
    handler.rfile = BytesIO(body)
    handler.wfile = BytesIO()
    if method == "GET":
        handler.do_GET()
    elif method == "HEAD":
        handler.do_HEAD()
    else:
        raise ValueError(method)
    raw = handler.wfile.getvalue()
    header_bytes, _, body_bytes = raw.partition(b"\r\n\r\n")
    header_lines = header_bytes.splitlines()
    status_line = header_lines[0].decode("ascii")
    status = int(status_line.split()[1])
    response_headers = {}
    for line in header_lines[1:]:
        key, _, value = line.decode("ascii").partition(":")
        if key:
            response_headers[key.strip()] = value.strip()
    return status, body_bytes, response_headers


def post_json(path: str, payload: dict[str, object], local_action: bool = True):
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
    }
    if local_action:
        headers["X-Link-Local-Action"] = "true"
    return run_handler(
        "POST",
        path,
        body,
        headers,
    )


class ServeTests(unittest.TestCase):
    def make_wiki(self) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="link-test-"))
        wiki = tmp / "wiki"
        wiki.mkdir()
        write_page(wiki, "index.md", "# Index\n")
        write_page(wiki, "log.md", "# Log\n")
        (wiki / "_backlinks.json").write_text("{}", encoding="utf-8")
        write_schema(wiki)
        reset_wiki(wiki)
        return wiki

    def test_plural_type_label_handles_entities(self):
        self.assertEqual(serve._plural_type_label("source"), "sources")
        self.assertEqual(serve._plural_type_label("concept"), "concepts")
        self.assertEqual(serve._plural_type_label("entity"), "entities")
        self.assertEqual(serve._plural_type_label("memory"), "memories")

    def test_layout_handles_search_enter_key(self):
        html = serve._layout("Test", "<p>Body</p>")

        self.assertIn("document.activeElement.id === 'search-input'", html)
        self.assertIn("window.location.href = '/search?q=' + encodeURIComponent(q);", html)
        self.assertIn("data-theme-toggle", html)
        self.assertIn("localStorage.getItem('link-theme')", html)
        self.assertIn("navigator.clipboard.writeText", html)
        self.assertIn("data-copy-text", html)
        self.assertIn("data-raw-source-form", html)
        self.assertIn("/api/raw-source", html)
        self.assertIn('<a href="/onboard">onboard</a>', html)
        self.assertIn('<a href="/ingest">ingest</a>', html)
        self.assertIn('<a href="/brief">brief</a>', html)
        self.assertIn('<a href="/propose">propose</a>', html)
        self.assertIn('<a href="/audit">audit</a>', html)
        self.assertIn('<a href="/captures">captures</a>', html)

    def test_local_server_uses_threaded_request_handling(self):
        self.assertTrue(issubclass(serve.ThreadingLocalTCPServer, socketserver.ThreadingMixIn))
        self.assertTrue(serve.ThreadingLocalTCPServer.daemon_threads)
        self.assertTrue(serve.ThreadingLocalTCPServer.allow_reuse_address)

    def test_http_handler_sets_request_timeout(self):
        class FakeSocket:
            def __init__(self):
                self.timeouts = []

            def makefile(self, *_args, **_kwargs):
                return BytesIO()

            def settimeout(self, value):
                self.timeouts.append(value)

        request = FakeSocket()
        handler = object.__new__(serve.Handler)
        handler.request = request

        handler.setup()

        self.assertEqual(request.timeouts, [serve.REQUEST_TIMEOUT_SECONDS])

    def test_css_has_mobile_overflow_guards(self):
        self.assertIn("* { box-sizing: border-box; margin: 0; padding: 0; }", serve.CSS)
        self.assertIn("html { overflow-x: hidden; background: var(--bg); }", serve.CSS)
        self.assertIn("overflow-x: hidden; overflow-wrap: anywhere", serve.CSS)
        self.assertIn("a, p, li, code { overflow-wrap: anywhere; }", serve.CSS)
        self.assertIn("header .header-top { display: flex;", serve.CSS)
        self.assertIn("header nav { display: flex; gap: 8px 14px;", serve.CSS)
        self.assertIn("header .nav-more-menu { position: absolute;", serve.CSS)
        self.assertIn(".wiki-page-shell { display: grid;", serve.CSS)
        self.assertIn("flex-wrap: wrap; min-width: 0", serve.CSS)
        self.assertIn(".raw-source-controls { grid-template-columns: minmax(0, 1fr); }", serve.CSS)
        self.assertIn(".memory-grid { grid-template-columns: minmax(0, 1fr); }", serve.CSS)
        self.assertIn(".memory-actions code, .memory-next code { word-break: break-word; }", serve.CSS)
        self.assertIn(".onboard-steps { display: grid;", serve.CSS)

    def test_all_pages_is_paginated_for_large_wikis(self):
        wiki = self.make_wiki()
        for index in range(300):
            write_page(
                wiki,
                f"concepts/topic-{index:03}.md",
                f"---\ntype: concept\ntitle: Topic {index:03}\n---\n# Topic\n",
            )
        reset_wiki(wiki)

        html = serve._render_all({"limit": ["25"], "offset": ["25"]})

        self.assertIn("All Pages (302)", html)
        self.assertIn("Showing 26-50 of 302", html)
        self.assertIn('href="/all?limit=25">Previous</a>', html)
        self.assertIn("/all?limit=25&amp;offset=50", html)
        self.assertIn("Topic 023", html)
        self.assertNotIn("Topic 299", html)
        self.assertIn("catalog-summary", html)
        self.assertIn('<a class="catalog-chip" href="/all?limit=25&amp;type=concept"><strong>concept</strong>300</a>', html)
        self.assertIn("<h2>concept <span>25</span></h2>", html)

        filtered = serve._render_all({"limit": ["25"], "type": ["concept"]})

        self.assertIn("All Pages / concept (300)", filtered)
        self.assertIn('<a class="catalog-chip active" href="/all?limit=25&amp;type=concept"><strong>concept</strong>300</a>', filtered)
        self.assertNotIn("Link Test Wiki Index", filtered)

    def test_security_headers_include_api_version(self):
        handler = object.__new__(serve.Handler)
        headers = []
        handler.send_header = lambda key, value: headers.append((key, value))

        handler._security_headers()

        self.assertIn(("X-Link-API-Version", serve.API_VERSION), headers)
        self.assertIn(("X-Content-Type-Options", "nosniff"), headers)
        self.assertIn(("X-Frame-Options", "DENY"), headers)
        self.assertIn(("X-DNS-Prefetch-Control", "off"), headers)
        self.assertIn(("X-Permitted-Cross-Domain-Policies", "none"), headers)
        self.assertIn(("Cross-Origin-Opener-Policy", "same-origin"), headers)
        self.assertIn(("Permissions-Policy", serve.PERMISSIONS_POLICY), headers)
        self.assertIn(("Content-Security-Policy", serve.CONTENT_SECURITY_POLICY), headers)
        self.assertIn("connect-src 'self'", serve.CONTENT_SECURITY_POLICY)
        self.assertIn("frame-ancestors 'none'", serve.CONTENT_SECURITY_POLICY)
        self.assertIn("camera=()", serve.PERMISSIONS_POLICY)
        self.assertNotIn("fullscreen=()", serve.PERMISSIONS_POLICY)

    def test_json_responses_are_not_browser_cached(self):
        self.make_wiki()

        status, payload, headers = run_handler_with_headers("GET", "/api/status")

        self.assertEqual(status, 200)
        self.assertEqual(payload["api_version"], serve.API_VERSION)
        self.assertEqual(payload["page_count"], 2)
        self.assertEqual(payload["content_page_count"], 0)
        self.assertEqual(payload["warnings"], [])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Pragma"], "no-cache")
        self.assertEqual(headers["Expires"], "0")

    def test_health_page_and_operations_api_show_interrupted_writes(self):
        wiki = self.make_wiki()
        begin_operation(
            wiki,
            "remember",
            "Save memory",
            timestamp="2026-05-17T00:00:00Z",
            paths=["wiki/memories/prefer-local.md"],
        )

        page_status, body, _ = run_handler_raw("GET", "/health")
        api_status, payload = run_handler("GET", "/api/operations")

        self.assertEqual(page_status, 200)
        self.assertIn(b"Health", body)
        self.assertIn(b"Interrupted Operations", body)
        self.assertIn(b"lnk operations", body)
        self.assertEqual(api_status, 200)
        self.assertEqual(payload["api_version"], serve.API_VERSION)
        self.assertEqual(payload["stale_count"], 1)
        self.assertEqual(payload["operations"][0]["operation"], "remember")

    def test_health_api_combines_status_validation_and_operations(self):
        wiki = self.make_wiki()
        for dirname in ("sources", "concepts", "entities", "memories", "comparisons", "explorations"):
            (wiki / dirname).mkdir(exist_ok=True)
        (wiki / "_backlinks.json").write_text(json.dumps(serve._build_backlinks()), encoding="utf-8")
        reset_wiki(wiki)

        status, payload = run_handler("GET", "/api/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["api_version"], serve.API_VERSION)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["status"]["api_version"], serve.API_VERSION)
        self.assertEqual(payload["status"]["validation"]["checked"], True)
        self.assertTrue(payload["status"]["validation"]["passed"])
        self.assertEqual(payload["operations"]["api_version"], serve.API_VERSION)
        self.assertEqual(payload["operations"]["operation_count"], 0)

    def test_api_root_returns_discovery_payload(self):
        self.make_wiki()

        status, payload = run_handler("GET", "/api")

        self.assertEqual(status, 200)
        self.assertEqual(payload["api_version"], serve.API_VERSION)
        self.assertTrue(payload["local_only"])
        self.assertEqual(payload["recommended"]["readiness"], "/api/health")
        self.assertIn("/api/query-link", payload["endpoints"]["read"])
        self.assertIn("/api/wins", payload["endpoints"]["read"])
        self.assertIn("/api/memory-log", payload["endpoints"]["read"])
        self.assertIn("/api/remember-memory", payload["endpoints"]["write"])
        self.assertEqual(payload["write_header"]["X-Link-Local-Action"], "true")

    def test_html_responses_are_not_browser_cached(self):
        self.make_wiki()

        status, body, headers = run_handler_raw("GET", "/")

        self.assertEqual(status, 200)
        self.assertIn(b"Link", body)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Pragma"], "no-cache")
        self.assertEqual(headers["Expires"], "0")

    def test_more_page_lists_advanced_tools(self):
        self.make_wiki()

        status, body, _ = run_handler_raw("GET", "/more")

        self.assertEqual(status, 200)
        self.assertIn(b"More Tools", body)
        self.assertIn(b"/onboard", body)
        self.assertIn(b"/prompts", body)
        self.assertIn(b"/propose", body)
        self.assertIn(b"/captures", body)
        self.assertIn(b"/wins", body)
        self.assertIn(b"/memory-log", body)
        self.assertIn(b"/all", body)

    def test_memory_wins_page_and_api_show_local_value_signals(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "memories/prefer-local-memory.md",
            "---\n"
            "type: memory\n"
            "title: \"Prefer local memory\"\n"
            "memory_type: preference\n"
            "scope: user\n"
            "status: active\n"
            "date_captured: \"2026-05-25T00:00:00Z\"\n"
            "source: \"unit test\"\n"
            "review_status: reviewed\n"
            "---\n\n"
            "# Prefer local memory\n\n"
            "> **TLDR:** User prefers local memory.\n\n"
            "## Memory\n\nUser prefers local memory.\n",
        )

        html = serve._render_memory_wins()
        status, payload = run_handler("GET", "/api/wins")
        page_status, body, _ = run_handler_raw("GET", "/wins")

        self.assertIn("Memory Wins", html)
        self.assertIn("not telemetry", html)
        self.assertEqual(status, 200)
        self.assertEqual(payload["schema"], "link-memory-wins-v1")
        self.assertEqual(payload["active_count"], 1)
        self.assertEqual(page_status, 200)
        self.assertIn(b"Memory Wins", body)

    def test_memory_log_page_and_api_show_lifecycle_events(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "log.md",
            "# Link Wiki Log\n\n"
            "## [2026-05-25T00:00:00Z] remember | Prefer local memory\n\n"
            "- Created: memories/prefer-local-memory.md\n"
            "- Scope: user\n\n"
            "---\n",
        )

        html = serve._render_memory_log()
        status, payload = run_handler("GET", "/api/memory-log")
        page_status, body, _ = run_handler_raw("GET", "/memory-log")

        self.assertIn("Memory Changelog", html)
        self.assertIn("Prefer local memory", html)
        self.assertEqual(status, 200)
        self.assertEqual(payload["entries"][0]["operation"], "remember")
        self.assertEqual(page_status, 200)
        self.assertIn(b"Memory Changelog", body)

    def test_head_status_sends_headers_without_body(self):
        self.make_wiki()

        status, body, headers = run_handler_raw("HEAD", "/api/status")

        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Pragma"], "no-cache")
        self.assertEqual(headers["Expires"], "0")

    def test_svg_security_headers_use_strict_policy(self):
        handler = object.__new__(serve.Handler)
        headers = []
        handler.send_header = lambda key, value: headers.append((key, value))

        handler._security_headers(content_security_policy=serve.SVG_CONTENT_SECURITY_POLICY)

        self.assertIn(("Content-Security-Policy", serve.SVG_CONTENT_SECURITY_POLICY), headers)
        self.assertIn("script-src 'none'", serve.SVG_CONTENT_SECURITY_POLICY)

    def test_rejects_unexpected_host_header(self):
        self.make_wiki()

        status, payload = run_handler("GET", "/api/status", headers={"Host": "attacker.example"})

        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "Host header must be localhost or 127.0.0.1")

    def test_local_mutation_rate_limit_returns_json_429(self):
        self.make_wiki()
        serve._mutation_rate_limiter = serve._CoreLocalRateLimiter(max_events=1, window_seconds=60)
        headers = {
            "Content-Type": "application/json",
            "Content-Length": "2",
            "X-Link-Local-Action": "true",
        }

        first_status, first_payload = run_handler("POST", "/api/rebuild-backlinks", body=b"{}", headers=headers)
        second_status, second_payload, second_headers = run_handler_with_headers(
            "POST",
            "/api/rebuild-backlinks",
            body=b"{}",
            headers=headers,
        )

        self.assertEqual(first_status, 200)
        self.assertTrue(first_payload["rebuilt"])
        self.assertEqual(second_status, 429)
        self.assertEqual(second_payload["error"], "local mutation rate limit exceeded")
        self.assertGreaterEqual(second_payload["retry_after_seconds"], 1)
        self.assertEqual(second_headers["Retry-After"], str(second_payload["retry_after_seconds"]))

    def test_options_preflight_returns_local_json_405(self):
        self.make_wiki()

        status, payload, headers = run_handler_with_headers("OPTIONS", "/api/rebuild-backlinks")

        self.assertEqual(status, 405)
        self.assertEqual(payload["error"], "CORS preflight is not supported; Link is localhost-only")
        self.assertEqual(headers["Allow"], "GET, HEAD, POST")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_unsupported_methods_return_hardened_json_405(self):
        self.make_wiki()

        for method in ("PUT", "PATCH", "DELETE", "TRACE", "CONNECT"):
            status, payload, headers = run_handler_with_headers(method, "/api/status")
            self.assertEqual(status, 405)
            self.assertEqual(payload["error"], "method not allowed; Link supports GET, HEAD, and POST")
            self.assertEqual(headers["Allow"], "GET, HEAD, POST")
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
            self.assertIn("Content-Security-Policy", headers)

    def test_server_args_stay_local_only(self):
        self.assertEqual(serve._parse_serve_port(["--port", "3010"], default=3000), 3010)
        self.assertEqual(serve._parse_serve_port(["--port=3011"], default=3000), 3011)
        port, root = serve._parse_serve_args(
            ["--root", "/tmp/link-demo", "--port", "3012"],
            default_port=3000,
            default_root=Path("/tmp/default"),
        )
        self.assertEqual(port, 3012)
        self.assertEqual(root, Path("/tmp/link-demo").resolve())
        with self.assertRaises(SystemExit):
            serve._parse_serve_port(["--port", "0"], default=3000)
        with self.assertRaises(SystemExit):
            serve._parse_serve_port(["--port=65536"], default=3000)
        with self.assertRaises(SystemExit):
            serve._parse_serve_port(["--host", "0.0.0.0"], default=3000)
        with self.assertRaises(SystemExit):
            serve._parse_serve_port(["--bind=0.0.0.0"], default=3000)

    def test_server_bind_error_message_suggests_next_port(self):
        message = serve._serve_bind_error_message(OSError(48, "Address already in use"), 3000)
        high_port_message = serve._serve_bind_error_message(OSError(48, "Address already in use"), 65535)

        self.assertIn("127.0.0.1:3000 is already in use", message)
        self.assertIn("python serve.py --port 3001", message)
        self.assertIn("python serve.py --port 3000", high_port_message)

    def test_home_page_shows_first_agent_prompts(self):
        self.make_wiki()

        html = serve._render_home()

        self.assertIn('href="/onboard"', html)
        self.assertIn('<a href="/prompts">prompts</a>', html)
        self.assertIn("Try These Prompts", html)
        self.assertIn("is Link ready?", html)
        self.assertIn("brief me from Link before we continue", html)
        self.assertIn("ingest raw/&lt;file&gt; into Link", html)
        self.assertIn("query Link for what you know about me", html)
        self.assertIn("propose memories from raw/&lt;file&gt;", html)
        self.assertIn("Open starter prompts", html)

    def test_prompts_page_and_api_share_starter_prompts(self):
        self.make_wiki()

        html = serve._render_prompts(project="Client Launch")
        status, payload = run_handler("GET", "/api/prompts?project=Client%20Launch")

        self.assertEqual(status, 200)
        self.assertEqual(payload["project"], "client-launch")
        self.assertEqual(payload["prompts"][0]["prompt"], "is Link ready?")
        self.assertIn("this project uses Link", payload["prompts"][2]["prompt"])
        self.assertIn("Starter Prompts", html)
        self.assertIn("Ask Your Agent", html)
        self.assertIn("Local Checks", html)
        self.assertIn("Project examples are scoped to <code>client-launch</code>", html)
        self.assertIn("lnk health", html)

    def test_onboard_page_shows_agent_setup_loop(self):
        self.make_wiki()

        html = serve._render_onboard()
        status, body, _ = run_handler_raw("GET", "/onboard")

        self.assertEqual(status, 200)
        self.assertIn("Onboard", html)
        self.assertIn("One local checklist", html)
        self.assertIn("MCP and CLI work without the viewer running", html)
        self.assertIn("lnk health", html)
        self.assertIn("lnk onboard", html)
        self.assertIn("--first-memory", html)
        self.assertIn("--agent codex", html)
        self.assertIn("is Link ready?", html)
        self.assertIn(b"Onboard", body)
        self.assertIn(b"--agent codex", body)

    def test_css_has_explicit_black_dark_theme(self):
        self.assertIn(':root[data-theme="dark"]', serve.CSS)
        self.assertIn("--bg: #000000;", serve.CSS)
        self.assertIn("body { font-family: Georgia", serve.CSS)
        self.assertIn("background: var(--bg); color: var(--text);", serve.CSS)
        self.assertNotIn("background: #1a1a1a", serve.CSS)

    def test_raw_static_paths_stay_under_raw_directory(self):
        wiki = self.make_wiki()
        raw = wiki.parent / "raw"
        raw.mkdir()
        asset = raw / "asset.png"
        asset.write_bytes(b"not really a png")

        good_path, good_type = serve._resolve_raw_static_path("asset.png")
        parent_path, parent_type = serve._resolve_raw_static_path("../logo.png")
        encoded_path, encoded_type = serve._resolve_raw_static_path("%2e%2e/logo.png")
        wiki_path, wiki_type = serve._resolve_raw_static_path("../wiki/index.png")

        self.assertEqual(good_path, asset.resolve())
        self.assertEqual(good_type, "image/png")
        self.assertIsNone(parent_path)
        self.assertIsNone(parent_type)
        self.assertIsNone(encoded_path)
        self.assertIsNone(encoded_type)
        self.assertIsNone(wiki_path)
        self.assertIsNone(wiki_type)

    def test_raw_static_files_are_not_browser_cached(self):
        wiki = self.make_wiki()
        raw = wiki.parent / "raw"
        raw.mkdir()
        asset = raw / "asset.png"
        asset.write_bytes(b"private image bytes")

        status, body, headers = run_handler_raw("GET", "/raw/asset.png")

        self.assertEqual(status, 200)
        self.assertEqual(body, b"private image bytes")
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Pragma"], "no-cache")
        self.assertEqual(headers["Expires"], "0")

    def test_head_raw_static_sends_headers_without_body(self):
        wiki = self.make_wiki()
        raw = wiki.parent / "raw"
        raw.mkdir()
        asset = raw / "asset.png"
        asset.write_bytes(b"private image bytes")

        status, body, headers = run_handler_raw("HEAD", "/raw/asset.png")

        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Pragma"], "no-cache")
        self.assertEqual(headers["Expires"], "0")

    def test_graph_labels_are_clamped_inside_canvas(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/a.md",
            "---\ntype: concept\ntitle: A\n---\n# A\n\n[[b]]\n",
        )
        write_page(
            wiki,
            "concepts/b.md",
            "---\ntype: concept\ntitle: B\n---\n# B\n",
        )
        html = serve._render_graph()

        self.assertIn("var labelWidth = ctx.measureText(label).width;", html)
        self.assertIn("var labelX = Math.max(labelWidth / 2 + 4", html)
        self.assertIn("ctx.fillText(label, labelX", html)

    def test_wiki_page_links_to_local_graph(self):
        wiki = self.make_wiki()
        page = write_page(
            wiki,
            "concepts/agent-memory.md",
            "---\ntype: concept\ntitle: Agent Memory\n---\n# Agent Memory\n",
        )

        html = serve._render_page(page)

        self.assertIn("/graph?focus=agent-memory&amp;depth=2", html)
        self.assertIn("Open local graph", html)
        self.assertIn('data-copy-text="query Link for Agent Memory"', html)
        self.assertIn("Copy query prompt", html)

    def test_wiki_page_shows_related_pages_from_graph_links(self):
        wiki = self.make_wiki()
        page = write_page(
            wiki,
            "concepts/a.md",
            "---\ntype: concept\ntitle: A\n---\n# A\n\n[[b]]\n",
        )
        write_page(
            wiki,
            "concepts/b.md",
            "---\ntype: concept\ntitle: B\n---\n# B\n",
        )
        write_page(
            wiki,
            "sources/c.md",
            "---\ntype: source\ntitle: C Source\n---\n# C\n\n[[a]]\n",
        )
        (wiki / "_backlinks.json").write_text(json.dumps(serve._build_backlinks()), encoding="utf-8")

        html = serve._render_page(page)

        self.assertIn("Related Pages", html)
        self.assertIn('<span class="relationship">links here</span><a href="/page/c">C Source</a>', html)
        self.assertIn('<span class="relationship">links out</span><a href="/page/b">B</a>', html)

    def test_source_page_links_to_memory_proposals(self):
        wiki = self.make_wiki()
        page = write_page(
            wiki,
            "sources/release-notes.md",
            "---\ntype: source\ntitle: Release Notes\n---\n"
            "# Release Notes\n\n## Summary\n\nNotes.\n\n## Raw Source\n\n`raw/release-notes.md`\n",
        )

        html = serve._render_page(page)

        self.assertIn("/propose?source=raw%2Frelease-notes.md", html)
        self.assertIn("Propose memories", html)
        self.assertIn('data-copy-text="propose memories from raw/release-notes.md"', html)

    def test_context_reads_current_backlinks_shape(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/a.md",
            "---\ntype: concept\ntitle: A\n---\n# A\n\nA body\n",
        )
        write_page(
            wiki,
            "concepts/b.md",
            "---\ntype: concept\ntitle: B\n---\n# B\n\nlinks [[a]]\n",
        )
        (wiki / "_backlinks.json").write_text(
            json.dumps({"backlinks": {"a": ["b"]}, "forward": {"b": ["a"]}}),
            encoding="utf-8",
        )

        ctx = serve._get_context("A")

        self.assertEqual(ctx["inbound_count"], 1)
        self.assertEqual([page["name"] for page in ctx["pages"]], ["a", "b"])

    def test_context_deduplicates_forward_links(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/a.md",
            "---\ntype: concept\ntitle: A\n---\n# A\n\n[[b]] [[b]] [[c]] [[b]]\n",
        )
        write_page(
            wiki,
            "concepts/b.md",
            "---\ntype: concept\ntitle: B\n---\n# B\n",
        )
        write_page(
            wiki,
            "concepts/c.md",
            "---\ntype: concept\ntitle: C\n---\n# C\n",
        )

        ctx = serve._get_context("A")

        self.assertEqual(ctx["forward_count"], 2)
        self.assertEqual([page["name"] for page in ctx["pages"]], ["a", "b", "c"])

    def test_context_api_requires_topic_with_bad_request(self):
        self.make_wiki()

        status, payload = run_handler("GET", "/api/context")

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "topic parameter required")

    def test_inline_markdown_sanitizes_html_and_links(self):
        rendered = serve._md_to_html(
            "Hello <script>alert(1)</script> "
            "and [bad](javascript:alert%281%29) "
            "and [ok](https://example.com?a=1&b=2) "
            "and [[target|<b>label</b>]] "
            "and `<tag>`"
        )

        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertIn('<a href="#">bad</a>', rendered)
        self.assertIn('<a href="https://example.com?a=1&amp;b=2">ok</a>', rendered)
        self.assertIn('<a href="/page/target">&lt;b&gt;label&lt;/b&gt;</a>', rendered)
        self.assertIn("<code>&lt;tag&gt;</code>", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("javascript:", rendered.lower())

    def test_wikilink_targets_encode_path_separators(self):
        rendered = serve._md_to_html("[[../raw/private|private]]")

        self.assertIn('<a href="/page/..%2Fraw%2Fprivate">private</a>', rendered)
        self.assertNotIn("/page/../raw/private", rendered)

    def test_json_for_script_escapes_script_end_tags(self):
        rendered = serve._json_for_script({"title": "</script><script>alert(1)</script>"})

        self.assertIn("\\u003c/script\\u003e", rendered)
        self.assertNotIn("</script>", rendered.lower())

    def test_static_file_allowlist_rejects_raw_traversal(self):
        wiki = self.make_wiki()
        raw_dir = wiki.parent / "raw"
        raw_dir.mkdir()
        reset_wiki(wiki)

        allowed = serve._safe_resolve(raw_dir / "image.png")
        unsupported = serve._safe_resolve(raw_dir / "note.txt")
        denied = serve._safe_resolve(raw_dir / "../serve.py")

        self.assertIsNotNone(allowed)
        self.assertIsNotNone(unsupported)
        self.assertIsNotNone(denied)
        self.assertTrue(serve._is_allowed_static_file(allowed))
        self.assertFalse(serve._is_allowed_static_file(unsupported))
        self.assertFalse(serve._is_allowed_static_file(denied))

    def test_logo_serves_from_configured_link_root(self):
        wiki = self.make_wiki()
        (wiki.parent / "logo.svg").write_text("<svg></svg>", encoding="utf-8")
        reset_wiki(wiki)

        status, body, headers = run_handler_raw("GET", "/logo.svg")

        self.assertEqual(status, 200)
        self.assertEqual(body, b"<svg></svg>")
        self.assertEqual(headers["Content-Type"], "image/svg+xml")

    def test_static_file_resolve_handles_malformed_paths(self):
        self.assertIsNone(serve._safe_resolve(Path("bad\0path")))

    def test_memory_dashboard_next_actions_empty_and_ready_states(self):
        empty_actions = serve._memory_dashboard_next_actions(
            memory_count=0,
            review_count=0,
            updated_count=0,
            archived_count=0,
        )
        ready_actions = serve._memory_dashboard_next_actions(
            memory_count=2,
            review_count=0,
            updated_count=0,
            archived_count=0,
        )

        self.assertEqual(empty_actions[0]["label"], "Create the first memory")
        self.assertIn("remember", empty_actions[0]["command"])
        self.assertEqual(ready_actions[0]["label"], "Memory is recall-ready")
        self.assertEqual(ready_actions[0]["href"], "/profile")

    def test_memory_dashboard_next_actions_uses_singular_memory_label(self):
        actions = serve._memory_dashboard_next_actions(
            memory_count=1,
            review_count=1,
            updated_count=0,
            archived_count=0,
        )

        self.assertIn("1 memory needs confirmation", actions[0]["detail"])
        self.assertNotIn("memoryy", actions[0]["detail"])

    def test_memory_dashboard_surfaces_raw_captures_and_secret_warnings(self):
        wiki = self.make_wiki()
        capture_dir = wiki.parent / "raw" / "memory-captures"
        capture_dir.mkdir(parents=True)
        fake_key = "sk-" + ("D" * 24)
        (capture_dir / "session.md").write_text(
            "---\n"
            "title: \"Session capture\"\n"
            "source_type: conversation\n"
            "date_captured: \"2026-05-05T00:00:00Z\"\n"
            "project: \"link\"\n"
            "---\n\n"
            "# Session capture\n\n"
            "## Notes\n\n"
            f"Remember that dashboard capture review is visible. Test key {fake_key}\n",
            encoding="utf-8",
        )

        dashboard = serve._memory_dashboard(limit=8)
        html = serve._render_memory_dashboard()

        self.assertEqual(dashboard["capture_count"], 1)
        self.assertEqual(dashboard["capture_warning_count"], 1)
        self.assertEqual(dashboard["captures"][0]["secret_warnings"], ["OpenAI API key"])
        self.assertIn("[redacted-secret]", dashboard["captures"][0]["snippet"])
        self.assertNotIn(fake_key, dashboard["captures"][0]["snippet"])
        self.assertIn("Redact capture warnings", dashboard["next_actions"][0]["label"])
        self.assertIn("accept-capture", dashboard["captures"][0]["commands"]["accept"])
        self.assertIn("Raw captures", html)
        self.assertIn("redact-capture", html)
        self.assertNotIn(fake_key, html)

    def test_capture_inbox_page_and_api_redact_secret_values(self):
        wiki = self.make_wiki()
        capture_dir = wiki.parent / "raw" / "memory-captures"
        capture_dir.mkdir(parents=True)
        fake_key = "sk-" + ("K" * 24)
        (capture_dir / "alpha.md").write_text(
            "---\n"
            "title: \"Alpha capture\"\n"
            "source_type: conversation\n"
            "date_captured: \"2026-05-05T00:00:00Z\"\n"
            "project: \"alpha\"\n"
            "---\n\n"
            "# Alpha capture\n\n"
            "## Notes\n\n"
            f"Remember that capture inbox is first class. Test key {fake_key}\n",
            encoding="utf-8",
        )
        (capture_dir / "beta.md").write_text(
            "---\n"
            "title: \"Beta capture\"\n"
            "source_type: conversation\n"
            "date_captured: \"2026-05-05T00:00:00Z\"\n"
            "project: \"beta\"\n"
            "---\n\n"
            "# Beta capture\n\n"
            "## Notes\n\n"
            "Remember that beta capture stays separate.\n",
            encoding="utf-8",
        )

        status, payload = run_handler("GET", "/api/capture-inbox?project=alpha")
        html = serve._render_captures(project="alpha")

        self.assertEqual(status, 200)
        self.assertEqual(payload["project"], "alpha")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["warning_count"], 1)
        self.assertEqual(payload["captures"][0]["secret_warnings"], ["OpenAI API key"])
        self.assertIn("[redacted-secret]", payload["captures"][0]["snippet"])
        self.assertNotIn(fake_key, json.dumps(payload))
        self.assertIn("Raw Capture Inbox", html)
        self.assertIn("Alpha capture", html)
        self.assertNotIn("Beta capture", html)
        self.assertIn("redact-capture", html)
        self.assertNotIn(fake_key, html)

    def test_capture_inbox_page_and_api_report_read_warnings(self):
        wiki = self.make_wiki()
        capture_dir = wiki.parent / "raw" / "memory-captures"
        capture_dir.mkdir(parents=True)
        (capture_dir / "locked.md").write_text(
            "---\n"
            "title: \"Locked capture\"\n"
            "---\n\n"
            "## Notes\n\n"
            "This capture should surface as unreadable.\n",
            encoding="utf-8",
        )
        original_read_text = Path.read_text

        def flaky_read_text(path: Path, *args, **kwargs):
            if path.name == "locked.md":
                raise OSError("permission denied")
            return original_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", flaky_read_text):
            status, payload = run_handler("GET", "/api/capture-inbox")
            html = serve._render_captures()
            audit = serve._memory_audit()

        self.assertEqual(status, 200)
        self.assertEqual(payload["read_warning_count"], 1)
        self.assertEqual(payload["read_warnings"][0]["capture"], "raw/memory-captures/locked.md")
        self.assertIn("capture_read_warnings", [item["code"] for item in audit["risk_factors"]])
        self.assertTrue(audit["next_actions"][1]["recommended"])
        self.assertIn("Fix capture access", html)
        self.assertIn("locked.md", html)

    def test_memory_brief_page_and_api_include_capture_status(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "memories/alpha-brief.md",
            (
                "---\n"
                "type: memory\n"
                "title: \"Alpha brief\"\n"
                "memory_type: project\n"
                "scope: project\n"
                "project: \"alpha\"\n"
                "status: active\n"
                "date_captured: \"2026-05-05T00:00:00Z\"\n"
                "source: \"unit test\"\n"
                "review_status: pending\n"
                "---\n\n"
                "# Alpha brief\n\n"
                "> **TLDR:** Alpha project uses memory brief before work.\n\n"
                "## Memory\n\nAlpha project uses memory brief before work.\n"
            ),
        )
        capture_dir = wiki.parent / "raw" / "memory-captures"
        capture_dir.mkdir(parents=True)
        fake_key = "sk-" + ("L" * 24)
        (capture_dir / "alpha.md").write_text(
            "---\n"
            "title: \"Alpha brief capture\"\n"
            "source_type: conversation\n"
            "date_captured: \"2026-05-05T00:00:00Z\"\n"
            "project: \"alpha\"\n"
            "---\n\n"
            "# Alpha brief capture\n\n"
            "## Notes\n\n"
            f"Remember that brief surfaces capture status. Test key {fake_key}\n",
            encoding="utf-8",
        )

        status, payload = run_handler("GET", "/api/memory-brief?q=brief&project=alpha")
        html = serve._render_brief(query="brief", project="alpha")

        self.assertEqual(status, 200)
        self.assertEqual(payload["query"], "brief")
        self.assertEqual(payload["project"], "alpha")
        self.assertEqual(payload["relevant_count"], 1)
        self.assertEqual(payload["captures"]["count"], 1)
        self.assertEqual(payload["captures"]["warning_count"], 1)
        self.assertIn("Redact raw captures", "\n".join(payload["agent_guidance"]))
        self.assertNotIn(fake_key, json.dumps(payload))
        self.assertIn("Memory Brief", html)
        self.assertIn("Agent Guidance", html)
        self.assertIn('data-copy-text="brief me from Link about brief for project alpha"', html)
        self.assertIn('data-copy-text="query Link for brief"', html)
        self.assertIn("Alpha brief", html)
        self.assertIn("Alpha brief capture", html)
        self.assertNotIn(fake_key, html)

    def test_query_link_api_returns_context_packet(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/agent-memory.md",
            "---\ntype: concept\ntitle: Agent memory\ntags: [memory]\n---\n\n"
            "# Agent memory\n\n"
            "> **TLDR:** Agents use durable local memory.\n\n"
            "## Overview\n\nAgent memory connects to [[retrieval]].\n",
        )
        write_page(
            wiki,
            "concepts/retrieval.md",
            "---\ntype: concept\ntitle: Retrieval\n---\n\n"
            "# Retrieval\n\n> **TLDR:** Retrieval selects context.\n",
        )
        write_page(
            wiki,
            "memories/prefer-local-memory.md",
            "---\n"
            "type: memory\n"
            "title: Prefer local memory\n"
            "memory_type: preference\n"
            "scope: user\n"
            "status: active\n"
            "date_captured: \"2026-05-05T00:00:00Z\"\n"
            "source: unit-test\n"
            "review_status: reviewed\n"
            "tags: [memory]\n"
            "---\n\n"
            "# Prefer local memory\n\n"
            "> **TLDR:** User prefers local agent memory.\n\n"
            "## Memory\n\nUser prefers local agent memory.\n",
        )
        (wiki / "_backlinks.json").write_text(json.dumps(serve._build_backlinks()), encoding="utf-8")
        reset_wiki(wiki)

        status, payload = run_handler("GET", "/api/query-link?q=agent%20memory&budget=small")

        self.assertEqual(status, 200)
        self.assertTrue(payload["found"])
        self.assertEqual(payload["budget"], "small")
        self.assertEqual(payload["wiki"]["primary"], "agent-memory")
        self.assertEqual(payload["memory"]["items"][0]["name"], "prefer-local-memory")
        self.assertIn("context_packet", payload)
        self.assertIn("budget_report", payload)
        self.assertIn("follow_up", payload)

    def test_status_api_returns_readiness_summary(self):
        wiki = self.make_wiki()
        for dirname in ("sources", "concepts", "entities", "memories", "comparisons", "explorations"):
            (wiki / dirname).mkdir(exist_ok=True)
        write_page(
            wiki,
            "memories/prefer-local-memory.md",
            "---\n"
            "type: memory\n"
            "title: Prefer local memory\n"
            "memory_type: preference\n"
            "scope: user\n"
            "status: active\n"
            "date_captured: \"2026-05-05T00:00:00Z\"\n"
            "source: unit-test\n"
            "review_status: reviewed\n"
            "---\n\n"
            "# Prefer local memory\n\n"
            "> **TLDR:** User prefers local memory.\n\n"
            "## Memory\n\nUser prefers local memory.\n\n"
            "## Source\n\nunit-test\n",
        )
        (wiki / "_backlinks.json").write_text(json.dumps(serve._build_backlinks()), encoding="utf-8")
        reset_wiki(wiki)

        status, payload = run_handler("GET", "/api/status?validate=true")

        self.assertEqual(status, 200)
        self.assertEqual(payload["api_version"], serve.API_VERSION)
        self.assertEqual(payload["version"], serve.LINK_VERSION)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["page_count"], 3)
        self.assertEqual(payload["content_page_count"], 1)
        self.assertEqual(payload["memory_count"], 1)
        self.assertIn(payload["search_backend"], {"sqlite-fts", "token-index"})
        self.assertTrue(payload["validation"]["passed"])
        self.assertEqual(payload["warnings"], [])
        self.assertEqual(payload["next_actions"][0]["tool"], "query_link")

    def test_status_api_reports_cache_warnings(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/locked-page.md",
            "---\ntype: concept\ntitle: Locked\n---\n# Locked\n",
        )
        reset_wiki(wiki)
        original_read_text = Path.read_text

        def flaky_read_text(path: Path, *args, **kwargs):
            if path.name == "locked-page.md":
                raise OSError("permission denied")
            return original_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", flaky_read_text):
            status, payload = run_handler("GET", "/api/status")

        self.assertEqual(status, 200)
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["page_count"], 2)
        self.assertEqual(payload["warnings"][0]["code"], "cache_read_warnings")

    def test_memory_inbox_and_explain_render_action_commands(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "memories/prefer-reviewable-memory.md",
            (
                "---\n"
                "type: memory\n"
                "title: \"Prefer reviewable memory\"\n"
                "memory_type: preference\n"
                "scope: user\n"
                "status: active\n"
                "date_captured: \"2026-05-05T00:00:00Z\"\n"
                "source: \"unit test\"\n"
                "review_status: pending\n"
                "---\n\n"
                "# Prefer reviewable memory\n\n"
                "> **TLDR:** User prefers visible memory actions.\n\n"
                "## Memory\n\nUser prefers visible memory actions.\n"
            ),
        )

        inbox_html = serve._render_inbox()
        explain_html = serve._render_explain_memory("prefer-reviewable-memory")

        self.assertIn("Next:</strong> Review", inbox_html)
        self.assertIn("review-memory", inbox_html)
        self.assertIn('data-memory-action="review"', inbox_html)
        self.assertIn('data-memory="prefer-reviewable-memory"', inbox_html)
        self.assertIn("archive-memory", inbox_html)
        self.assertIn('data-memory-action="archive"', inbox_html)
        self.assertIn("forget-memory", inbox_html)
        self.assertIn("<h2>Actions</h2>", explain_html)
        self.assertIn("Next:</strong> Review", explain_html)
        self.assertIn("forget-memory", explain_html)

    def test_memory_action_post_endpoints_update_pages(self):
        wiki = self.make_wiki()
        page = write_page(
            wiki,
            "memories/prefer-web-review.md",
            (
                "---\n"
                "type: memory\n"
                "title: \"Prefer web review\"\n"
                "memory_type: preference\n"
                "scope: user\n"
                "status: active\n"
                "date_captured: \"2026-05-05T00:00:00Z\"\n"
                "source: \"unit test\"\n"
                "review_status: pending\n"
                "---\n\n"
                "# Prefer web review\n\n"
                "> **TLDR:** User prefers safe web memory review.\n\n"
                "## Memory\n\nUser prefers safe web memory review.\n"
            ),
        )

        review_status, review_payload = post_json(
            "/api/review-memory",
            {"memory": "prefer-web-review", "note": "confirmed from web"},
        )
        archive_status, archive_payload = post_json(
            "/api/archive-memory",
            {"memory": "prefer-web-review", "reason": "validated archive"},
        )
        restore_status, restore_payload = post_json(
            "/api/restore-memory",
            {"memory": "Prefer web review"},
        )
        text = page.read_text(encoding="utf-8")
        log_text = (wiki / "log.md").read_text(encoding="utf-8")

        self.assertEqual(review_status, 200)
        self.assertTrue(review_payload["updated"])
        self.assertEqual(review_payload["review_status"], "reviewed")
        self.assertEqual(archive_status, 200)
        self.assertEqual(archive_payload["status"], "archived")
        self.assertEqual(restore_status, 200)
        self.assertEqual(restore_payload["status"], "active")
        self.assertIn("review_status: reviewed", text)
        self.assertIn('review_note: "confirmed from web"', text)
        self.assertIn("status: active", text)
        self.assertIn("review-memory", log_text)
        self.assertIn("archive-memory", log_text)
        self.assertIn("restore-memory", log_text)

    def test_memory_action_post_requires_memory_identifier(self):
        self.make_wiki()
        status, payload = post_json("/api/review-memory", {})

        self.assertEqual(status, 400)
        self.assertFalse(payload["updated"])
        self.assertEqual(payload["error"], "memory required")

    def test_memory_action_post_requires_local_action_header(self):
        self.make_wiki()
        status, payload = post_json(
            "/api/review-memory",
            {"memory": "prefer-web-review"},
            local_action=False,
        )

        self.assertEqual(status, 403)
        self.assertFalse(payload["updated"])
        self.assertIn("X-Link-Local-Action", payload["error"])

    def test_memory_audit_page_and_api_report_backlog(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "memories/alpha-review.md",
            (
                "---\n"
                "type: memory\n"
                "title: \"Alpha review\"\n"
                "memory_type: project\n"
                "scope: project\n"
                "project: \"alpha\"\n"
                "status: active\n"
                "date_captured: \"2026-05-05T00:00:00Z\"\n"
                "source: \"unit test\"\n"
                "review_status: pending\n"
                "---\n\n"
                "# Alpha review\n\n"
                "> **TLDR:** Alpha memory needs review.\n"
            ),
        )
        capture_dir = wiki.parent / "raw" / "memory-captures"
        capture_dir.mkdir(parents=True)
        fake_key = "sk-" + ("H" * 24)
        (capture_dir / "alpha.md").write_text(
            "---\n"
            "title: \"Alpha capture\"\n"
            "source_type: conversation\n"
            "date_captured: \"2026-05-05T00:00:00Z\"\n"
            "project: \"alpha\"\n"
            "---\n\n"
            "# Alpha capture\n\n"
            "## Notes\n\n"
            f"Remember that web audit reports capture risks. Test key {fake_key}\n",
            encoding="utf-8",
        )

        audit = serve._memory_audit(project="alpha")
        status, payload = run_handler("GET", "/api/memory-audit?project=alpha")
        html = serve._render_memory_audit(project="alpha")

        self.assertEqual(status, 200)
        self.assertEqual(audit["status"], "needs_attention")
        self.assertEqual(payload["project"], "alpha")
        self.assertEqual(payload["captures"]["warning_count"], 1)
        self.assertIn("capture_secret_warnings", [item["code"] for item in payload["risk_factors"]])
        self.assertIn("Memory Audit", html)
        self.assertIn("memory-inbox", html)
        self.assertIn("capture-inbox", html)
        self.assertNotIn(fake_key, html)

    def test_memory_dashboard_filters_project_memory_and_captures(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "memories/global-style.md",
            (
                "---\n"
                "type: memory\n"
                "title: \"Global style\"\n"
                "memory_type: preference\n"
                "scope: user\n"
                "status: active\n"
                "date_captured: \"2026-05-05T00:00:00Z\"\n"
                "source: \"unit test\"\n"
                "review_status: reviewed\n"
                "---\n\n"
                "# Global style\n\n"
                "> **TLDR:** User prefers concise updates.\n"
            ),
        )
        for project in ("alpha", "beta"):
            write_page(
                wiki,
                f"memories/{project}-imports.md",
                (
                    "---\n"
                    "type: memory\n"
                    f"title: \"{project.title()} imports\"\n"
                    "memory_type: project\n"
                    "scope: project\n"
                    f"project: \"{project}\"\n"
                    "status: active\n"
                    "date_captured: \"2026-05-05T00:00:00Z\"\n"
                    "source: \"unit test\"\n"
                    "review_status: reviewed\n"
                    "---\n\n"
                    f"# {project.title()} imports\n\n"
                    f"> **TLDR:** {project.title()} has project-specific imports.\n"
                ),
            )
        capture_dir = wiki.parent / "raw" / "memory-captures"
        capture_dir.mkdir(parents=True)
        for project in ("alpha", "beta"):
            (capture_dir / f"{project}.md").write_text(
                "---\n"
                f"title: \"{project.title()} capture\"\n"
                "source_type: conversation\n"
                "date_captured: \"2026-05-05T00:00:00Z\"\n"
                f"project: \"{project}\"\n"
                "---\n\n"
                "# Capture\n\n## Notes\n\nMemory capture.\n",
                encoding="utf-8",
            )

        dashboard = serve._memory_dashboard(limit=8, project="alpha")
        status, payload = run_handler("GET", "/api/memory-dashboard?project=alpha")
        html = serve._render_memory_dashboard(project="alpha")

        self.assertEqual(status, 200)
        self.assertEqual(dashboard["project"], "alpha")
        self.assertEqual(payload["project"], "alpha")
        self.assertEqual({record["name"] for record in dashboard["active"]}, {"global-style", "alpha-imports"})
        self.assertEqual([capture["project"] for capture in dashboard["captures"]], ["alpha"])
        self.assertIn("Project:</strong> alpha", html)
        self.assertNotIn("Beta imports", html)

    def test_cache_invalidation_sees_existing_page_edits(self):
        wiki = self.make_wiki()
        page = write_page(
            wiki,
            "concepts/a.md",
            "---\ntype: concept\ntitle: A\n---\n# A\n",
        )

        before = serve._get_all_pages()
        page.write_text("---\ntype: concept\ntitle: A2\n---\n# A2\n", encoding="utf-8")
        future = time.time() + 2
        os.utime(page, (future, future))
        after = serve._get_all_pages()

        self.assertEqual(next(p["title"] for p in before if p["name"] == "a"), "A")
        self.assertEqual(next(p["title"] for p in after if p["name"] == "a"), "A2")

    def test_cache_mtime_check_is_throttled_for_hot_navigation(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/a.md",
            "---\ntype: concept\ntitle: A\n---\n# A\n",
        )
        serve.CACHE_MTIME_CHECK_INTERVAL_SECONDS = 60.0

        with patch("serve._wiki_mtime", wraps=serve._wiki_mtime) as mtime:
            first = serve._get_all_pages()
            second = serve._get_all_pages()
            forced = serve._get_all_pages(force_check=True)

        self.assertIs(first, second)
        self.assertIs(first, forced)
        self.assertEqual(mtime.call_count, 2)

    def test_backlinks_loader_returns_documented_shape(self):
        wiki = self.make_wiki()
        (wiki / "_backlinks.json").write_text(
            json.dumps({"backlinks": {"a": ["b"]}, "forward": {"b": ["a"]}}),
            encoding="utf-8",
        )

        data, error = serve._load_backlinks_index()

        self.assertIsNone(error)
        self.assertEqual(data, {"backlinks": {"a": ["b"]}, "forward": {"b": ["a"]}})

    def test_backlinks_loader_supports_old_flat_shape(self):
        wiki = self.make_wiki()
        (wiki / "_backlinks.json").write_text(json.dumps({"a": ["b"]}), encoding="utf-8")

        data, error = serve._load_backlinks_index()

        self.assertIsNone(error)
        self.assertEqual(data, {"backlinks": {"a": ["b"]}, "forward": {}})

    def test_graph_data_uses_canonical_node_ids(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/transformers.md",
            "---\ntype: concept\ntitle: Transformers\n---\n# Transformers\n",
        )
        write_page(
            wiki,
            "concepts/ai-evolution.md",
            (
                "---\ntype: concept\ntitle: AI evolution\n---\n"
                "# AI evolution\n\n"
                "[[Transformers]] and [[transformers]] and [[missing-page]]\n"
            ),
        )

        graph = serve._get_graph_data()

        self.assertIn({"source": "ai-evolution", "target": "transformers"}, graph["edges"])
        self.assertNotIn({"source": "ai-evolution", "target": "Transformers"}, graph["edges"])
        self.assertFalse(any(edge["target"] == "missing-page" for edge in graph["edges"]))
        self.assertEqual(
            sum(1 for edge in graph["edges"] if edge == {"source": "ai-evolution", "target": "transformers"}),
            1,
        )

    def test_graph_summary_is_bounded_for_api_agents(self):
        wiki = self.make_wiki()
        for index in range(8):
            links = " ".join(f"[[node-{target}]]" for target in range(8) if target != index)
            write_page(
                wiki,
                f"concepts/node-{index}.md",
                f"---\ntype: concept\ntitle: Node {index}\n---\n# Node {index}\n\n{links}\n",
            )

        summary = serve._get_graph_summary(limit=4, max_edges=3)

        self.assertEqual(summary["returned_nodes"], 4)
        self.assertEqual(summary["returned_edges"], 3)
        self.assertTrue(summary["truncated"])
        self.assertIn("get_graph", {item["tool"] for item in summary["follow_up"]})

    def test_graph_data_uses_served_cache_forward_links_without_rereading_pages(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/agent-memory.md",
            "---\ntype: concept\ntitle: Agent Memory\n---\n# Agent Memory\n\n[[link]]\n",
        )
        write_page(wiki, "entities/link.md", "---\ntype: entity\ntitle: Link\n---\n# Link\n")
        serve._get_all_pages()

        with patch.object(Path, "read_text", side_effect=AssertionError("serve graph should use cache")):
            graph = serve._get_graph_data()

        self.assertIn({"source": "agent-memory", "target": "link"}, graph["edges"])

    def test_page_list_payload_is_bounded_for_api_agents(self):
        wiki = self.make_wiki()
        for index in range(5):
            write_page(
                wiki,
                f"concepts/page-{index}.md",
                f"---\ntype: concept\ntitle: Page {index}\n---\n# Page {index}\n",
            )

        payload = serve._page_list_payload(category="concepts", limit=2)

        self.assertEqual(payload["count"], 5)
        self.assertEqual(payload["returned_count"], 2)
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["follow_up"][0]["tool"], "get_pages")

    def test_page_links_payload_is_bounded_for_api_agents(self):
        wiki = self.make_wiki()
        (wiki / "_backlinks.json").write_text(
            json.dumps({
                "backlinks": {"hub": ["a", "b", "c", "d"]},
                "forward": {"hub": ["e", "f", "g"]},
            }),
            encoding="utf-8",
        )

        payload, status = serve._page_links_payload("hub", limit=2)

        self.assertEqual(status, 200)
        self.assertEqual(payload["inbound_count"], 4)
        self.assertEqual(payload["returned_inbound"], 2)
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["follow_up"][0]["tool"], "get_backlinks")

    def test_graph_tooltip_exists_before_graph_script(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/a.md",
            "---\ntype: concept\ntitle: A\n---\n# A\n",
        )

        html = serve._render_graph()

        self.assertLess(html.index('id="graph-tooltip"'), html.index("var tooltip ="))

    def test_propose_memories_post_is_write_free(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "memories/prefer-release-branches.md",
            (
                "---\n"
                "type: memory\n"
                "title: \"Prefer release branches\"\n"
                "memory_type: preference\n"
                "scope: project\n"
                "status: active\n"
                "date_captured: \"2026-05-05T00:00:00Z\"\n"
                "source: \"unit test\"\n"
                "review_status: pending\n"
                "tags: [memory, preference]\n"
                "---\n\n"
                "# Prefer release branches\n\n"
                "> **TLDR:** User prefers release branches for Link work.\n\n"
                "## Memory\n\nUser prefers release branches for Link work.\n"
            ),
        )
        before_files = sorted(path.relative_to(wiki).as_posix() for path in wiki.rglob("*") if path.is_file())

        request_body = json.dumps({
            "text": "\n".join([
                "I prefer release branches for Link work.",
                "We decided to keep Memory Mode local and source-backed.",
                "Maybe we could add cloud sync later.",
            ]),
            "source": "unit test session",
        }).encode("utf-8")
        status, payload = run_handler(
            "POST",
            "/api/propose-memories",
            body=request_body,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(request_body)),
            },
        )
        get_status, get_payload = run_handler("GET", "/api/propose-memories")
        bad_type_status, bad_type_payload = run_handler(
            "POST",
            "/api/propose-memories",
            body=request_body,
            headers={
                "Content-Type": "text/plain",
                "Content-Length": str(len(request_body)),
            },
        )

        after_files = sorted(path.relative_to(wiki).as_posix() for path in wiki.rglob("*") if path.is_file())

        self.assertEqual(status, 200)
        self.assertTrue(payload["proposed"])
        self.assertFalse(payload["writes_memory"])
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["proposals"][0]["suggested_action"], "update-memory")
        self.assertEqual(payload["proposals"][0]["duplicate_candidates"][0]["name"], "prefer-release-branches")
        self.assertEqual(payload["proposals"][0]["primary_action"]["tool"], "update_memory")
        self.assertIn("update-memory", payload["proposals"][0]["primary_action"]["command"])
        self.assertEqual(payload["proposals"][1]["suggested_action"], "remember")
        self.assertEqual(payload["proposals"][1]["primary_action"]["tool"], "remember_memory")
        self.assertIn(str(wiki.parent), payload["proposals"][1]["primary_action"]["command"])
        self.assertEqual(before_files, after_files)
        self.assertEqual(get_status, 405)
        self.assertIn("use POST", get_payload["error"])
        self.assertEqual(bad_type_status, 415)
        self.assertIn("application/json", bad_type_payload["error"])

    def test_propose_memories_post_bounds_source_and_project(self):
        self.make_wiki()
        request_body = json.dumps({
            "text": "  Remember that bounded proposal inputs matter.  ",
            "source": "s" * 600,
            "project": "p" * 100,
            "limit": 50,
        }).encode("utf-8")

        with patch.object(
            serve,
            "_propose_memories_from_text",
            return_value={"proposed": True, "count": 0, "proposals": []},
        ) as propose:
            status, payload = run_handler(
                "POST",
                "/api/propose-memories",
                body=request_body,
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(len(request_body)),
                },
            )

        self.assertEqual(status, 200)
        self.assertTrue(payload["proposed"])
        args, kwargs = propose.call_args
        self.assertEqual(args[0], "Remember that bounded proposal inputs matter.")
        self.assertEqual(kwargs["source"], "s" * 500)
        self.assertEqual(kwargs["project"], "p" * 80)
        self.assertEqual(kwargs["limit"], 20)

    def test_propose_page_renders_read_only_workflow(self):
        self.make_wiki()

        html = serve._render_propose(project="link", source="raw/first-memory.md")

        self.assertIn('<a href="/propose">propose</a>', html)
        self.assertIn('data-proposal-sources', html)
        self.assertIn('data-proposal-form', html)
        self.assertIn('data-initial-source="raw/first-memory.md"', html)
        self.assertIn('data-proposal-results', html)
        self.assertIn('value="link"', html)
        self.assertIn("without writing anything", html)
        self.assertIn("Save only preferences", html)
        self.assertIn("Review Gate", html)
        self.assertIn("Before saving memory", html)
        self.assertIn("ordinary facts in wiki pages", html)
        self.assertIn("Memory proposal path", html)
        self.assertIn("Approve explicitly", html)
        self.assertIn("This step never writes durable memory", html)
        self.assertIn("Proposal-only: no durable memory has been written yet.", html)
        self.assertIn("Manual review required", html)
        self.assertIn("Conflict found: use the approval prompt", html)
        self.assertIn("Writes durable local memory only after this explicit approval.", html)
        self.assertIn("Approve and save", html)
        self.assertIn("/api/remember-memory", html)
        self.assertIn("/api/update-memory", html)
        self.assertIn("Copy approval prompt", html)
        self.assertIn("navigator.clipboard.writeText", html)
        self.assertIn("var initialSource = form.getAttribute('data-initial-source')", html)

    def test_propose_page_bounds_query_seed_values(self):
        self.make_wiki()

        html = serve._render_propose(project="p" * 100, source="s" * 600)

        self.assertIn(f'value="{"p" * 80}"', html)
        self.assertNotIn("p" * 81, html)
        self.assertIn(f'data-initial-source="{"s" * 500}"', html)
        self.assertNotIn("s" * 501, html)

    def test_memory_approval_api_requires_header_and_writes_memory(self):
        wiki = self.make_wiki()
        payload = {
            "memory": "User wants Link memory approvals to stay explicit.",
            "title": "Explicit approvals",
            "memory_type": "preference",
            "scope": "user",
            "source": "web proposal",
            "review_after": "2026-08-01",
            "expires_at": "2026-12-01",
        }

        denied_status, denied_payload = post_json("/api/remember-memory", payload, local_action=False)
        create_status, created = post_json("/api/remember-memory", payload)
        duplicate_status, duplicate = post_json("/api/remember-memory", payload)
        update_status, updated = post_json(
            "/api/update-memory",
            {
                "memory": created["name"],
                "text": "User also wants the web proposal flow to preserve review.",
                "source": "web proposal",
            },
        )
        page_text = (wiki / "memories" / f"{created['name']}.md").read_text(encoding="utf-8")

        self.assertEqual(denied_status, 403)
        self.assertIn("X-Link-Local-Action", denied_payload["error"])
        self.assertEqual(create_status, 200)
        self.assertTrue(created["saved"])
        self.assertTrue(created["created"])
        self.assertEqual(created["path"], f"wiki/memories/{created['name']}.md")
        self.assertEqual(created["review_after"], "2026-08-01")
        self.assertEqual(created["expires_at"], "2026-12-01")
        self.assertIn('expires_at: "2026-12-01"', page_text)
        self.assertEqual(duplicate_status, 409)
        self.assertFalse(duplicate["saved"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(update_status, 200)
        self.assertTrue(updated["saved"])
        self.assertTrue(updated["updated"])
        self.assertEqual(updated["review_status"], "pending")
        self.assertIn("User also wants the web proposal flow", page_text)

    def test_memory_approval_api_ignores_duplicate_override_flags(self):
        wiki = self.make_wiki()
        payload = {
            "memory": "User prefers Link web approvals to be reviewable.",
            "title": "Reviewable web approvals",
            "memory_type": "preference",
            "scope": "user",
            "source": "web proposal",
        }

        create_status, created = post_json("/api/remember-memory", payload)
        duplicate_status, duplicate = post_json(
            "/api/remember-memory",
            {**payload, "allow_duplicate": True, "allow_conflict": True},
        )

        memory_pages = sorted((wiki / "memories").glob("reviewable-web-approvals*.md"))
        self.assertEqual(create_status, 200)
        self.assertTrue(created["saved"])
        self.assertEqual(duplicate_status, 409)
        self.assertFalse(duplicate["saved"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(len(memory_pages), 1)

    def test_memory_update_api_ignores_conflict_override_flags(self):
        wiki = self.make_wiki()
        first_status, first = post_json(
            "/api/remember-memory",
            {
                "memory": "User prefers release branches for Link work.",
                "title": "Prefer release branches",
                "memory_type": "preference",
                "scope": "project",
                "project": "link",
                "source": "web proposal",
            },
        )
        second = serve._core_write_memory_page(
            wiki,
            "User prefers dark mode for Link work.",
            "Prefer dark mode",
            "preference",
            "project",
            None,
            "test setup",
            serve._utc_timestamp(),
            project="link",
            records=serve._memory_records(),
            allow_conflict=True,
        )
        update_status, update = post_json(
            "/api/update-memory",
            {
                "memory": second["name"],
                "text": "User prefers develop branches for Link work.",
                "source": "web proposal",
                "project": "link",
                "allow_conflict": True,
            },
        )

        self.assertEqual(first_status, 200)
        self.assertTrue(second["created"])
        self.assertEqual(update_status, 409)
        self.assertFalse(update["saved"])
        self.assertTrue(update["conflict"])

    def test_proposal_sources_api_lists_safe_raw_files(self):
        wiki = self.make_wiki()
        raw = wiki.parent / "raw"
        raw.mkdir()
        (raw / "first-memory.md").write_text(
            "# First Memory\n\nI prefer local-first agent memory.",
            encoding="utf-8",
        )
        fake_secret = "sk-" + ("a" * 24)
        (raw / "secret-note.md").write_text(
            f"# Secret Note\n\nToken {fake_secret} should not be loaded.",
            encoding="utf-8",
        )
        (raw / "big-note.md").write_text(
            "# Big Note\n\n" + ("large source text\n" * 5000),
            encoding="utf-8",
        )
        (raw / ".hidden-note.md").write_text(
            "# Hidden Note\n\nThis should not be listed or loaded directly.",
            encoding="utf-8",
        )
        (raw / "image.png").write_bytes(b"not listed")
        reset_wiki(wiki)

        list_status, list_payload = run_handler("GET", "/api/proposal-sources")
        load_status, load_payload = run_handler("GET", "/api/proposal-source?path=raw/first-memory.md")
        secret_status, secret_payload = run_handler("GET", "/api/proposal-source?path=raw/secret-note.md")
        big_status, big_payload = run_handler("GET", "/api/proposal-source?path=raw/big-note.md")
        traversal_status, traversal_payload = run_handler("GET", "/api/proposal-source?path=../serve.py")
        hidden_status, hidden_payload = run_handler("GET", "/api/proposal-source?path=raw/.hidden-note.md")
        long_status, long_payload = run_handler("GET", f"/api/proposal-source?path={'x' * 1001}.md")

        self.assertEqual(list_status, 200)
        self.assertEqual(list_payload["count"], 3)
        sources = {item["path"]: item for item in list_payload["sources"]}
        self.assertTrue(sources["raw/first-memory.md"]["loadable"])
        self.assertEqual(sources["raw/first-memory.md"]["action"], "load")
        self.assertEqual(sources["raw/first-memory.md"]["action_label"], "Use in form")
        self.assertFalse(sources["raw/secret-note.md"]["loadable"])
        self.assertEqual(sources["raw/secret-note.md"]["action"], "redact")
        self.assertEqual(sources["raw/secret-note.md"]["action_label"], "Redact first")
        self.assertEqual(sources["raw/secret-note.md"]["secret_warnings"], ["OpenAI API key"])
        self.assertNotIn(fake_secret, sources["raw/secret-note.md"]["snippet"])
        self.assertFalse(sources["raw/big-note.md"]["loadable"])
        self.assertTrue(sources["raw/big-note.md"]["truncated"])
        self.assertEqual(sources["raw/big-note.md"]["action"], "split")
        self.assertEqual(sources["raw/big-note.md"]["action_label"], "Split file")
        self.assertNotIn("raw/.hidden-note.md", sources)
        self.assertEqual(load_status, 200)
        self.assertIn("local-first agent memory", load_payload["text"])
        self.assertEqual(load_payload["source"], "raw/first-memory.md")
        self.assertEqual(secret_status, 409)
        self.assertIn("redact", secret_payload["error"])
        self.assertNotIn("text", secret_payload)
        self.assertEqual(big_status, 413)
        self.assertIn("too large", big_payload["error"])
        self.assertNotIn("text", big_payload)
        self.assertEqual(traversal_status, 404)
        self.assertFalse(traversal_payload["found"])
        self.assertEqual(hidden_status, 404)
        self.assertFalse(hidden_payload["found"])
        self.assertEqual(long_status, 404)
        self.assertFalse(long_payload["found"])

    def test_proposal_sources_api_blocks_unreadable_raw_files(self):
        wiki = self.make_wiki()
        raw = wiki.parent / "raw"
        raw.mkdir()
        (raw / "locked-note.md").write_text("# Locked note\n", encoding="utf-8")
        reset_wiki(wiki)
        original_open = Path.open

        def open_path(path: Path, *args: object, **kwargs: object):
            if path.name == "locked-note.md":
                raise OSError("permission denied")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", open_path):
            list_status, list_payload = run_handler("GET", "/api/proposal-sources")
            load_status, load_payload = run_handler("GET", "/api/proposal-source?path=raw/locked-note.md")

        self.assertEqual(list_status, 200)
        self.assertEqual(list_payload["count"], 1)
        source = list_payload["sources"][0]
        self.assertEqual(source["path"], "raw/locked-note.md")
        self.assertFalse(source["loadable"])
        self.assertEqual(source["action"], "unavailable")
        self.assertEqual(source["action_label"], "Fix access")
        self.assertEqual(source["error"], "permission denied")
        self.assertEqual(load_status, 423)
        self.assertEqual(load_payload["action"], "unavailable")
        self.assertIn("permission denied", load_payload["error"])
        self.assertNotIn("text", load_payload)

    def test_raw_source_api_creates_local_source_for_ingest(self):
        wiki = self.make_wiki()

        status, payload = post_json(
            "/api/raw-source",
            {
                "title": "Project Notes",
                "filename": "Project Notes.md",
                "text": "User wants a web path for adding Link sources.",
            },
        )
        duplicate_status, duplicate_payload = post_json(
            "/api/raw-source",
            {
                "title": "Project Notes",
                "filename": "Project Notes.md",
                "text": "# Project Notes\n\nSecond source.",
            },
        )
        missing_header_status, missing_header = post_json(
            "/api/raw-source",
            {"title": "No Header", "text": "Should not save."},
            local_action=False,
        )

        self.assertEqual(status, 201)
        self.assertTrue(payload["created"])
        self.assertEqual(payload["path"], "raw/project-notes.md")
        self.assertEqual(payload["next_prompt"], "ingest raw/project-notes.md into Link")
        self.assertTrue((wiki.parent / payload["path"]).exists())
        self.assertIn("# Project Notes", (wiki.parent / payload["path"]).read_text(encoding="utf-8"))
        self.assertIn("add-raw-source", (wiki / "log.md").read_text(encoding="utf-8"))
        self.assertEqual(duplicate_status, 201)
        self.assertEqual(duplicate_payload["path"], "raw/project-notes-2.md")
        self.assertEqual(missing_header_status, 403)
        self.assertFalse(missing_header["created"])

    def test_raw_source_api_blocks_secret_and_unsafe_names(self):
        wiki = self.make_wiki()

        secret_status, secret_payload = post_json(
            "/api/raw-source",
            {
                "title": "Secret",
                "filename": "secret.md",
                "text": "Do not save sk-" + ("a" * 25),
            },
        )
        unsafe_status, unsafe_payload = post_json(
            "/api/raw-source",
            {
                "title": "Unsafe",
                "filename": "../unsafe.md",
                "text": "Safe text.",
            },
        )
        get_status, get_payload = run_handler("GET", "/api/raw-source")

        self.assertEqual(secret_status, 422)
        self.assertFalse(secret_payload["created"])
        self.assertEqual(secret_payload["secret_warnings"], ["OpenAI API key"])
        self.assertFalse((wiki.parent / "raw" / "secret.md").exists())
        self.assertEqual(unsafe_status, 400)
        self.assertIn("filename", unsafe_payload["error"])
        self.assertEqual(get_status, 405)
        self.assertIn("POST", get_payload["error"])

    def test_ingest_page_and_api_show_pending_raw(self):
        wiki = self.make_wiki()
        raw = wiki.parent / "raw"
        raw.mkdir()
        (raw / "new-source.md").write_text("# New source\n", encoding="utf-8")
        reset_wiki(wiki)

        api_status, payload = run_handler("GET", "/api/ingest-status")
        html = serve._render_ingest()

        self.assertEqual(api_status, 200)
        self.assertEqual(payload["pending_count"], 1)
        self.assertEqual(payload["guidance"]["state"], "pending_raw")
        self.assertEqual(payload["safety"]["status"], "clear")
        self.assertEqual(payload["plan"]["batch"][0]["suggested_source_page"], "wiki/sources/new-source.md")
        self.assertIn(str(wiki.parent), "\n".join(payload["guidance"]["commands"]))
        self.assertIn("Add Raw Source", html)
        self.assertIn('data-raw-source-form', html)
        self.assertIn('data-raw-source-status', html)
        self.assertIn("Save to raw/", html)
        self.assertIn("blocks secret-looking values", html)
        self.assertIn("Next step", html)
        self.assertIn("Raw safety: clear", html)
        self.assertIn("No secret-looking values detected in raw sources.", html)
        self.assertIn("Copy this into your agent chat", html)
        self.assertIn('data-copy-text="ingest raw/new-source.md into Link"', html)
        self.assertIn("Copy prompt", html)
        self.assertIn("Copy command", html)
        self.assertIn('data-copy-text="lnk validate ', html)
        self.assertIn(str(wiki.parent), html)
        self.assertIn("ingest raw/new-source.md into Link", html)
        self.assertIn("open memory proposals first", html)
        self.assertIn("Ingest path", html)
        self.assertIn("Optional memory", html)
        self.assertIn("propose memories from raw/new-source.md", html)
        self.assertIn("Post-ingest checks", html)
        self.assertIn("run before reporting done", html)
        self.assertIn("Ingest pending raw sources", html)
        self.assertIn("wiki/sources/new-source.md", html)
        self.assertIn('/propose?source=raw/new-source.md', html)
        self.assertIn("Pending Raw Files", html)

    def test_ingest_page_shows_completion_for_represented_raw(self):
        wiki = self.make_wiki()
        raw = wiki.parent / "raw"
        raw.mkdir()
        (raw / "represented-source.md").write_text("# Represented source\n", encoding="utf-8")
        (wiki / "sources").mkdir(parents=True, exist_ok=True)
        (wiki / "sources" / "represented-source.md").write_text(
            "---\ntype: source\ntitle: Represented Source\n---\n\n"
            "# Represented Source\n\n"
            "## Raw Source\n\n`raw/represented-source.md`\n",
            encoding="utf-8",
        )
        reset_wiki(wiki)

        api_status, payload = run_handler("GET", "/api/ingest-status")
        html = serve._render_ingest()

        self.assertEqual(api_status, 200)
        self.assertEqual(payload["guidance"]["state"], "ready")
        self.assertEqual(payload["completion"]["items"][0]["source_pages"][0]["title"], "Represented Source")
        self.assertIn("Ingest completion", html)
        self.assertIn("All 1 raw source(s) are represented", html)
        self.assertIn("raw/represented-source.md", html)
        self.assertIn('/page/represented-source', html)
        self.assertIn("Represented Source", html)
        self.assertIn('/propose?source=raw/represented-source.md', html)
        self.assertIn('data-copy-text="propose memories from raw/represented-source.md"', html)
        self.assertIn('data-copy-text="query Link for represented source"', html)
        self.assertIn("brief me from Link before we continue", html)

    def test_ingest_page_marks_stale_represented_raw(self):
        wiki = self.make_wiki()
        raw = wiki.parent / "raw"
        raw.mkdir()
        raw_page = raw / "represented-source.md"
        raw_page.write_text("# Represented source\n\nOriginal note.\n", encoding="utf-8")
        (wiki / "sources").mkdir(parents=True, exist_ok=True)
        (wiki / "sources" / "represented-source.md").write_text(
            "---\ntype: source\ntitle: Represented Source\n---\n\n"
            "# Represented Source\n\n"
            "## Raw Source\n\n`raw/represented-source.md`\n",
            encoding="utf-8",
        )
        time.sleep(0.02)
        raw_page.write_text("# Represented source\n\nUpdated note.\n", encoding="utf-8")
        reset_wiki(wiki)

        api_status, payload = run_handler("GET", "/api/ingest-status")
        html = serve._render_ingest()

        self.assertEqual(api_status, 200)
        self.assertEqual(payload["guidance"]["state"], "stale_raw")
        self.assertEqual(payload["stale_count"], 1)
        self.assertIn("<span class=\"label\">stale</span>", html)
        self.assertIn("raw changed after wiki source page", html)
        self.assertIn("Refresh stale source pages", html)
        self.assertIn("wiki/sources/represented-source.md", html)
        self.assertIn('data-copy-text="re-ingest raw/represented-source.md into Link"', html)

    def test_ingest_page_blocks_secret_looking_raw(self):
        wiki = self.make_wiki()
        raw = wiki.parent / "raw"
        raw.mkdir()
        (raw / "a-safe-note.md").write_text(
            "# Safe note\n\nThis should stay available for memory proposals.\n",
            encoding="utf-8",
        )
        (raw / "secret-note.md").write_text(
            "# Secret note\n\nDo not ingest sk-" + ("a" * 25) + "\n",
            encoding="utf-8",
        )
        reset_wiki(wiki)

        api_status, payload = run_handler("GET", "/api/ingest-status")
        html = serve._render_ingest()

        self.assertEqual(api_status, 200)
        self.assertEqual(payload["guidance"]["state"], "blocked_secrets")
        self.assertIsNone(payload["guidance"]["agent_prompt"])
        self.assertEqual(payload["safety"]["status"], "blocked")
        self.assertEqual(payload["safety"]["blocked_raw"], ["raw/secret-note.md"])
        self.assertIn("Raw safety: blocked", html)
        self.assertIn('data-copy-text="edit raw/secret-note.md"', html)
        self.assertIn("Copy next step", html)
        self.assertIn("Redact raw sources before ingest", html)
        self.assertIn("redact secret-looking values in raw/secret-note.md before ingest", html)
        self.assertIn("secret warning: OpenAI API key", html)
        self.assertIn("redact before ingest", html)
        self.assertIn('/propose?source=raw/a-safe-note.md', html)
        self.assertNotIn('/propose?source=raw/secret-note.md', html)

    def test_ingest_page_blocks_unreadable_raw(self):
        wiki = self.make_wiki()
        raw = wiki.parent / "raw"
        raw.mkdir()
        (raw / "locked-note.md").write_text("# Locked note\n", encoding="utf-8")
        reset_wiki(wiki)

        with patch(
            "link_core.ingest.secret_file_scan",
            return_value={"labels": [], "readable": False, "error": "permission denied"},
        ):
            api_status, payload = run_handler("GET", "/api/ingest-status")
            html = serve._render_ingest()

        self.assertEqual(api_status, 200)
        self.assertEqual(payload["guidance"]["state"], "blocked_raw_access")
        self.assertIsNone(payload["guidance"]["agent_prompt"])
        self.assertEqual(payload["safety"]["status"], "blocked")
        self.assertEqual(payload["raw_scan_warning_count"], 1)
        self.assertIn("Raw safety: blocked", html)
        self.assertIn('data-copy-text="inspect raw/locked-note.md"', html)
        self.assertIn("Inspect raw source access", html)
        self.assertIn("fix raw source access for raw/locked-note.md before ingest", html)
        self.assertIn("could not inspect: permission denied", html)
        self.assertIn("fix access before ingest", html)
        self.assertNotIn('/propose?source=raw/locked-note.md', html)

    def test_ingest_page_blocks_unreadable_source_pages(self):
        wiki = self.make_wiki()
        raw = wiki.parent / "raw"
        raw.mkdir()
        (raw / "broken-source.md").write_text("# Broken source\n", encoding="utf-8")
        write_page(
            wiki,
            "sources/broken.md",
            "---\ntype: source\ntitle: Broken\n---\n\n`raw/broken-source.md`\n",
        )
        reset_wiki(wiki)
        original_read_text = Path.read_text

        def read_text(path: Path, *args: object, **kwargs: object) -> str:
            if path.name == "broken.md":
                raise OSError("permission denied")
            return original_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", read_text):
            api_status, payload = run_handler("GET", "/api/ingest-status")
            html = serve._render_ingest()

        self.assertEqual(api_status, 200)
        self.assertEqual(payload["guidance"]["state"], "blocked_source_access")
        self.assertIsNone(payload["guidance"]["agent_prompt"])
        self.assertEqual(payload["source_read_warning_count"], 1)
        self.assertIn("Source Page Warnings", html)
        self.assertIn("wiki/sources/broken.md", html)
        self.assertIn("could not inspect: permission denied", html)
        self.assertIn("Inspect source page access", html)
        self.assertIn("fix source page access before ingest", html)

    def test_rebuild_backlinks_requires_json_post(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/a.md",
            "---\ntype: concept\ntitle: A\n---\n# A\n\n[[b]]\n",
        )
        write_page(
            wiki,
            "concepts/b.md",
            "---\ntype: concept\ntitle: B\n---\n# B\n",
        )
        backlinks_path = wiki / "_backlinks.json"
        backlinks_path.write_text(json.dumps({"backlinks": {}, "forward": {}}), encoding="utf-8")

        get_status, get_payload = run_handler("GET", "/api/rebuild-backlinks")
        bad_post_status, bad_post_payload = run_handler("POST", "/api/rebuild-backlinks")
        missing_header_status, missing_header_payload = run_handler(
            "POST",
            "/api/rebuild-backlinks",
            body=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": "2"},
        )
        post_status, post_payload = run_handler(
            "POST",
            "/api/rebuild-backlinks",
            body=b"{}",
            headers={
                "Content-Type": "application/json",
                "Content-Length": "2",
                "X-Link-Local-Action": "true",
            },
        )
        bad_origin_status, bad_origin_payload = run_handler(
            "POST",
            "/api/rebuild-backlinks",
            body=b"{}",
            headers={
                "Content-Type": "application/json",
                "Content-Length": "2",
                "X-Link-Local-Action": "true",
                "Origin": "https://attacker.example",
            },
        )
        rebuilt = json.loads(backlinks_path.read_text(encoding="utf-8"))

        self.assertEqual(get_status, 405)
        self.assertIn("use POST", get_payload["error"])
        self.assertEqual(bad_post_status, 403)
        self.assertFalse(bad_post_payload["rebuilt"])
        self.assertIn("X-Link-Local-Action", bad_post_payload["error"])
        self.assertEqual(missing_header_status, 403)
        self.assertFalse(missing_header_payload["rebuilt"])
        self.assertIn("X-Link-Local-Action", missing_header_payload["error"])
        self.assertEqual(post_status, 200)
        self.assertTrue(post_payload["rebuilt"])
        self.assertEqual(bad_origin_status, 403)
        self.assertFalse(bad_origin_payload["rebuilt"])
        self.assertIn("Origin/Referer", bad_origin_payload["error"])
        self.assertEqual(rebuilt["backlinks"], {"b": ["a"]})
        self.assertEqual(rebuilt["forward"], {"a": ["b"]})

    def test_rebuild_backlinks_reports_read_errors(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/locked-page.md",
            "---\ntype: concept\ntitle: Locked\n---\n# Locked\n\n[[link]]\n",
        )
        original_read_text = Path.read_text

        def flaky_read_text(path: Path, *args, **kwargs):
            if path.name == "locked-page.md":
                raise OSError("permission denied")
            return original_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", flaky_read_text):
            status, payload = run_handler(
                "POST",
                "/api/rebuild-backlinks",
                body=b"{}",
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": "2",
                    "X-Link-Local-Action": "true",
                },
            )

        self.assertEqual(status, 200)
        self.assertFalse(payload["rebuilt"])
        self.assertIn("Could not rebuild backlinks", payload["error"])

    def test_rebuild_backlinks_rejects_bad_json_after_local_header(self):
        self.make_wiki()

        bad_post_status, bad_post_payload = run_handler(
            "POST",
            "/api/rebuild-backlinks",
            headers={"X-Link-Local-Action": "true"},
        )

        self.assertEqual(bad_post_status, 415)
        self.assertFalse(bad_post_payload["rebuilt"])

    def test_rebuild_index_requires_json_post(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/a.md",
            "---\ntype: concept\ntitle: A\n---\n# A\n\n> **TLDR:** A page.\n",
        )
        index_path = wiki / "index.md"
        index_path.write_text("# Broken Index\n", encoding="utf-8")

        get_status, get_payload = run_handler("GET", "/api/rebuild-index")
        bad_post_status, bad_post_payload = run_handler("POST", "/api/rebuild-index")
        missing_header_status, missing_header_payload = run_handler(
            "POST",
            "/api/rebuild-index",
            body=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": "2"},
        )
        post_status, post_payload = run_handler(
            "POST",
            "/api/rebuild-index",
            body=b"{}",
            headers={
                "Content-Type": "application/json",
                "Content-Length": "2",
                "X-Link-Local-Action": "true",
            },
        )
        index_text = index_path.read_text(encoding="utf-8")

        self.assertEqual(get_status, 405)
        self.assertIn("use POST", get_payload["error"])
        self.assertEqual(bad_post_status, 403)
        self.assertFalse(bad_post_payload["rebuilt"])
        self.assertIn("X-Link-Local-Action", bad_post_payload["error"])
        self.assertEqual(missing_header_status, 403)
        self.assertFalse(missing_header_payload["rebuilt"])
        self.assertIn("X-Link-Local-Action", missing_header_payload["error"])
        self.assertEqual(post_status, 200)
        self.assertTrue(post_payload["rebuilt"])
        self.assertIn("[[a]]", index_text)
        self.assertEqual(post_payload["category_counts"]["concepts"], 1)

    def test_rebuild_index_reports_read_errors(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/locked-page.md",
            "---\ntype: concept\ntitle: Locked\n---\n# Locked\n",
        )
        original_read_text = Path.read_text

        def flaky_read_text(path: Path, *args, **kwargs):
            if path.name == "locked-page.md":
                raise OSError("permission denied")
            return original_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", flaky_read_text):
            status, payload = run_handler(
                "POST",
                "/api/rebuild-index",
                body=b"{}",
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": "2",
                    "X-Link-Local-Action": "true",
                },
            )

        self.assertEqual(status, 200)
        self.assertFalse(payload["rebuilt"])
        self.assertIn("Could not rebuild index", payload["error"])

    def test_rebuild_index_rejects_bad_json_after_local_header(self):
        self.make_wiki()

        bad_post_status, bad_post_payload = run_handler(
            "POST",
            "/api/rebuild-index",
            headers={"X-Link-Local-Action": "true"},
        )

        self.assertEqual(bad_post_status, 415)
        self.assertFalse(bad_post_payload["rebuilt"])

    def test_validate_api_reports_wiki_gate_status(self):
        wiki = self.make_wiki()
        for dirname in ("sources", "concepts", "entities", "memories", "comparisons", "explorations"):
            (wiki / dirname).mkdir(exist_ok=True)
        write_page(
            wiki,
            "sources/example-source.md",
            "---\ntype: source\ntitle: Example Source\n---\n\n"
            "# Example Source\n\n"
            "> **TLDR:** A valid source page.\n\n"
            "## Summary\n\nUseful source.\n\n"
            "## Raw Source\n\n`raw/example.md`\n",
        )
        write_page(
            wiki,
            "concepts/example-concept.md",
            "---\ntype: concept\ntitle: Example Concept\n---\n\n"
            "# Example Concept\n\n"
            "> **TLDR:** A valid concept page.\n\n"
            "## Overview\n\nConcept cites [[example-source]].\n\n"
            "## Sources\n\n- [[example-source]]\n",
        )
        (wiki / "_backlinks.json").write_text(json.dumps(serve._build_backlinks()), encoding="utf-8")

        status, payload = run_handler("GET", "/api/validate")

        self.assertEqual(status, 200)
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["error_count"], 0)

    def test_validate_api_uses_422_for_failed_gate(self):
        wiki = self.make_wiki()
        for dirname in ("sources", "concepts", "entities", "memories", "comparisons", "explorations"):
            (wiki / dirname).mkdir(exist_ok=True)
        write_page(
            wiki,
            "concepts/bad-page.md",
            "---\ntype: source\n---\n\n"
            "# Bad Page\n\n"
            "Mentions [[missing-page]].\n",
        )
        (wiki / "_backlinks.json").write_text(json.dumps(serve._build_backlinks()), encoding="utf-8")

        status, payload = run_handler("GET", "/api/validate?strict=true")
        codes = {finding["code"] for finding in payload["findings"]}

        self.assertEqual(status, 422)
        self.assertFalse(payload["passed"])
        self.assertIn("type_directory_mismatch", codes)
        self.assertIn("dead_wikilink", codes)

    def test_graph_controls_exist_before_graph_script(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/a.md",
            "---\ntype: concept\ntitle: A\n---\n# A\n",
        )

        html = serve._render_graph()

        self.assertLess(html.index('id="graph-reset"'), html.index("var resetButton ="))
        self.assertLess(html.index('id="graph-fit"'), html.index("var fitButton ="))
        self.assertLess(html.index('id="graph-labels"'), html.index("var labelsButton ="))
        self.assertLess(html.index('id="graph-motion"'), html.index("var motionButton ="))
        self.assertLess(html.index('id="graph-search"'), html.index("var searchInput ="))
        self.assertLess(html.index('id="graph-category"'), html.index("var categoryFilter ="))
        self.assertLess(html.index('id="graph-depth"'), html.index("var depthFilter ="))
        self.assertLess(html.index('id="graph-copy-link"'), html.index("var copyLinkButton ="))
        self.assertLess(html.index('id="graph-legend"'), html.index("var legend ="))
        self.assertLess(html.index('id="graph-inspector"'), html.index("var inspector ="))
        self.assertLess(html.index('id="graph-focus"'), html.index("var inspectorFocus ="))
        self.assertLess(html.index('id="graph-local"'), html.index("var inspectorLocal ="))
        self.assertIn('id="graph-status"', html)
        self.assertIn('data-graph-category="concepts"', html)
        self.assertIn("Focus neighborhood", html)
        self.assertIn("Open local graph", html)
        self.assertIn('id="graph-open"', html)
        self.assertIn('tabindex="0"', html)
        self.assertIn('role="img"', html)
        self.assertIn('<option value="concepts">concepts</option>', html)
        self.assertIn("function visibleNodes()", html)
        self.assertIn("function visibleEdges()", html)
        self.assertIn("function graphStateUrl()", html)
        self.assertIn("copyLinkButton.addEventListener('click', copyGraphLink);", html)
        self.assertIn("function syncDepthControl()", html)
        self.assertIn("depthValue = '1'", html)
        self.assertIn("depthFilter.disabled = !selectedNode;", html)
        self.assertIn("Select a node before filtering by neighborhood.", html)
        self.assertIn("var LARGE_GRAPH_LIMIT = 350;", html)
        self.assertIn("var LARGE_LABEL_LIMIT = 160;", html)
        self.assertIn("var FAST_RENDER_NODE_LIMIT = 450;", html)
        self.assertIn("var FAST_RENDER_EDGE_LIMIT = 1200;", html)
        self.assertIn("function syncLabelsButton()", html)
        self.assertIn("function graphNeedsFastRender(currentNodes, currentEdges)", html)
        self.assertIn("function graphTooLargeForMotion()", html)
        self.assertIn("searchInput.addEventListener('input'", html)

    def test_graph_empty_state_when_no_visible_pages(self):
        self.make_wiki()

        html = serve._render_graph()

        self.assertIn("No graph pages yet.", html)
        self.assertNotIn('id="graph-canvas"', html)

    def test_graph_drag_and_zoom_interactions_are_guarded(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/a.md",
            "---\ntype: concept\ntitle: A\n---\n# A\n",
        )

        html = serve._render_graph()

        self.assertIn("return dx * dx + dy * dy > 9;", html)
        self.assertIn("pinned[dragging.id] = didDrag;", html)
        self.assertIn("if (hit) selectNode(hit);", html)
        self.assertIn("canvas.addEventListener('dblclick'", html)
        self.assertIn("if (hit) openNode(hit);", html)
        self.assertIn("panX += after.x - before.x;", html)

    def test_graph_motion_is_capped_for_large_visible_sets(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/a.md",
            "---\ntype: concept\ntitle: A\n---\n# A\n",
        )

        html = serve._render_graph()

        self.assertIn("var simNodes = visibleNodes();", html)
        self.assertIn("if (simNodes.length > LARGE_GRAPH_LIMIT) return;", html)
        self.assertIn("if (graphTooLargeForMotion()) parts.push('motion capped');", html)
        self.assertIn("motionButton.textContent = graphTooLargeForMotion() ? 'Motion capped'", html)
        self.assertIn("var renderQueued = false;", html)
        self.assertIn("function shouldRunContinuously()", html)
        self.assertIn("function drawSoon()", html)
        self.assertIn("var animateFlow = !motionPaused && !graphTooLargeForMotion();", html)
        self.assertIn("if (activeEdge && animateFlow)", html)
        self.assertIn("if (shouldRunContinuously()) startLoop();", html)

    def test_graph_uses_fast_canvas_rendering_for_large_visible_sets(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/a.md",
            "---\ntype: concept\ntitle: A\n---\n# A\n",
        )

        html = serve._render_graph()

        self.assertIn("if (graphNeedsFastRender(currentNodes, currentEdges)) parts.push('fast render');", html)
        self.assertIn("function strokeEdgeBatch(edgeList, strokeStyle, lineWidth)", html)
        self.assertIn("if (fastRender) {", html)
        self.assertIn("strokeEdgeBatch(currentEdges, 'rgba(88,166,255,0.07)', 0.45);", html)
        self.assertIn("Radial glow stays off in large overview mode except for focused nodes.", html)
        self.assertIn("function seedLargeGraphPosition(n, i, total)", html)
        self.assertIn("function categoryClusterCenter(category, total)", html)
        self.assertIn("Large graphs skip physics, so they use stable category clusters instead of global rings.", html)
        self.assertIn("seedMissingPositions();\n    invalidateSearchCache();", html)
        self.assertIn("ctx.fillStyle = fastRender ? color + '28' : color + '40';", html)

    def test_graph_caps_default_overview_for_huge_visible_sets(self):
        wiki = self.make_wiki()
        for index in range(700):
            write_page(
                wiki,
                f"concepts/topic-{index}.md",
                "---\ntype: concept\ntitle: Topic\n---\n"
                f"# Topic {index}\n\n[[topic-{(index + 1) % 700}]]\n",
            )
        reset_wiki(wiki)

        html = serve._render_graph()

        self.assertIn("var DEFAULT_OVERVIEW_NODE_LIMIT = 650;", html)
        self.assertIn("var displayLimitFilter = document.getElementById('graph-display-limit');", html)
        self.assertIn("function capEligibleNodes(eligible)", html)
        self.assertIn("lockedOverviewIds[n.id] = true;", html)
        self.assertIn("fullGraphLoaded && lockedOverviewIds && !searchTerm", html)
        self.assertIn("function markKeep(n)", html)
        self.assertIn("var highSignalLimit = Math.floor(overviewNodeLimit * 0.65);", html)
        self.assertIn("display capped", html)
        self.assertIn(".slice(0, highSignalLimit)", html)
        self.assertIn("var sampled = eligible[Math.floor((i + 0.5) * eligible.length / Math.max(sampleLimit, 1))];", html)
        self.assertIn("while (keepCount < overviewNodeLimit && fillIndex < eligible.length)", html)
        self.assertIn("function reseedVisiblePositions()", html)
        self.assertIn("if (searchMatches(n)) markKeep(n);", html)
        self.assertIn("invalidateFilters();\n      if (searchTerm && !fullGraphLoaded) loadFullGraph();", html)
        self.assertIn("cachedSearchMatches = nodes.filter(searchMatches).length;", html)
        self.assertIn("matches > SEARCH_LABEL_LIMIT", html)
        self.assertIn("parts.push('data loaded');", html)
        self.assertIn("parts.push('display capped ' + overviewNodeLimit);", html)

    def test_graph_route_can_focus_on_page_neighborhood(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/agent-memory.md",
            "---\ntype: concept\ntitle: Agent Memory\n---\n# Agent Memory\n\n[[link]]\n",
        )
        write_page(
            wiki,
            "entities/link.md",
            "---\ntype: entity\ntitle: Link\n---\n# Link\n",
        )
        reset_wiki(wiki)

        status, body, headers = run_handler_raw("GET", "/graph?focus=agent-memory&depth=2")
        html = body.decode("utf-8")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        self.assertIn("Focused on <strong>agent-memory</strong> · depth 2", html)
        self.assertIn('var initialFocusId = "agent-memory";', html)
        self.assertIn("var initialFocusDepth = 2;", html)

    def test_graph_route_can_load_search_and_type_state(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/agent-memory.md",
            "---\ntype: concept\ntitle: Agent Memory\n---\n# Agent Memory\n",
        )
        reset_wiki(wiki)

        status, body, _ = run_handler_raw("GET", "/graph?q=agent%20memory&type=concepts&size=degree&labels=neighbors")
        html = body.decode("utf-8")

        self.assertEqual(status, 200)
        self.assertIn('var initialSearchTerm = "agent memory";', html)
        self.assertIn('var initialCategoryValue = "concepts";', html)
        self.assertIn('var initialSizeValue = "degree";', html)
        self.assertIn('var initialLabelMode = "neighbors";', html)
        self.assertIn("Search <strong>agent memory</strong>", html)
        self.assertIn("Type <strong>concepts</strong>", html)
        self.assertIn("Size <strong>degree</strong>", html)
        self.assertIn("Labels <strong>neighbors</strong>", html)

    def test_graph_uses_bounded_initial_payload_for_large_wikis(self):
        wiki = self.make_wiki()
        for index in range(920):
            write_page(
                wiki,
                f"concepts/topic-{index}.md",
                "---\ntype: concept\ntitle: Topic\n---\n"
                f"# Topic {index}\n\n[[topic-{(index + 1) % 920}]]\n",
            )
        reset_wiki(wiki)

        html = serve._render_graph()

        self.assertIn('var initialGraphMode = "summary";', html)
        self.assertIn("var totalNodeCount = 920;", html)
        self.assertIn("250/920 nodes", html)
        self.assertIn("fast overview", html)
        self.assertIn("Load all data (920 nodes)", html)
        self.assertIn("var loadFullButton = document.getElementById('graph-load-full');", html)
        self.assertIn("function loadFullGraph()", html)
        self.assertIn("fetch('/api/graph')", html)
        self.assertIn("All data ready; overview capped", html)

    def test_graph_labels_are_sparse_for_large_visible_sets(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/a.md",
            "---\ntype: concept\ntitle: A\n---\n# A\n",
        )

        html = serve._render_graph()

        self.assertIn("function graphTooLargeForDefaultLabels()", html)
        self.assertIn("if (graphTooLargeForDefaultLabels() && labelMode === 'sparse') parts.push('labels sparse');", html)
        self.assertIn("function cycleLabelMode()", html)
        self.assertIn("labelsButton.textContent = labelMode === 'all' ? 'Labels all'", html)
        self.assertIn("var largeLabelSet = currentNodes.length > LARGE_LABEL_LIMIT;", html)
        self.assertIn("var defaultSparseLabel = !largeLabelSet", html)

    def test_graph_script_embeds_titles_safely(self):
        wiki = self.make_wiki()
        write_page(
            wiki,
            "concepts/evil.md",
            "---\ntype: concept\ntitle: </script><script>alert(1)</script>\n---\n# Evil\n",
        )

        rendered = serve._render_graph()

        self.assertIn("\\u003c/script\\u003e\\u003cscript\\u003ealert(1)\\u003c/script\\u003e", rendered)
        self.assertNotIn("</script><script>alert(1)</script>", rendered.lower())

    def test_search_limit_validation(self):
        self.assertEqual(serve._parse_search_limit("3"), (3, None))
        self.assertEqual(serve._parse_search_limit("500"), (50, None))
        self.assertEqual(serve._parse_search_limit(""), (20, None))
        self.assertEqual(serve._parse_search_limit("bad"), (None, "limit must be an integer"))
        self.assertEqual(serve._parse_search_limit("0"), (None, "limit must be at least 1"))

    def test_query_text_bounds_and_falls_back_across_names(self):
        self.assertEqual(serve._query_text({"q": ["  agent memory  "]}, "q"), "agent memory")
        self.assertEqual(serve._query_text({"q": [""], "query": ["fallback"]}, "q", "query"), "fallback")
        self.assertEqual(serve._query_text({"q": ["x" * 600]}, "q"), "x" * serve.MAX_QUERY_TEXT)
        self.assertEqual(serve._query_text({"project": ["x" * 100]}, "project", max_len=80), "x" * 80)

    def test_search_api_bounds_query_text(self):
        self.make_wiki()
        long_query = "x" * 600

        status, payload = run_handler("GET", f"/api/search?q={long_query}")

        self.assertEqual(status, 200)
        self.assertEqual(payload["query"], "x" * serve.MAX_QUERY_TEXT)


if __name__ == "__main__":
    unittest.main()
