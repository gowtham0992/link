"""Shared local HTTP guard helpers for Link's web viewer."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Iterable, Mapping
from urllib.parse import unquote, urlsplit


ALLOWED_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost"})
HOST_HEADER_REQUIRED = "Host header required"
HOST_HEADER_LOCAL_ONLY = "Host header must be localhost or 127.0.0.1"
BROWSER_SOURCE_LOCAL_ONLY = "Origin/Referer must match local Link viewer"
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self'; "
    "script-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)
PERMISSIONS_POLICY = (
    "camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
    "serial=(), bluetooth=(), accelerometer=(), gyroscope=(), magnetometer=()"
)
def html_content_security_policy(nonce: str) -> str:
    """The HTML policy: same-origin assets plus this response's inline script."""
    return CONTENT_SECURITY_POLICY.replace("script-src 'self'; ", f"script-src 'self' 'nonce-{nonce}'; ")


SVG_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "img-src 'self' data:; "
    "style-src 'unsafe-inline'; "
    "script-src 'none'; "
    "object-src 'none'; "
    "sandbox"
)


def parse_bounded_int(
    raw: object,
    label: str,
    default: int,
    min_value: int,
    max_value: int,
) -> tuple[int | None, str | None]:
    """Parse a bounded integer query parameter."""
    if raw == "" or raw is None:
        return default, None
    try:
        value = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None, f"{label} must be an integer"
    if value < min_value:
        return None, f"{label} must be at least {min_value}"
    return min(value, max_value), None


class LocalRateLimiter:
    """Small in-memory sliding-window limiter for local HTTP mutation APIs."""

    def __init__(
        self,
        max_events: int,
        window_seconds: float,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.max_events = max(1, int(max_events))
        self.window_seconds = max(0.1, float(window_seconds))
        self._clock = clock or time.monotonic
        self._events: dict[str, list[float]] = {}

    def check(self, key: object) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        now = self._clock()
        key_text = str(key or "local")
        cutoff = now - self.window_seconds
        events = [
            timestamp
            for timestamp in self._events.get(key_text, [])
            if timestamp > cutoff
        ]
        if len(events) >= self.max_events:
            retry_after = max(1, int(round(events[0] + self.window_seconds - now)))
            self._events[key_text] = events
            return False, retry_after
        events.append(now)
        self._events[key_text] = events
        return True, 0


def local_security_headers(
    api_version: str,
    content_security_policy: str = CONTENT_SECURITY_POLICY,
) -> tuple[tuple[str, str], ...]:
    """Return baseline local-viewer security headers."""
    return (
        ("X-Link-API-Version", str(api_version)),
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("X-DNS-Prefetch-Control", "off"),
        ("X-Permitted-Cross-Domain-Policies", "none"),
        ("Referrer-Policy", "no-referrer"),
        ("Cross-Origin-Resource-Policy", "same-origin"),
        ("Cross-Origin-Opener-Policy", "same-origin"),
        ("Permissions-Policy", PERMISSIONS_POLICY),
        ("Content-Security-Policy", content_security_policy),
    )


def local_no_store_headers() -> tuple[tuple[str, str], ...]:
    """Return cache-prevention headers for personal local memory responses."""
    return (
        ("Cache-Control", "no-store"),
        ("Pragma", "no-cache"),
        ("Expires", "0"),
    )


def _host_without_port(host: str) -> str | None:
    if any(char.isspace() for char in host):
        return None
    if host.startswith("["):
        closing = host.find("]")
        if closing < 0:
            return None
        host_name = host[1:closing]
        remainder = host[closing + 1:]
        if remainder:
            if not remainder.startswith(":"):
                return None
            port = remainder[1:]
            if port and not port.isdigit():
                return None
        return host_name
    if host.count(":") == 1:
        host_name, port = host.rsplit(":", 1)
        if port and not port.isdigit():
            return None
        return host_name
    if ":" in host:
        return None
    return host


def validate_local_host_header(
    host_header: object,
    allowed_hosts: Iterable[str] = ALLOWED_LOCAL_HOSTS,
) -> tuple[bool, str | None]:
    """Validate a local-only Host header for the unauthenticated viewer."""
    host = str(host_header or "").strip().lower()
    if not host:
        return False, HOST_HEADER_REQUIRED
    host_name = _host_without_port(host)
    if host_name in set(allowed_hosts):
        return True, None
    return False, HOST_HEADER_LOCAL_ONLY


def _browser_source_host(header_value: object) -> str | None:
    value = str(header_value or "").strip().lower()
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return _host_without_port(parsed.netloc) or ""


def _browser_source_port(header_value: object) -> int | None:
    parsed = urlsplit(str(header_value or "").strip().lower())
    try:
        port = parsed.port
    except ValueError:
        return -1
    if port is None:
        return {"http": 80, "https": 443}.get(parsed.scheme)
    return port


def host_header_port(host_header: object, *, default: int | None = 80) -> int | None:
    """The port the browser addressed, from the Host header ("localhost:8080" -> 8080).

    This, not the port the server bound, is what a same-origin Origin carries:
    behind `ssh -L 8080:127.0.0.1:3000` or an editor's port forwarding the
    viewer listens on 3000 while the page is served, and posts, as :8080.
    """
    host = str(host_header or "").strip().lower()
    if not host:
        return None
    try:
        port = urlsplit(f"//{host}").port
    except ValueError:
        return None
    return port if port is not None else default


def validate_local_browser_source_headers(
    origin_header: object,
    referer_header: object,
    allowed_hosts: Iterable[str] = ALLOWED_LOCAL_HOSTS,
    *,
    allowed_port: int | None = None,
) -> tuple[bool, str | None]:
    """Allow browser-supplied Origin/Referer only from the local viewer.

    With `allowed_port`, the source must also be the viewer's own port as the
    browser sees it (pass `host_header_port` of the request's Host header):
    any other dev server or tool on localhost is a different origin, and the
    custom header should not be the only thing standing between it and a
    mutation.
    """
    allowed = set(allowed_hosts)
    for header_value in (origin_header, referer_header):
        host = _browser_source_host(header_value)
        if host is None:
            continue
        if host not in allowed:
            return False, BROWSER_SOURCE_LOCAL_ONLY
        if allowed_port is not None and _browser_source_port(header_value) != allowed_port:
            return False, BROWSER_SOURCE_LOCAL_ONLY
    return True, None


def safe_resolve(path: Path) -> Path | None:
    """Resolve a path, returning None for malformed filesystem inputs."""
    if "\0" in str(path):
        return None
    try:
        return path.resolve()
    except (OSError, ValueError):
        return None


def is_relative_to(path: Path, root: Path) -> bool:
    """Return whether path stays under root after both paths are resolved."""
    resolved_path = safe_resolve(path)
    resolved_root = safe_resolve(root)
    if not resolved_path or not resolved_root:
        return False
    try:
        resolved_path.relative_to(resolved_root)
        return True
    except ValueError:
        return False


def is_allowed_static_file(
    path: Path,
    raw_dir: Path,
    root_files: Iterable[Path],
    raw_static_types: Mapping[str, str],
) -> bool:
    """Check whether a static file is an allowed root asset or raw media file."""
    resolved_path = safe_resolve(path)
    resolved_raw_dir = safe_resolve(raw_dir)
    if not resolved_path or not resolved_raw_dir:
        return False
    allowed_root_files = {
        resolved
        for root_file in root_files
        if (resolved := safe_resolve(root_file)) is not None
    }
    return resolved_path in allowed_root_files or (
        is_relative_to(resolved_path, resolved_raw_dir)
        and resolved_path.suffix.lower() in raw_static_types
    )


def resolve_raw_static_path(
    raw_dir: Path,
    url_fragment: object,
    raw_static_types: Mapping[str, str],
) -> tuple[Path | None, str | None]:
    """Resolve a /raw/ URL fragment to an allowed local file and MIME type."""
    decoded = unquote(str(url_fragment or "")).lstrip("/")
    resolved_raw_dir = safe_resolve(raw_dir)
    resolved = safe_resolve(raw_dir / decoded)
    if not resolved_raw_dir or not resolved or not is_relative_to(resolved, resolved_raw_dir):
        return None, None
    content_type = raw_static_types.get(resolved.suffix.lower())
    if not content_type:
        return None, None
    return resolved, content_type
