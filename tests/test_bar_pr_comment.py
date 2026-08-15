from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from scripts import bar_investigate as investigate
from scripts import bar_pr_comment as comments
from scripts import bar_summary_poll as poll


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = 318_694_036_59
RUN_ATTEMPT = 2
PR_NUMBER = 60
PACKAGE_ID = "a" * 64
WINDOWS_ID = "b" * 64


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def sleep(self, delay: float) -> None:
        self.value += delay


def summary_response(
    investigation_id: str,
    *,
    status: str = "complete",
    job_name: str = "package",
    diagnosis: dict | None = None,
) -> poll.HttpResponse:
    terminal = status in {"complete", "failed"}
    if diagnosis is None and status == "complete":
        diagnosis = {
            "outcome": "diagnosed",
            "summary": "The source distribution omits .linkignore.",
            "confidence": 0.9,
            "uncertainty": "The exact packaging command was not reproduced.",
            "evidenceIds": ["E-LINK-001", "E-LINK-003"],
        }
    body = {
        "schemaVersion": 1,
        "investigation": {
            "id": investigation_id,
            "repository": poll.REPOSITORY,
            "status": status,
            "terminal": terminal,
            "source": {
                "runId": RUN_ID,
                "runAttempt": RUN_ATTEMPT,
                "headSha": "c" * 40,
                "pullRequestNumber": PR_NUMBER,
            },
            "check": {"jobName": job_name, "failedStep": "Build link-mcp"},
            "diagnosis": diagnosis if status == "complete" else None,
            "error": {"code": "investigation_failed"} if status == "failed" else None,
            "url": f"/private/investigations/{investigation_id}",
        },
    }
    return poll.HttpResponse(
        200 if terminal else 202,
        {"cache-control": "private, no-store", "content-type": "application/json; charset=utf-8"},
        json.dumps(body, separators=(",", ":")).encode(),
    )


def decoded(encoded: str) -> dict:
    padding = "=" * (-len(encoded) % 4)
    return json.loads(base64.urlsafe_b64decode(encoded + padding))


class WireResponse:
    status = 302

    def read(self, _limit: int) -> bytes:
        return b"redirect"

    def getheaders(self) -> list[tuple[str, str]]:
        return [("Location", "https://attacker.example/steal")]


class WireConnection:
    instances: list["WireConnection"] = []

    def __init__(self, host: str, port: int, *, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.method = ""
        self.path = ""
        self.headers: list[tuple[str, str]] = []
        self.closed = False
        self.__class__.instances.append(self)

    def putrequest(self, method: str, path: str) -> None:
        self.method = method
        self.path = path

    def putheader(self, name: str, value: str) -> None:
        self.headers.append((name, value))

    def endheaders(self) -> None:
        return None

    def getresponse(self) -> WireResponse:
        return WireResponse()

    def close(self) -> None:
        self.closed = True


def test_summary_transport_preserves_access_header_names_and_never_follows_redirects():
    WireConnection.instances.clear()

    response = poll.fetch_summary(
        PACKAGE_ID,
        client_id="client-id",
        client_secret="client-secret",
        connection_factory=WireConnection,
    )

    assert response.status == 302
    assert len(WireConnection.instances) == 1
    connection = WireConnection.instances[0]
    assert connection.host == poll.BAR_HOST
    assert connection.method == "GET"
    assert connection.path == f"{poll.SUMMARY_PATH_PREFIX}/{PACKAGE_ID}/summary"
    assert ("CF-Access-Client-Id", "client-id") in connection.headers
    assert ("CF-Access-Client-Secret", "client-secret") in connection.headers
    assert all(host != "attacker.example" for host in [item.host for item in WireConnection.instances])
    assert connection.closed


def test_polling_waits_for_terminal_summaries_and_uses_only_summary_gets():
    clock = FakeClock()
    responses = {
        PACKAGE_ID: [summary_response(PACKAGE_ID, status="diagnosing"), summary_response(PACKAGE_ID)],
        WINDOWS_ID: [summary_response(WINDOWS_ID, status="failed", job_name="windows-smoke")],
    }
    calls: list[str] = []

    def fetch(investigation_id: str) -> poll.HttpResponse:
        calls.append(investigation_id)
        return responses[investigation_id].pop(0)

    payload = poll.poll_summaries(
        [PACKAGE_ID, WINDOWS_ID],
        expected_run_id=RUN_ID,
        expected_run_attempt=RUN_ATTEMPT,
        expected_pull_request_number=PR_NUMBER,
        fetcher=fetch,
        timeout_seconds=10,
        poll_interval_seconds=2,
        clock=clock,
        sleeper=clock.sleep,
    )

    assert [item["id"] for item in payload["summaries"]] == [PACKAGE_ID, WINDOWS_ID]
    assert payload["unavailable"] == []
    assert calls == [PACKAGE_ID, WINDOWS_ID, PACKAGE_ID]
    assert clock.value == 2


def test_poll_timeout_preserves_successful_summaries_and_records_partial_result():
    clock = FakeClock()

    def fetch(investigation_id: str) -> poll.HttpResponse:
        if investigation_id == PACKAGE_ID:
            return summary_response(PACKAGE_ID)
        return summary_response(WINDOWS_ID, status="diagnosing", job_name="windows-smoke")

    payload = poll.poll_summaries(
        [PACKAGE_ID, WINDOWS_ID],
        expected_run_id=RUN_ID,
        expected_run_attempt=RUN_ATTEMPT,
        expected_pull_request_number=PR_NUMBER,
        fetcher=fetch,
        timeout_seconds=5,
        poll_interval_seconds=2,
        clock=clock,
        sleeper=clock.sleep,
    )

    assert [item["id"] for item in payload["summaries"]] == [PACKAGE_ID]
    assert payload["unavailable"] == [{"id": WINDOWS_ID, "jobName": "windows-smoke", "reason": "timeout"}]
    assert clock.value == 5


def test_polling_rejects_more_than_four_investigations_before_fetching():
    calls = []
    with pytest.raises(poll.SummaryIntegrationError, match="at most four"):
        poll.poll_summaries(
            [f"{index:064x}" for index in range(5)],
            expected_run_id=RUN_ID,
            expected_run_attempt=RUN_ATTEMPT,
            expected_pull_request_number=PR_NUMBER,
            fetcher=lambda investigation_id: calls.append(investigation_id),
        )
    assert calls == []


def test_encoded_job_output_is_base64url_and_capped_after_encoding():
    maximal = {
        "schemaVersion": 1,
        "repository": poll.REPOSITORY,
        "runId": RUN_ID,
        "runAttempt": RUN_ATTEMPT,
        "pullRequestNumber": PR_NUMBER,
        "summaries": [],
        "unavailable": [],
    }
    for index in range(4):
        maximal["summaries"].append(
            {
                "id": f"{index + 1:064x}",
                "status": "complete",
                "jobName": "j" * poll.MAX_CHECK_TEXT,
                "failedStep": "s" * poll.MAX_CHECK_TEXT,
                "diagnosis": {
                    "outcome": "diagnosed",
                    "summary": "d" * poll.MAX_DIAGNOSIS_TEXT,
                    "confidence": 1.0,
                    "uncertainty": "u" * poll.MAX_DIAGNOSIS_TEXT,
                    "evidenceIds": [f"E-{letter * 62}" for letter in "ABCDEF"],
                },
            }
        )

    encoded = poll.encode_job_output(maximal)

    assert len(encoded.encode()) <= poll.MAX_ENCODED_OUTPUT_BYTES
    assert set(encoded) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    assert decoded(encoded) == maximal


def test_encoded_job_output_rejects_payloads_over_limit_after_encoding():
    with pytest.raises(poll.SummaryIntegrationError, match="after encoding|encoded"):
        poll.encode_job_output({"value": "x" * poll.MAX_ENCODED_OUTPUT_BYTES})


def test_summary_projection_rejects_any_evidence_body_field():
    response = summary_response(PACKAGE_ID)
    parsed = json.loads(response.body)
    parsed["investigation"]["evidence"] = [{"id": "E-LINK-001", "body": "secret log"}]
    hostile = poll.HttpResponse(response.status, response.headers, json.dumps(parsed).encode())

    with pytest.raises(poll.SummaryIntegrationError, match="shape"):
        poll.project_summary(
            hostile,
            PACKAGE_ID,
            expected_run_id=RUN_ID,
            expected_run_attempt=RUN_ATTEMPT,
            expected_pull_request_number=PR_NUMBER,
        )


def test_comment_rendering_neutralizes_hostile_diagnosis_fields_and_builds_only_fixed_links():
    hostile = summary_response(
        PACKAGE_ID,
        job_name="@release <b>package</b> [job](https://evil.example)",
        diagnosis={
            "outcome": "diagnosed",
            "summary": (
                "@octocat &#64;team <img src=x onerror=alert(1)> "
                "[click](https://evil.example) https://evil.example "
                "javascript:alert(1) www.evil.example"
            ),
            "confidence": 0.5,
            "uncertainty": "safe\u202eexe\u200b\n<script>alert(1)</script>",
            "evidenceIds": ["E-LINK-001"],
        },
    )
    projected = poll.project_summary(
        hostile,
        PACKAGE_ID,
        expected_run_id=RUN_ID,
        expected_run_attempt=RUN_ATTEMPT,
        expected_pull_request_number=PR_NUMBER,
    )
    payload = poll.build_comment_payload(
        [projected],
        [],
        expected_run_id=RUN_ID,
        expected_run_attempt=RUN_ATTEMPT,
        expected_pull_request_number=PR_NUMBER,
    )

    body = comments.render_comment(payload)

    assert body.startswith(comments.COMMENT_MARKER)
    assert "@octocat" not in body
    assert "@release" not in body
    assert "evil.example" not in body
    assert "javascript:" not in body
    assert "&#64;" not in body
    assert "<script" not in body and "<img" not in body and "<b>" not in body
    assert "\u202e" not in body and "\u200b" not in body
    assert "[click]" not in body
    expected_url = f"https://bar-private.gowthamsarveswaran.com/private/investigations/{PACKAGE_ID}"
    assert body.count("https://") == 1
    assert expected_url in body
    assert len(body.encode()) <= comments.MAX_COMMENT_BYTES


class FakeGitHubComments:
    def __init__(self, listings: list[list[dict]], *, create_results=None, update_results=None) -> None:
        self.listings = list(listings)
        self.create_results = list(create_results or [])
        self.update_results = list(update_results or [])
        self.created: list[str] = []
        self.updated: list[tuple[int, str]] = []

    def list_comments(self, _pull_request_number: int) -> list[dict]:
        assert self.listings
        return self.listings.pop(0)

    def create_comment(self, _pull_request_number: int, body: str) -> dict:
        self.created.append(body)
        result = self.create_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def update_comment(self, comment_id: int, body: str) -> dict:
        self.updated.append((comment_id, body))
        result = self.update_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def bot_comment(comment_id: int, body: str) -> dict:
    return {"id": comment_id, "body": body, "user": {"login": "github-actions[bot]", "type": "Bot"}}


def test_first_run_creates_one_marker_comment():
    body = comments.COMMENT_MARKER + "\nbody"
    client = FakeGitHubComments([[]], create_results=[bot_comment(41, body)])

    assert comments.upsert_comment(client, PR_NUMBER, body) == "created"
    assert client.created == [body]
    assert client.updated == []


def test_upsert_fails_closed_if_multiple_marker_comments_exist():
    body = comments.COMMENT_MARKER + "\nbody"
    client = FakeGitHubComments([[bot_comment(1, body), bot_comment(2, body)]])

    with pytest.raises(comments.CommentIntegrationError, match="multiple"):
        comments.upsert_comment(client, PR_NUMBER, body)

    assert client.created == []
    assert client.updated == []


def test_marker_comment_from_a_normal_user_is_ignored_rather_than_blocking():
    """The marker is public text. If a user pasting it counted as a conflict,
    a single comment could permanently wedge Bar's updates."""
    body = comments.COMMENT_MARKER + "\nbody"
    forged = {"id": 1, "body": body, "user": {"login": "attacker", "type": "User"}}
    client = FakeGitHubComments([[forged]], create_results=[bot_comment(41, body)])

    assert comments.upsert_comment(client, PR_NUMBER, body) == "created"
    assert client.created == [body]
    assert client.updated == []


def test_a_user_marker_does_not_mask_bars_own_comment():
    """A forged marker beside the real one must not hide it, or Bar would
    create a duplicate on every run."""
    body = comments.COMMENT_MARKER + "\nbody"
    forged = {"id": 1, "body": body, "user": {"login": "attacker", "type": "User"}}
    updated_body = comments.COMMENT_MARKER + "\nnew body"
    client = FakeGitHubComments(
        [[forged, bot_comment(7, body)]],
        update_results=[bot_comment(7, updated_body)],
    )

    assert comments.upsert_comment(client, PR_NUMBER, updated_body) == "updated"
    assert client.created == []
    assert client.updated == [(7, updated_body)]


def test_repeated_run_updates_the_single_existing_bot_comment():
    old = comments.COMMENT_MARKER + "\nold"
    new = comments.COMMENT_MARKER + "\nnew"
    client = FakeGitHubComments(
        [[bot_comment(42, old)]],
        update_results=[bot_comment(42, new)],
    )

    assert comments.upsert_comment(client, PR_NUMBER, new) == "updated"
    assert client.created == []
    assert client.updated == [(42, new)]


def test_ambiguous_create_relists_before_retry_and_does_not_duplicate():
    body = comments.COMMENT_MARKER + "\nbody"
    client = FakeGitHubComments(
        [[], [bot_comment(77, body)]],
        create_results=[comments.AmbiguousWriteError("connection reset")],
    )

    assert comments.upsert_comment(client, PR_NUMBER, body) == "created"
    assert client.created == [body]
    assert client.updated == []


def test_ambiguous_update_relists_before_retrying_the_same_comment():
    old = comments.COMMENT_MARKER + "\nold"
    new = comments.COMMENT_MARKER + "\nnew"
    client = FakeGitHubComments(
        [[bot_comment(42, old)], [bot_comment(42, old)]],
        update_results=[comments.AmbiguousWriteError("timeout"), bot_comment(42, new)],
    )

    assert comments.upsert_comment(client, PR_NUMBER, new) == "updated"
    assert client.updated == [(42, new), (42, new)]


def test_workflow_separates_read_only_collection_from_pull_request_comment_permissions():
    workflow = (ROOT / ".github/workflows/bar-investigate.yml").read_text()

    investigate = workflow.split("  investigate:", 1)[1].split("  comment:", 1)[0]
    comment = workflow.split("  comment:", 1)[1]
    investigate_permissions = investigate.split("    permissions:\n", 1)[1].split("    outputs:", 1)[0]
    comment_permissions = comment.split("    permissions:\n", 1)[1].split("    steps:", 1)[0]
    assert investigate_permissions == (
        "      actions: read\n"
        "      contents: read\n"
        "      pull-requests: read\n"
    )
    assert comment_permissions == (
        "      contents: read\n"
        "      pull-requests: write\n"
    )
    assert "BAR_ACCESS_CLIENT_ID" not in comment
    assert "BAR_ACCESS_CLIENT_SECRET" not in comment
    assert "ref: ${{ github.workflow_sha }}" in comment
    assert "persist-credentials: false" in comment


def test_github_api_error_reports_only_safe_bounded_message_and_official_documentation_url():
    client = comments.GitHubCommentsClient("token")
    client.request = lambda *_args, **_kwargs: (
        403,
        {
            "message": "Resource not accessible by integration",
            "documentation_url": "https://docs.github.com/rest/issues/comments#create-an-issue-comment",
            "sensitive_detail": "must not be logged",
        },
    )

    with pytest.raises(comments.CommentIntegrationError) as caught:
        client.create_comment(PR_NUMBER, comments.COMMENT_MARKER + "\nbody")

    message = str(caught.value)
    assert message == (
        "GitHub comment create returned HTTP 403: "
        "Resource not accessible by integration "
        "(https://docs.github.com/rest/issues/comments#create-an-issue-comment)"
    )
    assert "sensitive_detail" not in message
    assert "must not be logged" not in message


def test_github_api_error_neutralizes_log_injection_and_rejects_external_documentation_urls():
    client = comments.GitHubCommentsClient("token")
    client.request = lambda *_args, **_kwargs: (
        403,
        {
            "message": "denied\n::warning:: @team\u202e<script>" + "x" * 500,
            "documentation_url": "https://attacker.example/collect?secret=value",
        },
    )

    with pytest.raises(comments.CommentIntegrationError) as caught:
        client.create_comment(PR_NUMBER, comments.COMMENT_MARKER + "\nbody")

    message = str(caught.value)
    assert message.startswith("GitHub comment create returned HTTP 403: denied warning team script")
    assert "\n" not in message
    assert "::" not in message
    assert "@" not in message
    assert "\u202e" not in message
    assert "<" not in message and ">" not in message
    assert "attacker.example" not in message
    assert len(message) <= 260


def test_comment_retry_path_has_no_bar_credentials_or_investigation_calls():
    workflow = (ROOT / ".github/workflows/bar-investigate.yml").read_text()
    comment = workflow.split("  comment:", 1)[1]
    script = (ROOT / "scripts/bar_pr_comment.py").read_text()

    assert "scripts/bar_investigate.py" not in comment
    assert "BAR_ACCESS_CLIENT" not in comment
    assert "bar_summary_poll" not in script
    assert poll.SUMMARY_PATH_PREFIX not in script
    assert "Workers AI" not in script


def test_investigation_job_emits_exactly_one_encoded_comment_output_after_all_packets(monkeypatch, tmp_path):
    packet_ids = [PACKAGE_ID, WINDOWS_ID]
    packets = [
        {"packet": index, "source": {"pull_request": {"number": PR_NUMBER}}}
        for index in range(2)
    ]
    sent: list[dict] = []
    seen_kwargs: list[dict] = []
    output = tmp_path / "github-output"

    monkeypatch.setattr(
        investigate,
        "validate_capture_context",
        lambda *_args, **_kwargs: (RUN_ID, RUN_ATTEMPT, "c" * 40),
    )
    monkeypatch.setattr(investigate, "collect_packets", lambda *_args, **_kwargs: packets)

    def send_packet(packet: dict, **_kwargs) -> dict:
        sent.append(packet)
        return {
            "investigation": {
                "id": packet_ids[len(sent) - 1],
                "url": f"/private/investigations/{packet_ids[len(sent) - 1]}",
            }
        }

    monkeypatch.setattr(investigate, "send_packet", send_packet)
    monkeypatch.setattr(
        investigate.bar_summary_poll,
        "poll_and_encode",
        lambda ids, **kwargs: (seen_kwargs.append(kwargs), "encoded-summary")[1],
    )
    monkeypatch.setattr(
        investigate.os,
        "environ",
        {
            "BAR_ACCESS_CLIENT_ID": "id",
            "BAR_ACCESS_CLIENT_SECRET": "secret",
            "BAR_ENDPOINT": "https://bar-private.gowthamsarveswaran.com/api/v1/github/investigations",
            "BAR_SOURCE_RUN_ATTEMPT": str(RUN_ATTEMPT),
            "BAR_SOURCE_RUN_ID": str(RUN_ID),
            "GITHUB_OUTPUT": str(output),
            "GITHUB_TOKEN": "token",
        },
    )

    assert investigate.main() == 0
    assert sent == packets
    assert output.read_text() == "bar_comment_payload=encoded-summary\n"
    # The destination comes from the collector's GitHub-validated packets.
    assert seen_kwargs[0]["expected_pull_request_number"] == PR_NUMBER


def test_bar_pull_request_number_is_cross_checked_never_used_as_the_destination():
    """Bar's number is only ever compared to the collector's GitHub-validated
    one. A mismatch is rejected outright rather than silently redirecting the
    comment to another issue in the repository."""
    response = summary_response(PACKAGE_ID)
    body = json.loads(response.body)
    body["investigation"]["source"]["pullRequestNumber"] = PR_NUMBER + 1
    hostile = poll.HttpResponse(response.status, response.headers, json.dumps(body).encode())

    with pytest.raises(poll.SummaryIntegrationError, match="pull request does not match"):
        poll.project_summary(
            hostile,
            PACKAGE_ID,
            expected_run_id=RUN_ID,
            expected_run_attempt=RUN_ATTEMPT,
            expected_pull_request_number=PR_NUMBER,
        )


def test_payload_identity_comes_from_the_collector_not_from_bar():
    projected = poll.project_summary(
        summary_response(PACKAGE_ID),
        PACKAGE_ID,
        expected_run_id=RUN_ID,
        expected_run_attempt=RUN_ATTEMPT,
        expected_pull_request_number=PR_NUMBER,
    )
    payload = poll.build_comment_payload(
        [projected],
        [],
        expected_run_id=RUN_ID,
        expected_run_attempt=RUN_ATTEMPT,
        expected_pull_request_number=PR_NUMBER,
    )

    assert payload["pullRequestNumber"] == PR_NUMBER
    assert payload["runId"] == RUN_ID
    assert payload["runAttempt"] == RUN_ATTEMPT


def test_total_poll_timeout_still_produces_an_updatable_comment_payload():
    """Successful ingestion must not read as a failed job. With nothing
    terminal, the payload still reports the run and can be updated later."""
    clock = FakeClock()
    payload = poll.poll_summaries(
        [PACKAGE_ID, WINDOWS_ID],
        expected_run_id=RUN_ID,
        expected_run_attempt=RUN_ATTEMPT,
        expected_pull_request_number=PR_NUMBER,
        fetcher=lambda investigation_id: summary_response(investigation_id, status="diagnosing"),
        timeout_seconds=10.0,
        poll_interval_seconds=3.0,
        clock=clock,
        sleeper=clock.sleep,
    )

    assert payload["summaries"] == []
    assert {item["reason"] for item in payload["unavailable"]} == {"timeout"}
    assert payload["pullRequestNumber"] == PR_NUMBER
    encoded = poll.encode_job_output(payload)
    assert len(encoded.encode()) <= poll.MAX_ENCODED_OUTPUT_BYTES

    body = comments.render_comment(comments.decode_comment_payload(encoded))
    assert "Diagnosis is still unavailable" in body
    assert "Evidence was delivered to Bar" in body
    assert body.startswith(comments.COMMENT_MARKER)
    assert len(body.encode()) <= comments.MAX_COMMENT_BYTES


def test_poller_treats_a_tls_certificate_failure_as_permanent():
    """Retrying until the deadline would report an intercepted connection as
    an ordinary timeout."""
    import ssl

    calls: list[str] = []

    def fetcher(investigation_id: str):
        calls.append(investigation_id)
        raise ssl.SSLCertVerificationError(1, "certificate verify failed")

    clock = FakeClock()
    payload = poll.poll_summaries(
        [PACKAGE_ID],
        expected_run_id=RUN_ID,
        expected_run_attempt=RUN_ATTEMPT,
        expected_pull_request_number=PR_NUMBER,
        fetcher=fetcher,
        timeout_seconds=30.0,
        poll_interval_seconds=3.0,
        clock=clock,
        sleeper=clock.sleep,
    )

    assert len(calls) == 1
    assert payload["unavailable"] == [{"id": PACKAGE_ID, "reason": "tls_error"}]
    comments.decode_comment_payload(poll.encode_job_output(payload))


def test_transient_socket_errors_are_still_retried_by_the_poller():
    """The TLS clause must not swallow genuinely transient failures."""
    calls: list[str] = []

    def fetcher(investigation_id: str):
        calls.append(investigation_id)
        raise ConnectionResetError("connection reset by peer")

    clock = FakeClock()
    poll.poll_summaries(
        [PACKAGE_ID],
        expected_run_id=RUN_ID,
        expected_run_attempt=RUN_ATTEMPT,
        expected_pull_request_number=PR_NUMBER,
        fetcher=fetcher,
        timeout_seconds=10.0,
        poll_interval_seconds=3.0,
        clock=clock,
        sleeper=clock.sleep,
    )

    assert len(calls) > 1


def test_newlines_become_spaces_without_weakening_zero_width_stripping():
    """Wrapped prose must not glue words together, but zero-width and bidi
    obfuscation must still collapse so the URL rules can see through it."""
    assert comments.neutralize("line1\nline2", comments.MAX_DIAGNOSIS_TEXT) == "line1 line2"
    assert comments.neutralize("a\r\nb c d", comments.MAX_DIAGNOSIS_TEXT) == "a b c d"

    obfuscated = comments.neutralize("ev​il.te​st", comments.MAX_DIAGNOSIS_TEXT)
    assert "URL removed" in obfuscated
    assert "evil.test" not in obfuscated

    bidi = comments.neutralize("safe‮txt.exe‬ tail", comments.MAX_DIAGNOSIS_TEXT)
    assert "‮" not in bidi and "‬" not in bidi
