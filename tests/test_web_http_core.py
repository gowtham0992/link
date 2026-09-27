import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.web_http import (  # noqa: E402
    BROWSER_SOURCE_LOCAL_ONLY,
    CONTENT_SECURITY_POLICY,
    HOST_HEADER_LOCAL_ONLY,
    HOST_HEADER_REQUIRED,
    LocalRateLimiter,
    PERMISSIONS_POLICY,
    SVG_CONTENT_SECURITY_POLICY,
    is_allowed_static_file,
    local_no_store_headers,
    local_security_headers,
    parse_bounded_int,
    resolve_raw_static_path,
    safe_resolve,
    validate_local_browser_source_headers,
    validate_local_host_header,
)


class WebHttpCoreTests(unittest.TestCase):
    def test_local_security_headers_include_browser_isolation(self):
        headers = dict(local_security_headers("1"))

        self.assertEqual(headers["X-Link-API-Version"], "1")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["X-DNS-Prefetch-Control"], "off")
        self.assertEqual(headers["X-Permitted-Cross-Domain-Policies"], "none")
        self.assertEqual(headers["Cross-Origin-Opener-Policy"], "same-origin")
        self.assertEqual(headers["Permissions-Policy"], PERMISSIONS_POLICY)
        self.assertEqual(headers["Content-Security-Policy"], CONTENT_SECURITY_POLICY)
        self.assertIn("frame-ancestors 'none'", CONTENT_SECURITY_POLICY)
        self.assertIn("camera=()", PERMISSIONS_POLICY)
        self.assertNotIn("fullscreen=()", PERMISSIONS_POLICY)

    def test_local_security_headers_can_use_strict_svg_policy(self):
        headers = dict(local_security_headers("2", SVG_CONTENT_SECURITY_POLICY))

        self.assertEqual(headers["X-Link-API-Version"], "2")
        self.assertEqual(headers["Content-Security-Policy"], SVG_CONTENT_SECURITY_POLICY)
        self.assertIn("script-src 'none'", SVG_CONTENT_SECURITY_POLICY)

    def test_local_no_store_headers_include_legacy_cache_guards(self):
        headers = dict(local_no_store_headers())

        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Pragma"], "no-cache")
        self.assertEqual(headers["Expires"], "0")

    def test_local_rate_limiter_reports_retry_after_window(self):
        now = 100.0

        def clock() -> float:
            return now

        limiter = LocalRateLimiter(max_events=2, window_seconds=10, clock=clock)

        self.assertEqual(limiter.check("127.0.0.1"), (True, 0))
        self.assertEqual(limiter.check("127.0.0.1"), (True, 0))
        self.assertEqual(limiter.check("127.0.0.1"), (False, 10))
        now = 111.0
        self.assertEqual(limiter.check("127.0.0.1"), (True, 0))

    def test_parse_bounded_int_clamps_and_reports_errors(self):
        self.assertEqual(parse_bounded_int("", "limit", 40, 1, 100), (40, None))
        self.assertEqual(parse_bounded_int("250", "limit", 40, 1, 100), (100, None))
        self.assertEqual(parse_bounded_int("0", "limit", 40, 1, 100), (None, "limit must be at least 1"))
        self.assertEqual(parse_bounded_int("bad", "limit", 40, 1, 100), (None, "limit must be an integer"))

    def test_validate_local_host_header_accepts_local_hosts_with_ports(self):
        for host in ("127.0.0.1", "127.0.0.1:3000", "localhost", "localhost:3000"):
            self.assertEqual(validate_local_host_header(host), (True, None))

    def test_validate_local_host_header_rejects_missing_or_remote_hosts(self):
        self.assertEqual(validate_local_host_header(""), (False, HOST_HEADER_REQUIRED))
        self.assertEqual(validate_local_host_header("attacker.example"), (False, HOST_HEADER_LOCAL_ONLY))
        self.assertEqual(validate_local_host_header("localhost.evil.test"), (False, HOST_HEADER_LOCAL_ONLY))
        self.assertEqual(validate_local_host_header("localhost:bad"), (False, HOST_HEADER_LOCAL_ONLY))
        self.assertEqual(validate_local_host_header("localhost attacker"), (False, HOST_HEADER_LOCAL_ONLY))

    def test_validate_local_browser_source_headers_accepts_local_or_missing_sources(self):
        self.assertEqual(validate_local_browser_source_headers("", ""), (True, None))
        self.assertEqual(validate_local_browser_source_headers("http://localhost:3000", ""), (True, None))
        self.assertEqual(validate_local_browser_source_headers("", "http://127.0.0.1:3000/graph"), (True, None))

    def test_browser_source_must_be_the_viewers_own_port(self):
        self.assertEqual(
            validate_local_browser_source_headers("http://localhost:3777", "", allowed_port=3777), (True, None))
        self.assertEqual(
            validate_local_browser_source_headers("", "http://127.0.0.1:3777/memory", allowed_port=3777), (True, None))
        self.assertFalse(validate_local_browser_source_headers("http://localhost:8080", "", allowed_port=3777)[0])
        from link_core.web_http import host_header_port
        self.assertEqual(host_header_port("localhost:8080"), 8080)
        self.assertEqual(host_header_port("127.0.0.1"), 80)
        self.assertEqual(host_header_port("[::1]:3000"), 3000)
        self.assertIsNone(host_header_port(""))
        self.assertIsNone(host_header_port("localhost:notaport"))
        self.assertFalse(validate_local_browser_source_headers("http://localhost", "", allowed_port=3777)[0])
        self.assertFalse(
            validate_local_browser_source_headers("", "http://127.0.0.1:5173/x", allowed_port=3777)[0])

    def test_validate_local_browser_source_headers_rejects_remote_sources(self):
        self.assertEqual(
            validate_local_browser_source_headers("https://attacker.example", ""),
            (False, BROWSER_SOURCE_LOCAL_ONLY),
        )
        self.assertEqual(
            validate_local_browser_source_headers("", "http://localhost.evil.test/page"),
            (False, BROWSER_SOURCE_LOCAL_ONLY),
        )
        self.assertEqual(validate_local_browser_source_headers("null", ""), (False, BROWSER_SOURCE_LOCAL_ONLY))

    def test_raw_static_resolver_stays_under_raw_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw"
            raw.mkdir()
            asset = raw / "asset.png"
            asset.write_bytes(b"png")
            allowed_types = {".png": "image/png"}

            self.assertEqual(
                resolve_raw_static_path(raw, "asset.png", allowed_types),
                (asset.resolve(), "image/png"),
            )
            self.assertEqual(resolve_raw_static_path(raw, "../logo.png", allowed_types), (None, None))
            self.assertEqual(resolve_raw_static_path(raw, "%2e%2e/logo.png", allowed_types), (None, None))
            self.assertEqual(resolve_raw_static_path(raw, "asset.txt", allowed_types), (None, None))

    def test_static_file_allowlist_allows_root_assets_and_raw_media_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw"
            raw.mkdir()
            logo = root / "logo.svg"
            image = raw / "image.png"
            note = raw / "note.txt"
            private = root / "serve.py"
            for path in (logo, image, note, private):
                path.write_text("x", encoding="utf-8")

            allowed_types = {".png": "image/png"}
            self.assertTrue(is_allowed_static_file(logo, raw, [logo], allowed_types))
            self.assertTrue(is_allowed_static_file(image, raw, [logo], allowed_types))
            self.assertFalse(is_allowed_static_file(note, raw, [logo], allowed_types))
            self.assertFalse(is_allowed_static_file(private, raw, [logo], allowed_types))

    def test_safe_resolve_handles_malformed_paths(self):
        self.assertIsNone(safe_resolve(Path("bad\0path")))


if __name__ == "__main__":
    unittest.main()
