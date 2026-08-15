#!/usr/bin/env python3
"""Collect bounded CI evidence for Bar without executing the failed revision."""

from __future__ import annotations

import base64
import email.utils
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Iterable


REPOSITORY = "gowtham0992/link"
CI_WORKFLOW_NAME = "CI"
CI_WORKFLOW_PATH = ".github/workflows/ci.yml"
CAPTURE_WORKFLOW_PATH = ".github/workflows/bar-investigate.yml"
DEVELOP_BRANCH = "develop"
MAIN_REF = "refs/heads/main"
PRODUCER = "link-bar-action/v1"
GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2026-03-10"
DEFAULT_ENDPOINT = (
    "https://bar-private.gowthamsarveswaran.com/api/v1/github/investigations"
)
MAX_PACKET_BYTES = 128 * 1024
MAX_LOG_BYTES = 2 * 1024 * 1024
MAX_EVIDENCE_ITEM_BYTES = 12 * 1024
MAX_EVIDENCE_BYTES = 64 * 1024
MAX_EVIDENCE_LINES = 400
EVIDENCE_KIND_BUDGETS = {
    "job_log": (56, 12 * 1024),
    "workflow": (48, 8 * 1024),
    "source_diff": (40, 5 * 1024),
    "source": (40, 5 * 1024),
    "check_annotation": (24, 4 * 1024),
}
MAX_FAILED_JOBS = 4
MAX_JOBS = 50
MAX_CHANGED_FILES = 100
MAX_RETRY_AFTER_SECONDS = 60.0

SHA_RE = re.compile(r"^[a-f0-9]{40}$")
HASH_RE = re.compile(r"^[a-f0-9]{64}$")
INTEGER_RE = re.compile(r"^[1-9][0-9]*$")
ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
UNSAFE_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
WINDOWS_WORKSPACE_RE = re.compile(
    r"(?i)(?:[A-Z]:\\a\\link\\link|[A-Z]:/a/link/link)(?P<tail>(?:[\\/][^\s:'\"<>|]*)*)"
)
POSIX_WORKSPACE_RE = re.compile(
    r"/(?:home/runner/work/link/link|github/workspace)(?P<tail>/[^\s:'\"<>]*)?"
)
HOME_RE = re.compile(r"/(?:Users|home)/[^/\s]+(?P<tail>/[^\s:'\"<>]*)?")
TEMP_ROOT_PATTERNS = (
    re.compile(
        r"(?i)(?:[A-Z]:\\(?:Users\\[^\\\s]+\\AppData\\Local\\Temp|Windows\\Temp))"
        r"(?P<tail>(?:[\\/][^\s:'\"<>|]*)*)"
    ),
    re.compile(r"/(?:private/tmp|tmp)(?P<tail>/[^\s:'\"<>]*)?"),
    re.compile(
        r"/(?:private/)?var/folders/[^/\s]+/[^/\s]+/T"
        r"(?P<tail>/[^\s:'\"<>]*)?"
    ),
)
TOOLCACHE_RE = re.compile(
    r"(?i)(?:/opt/hostedtoolcache|[A-Z]:\\hostedtoolcache)(?P<tail>[/\\][^\s:'\"<>]*)?"
)
ENV_LINE_RE = re.compile(
    r"(?m)^(?P<prefix>(?:\d{4}-\d{2}-\d{2}T[0-9:.+-]+Z\s+)?[ +\-]?)"
    r"(?P<key>[A-Z][A-Z0-9_]{2,})\s*=\s*.+$"
)

TOKEN_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I),
    re.compile(r"\b(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(
        r"\b(?:authorization|proxy-authorization)\s*[:=]\s*(?:bearer|basic)\s+\S+",
        re.I,
    ),
    re.compile(
        r"\b(?:password|passwd|secret|token|api[_-]?key|client[_-]?secret)\s*[:=]\s*[^\s<]{8,}",
        re.I,
    ),
)

FAILURE_SIGNAL_RE = re.compile(
    r"(?:##\[error\]|traceback|filenotfounderror|permissionerror|assertionerror|"
    r"databaseerror|operationalerror|\bfailed\b|\berror\b|exit code)",
    re.I,
)


class IntegrationError(RuntimeError):
    """A safe-to-display integration failure."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, _request, _file_pointer, _code, _message, _headers, _url):
        return None


@dataclass(frozen=True)
class CollectedLog:
    text: str
    truncated: bool
    line_offset: int


def require(condition: bool, message: str) -> None:
    if not condition:
        raise IntegrationError(message)


def parse_positive_integer(value: str, field: str) -> int:
    require(bool(INTEGER_RE.fullmatch(value)), f"{field} must be a positive integer")
    return int(value)


def zero_counts() -> dict[str, int]:
    return {"credential": 0, "email": 0, "environment": 0, "path": 0, "url": 0}


def add_counts(total: dict[str, int], other: dict[str, int]) -> None:
    for key in total:
        total[key] += other[key]


def _replace_with_count(
    pattern: re.Pattern[str],
    replacement: str | Callable[[re.Match[str]], str],
    text: str,
) -> tuple[str, int]:
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return replacement(match) if callable(replacement) else replacement

    return pattern.sub(replace, text), count


def _sanitize_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    trailing = ""
    while raw and raw[-1] in "),.;":
        trailing = raw[-1] + trailing
        raw = raw[:-1]
    try:
        url = urllib.parse.urlsplit(raw)
    except ValueError:
        return "<URL>" + trailing
    if url.username or url.password or not url.hostname:
        return "<URL>" + trailing
    sensitive_parameters = {
        "token", "key", "sig", "signature", "credential", "auth", "expires"
    }
    query_names = {name.lower() for name, _ in urllib.parse.parse_qsl(url.query)}
    if any(
        name in sensitive_parameters or name.startswith("x-amz-") for name in query_names
    ):
        return "<SIGNED_LOG_URL>" + trailing
    clean = urllib.parse.urlunsplit((url.scheme, url.netloc, url.path, "", ""))
    return clean + trailing


def sanitize_text(value: str) -> tuple[str, dict[str, int]]:
    """Sanitize model-visible text and return exact redaction counts."""
    counts = zero_counts()
    text = ANSI_RE.sub("", value.replace("\r\n", "\n").replace("\r", "\n"))
    text = UNSAFE_CONTROL_RE.sub("", text)
    text = "".join(character for character in text if character in "\n\t" or character.isprintable())

    def environment_replacement(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}<REDACTED_ENVIRONMENT>"

    text, counts["environment"] = _replace_with_count(
        ENV_LINE_RE, environment_replacement, text
    )

    for pattern in TOKEN_PATTERNS:
        text, count = _replace_with_count(pattern, "<REDACTED_CREDENTIAL>", text)
        counts["credential"] += count

    text, counts["email"] = _replace_with_count(EMAIL_RE, "<REDACTED_EMAIL>", text)

    url_matches = list(URL_RE.finditer(text))
    text = URL_RE.sub(_sanitize_url, text)
    counts["url"] = 0
    for match in url_matches:
        raw = match.group(0).rstrip("),.;")
        try:
            parsed = urllib.parse.urlsplit(raw)
        except ValueError:
            counts["url"] += 1
            continue
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            counts["url"] += 1

    path_count = 0
    for pattern, marker in (
        (WINDOWS_WORKSPACE_RE, "<WORKSPACE>"),
        (POSIX_WORKSPACE_RE, "<WORKSPACE>"),
        (TOOLCACHE_RE, "<TOOL_CACHE>"),
        (HOME_RE, "<HOME>"),
    ):
        def path_replacement(match: re.Match[str], marker: str = marker) -> str:
            tail = match.groupdict().get("tail") or ""
            return marker + tail.replace("\\", "/")

        text, replaced = _replace_with_count(pattern, path_replacement, text)
        path_count += replaced
    for pattern in TEMP_ROOT_PATTERNS:
        text, replaced = _replace_with_count(
            pattern,
            lambda match: "<TEMP>" + (match.group("tail") or "").replace("\\", "/"),
            text,
        )
        path_count += replaced
    counts["path"] = path_count

    assert_no_sensitive_survivor(text)
    return text, counts


def assert_no_sensitive_survivor(value: str) -> None:
    require(not EMAIL_RE.search(value), "sanitizer left an email in model-visible data")
    require(
        not any(pattern.search(value) for pattern in TOKEN_PATTERNS),
        "sanitizer left a credential in model-visible data",
    )
    for match in URL_RE.finditer(value):
        raw = match.group(0).rstrip("),.;")
        try:
            url = urllib.parse.urlsplit(raw)
        except ValueError as error:
            raise IntegrationError("sanitizer left a malformed URL") from error
        require(
            not url.username
            and not url.password
            and not url.query
            and not url.fragment,
            "sanitizer left a sensitive URL in model-visible data",
        )


def sanitize_inline(value: Any, field: str, maximum: int = 160) -> str:
    require(isinstance(value, str) and value.strip(), f"{field} is missing")
    clean, _ = sanitize_text(value.strip())
    require(len(clean) <= maximum, f"{field} is too long")
    return clean


def validate_repo_path(value: Any, field: str) -> str:
    require(isinstance(value, str) and value, f"{field} is missing")
    require(
        len(value) <= 300
        and not value.startswith("/")
        and "\\" not in value
        and all(part not in ("", ".", "..") for part in value.split("/")),
        f"{field} is not a canonical repository path",
    )
    assert_no_sensitive_survivor(value)
    return value


def read_bounded_log(response: Any) -> CollectedLog:
    buffer = bytearray()
    discarded_lines = 0
    truncated = False
    starts_mid_line = False
    while True:
        chunk = response.read(64 * 1024)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) <= MAX_LOG_BYTES:
            continue
        truncated = True
        overflow = len(buffer) - MAX_LOG_BYTES
        newline = buffer.find(b"\n", overflow)
        if newline >= 0:
            removed = buffer[: newline + 1]
            discarded_lines += removed.count(b"\n")
            del buffer[: newline + 1]
            starts_mid_line = False
        else:
            removed = buffer[:overflow]
            discarded_lines += removed.count(b"\n")
            del buffer[:overflow]
            starts_mid_line = True
    if starts_mid_line:
        newline = buffer.find(b"\n")
        if newline >= 0:
            discarded_lines += 1
            del buffer[: newline + 1]
    return CollectedLog(
        text=bytes(buffer).decode("utf-8", errors="replace"),
        truncated=truncated,
        line_offset=discarded_lines,
    )


class GitHubClient:
    def __init__(self, token: str, timeout: float = 20.0):
        require(bool(token), "GITHUB_TOKEN is not configured")
        self._token = token
        self._timeout = timeout

    def _request(self, path: str, accept: str) -> bytes:
        require(path.startswith("/repos/gowtham0992/link/"), "unexpected GitHub API path")
        request = urllib.request.Request(
            GITHUB_API + path,
            headers={
                "Accept": accept,
                "Authorization": f"Bearer {self._token}",
                "User-Agent": "link-bar-action/v1",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                data = response.read(MAX_LOG_BYTES + 1)
        except urllib.error.HTTPError as error:
            raise IntegrationError(f"GitHub API returned HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise IntegrationError("GitHub API request failed") from error
        require(len(data) <= MAX_LOG_BYTES, "GitHub response exceeded the collection limit")
        return data

    def get_json(self, path: str) -> dict[str, Any] | list[Any]:
        data = self._request(path, "application/vnd.github+json")
        try:
            parsed = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise IntegrationError("GitHub API returned malformed JSON") from error
        require(isinstance(parsed, (dict, list)), "GitHub API returned an invalid document")
        return parsed

    def get_log(self, job_id: int) -> CollectedLog:
        api_request = urllib.request.Request(
            f"{GITHUB_API}/repos/{REPOSITORY}/actions/jobs/{job_id}/logs",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "User-Agent": "link-bar-action/v1",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
        )
        try:
            urllib.request.build_opener(_NoRedirect).open(api_request, timeout=self._timeout)
            raise IntegrationError("GitHub log endpoint did not redirect")
        except urllib.error.HTTPError as error:
            require(error.code in (301, 302, 303, 307, 308), "GitHub log request failed")
            location = error.headers.get("Location", "")
        try:
            redirect = urllib.parse.urlsplit(location)
        except ValueError as error:
            raise IntegrationError("GitHub log redirect was invalid") from error
        require(
            redirect.scheme == "https"
            and bool(redirect.hostname)
            and not redirect.username
            and not redirect.password
            and redirect.hostname not in ("localhost", "127.0.0.1", "::1"),
            "GitHub log redirect was not a safe HTTPS URL",
        )
        # The signed redirect URL is a credential itself. Fetch it without the
        # GitHub Authorization header and never expose or persist it.
        redirected_request = urllib.request.Request(
            location, headers={"User-Agent": "link-bar-action/v1"}
        )
        try:
            with urllib.request.urlopen(redirected_request, timeout=self._timeout) as response:
                return read_bounded_log(response)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
            raise IntegrationError("GitHub log download failed") from error


def validate_capture_context(environment: dict[str, str]) -> tuple[int, int, str]:
    run_id = parse_positive_integer(environment.get("BAR_SOURCE_RUN_ID", ""), "run ID")
    attempt = parse_positive_integer(
        environment.get("BAR_SOURCE_RUN_ATTEMPT", ""), "run attempt"
    )
    capture_sha = environment.get("BAR_CAPTURE_SHA", "")
    require(bool(SHA_RE.fullmatch(capture_sha)), "capture SHA must be a lowercase commit SHA")
    require(environment.get("BAR_CAPTURE_REF") == MAIN_REF, "collector must come from main")
    expected_workflow_ref = f"{REPOSITORY}/{CAPTURE_WORKFLOW_PATH}@{MAIN_REF}"
    require(
        environment.get("BAR_WORKFLOW_REF") == expected_workflow_ref,
        "collector workflow ref is not trusted main",
    )
    require(
        environment.get("BAR_TRIGGER_EVENT") in ("workflow_run", "workflow_dispatch"),
        "unsupported collector trigger",
    )
    return run_id, attempt, capture_sha


def validate_source_run(run: dict[str, Any], requested_attempt: int) -> None:
    repository = run.get("repository") or {}
    head_repository = run.get("head_repository") or {}
    require(repository.get("full_name") == REPOSITORY, "run belongs to another repository")
    require(head_repository.get("full_name") == REPOSITORY, "fork runs are not accepted")
    require(run.get("name") == CI_WORKFLOW_NAME, "run is not the CI workflow")
    require(run.get("path") == CI_WORKFLOW_PATH, "run used an unexpected workflow file")
    require(run.get("head_branch") == DEVELOP_BRANCH, "run did not fail on develop")
    require(run.get("status") == "completed", "run is not complete")
    require(run.get("conclusion") == "failure", "run did not fail")
    require(run.get("run_attempt") == requested_attempt, "run attempt does not match")
    require(run.get("event") in ("pull_request", "workflow_dispatch"), "run event is not allowed")
    require(bool(SHA_RE.fullmatch(str(run.get("head_sha", "")))), "run head SHA is invalid")
    html_url = str(run.get("html_url", ""))
    require(
        html_url.startswith(f"https://github.com/{REPOSITORY}/actions/runs/")
        and "?" not in html_url
        and "#" not in html_url,
        "run URL is not a public Link Actions URL",
    )


def normalize_conclusion(value: Any) -> str:
    allowed = {
        "success", "failure", "neutral", "cancelled", "skipped", "timed_out",
        "action_required", "stale", "startup_failure",
    }
    return value if value in allowed else "skipped"


def build_job_summary(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    require(0 < len(jobs) <= MAX_JOBS, "unexpected number of jobs")
    output = []
    for job in jobs:
        output.append(
            {
                "name": sanitize_inline(job.get("name"), "job name"),
                "conclusion": normalize_conclusion(job.get("conclusion")),
                "steps": [
                    {
                        "name": sanitize_inline(step.get("name"), "step name"),
                        "conclusion": normalize_conclusion(step.get("conclusion")),
                    }
                    for step in (job.get("steps") or [])
                    if step.get("name") and step.get("conclusion")
                ],
            }
        )
    return output


def failure_windows(
    log: str,
    radius: int = 14,
    maximum_windows: int = 3,
    line_offset: int = 0,
) -> list[tuple[int, int, str]]:
    clean = ANSI_RE.sub("", log.replace("\r\n", "\n").replace("\r", "\n"))
    lines = clean.splitlines()
    signals = [index for index, line in enumerate(lines) if FAILURE_SIGNAL_RE.search(line)]
    if not signals:
        signals = [max(0, len(lines) - 1)]
    ranges: list[list[int]] = []
    for index in signals:
        start = max(0, index - radius)
        end = min(len(lines), index + radius + 1)
        if (
            ranges
            and start <= ranges[-1][1]
            and end - ranges[-1][0] <= (radius * 4)
        ):
            ranges[-1][1] = max(ranges[-1][1], end)
        else:
            ranges.append([start, end])
    if len(ranges) > maximum_windows:
        ranges = ranges[: maximum_windows - 1] + [ranges[-1]]
    return [
        (start + 1 + line_offset, end + line_offset, "\n".join(lines[start:end]))
        for start, end in ranges
    ]


def first_patch_range(patch: str) -> tuple[int, int]:
    match = re.search(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", patch, re.M)
    if not match:
        return 1, max(1, len(patch.splitlines()))
    start = int(match.group(1))
    length = int(match.group(2) or "1")
    return max(1, start), max(1, start + max(length, 1) - 1)


def relevant_pull_files(
    files: list[dict[str, Any]], diagnostic_text: str, job_name: str, step_name: str
) -> list[dict[str, Any]]:
    haystack = f"{diagnostic_text}\n{job_name}\n{step_name}".lower()
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for item in files:
        path = str(item.get("filename", ""))
        basename = path.rsplit("/", 1)[-1].lower()
        stem = basename.rsplit(".", 1)[0]
        score = 0
        if path.lower() in haystack:
            score += 10
        if basename and basename in haystack:
            score += 6
        if len(stem) >= 5 and stem in haystack:
            score += 3
        if "link-mcp" in haystack and path == "mcp_package/pyproject.toml":
            score += 8
        if score and item.get("patch"):
            scored.append((score, path, item))
    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    return [item for _, _, item in scored[:4]]


@dataclass
class EvidenceBuilder:
    items: list[dict[str, Any]]
    totals: dict[str, int]
    truncated: bool = False
    budget_truncated: bool = False

    @classmethod
    def create(cls) -> "EvidenceBuilder":
        return cls([], zero_counts())

    def add(
        self,
        *,
        kind: str,
        title: str,
        content: str,
        job: str | None,
        step: str | None,
        path: str | None,
        sha_role: str | None,
        line_start: int,
        line_end: int,
    ) -> bool:
        clean, counts = sanitize_text(content)
        original = clean
        line_budget, byte_budget = EVIDENCE_KIND_BUDGETS.get(
            kind, (40, 5 * 1024)
        )
        used_lines = sum(len(item["content"].splitlines()) for item in self.items)
        used_bytes = sum(
            len(item["content"].encode("utf-8")) for item in self.items
        )
        line_budget = min(line_budget, MAX_EVIDENCE_LINES - used_lines)
        byte_budget = min(
            byte_budget,
            MAX_EVIDENCE_ITEM_BYTES,
            MAX_EVIDENCE_BYTES - used_bytes,
        )
        clean = bounded_evidence_text(clean, line_budget, byte_budget)
        if clean != original:
            self.truncated = True
            self.budget_truncated = True
        if not clean.strip():
            return False
        sequence = len(self.items) + 1
        item = {
            "id": f"E-LINK-{sequence:03d}",
            "kind": kind,
            "title": sanitize_inline(title, "evidence title"),
            "content": clean,
            "sequence": sequence,
            "source": {
                "job": sanitize_inline(job, "evidence job") if job else None,
                "step": sanitize_inline(step, "evidence step") if step else None,
                "path": validate_repo_path(path, "evidence path") if path else None,
                "sha_role": sha_role,
                "original_line_start": max(1, line_start),
                "original_line_end": min(
                    max(max(1, line_start), line_end),
                    max(1, line_start) + len(clean.splitlines()) - 1,
                ),
            },
            "redactions": counts,
        }
        self.items.append(item)
        add_counts(self.totals, counts)
        return True

    def validate_limits(self) -> None:
        require(len(self.items) <= 20, "too many evidence items")
        require(
            sum(len(item["content"].encode("utf-8")) for item in self.items)
            <= MAX_EVIDENCE_BYTES,
            "evidence exceeds 64 KiB",
        )
        require(
            sum(len(item["content"].splitlines()) for item in self.items)
            <= MAX_EVIDENCE_LINES,
            "evidence exceeds 400 lines",
        )


def bounded_evidence_text(content: str, maximum_lines: int, maximum_bytes: int) -> str:
    """Keep a deterministic prefix that satisfies both Bar evidence limits."""
    if maximum_lines <= 0 or maximum_bytes <= 0:
        return ""
    kept: list[str] = []
    used_bytes = 0
    for line in content.splitlines(keepends=True)[:maximum_lines]:
        encoded = line.encode("utf-8")
        if used_bytes + len(encoded) > maximum_bytes:
            remaining = maximum_bytes - used_bytes
            if remaining > 0:
                prefix = encoded[:remaining].decode("utf-8", errors="ignore")
                if prefix:
                    kept.append(prefix)
            break
        kept.append(line)
        used_bytes += len(encoded)
    return "".join(kept).rstrip("\n")


def fetch_pull_request(
    client: GitHubClient, run: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if run["event"] != "pull_request":
        return None, []
    pulls = run.get("pull_requests") or []
    require(len(pulls) == 1, "pull-request run must identify exactly one pull request")
    number = pulls[0].get("number")
    require(isinstance(number, int) and number > 0, "pull request number is invalid")
    pull = client.get_json(f"/repos/{REPOSITORY}/pulls/{number}")
    require(isinstance(pull, dict), "pull request response is invalid")
    require((pull.get("head") or {}).get("sha") == run["head_sha"], "pull request head SHA differs")
    require(
        ((pull.get("head") or {}).get("repo") or {}).get("full_name") == REPOSITORY,
        "fork pull requests are not accepted",
    )
    files = client.get_json(f"/repos/{REPOSITORY}/pulls/{number}/files?per_page=100")
    require(isinstance(files, list), "pull request files response is invalid")
    require(len(files) <= MAX_CHANGED_FILES, "pull request has too many changed files")
    if len(files) == MAX_CHANGED_FILES:
        overflow = client.get_json(
            f"/repos/{REPOSITORY}/pulls/{number}/files?per_page=100&page=2"
        )
        require(isinstance(overflow, list) and not overflow, "pull request has too many changed files")
    return pull, files


def fetch_workflow_snippet(
    client: GitHubClient, head_sha: str, failed_step: str
) -> tuple[int, int, str] | None:
    encoded_path = urllib.parse.quote(CI_WORKFLOW_PATH, safe="/")
    response = client.get_json(
        f"/repos/{REPOSITORY}/contents/{encoded_path}?ref={head_sha}"
    )
    require(isinstance(response, dict), "workflow source response is invalid")
    require(response.get("encoding") == "base64", "workflow source encoding is invalid")
    try:
        encoded = "".join(response["content"].split())
        content = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (KeyError, ValueError, UnicodeDecodeError) as error:
        raise IntegrationError("workflow source content is malformed") from error
    lines = content.splitlines()
    needle = failed_step.lower()
    for index, line in enumerate(lines):
        if needle in line.lower():
            start = max(0, index - 10)
            end = min(len(lines), index + 16)
            return start + 1, end, "\n".join(lines[start:end])
    return None


def build_packet_for_job(
    *,
    client: GitHubClient,
    run: dict[str, Any],
    jobs: list[dict[str, Any]],
    pull: dict[str, Any] | None,
    pull_files: list[dict[str, Any]],
    focused_job: dict[str, Any],
    capture_sha: str,
) -> dict[str, Any]:
    failed_steps = [
        step for step in (focused_job.get("steps") or []) if step.get("conclusion") == "failure"
    ]
    require(bool(failed_steps), "failed job has no failed step")
    failed_step = failed_steps[0]
    job_name = sanitize_inline(focused_job.get("name"), "focused job name")
    step_name = sanitize_inline(failed_step.get("name"), "failed step name")
    job_id = focused_job.get("id")
    require(isinstance(job_id, int) and job_id > 0, "focused job ID is invalid")

    collected_log = client.get_log(job_id)
    windows = failure_windows(
        collected_log.text,
        line_offset=collected_log.line_offset,
    )
    builder = EvidenceBuilder.create()
    builder.truncated = collected_log.truncated
    missing: list[str] = []
    if collected_log.truncated:
        missing.append(
            f"Job log exceeded {MAX_LOG_BYTES} bytes; retained the bounded final portion"
        )
    diagnostic_text = "\n".join(content for _, _, content in windows)
    for index, (start, end, content) in enumerate(windows, start=1):
        builder.add(
            kind="job_log",
            title=f"{job_name} failure log window {index}",
            content=content,
            job=job_name,
            step=step_name,
            path=None,
            sha_role=None,
            line_start=start,
            line_end=end,
        )

    workflow = fetch_workflow_snippet(client, run["head_sha"], step_name)
    if workflow:
        start, end, content = workflow
        builder.add(
            kind="workflow",
            title=f"CI definition for {step_name}",
            content=content,
            job=job_name,
            step=step_name,
            path=CI_WORKFLOW_PATH,
            sha_role="head",
            line_start=start,
            line_end=end,
        )
    else:
        missing.append(f"No workflow snippet matched failed step: {step_name}")

    relevant = relevant_pull_files(pull_files, diagnostic_text, job_name, step_name)
    for item in relevant:
        path = validate_repo_path(item.get("filename"), "changed file path")
        patch = str(item.get("patch"))
        start, end = first_patch_range(patch)
        builder.add(
            kind="source_diff",
            title=f"Change in {path}",
            content=patch,
            job=job_name,
            step=step_name,
            path=path,
            sha_role="base_to_head",
            line_start=start,
            line_end=end,
        )
    if pull and not relevant:
        missing.append("No changed-file patch matched the bounded failure evidence")

    if builder.budget_truncated:
        missing.append(
            "Lower-value evidence context was deterministically truncated to Bar's "
            "per-job line and byte budgets"
        )

    builder.validate_limits()
    job_summary = build_job_summary(jobs)
    change_summary = [
        {
            "path": validate_repo_path(item.get("filename"), "changed file path"),
            "status": item.get("status") if item.get("status") in {
                "added", "modified", "removed", "renamed", "copied", "changed", "unchanged"
            } else "changed",
            "additions": max(0, int(item.get("additions") or 0)),
            "deletions": max(0, int(item.get("deletions") or 0)),
        }
        for item in pull_files
    ]
    pull_summary = None
    if pull:
        base_sha = (pull.get("base") or {}).get("sha")
        head_sha = (pull.get("head") or {}).get("sha")
        require(bool(SHA_RE.fullmatch(str(base_sha))), "pull request base SHA is invalid")
        require(head_sha == run["head_sha"], "pull request head SHA differs")
        pull_summary = {"number": pull["number"], "base_sha": base_sha, "head_sha": head_sha}

    delivery_id = hashlib.sha256(
        "\0".join(
            ["github", REPOSITORY, str(run["id"]), str(run["run_attempt"]), str(job_id)]
        ).encode()
    ).hexdigest()
    sent_at = focused_job.get("completed_at") or run.get("updated_at")
    require(isinstance(sent_at, str) and sent_at.endswith("Z"), "completion time is invalid")

    packet = {
        "schema_version": 1,
        "capture": {
            "code_repository": REPOSITORY,
            "code_ref": MAIN_REF,
            "code_sha": capture_sha,
            "workflow_path": CAPTURE_WORKFLOW_PATH,
        },
        "delivery": {"id": delivery_id, "producer": PRODUCER, "sent_at": sent_at},
        "source": {
            "repository": REPOSITORY,
            "workflow": {
                "id": run["workflow_id"],
                "name": sanitize_inline(run["name"], "workflow name"),
                "path": validate_repo_path(run["path"], "workflow path"),
            },
            "run": {
                "id": run["id"],
                "attempt": run["run_attempt"],
                "event": run["event"],
                "head_sha": run["head_sha"],
                "html_url": run["html_url"],
            },
            "pull_request": pull_summary,
        },
        "focus": {"job_id": job_id, "job_name": job_name, "failed_step": step_name},
        "job_summary": job_summary,
        "change_summary": change_summary,
        "evidence": builder.items,
        "missing_evidence": missing,
        "sanitization": {
            "version": 1,
            "truncated": builder.truncated,
            "redaction_counts": builder.totals,
        },
    }
    assert_model_bound_fields_sanitized(packet)
    body = canonical_json_bytes(packet)
    require(len(body) <= MAX_PACKET_BYTES, "evidence packet exceeds 128 KiB")
    return packet


def assert_model_bound_fields_sanitized(packet: dict[str, Any]) -> None:
    def walk(value: Any) -> Iterable[str]:
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for item in value:
                yield from walk(item)
        elif isinstance(value, dict):
            for item in value.values():
                yield from walk(item)

    for text in walk(packet):
        assert_no_sensitive_survivor(text)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def retry_after_seconds(value: str | None, now: float) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return min(float(value), MAX_RETRY_AFTER_SECONDS)
    try:
        retry_at = email.utils.parsedate_to_datetime(value)
        if retry_at.tzinfo is None:
            return None
        delay = max(0.0, retry_at.timestamp() - now)
    except (TypeError, ValueError, OverflowError):
        return None
    return min(delay, MAX_RETRY_AFTER_SECONDS)


def send_packet(
    packet: dict[str, Any],
    *,
    endpoint: str,
    client_id: str,
    client_secret: str,
    opener: Callable[..., Any] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    require(endpoint == DEFAULT_ENDPOINT, "Bar endpoint is not allowlisted")
    require(bool(client_id) and bool(client_secret), "Bar service credentials are not configured")
    transport = opener or urllib.request.build_opener(_NoRedirect).open
    body = canonical_json_bytes(packet)
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": packet["delivery"]["id"],
            "CF-Access-Client-Id": client_id,
            "CF-Access-Client-Secret": client_secret,
        },
    )
    for attempt in range(3):
        try:
            with transport(request, timeout=30) as response:
                status = response.status
                response_body = response.read(64 * 1024 + 1)
            require(len(response_body) <= 64 * 1024, "Bar response exceeded the limit")
            require(status in (200, 202), f"Bar returned HTTP {status}")
            try:
                result = json.loads(response_body)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise IntegrationError("Bar returned invalid JSON") from error
            require(isinstance(result, dict), "Bar returned an invalid response")
            return result
        except urllib.error.HTTPError as error:
            if error.code not in (408, 429, 500, 502, 503, 504) or attempt == 2:
                raise IntegrationError(f"Bar returned HTTP {error.code}") from error
            delay = None
            if error.code == 429:
                headers = getattr(error, "headers", None)
                retry_after = headers.get("Retry-After") if headers is not None else None
                delay = retry_after_seconds(retry_after, clock())
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == 2:
                raise IntegrationError("Bar request failed after retries") from error
            delay = None
        sleeper(delay if delay is not None else float(2**attempt))
    raise IntegrationError("Bar request failed after retries")


def parse_bar_response(result: dict[str, Any]) -> tuple[str, str]:
    investigation = result.get("investigation")
    require(isinstance(investigation, dict), "Bar response omitted investigation")
    investigation_id = investigation.get("id")
    path = investigation.get("url")
    require(
        isinstance(investigation_id, str) and bool(HASH_RE.fullmatch(investigation_id)),
        "Bar response omitted investigation ID",
    )
    require(
        path == f"/private/investigations/{investigation_id}",
        "Bar response returned an unexpected investigation URL",
    )
    return investigation_id, f"https://bar-private.gowthamsarveswaran.com{path}"


def collect_packets(
    client: GitHubClient, run_id: int, attempt: int, capture_sha: str
) -> list[dict[str, Any]]:
    run = client.get_json(
        f"/repos/{REPOSITORY}/actions/runs/{run_id}/attempts/{attempt}"
    )
    require(isinstance(run, dict), "run response is invalid")
    validate_source_run(run, attempt)
    jobs_response = client.get_json(
        f"/repos/{REPOSITORY}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100"
    )
    require(isinstance(jobs_response, dict), "jobs response is invalid")
    jobs = jobs_response.get("jobs")
    require(isinstance(jobs, list), "jobs response is missing jobs")
    require(jobs_response.get("total_count") == len(jobs), "jobs response was truncated")
    failed_jobs = [job for job in jobs if job.get("conclusion") == "failure"]
    require(0 < len(failed_jobs) <= MAX_FAILED_JOBS, "unexpected number of failed jobs")
    pull, pull_files = fetch_pull_request(client, run)
    return [
        build_packet_for_job(
            client=client,
            run=run,
            jobs=jobs,
            pull=pull,
            pull_files=pull_files,
            focused_job=job,
            capture_sha=capture_sha,
        )
        for job in failed_jobs
    ]


def main() -> int:
    try:
        run_id, attempt, capture_sha = validate_capture_context(dict(os.environ))
        client = GitHubClient(os.environ.get("GITHUB_TOKEN", ""))
        packets = collect_packets(client, run_id, attempt, capture_sha)
        for packet in packets:
            result = send_packet(
                packet,
                endpoint=os.environ.get("BAR_ENDPOINT", ""),
                client_id=os.environ.get("BAR_ACCESS_CLIENT_ID", ""),
                client_secret=os.environ.get("BAR_ACCESS_CLIENT_SECRET", ""),
            )
            investigation_id, url = parse_bar_response(result)
            print(f"Bar investigation {investigation_id}: {url}")
            summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
            if summary_path:
                with open(summary_path, "a", encoding="utf-8") as summary:
                    summary.write(f"- [{investigation_id}]({url})\n")
        return 0
    except IntegrationError as error:
        print(f"Bar collection failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
