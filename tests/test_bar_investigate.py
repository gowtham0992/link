from __future__ import annotations

import base64
import email.utils
import hashlib
import json
import urllib.error
from pathlib import Path

import pytest

from scripts import bar_investigate as bar


ROOT = Path(__file__).resolve().parents[1]
CAPTURE_SHA = "a" * 40
HEAD_SHA = "b" * 40
BASE_SHA = "c" * 40


def sample_run() -> dict:
    return {
        "id": 31668261705,
        "run_attempt": 1,
        "workflow_id": 12345,
        "name": "CI",
        "path": ".github/workflows/ci.yml",
        "event": "pull_request",
        "status": "completed",
        "conclusion": "failure",
        "head_branch": "develop",
        "head_sha": HEAD_SHA,
        "html_url": "https://github.com/gowtham0992/link/actions/runs/31668261705",
        "updated_at": "2026-08-14T12:00:00Z",
        "repository": {"full_name": "gowtham0992/link"},
        "head_repository": {"full_name": "gowtham0992/link"},
        "pull_requests": [{"number": 60}],
    }


def sample_jobs() -> list[dict]:
    return [
        {
            "id": 94347441040,
            "name": "package",
            "conclusion": "failure",
            "completed_at": "2026-08-14T12:00:00Z",
            "steps": [
                {"name": "Set up job", "conclusion": "success"},
                {"name": "Build link-mcp", "conclusion": "failure"},
            ],
        },
        {
            "id": 94347441096,
            "name": "windows-smoke",
            "conclusion": "failure",
            "completed_at": "2026-08-14T12:00:01Z",
            "steps": [
                {"name": "Run broad Windows tests", "conclusion": "failure"},
            ],
        },
    ]


def sample_pull() -> dict:
    return {
        "number": 60,
        "base": {"sha": BASE_SHA},
        "head": {"sha": HEAD_SHA, "repo": {"full_name": "gowtham0992/link"}},
    }


class FakeClient:
    def get_log(self, job_id: int) -> bar.CollectedLog:
        if job_id == 94347441040:
            return bar.CollectedLog(
                "\n".join(
                    [
                        "Building source distribution",
                        "/home/runner/work/link/link/mcp_package/pyproject.toml",
                        "FileNotFoundError: .linkignore was configured but is missing",
                        "##[error]Process completed with exit code 1",
                    ]
                ),
                False,
                0,
            )
        return bar.CollectedLog(
            "PermissionError: SQLite database file is still open", False, 0
        )


class Response:
    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int) -> bytes:
        chunk = self._body[:_limit]
        self._body = self._body[_limit:]
        return chunk


def capture_environment(**overrides: str) -> dict[str, str]:
    environment = {
        "BAR_SOURCE_RUN_ID": "31668261705",
        "BAR_SOURCE_RUN_ATTEMPT": "1",
        "BAR_CAPTURE_SHA": CAPTURE_SHA,
        "BAR_CAPTURE_REF": "refs/heads/main",
        "BAR_WORKFLOW_REF": (
            "gowtham0992/link/.github/workflows/bar-investigate.yml@refs/heads/main"
        ),
        "BAR_TRIGGER_EVENT": "workflow_dispatch",
    }
    environment.update(overrides)
    return environment


def test_workflow_checks_out_exact_workflow_revision_and_never_failed_sha():
    workflow = (ROOT / ".github/workflows/bar-investigate.yml").read_text()

    assert "ref: ${{ github.workflow_sha }}" in workflow
    assert "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09" in workflow
    assert "persist-credentials: false" in workflow
    assert "github.event.workflow_run.head_sha" not in workflow
    assert "BAR_CAPTURE_SHA: ${{ github.workflow_sha }}" in workflow
    assert "BAR_ACCESS_CLIENT_ID: ${{ secrets.BAR_ACCESS_CLIENT_ID }}" in workflow
    assert "BAR_ACCESS_CLIENT_SECRET: ${{ secrets.BAR_ACCESS_CLIENT_SECRET }}" in workflow
    assert "contents: read" in workflow
    assert "actions: read" in workflow
    assert "pull-requests: read" in workflow


def test_manual_capture_context_requires_trusted_main_workflow_revision():
    assert bar.validate_capture_context(capture_environment()) == (
        31668261705,
        1,
        CAPTURE_SHA,
    )

    for override in (
        {"BAR_SOURCE_RUN_ID": "abc"},
        {"BAR_SOURCE_RUN_ATTEMPT": "0"},
        {"BAR_CAPTURE_SHA": HEAD_SHA[:-1]},
        {"BAR_CAPTURE_REF": "refs/heads/develop"},
        {"BAR_WORKFLOW_REF": "gowtham0992/link/.github/workflows/ci.yml@refs/heads/main"},
        {"BAR_TRIGGER_EVENT": "pull_request"},
    ):
        with pytest.raises(bar.IntegrationError):
            bar.validate_capture_context(capture_environment(**override))


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("repository", "full_name"), "someone/else"),
        (("head_repository", "full_name"), "someone/fork"),
        (("name",), "Other"),
        (("path",), ".github/workflows/other.yml"),
        (("head_branch",), "main"),
        (("status",), "in_progress"),
        (("conclusion",), "success"),
        (("run_attempt",), 2),
    ],
)
def test_requested_run_is_rejected_unless_it_is_the_exact_failed_link_ci_attempt(
    path: tuple[str, ...], value: object
):
    run = sample_run()
    target = run
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value

    with pytest.raises(bar.IntegrationError):
        bar.validate_source_run(run, 1)


def test_sanitizer_removes_sensitive_values_but_preserves_diagnostic_context():
    raw = "\n".join(
        [
            "\x1b[31mFileNotFoundError: .linkignore\x1b[0m",
            "/home/runner/work/link/link/mcp_package/pyproject.toml",
            r"D:\a\link\link\tests\test_guard_core.py",
            "maintainer@example.com",
            "TOKEN=github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
            "See https://example.test/result?sig=secret#fragment\u202e",
        ]
    )

    clean, counts = bar.sanitize_text(raw)

    assert "FileNotFoundError: .linkignore" in clean
    assert "<WORKSPACE>/mcp_package/pyproject.toml" in clean
    assert "<WORKSPACE>/tests/test_guard_core.py" in clean
    assert "maintainer@example.com" not in clean
    assert "github_pat_" not in clean
    assert "?sig=" not in clean
    assert "#fragment" not in clean
    assert "<SIGNED_LOG_URL>" in clean
    assert "\u202e" not in clean
    assert counts["email"] == 1
    assert counts["credential"] + counts["environment"] >= 1
    assert counts["path"] == 2
    assert counts["url"] == 1
    bar.assert_no_sensitive_survivor(clean)


def test_temp_path_keeps_the_diagnostic_filename_and_suffix():
    clean, counts = bar.sanitize_text(
        "/tmp/link_mcp-2.3.0/.linkignore: No such file or directory"
    )

    assert clean == "<TEMP>/link_mcp-2.3.0/.linkignore: No such file or directory"
    assert counts["path"] == 1


def test_environment_redaction_handles_github_timestamps_and_diff_prefixes():
    raw = "\n".join(
        [
            "2026-08-14T12:00:00.1234567Z BAR_ACCESS_CLIENT_SECRET=should-not-survive",
            "+PACKAGE_TOKEN=github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
            "-OLD_SETTING=private-value",
        ]
    )

    clean, counts = bar.sanitize_text(raw)

    assert clean.splitlines() == [
        "2026-08-14T12:00:00.1234567Z <REDACTED_ENVIRONMENT>",
        "+<REDACTED_ENVIRONMENT>",
        "-<REDACTED_ENVIRONMENT>",
    ]
    assert "should-not-survive" not in clean
    assert "github_pat_" not in clean
    assert "private-value" not in clean
    assert counts["environment"] == 3


def test_secret_survivor_check_covers_metadata_and_path_fields():
    packet = {
        "source": {"workflow": {"name": "CI", "path": ".github/workflows/ci.yml"}},
        "focus": {"job_name": "package", "failed_step": "Build"},
        "job_summary": [],
        "change_summary": [{"path": "safe/file.py"}],
        "evidence": [{"title": "safe", "source": {"path": "safe/file.py"}}],
        "missing_evidence": [],
    }
    packet["source"]["workflow"]["name"] = "token=super-secret-value"

    with pytest.raises(bar.IntegrationError):
        bar.assert_model_bound_fields_sanitized(packet)


def test_log_redirect_never_forwards_github_authorization(monkeypatch):
    api_requests = []
    redirected_requests = []

    class RedirectOpener:
        def open(self, request, timeout):
            assert timeout == 20.0
            api_requests.append(request)
            raise urllib.error.HTTPError(
                request.full_url,
                302,
                "Found",
                {"Location": "https://results.example.test/job.log?sig=signed"},
                None,
            )

    def redirected_urlopen(request, timeout):
        assert timeout == 20.0
        redirected_requests.append(request)
        return Response(200, b"##[error]safe failure")

    monkeypatch.setattr(bar.urllib.request, "build_opener", lambda *_args: RedirectOpener())
    monkeypatch.setattr(bar.urllib.request, "urlopen", redirected_urlopen)

    log = bar.GitHubClient("github-token").get_log(123)

    assert log == bar.CollectedLog("##[error]safe failure", False, 0)
    assert api_requests[0].get_header("Authorization") == "Bearer github-token"
    assert redirected_requests[0].get_header("Authorization") is None
    assert redirected_requests[0].full_url.endswith("?sig=signed")


def test_oversized_job_log_keeps_a_bounded_tail_as_truncated_evidence(monkeypatch):
    class RedirectOpener:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(
                request.full_url,
                302,
                "Found",
                {"Location": "https://results.example.test/job.log?sig=signed"},
                None,
            )

    oversized = (
        b"old unhelpful line\n" * ((bar.MAX_LOG_BYTES // 19) + 10)
        + b"FileNotFoundError: /tmp/link_mcp-2.3.0/.linkignore\n"
    )
    monkeypatch.setattr(bar.urllib.request, "build_opener", lambda *_args: RedirectOpener())
    monkeypatch.setattr(
        bar.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(200, oversized),
    )

    collected = bar.GitHubClient("github-token").get_log(123)

    assert collected.truncated is True
    assert len(collected.text.encode()) <= bar.MAX_LOG_BYTES
    assert "FileNotFoundError: /tmp/link_mcp-2.3.0/.linkignore" in collected.text
    assert collected.line_offset > 0


def test_workflow_source_is_read_as_text_only_and_accepts_github_base64_wrapping():
    workflow = "jobs:\n  package:\n    steps:\n      - name: Build link-mcp\n        run: python -m build\n"
    encoded = base64.b64encode(workflow.encode()).decode()

    class SourceClient:
        def get_json(self, path):
            assert path.endswith(f"?ref={HEAD_SHA}")
            return {"encoding": "base64", "content": encoded[:20] + "\n" + encoded[20:]}

    start, end, content = bar.fetch_workflow_snippet(
        SourceClient(), HEAD_SHA, "Build link-mcp"
    )

    assert start == 1
    assert end == 5
    assert "run: python -m build" in content


def test_packet_is_bounded_deterministic_and_uses_job_scoped_delivery_id(monkeypatch):
    monkeypatch.setattr(
        bar,
        "fetch_workflow_snippet",
        lambda *_args: (10, 12, "- name: Build link-mcp\n  run: python -m build"),
    )
    files = [
        {
            "filename": "mcp_package/pyproject.toml",
            "status": "modified",
            "additions": 2,
            "deletions": 1,
            "patch": "@@ -5,1 +5,2 @@\n include = [\".linkignore\"]",
        }
    ]
    arguments = {
        "client": FakeClient(),
        "run": sample_run(),
        "jobs": sample_jobs(),
        "pull": sample_pull(),
        "pull_files": files,
        "focused_job": sample_jobs()[0],
        "capture_sha": CAPTURE_SHA,
    }

    first = bar.build_packet_for_job(**arguments)
    second = bar.build_packet_for_job(**arguments)

    expected = hashlib.sha256(
        "\0".join(
            ["github", "gowtham0992/link", "31668261705", "1", "94347441040"]
        ).encode()
    ).hexdigest()
    assert first == second
    assert first["delivery"]["id"] == expected
    assert first["capture"]["code_sha"] == CAPTURE_SHA
    assert first["focus"]["failed_step"] == "Build link-mcp"
    assert any(item["kind"] == "job_log" for item in first["evidence"])
    assert any(item["kind"] == "workflow" for item in first["evidence"])
    assert any(item["kind"] == "source_diff" for item in first["evidence"])
    assert len(bar.canonical_json_bytes(first)) <= 128 * 1024


def test_truncated_log_is_marked_without_aborting_packet_creation(monkeypatch):
    class TruncatedClient(FakeClient):
        def get_log(self, _job_id):
            return bar.CollectedLog(
                "FileNotFoundError: /tmp/link_mcp-2.3.0/.linkignore",
                True,
                50_000,
            )

    monkeypatch.setattr(
        bar,
        "fetch_workflow_snippet",
        lambda *_args: (10, 12, "- name: Build link-mcp\n  run: python -m build"),
    )

    packet = bar.build_packet_for_job(
        client=TruncatedClient(),
        run=sample_run(),
        jobs=sample_jobs(),
        pull=sample_pull(),
        pull_files=[],
        focused_job=sample_jobs()[0],
        capture_sha=CAPTURE_SHA,
    )

    assert packet["sanitization"]["truncated"] is True
    assert packet["evidence"][0]["content"] == (
        "FileNotFoundError: <TEMP>/link_mcp-2.3.0/.linkignore"
    )
    assert packet["evidence"][0]["source"]["original_line_start"] == 50_001
    assert any("retained the bounded final portion" in item for item in packet["missing_evidence"])


def test_retry_sends_identical_packet_and_idempotency_key(monkeypatch):
    packet = {"delivery": {"id": "d" * 64}, "value": "safe"}
    requests = []

    def opener(request, timeout):
        assert timeout == 30
        requests.append(request)
        if len(requests) == 1:
            raise urllib.error.HTTPError(request.full_url, 503, "retry", {}, None)
        return Response(
            202,
            json.dumps(
                {
                    "investigation": {
                        "id": "e" * 64,
                        "url": f"/private/investigations/{'e' * 64}",
                    }
                }
            ).encode(),
        )

    sleeps = []
    result = bar.send_packet(
        packet,
        endpoint=bar.DEFAULT_ENDPOINT,
        client_id="client-id",
        client_secret="client-secret",
        opener=opener,
        sleeper=sleeps.append,
    )

    assert result["investigation"]["id"] == "e" * 64
    assert len(requests) == 2
    assert requests[0].data == requests[1].data == bar.canonical_json_bytes(packet)
    assert requests[0].get_header("Idempotency-key") == "d" * 64
    assert requests[0].get_header("Cf-access-client-id") == "client-id"
    assert requests[0].get_header("Cf-access-client-secret") == "client-secret"
    assert sleeps == [1.0]


def test_default_bar_transport_rejects_redirect_without_following_access_headers(
    monkeypatch,
):
    packet = {"delivery": {"id": "d" * 64}, "value": "safe"}
    seen_requests = []
    seen_handlers = []

    class RedirectOpener:
        def open(self, request, timeout):
            seen_requests.append(request)
            raise urllib.error.HTTPError(
                request.full_url,
                302,
                "Found",
                {"Location": "https://redirect.example.test/steal"},
                None,
            )

    monkeypatch.setattr(
        bar.urllib.request,
        "build_opener",
        lambda *handlers: seen_handlers.extend(handlers) or RedirectOpener(),
    )

    with pytest.raises(bar.IntegrationError, match="HTTP 302"):
        bar.send_packet(
            packet,
            endpoint=bar.DEFAULT_ENDPOINT,
            client_id="client-id",
            client_secret="client-secret",
            opener=None,
            sleeper=lambda _delay: None,
        )

    assert len(seen_requests) == 1
    assert seen_handlers == [bar._NoRedirect]
    assert seen_requests[0].get_header("Cf-access-client-id") == "client-id"
    assert seen_requests[0].get_header("Cf-access-client-secret") == "client-secret"


def test_rate_limit_retry_respects_retry_after_header():
    packet = {"delivery": {"id": "d" * 64}, "value": "safe"}
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "rate limited",
                {"Retry-After": "7"},
                None,
            )
        return Response(202, b"{}")

    sleeps = []
    bar.send_packet(
        packet,
        endpoint=bar.DEFAULT_ENDPOINT,
        client_id="client-id",
        client_secret="client-secret",
        opener=opener,
        sleeper=sleeps.append,
    )

    assert calls == 2
    assert sleeps == [7.0]


def test_retry_after_supports_http_dates_and_rejects_invalid_values():
    assert bar.retry_after_seconds(email.utils.formatdate(1_007, usegmt=True), 1_000) == 7.0
    assert bar.retry_after_seconds("9999", 1_000) == bar.MAX_RETRY_AFTER_SECONDS
    assert bar.retry_after_seconds("invalid", 1_000) is None


def test_request_timeout_response_is_retried():
    packet = {"delivery": {"id": "d" * 64}, "value": "safe"}
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(request.full_url, 408, "timeout", {}, None)
        return Response(202, b"{}")

    sleeps = []
    bar.send_packet(
        packet,
        endpoint=bar.DEFAULT_ENDPOINT,
        client_id="client-id",
        client_secret="client-secret",
        opener=opener,
        sleeper=sleeps.append,
    )

    assert calls == 2
    assert sleeps == [1.0]


@pytest.mark.parametrize("body", [b"", b"not-json", b"\xff"])
def test_empty_or_malformed_bar_response_is_a_clean_integration_error(body):
    packet = {"delivery": {"id": "d" * 64}, "value": "safe"}

    with pytest.raises(bar.IntegrationError, match="invalid JSON"):
        bar.send_packet(
            packet,
            endpoint=bar.DEFAULT_ENDPOINT,
            client_id="client-id",
            client_secret="client-secret",
            opener=lambda *_args, **_kwargs: Response(202, body),
            sleeper=lambda _delay: None,
        )


def test_main_reports_bad_bar_response_without_a_traceback(monkeypatch, capsys):
    monkeypatch.setattr(
        bar, "validate_capture_context", lambda _environment: (123, 1, CAPTURE_SHA)
    )
    monkeypatch.setattr(bar, "GitHubClient", lambda _token: object())
    monkeypatch.setattr(bar, "collect_packets", lambda *_args: [{"packet": "safe"}])
    monkeypatch.setattr(
        bar,
        "send_packet",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            bar.IntegrationError("Bar returned invalid JSON")
        ),
    )

    assert bar.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Bar collection failed: Bar returned invalid JSON\n"
    assert "Traceback" not in captured.err


def test_bar_response_is_restricted_to_the_expected_private_page():
    investigation_id = "e" * 64
    result = {
        "investigation": {
            "id": investigation_id,
            "url": f"/private/investigations/{investigation_id}",
        }
    }

    assert bar.parse_bar_response(result) == (
        investigation_id,
        f"https://bar-private.gowthamsarveswaran.com/private/investigations/{investigation_id}",
    )

    result["investigation"]["url"] = "https://attacker.example/"
    with pytest.raises(bar.IntegrationError):
        bar.parse_bar_response(result)


def test_evidence_builder_rejects_aggregate_line_limit():
    builder = bar.EvidenceBuilder.create()
    for index in range(14):
        builder.add(
            kind="job_log",
            title=f"window {index}",
            content="\n".join(["failure"] * 30),
            job="package",
            step="Build link-mcp",
            path=None,
            sha_role=None,
            line_start=1,
            line_end=30,
        )

    with pytest.raises(bar.IntegrationError, match="400 lines"):
        builder.validate_limits()
