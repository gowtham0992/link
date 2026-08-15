#!/usr/bin/env python3
"""Poll Bar's bounded machine summaries and emit a safe job output."""

from __future__ import annotations

import base64
import http.client
import json
import math
import re
import ssl
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


REPOSITORY = "gowtham0992/link"
BAR_HOST = "bar-private.gowthamsarveswaran.com"
SUMMARY_PATH_PREFIX = "/api/v1/github/investigations"
MAX_INVESTIGATIONS = 4
MAX_SUMMARY_RESPONSE_BYTES = 8 * 1024
MAX_ENCODED_OUTPUT_BYTES = 8 * 1024
MAX_CHECK_TEXT = 80
MAX_DIAGNOSIS_TEXT = 200
DEFAULT_POLL_TIMEOUT_SECONDS = 120.0
DEFAULT_POLL_INTERVAL_SECONDS = 3.0

INVESTIGATION_ID_RE = re.compile(r"^[a-f0-9]{64}$")
SHA_RE = re.compile(r"^[a-f0-9]{40}$")
EVIDENCE_ID_RE = re.compile(r"^E-[A-Z0-9][A-Z0-9-]{0,62}$")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class SummaryIntegrationError(RuntimeError):
    """A safe-to-display summary integration failure."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SummaryIntegrationError(message)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def bounded_text(value: Any, field: str, maximum: int) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{field} is invalid")
    require(not CONTROL_RE.search(value), f"{field} contains control characters")
    return value.strip()[:maximum]


def fetch_summary(
    investigation_id: str,
    *,
    client_id: str,
    client_secret: str,
    timeout: float = 20.0,
    connection_factory: Callable[..., Any] = http.client.HTTPSConnection,
) -> HttpResponse:
    require(bool(INVESTIGATION_ID_RE.fullmatch(investigation_id)), "invalid investigation ID")
    require(bool(client_id) and bool(client_secret), "Bar service credentials are not configured")
    path = f"{SUMMARY_PATH_PREFIX}/{investigation_id}/summary"
    connection = connection_factory(BAR_HOST, 443, timeout=timeout)
    try:
        connection.putrequest("GET", path)
        connection.putheader("Accept", "application/json")
        connection.putheader("User-Agent", "link-bar-summary-poller/v1")
        connection.putheader("CF-Access-Client-Id", client_id)
        connection.putheader("CF-Access-Client-Secret", client_secret)
        connection.endheaders()
        response = connection.getresponse()
        body = response.read(MAX_SUMMARY_RESPONSE_BYTES + 1)
        headers = {name.lower(): value for name, value in response.getheaders()}
        return HttpResponse(response.status, headers, body)
    finally:
        connection.close()


def project_summary(
    response: HttpResponse,
    investigation_id: str,
    *,
    expected_run_id: int,
    expected_run_attempt: int,
    expected_pull_request_number: int,
) -> dict[str, Any]:
    require(response.status in (200, 202), f"summary returned HTTP {response.status}")
    require(len(response.body) <= MAX_SUMMARY_RESPONSE_BYTES, "summary response exceeded 8 KiB")
    require(response.headers.get("cache-control") == "private, no-store", "summary cache policy is invalid")
    require(
        response.headers.get("content-type", "").lower().startswith("application/json"),
        "summary content type is invalid",
    )
    try:
        body = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SummaryIntegrationError("summary returned invalid JSON") from error
    require(isinstance(body, dict) and set(body) == {"schemaVersion", "investigation"}, "summary shape is invalid")
    require(body.get("schemaVersion") == 1, "summary schema version is invalid")
    investigation = body.get("investigation")
    expected_fields = {"id", "repository", "status", "terminal", "source", "check", "diagnosis", "error", "url"}
    require(
        isinstance(investigation, dict) and set(investigation) == expected_fields,
        "investigation summary shape is invalid",
    )
    require(investigation.get("id") == investigation_id, "summary investigation ID does not match")
    require(investigation.get("repository") == REPOSITORY, "summary repository does not match")
    require(
        investigation.get("url") == f"/private/investigations/{investigation_id}",
        "summary investigation URL is invalid",
    )
    source = investigation.get("source")
    require(
        isinstance(source, dict) and set(source) == {"runId", "runAttempt", "headSha", "pullRequestNumber"},
        "summary source shape is invalid",
    )
    require(source.get("runId") == expected_run_id, "summary run ID does not match")
    require(source.get("runAttempt") == expected_run_attempt, "summary run attempt does not match")
    require(
        isinstance(source.get("headSha"), str) and bool(SHA_RE.fullmatch(source["headSha"])), "summary SHA is invalid"
    )
    pull_request_number = source.get("pullRequestNumber")
    require(
        isinstance(pull_request_number, int) and not isinstance(pull_request_number, bool) and pull_request_number > 0,
        "summary does not identify a pull request",
    )
    # Bar's pull request number is cross-checked, never trusted as the
    # destination. The authority is the number the collector read from the
    # GitHub-validated run, which is what the payload actually carries.
    require(
        pull_request_number == expected_pull_request_number,
        "summary pull request does not match the collector's validated pull request",
    )
    check = investigation.get("check")
    require(isinstance(check, dict) and set(check) == {"jobName", "failedStep"}, "summary check shape is invalid")
    job_name = bounded_text(check.get("jobName"), "summary job name", MAX_CHECK_TEXT)
    failed_step = bounded_text(check.get("failedStep"), "summary failed step", MAX_CHECK_TEXT)
    terminal = investigation.get("terminal")
    require(isinstance(terminal, bool), "summary terminal state is invalid")
    status = investigation.get("status")
    require(status in {"queued", "collecting", "diagnosing", "complete", "failed"}, "summary status is invalid")
    require((response.status == 200) == terminal, "summary HTTP status and terminal state disagree")

    diagnosis = investigation.get("diagnosis")
    error = investigation.get("error")
    projected_diagnosis = None
    if terminal and status == "complete":
        require(isinstance(diagnosis, dict), "completed summary omitted diagnosis")
        require(
            set(diagnosis) == {"outcome", "summary", "confidence", "uncertainty", "evidenceIds"},
            "diagnosis summary shape is invalid",
        )
        outcome = diagnosis.get("outcome")
        require(outcome in {"diagnosed", "insufficient_evidence"}, "diagnosis outcome is invalid")
        confidence = diagnosis.get("confidence")
        require(
            isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and math.isfinite(confidence)
            and 0 <= confidence <= 1,
            "diagnosis confidence is invalid",
        )
        evidence_ids = diagnosis.get("evidenceIds")
        require(
            isinstance(evidence_ids, list)
            and 1 <= len(evidence_ids) <= 8
            and len(set(evidence_ids)) == len(evidence_ids)
            and all(isinstance(item, str) and bool(EVIDENCE_ID_RE.fullmatch(item)) for item in evidence_ids),
            "diagnosis evidence IDs are invalid",
        )
        projected_diagnosis = {
            "outcome": outcome,
            "summary": bounded_text(diagnosis.get("summary"), "diagnosis summary", MAX_DIAGNOSIS_TEXT),
            "confidence": float(confidence),
            "uncertainty": bounded_text(diagnosis.get("uncertainty"), "diagnosis uncertainty", MAX_DIAGNOSIS_TEXT),
            "evidenceIds": evidence_ids,
        }
        require(error is None, "completed summary included an error")
    elif terminal and status == "failed":
        require(diagnosis is None, "failed summary included a diagnosis")
        require(error == {"code": "investigation_failed"}, "failed summary error is invalid")
    else:
        require(
            not terminal and status in {"queued", "collecting", "diagnosing"}, "nonterminal summary state is invalid"
        )
        require(diagnosis is None and error is None, "nonterminal summary exposed terminal data")

    return {
        "id": investigation_id,
        "status": status,
        "terminal": terminal,
        "runId": expected_run_id,
        "runAttempt": expected_run_attempt,
        "pullRequestNumber": pull_request_number,
        "jobName": job_name,
        "failedStep": failed_step,
        "diagnosis": projected_diagnosis,
    }


def build_comment_payload(
    projected: list[dict[str, Any]],
    unavailable: list[dict[str, Any]],
    *,
    expected_run_id: int,
    expected_run_attempt: int,
    expected_pull_request_number: int,
) -> dict[str, Any]:
    """Assemble the comment payload from collector-owned identity.

    Run, attempt, and pull request come from the GitHub-validated collector,
    never from Bar's response, so the comment destination cannot move even if
    Bar returns something unexpected. Every summary has already been
    cross-checked against these values by `project_summary`.

    A payload with no terminal summaries is still a valid payload: it reports
    that diagnosis is not available yet. Turning that into a failed job would
    mean successful evidence ingestion looked like a collection failure, and
    the comment can be updated by a later rerun.
    """
    terminal = [item for item in projected if item.get("terminal") is True]
    require(bool(terminal) or bool(unavailable), "no Bar summaries to report")
    summaries = [
        {
            "id": item["id"],
            "status": item["status"],
            "jobName": item["jobName"],
            "failedStep": item["failedStep"],
            "diagnosis": item["diagnosis"],
        }
        for item in terminal
    ]
    return {
        "schemaVersion": 1,
        "repository": REPOSITORY,
        "runId": expected_run_id,
        "runAttempt": expected_run_attempt,
        "pullRequestNumber": expected_pull_request_number,
        "summaries": summaries,
        "unavailable": unavailable,
    }


def poll_summaries(
    investigation_ids: list[str],
    *,
    expected_run_id: int,
    expected_run_attempt: int,
    expected_pull_request_number: int,
    fetcher: Callable[[str], HttpResponse],
    timeout_seconds: float = DEFAULT_POLL_TIMEOUT_SECONDS,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    require(1 <= len(investigation_ids) <= MAX_INVESTIGATIONS, "must poll at most four investigations")
    require(len(set(investigation_ids)) == len(investigation_ids), "investigation IDs must be unique")
    require(all(bool(INVESTIGATION_ID_RE.fullmatch(item)) for item in investigation_ids), "invalid investigation ID")
    require(timeout_seconds > 0 and poll_interval_seconds > 0, "poll timing is invalid")
    deadline = clock() + timeout_seconds
    pending = list(investigation_ids)
    latest: dict[str, dict[str, Any]] = {}
    terminal: dict[str, dict[str, Any]] = {}
    unavailable: dict[str, dict[str, Any]] = {}

    while pending and clock() < deadline:
        next_pending: list[str] = []
        for investigation_id in pending:
            try:
                response = fetcher(investigation_id)
                if response.status not in (200, 202):
                    if response.status in {408, 429, 500, 502, 503, 504}:
                        next_pending.append(investigation_id)
                    else:
                        unavailable[investigation_id] = {
                            "id": investigation_id,
                            "reason": f"http_{response.status}",
                        }
                    continue
                item = project_summary(
                    response,
                    investigation_id,
                    expected_run_id=expected_run_id,
                    expected_run_attempt=expected_run_attempt,
                    expected_pull_request_number=expected_pull_request_number,
                )
                latest[investigation_id] = item
                if item["terminal"]:
                    terminal[investigation_id] = item
                else:
                    next_pending.append(investigation_id)
            except ssl.SSLCertVerificationError:
                # A certificate that does not verify is a permanent trust
                # failure. Retrying until the deadline would report an
                # intercepted connection as an ordinary timeout. Must precede
                # the clause below: it is an OSError.
                unavailable[investigation_id] = {"id": investigation_id, "reason": "tls_error"}
            except (SummaryIntegrationError, UnicodeError, ValueError):
                unavailable[investigation_id] = {"id": investigation_id, "reason": "invalid_response"}
            except (http.client.HTTPException, OSError, TimeoutError):
                next_pending.append(investigation_id)
        pending = next_pending
        if pending:
            remaining = deadline - clock()
            if remaining > 0:
                sleeper(min(poll_interval_seconds, remaining))

    for investigation_id in pending:
        item = {"id": investigation_id, "reason": "timeout"}
        if investigation_id in latest:
            item["jobName"] = latest[investigation_id]["jobName"]
        unavailable[investigation_id] = item

    ordered_terminal = [terminal[item] for item in investigation_ids if item in terminal]
    ordered_unavailable = [unavailable[item] for item in investigation_ids if item in unavailable]
    return build_comment_payload(
        ordered_terminal,
        ordered_unavailable,
        expected_run_id=expected_run_id,
        expected_run_attempt=expected_run_attempt,
        expected_pull_request_number=expected_pull_request_number,
    )


def encode_job_output(payload: dict[str, Any]) -> str:
    encoded = base64.urlsafe_b64encode(canonical_json_bytes(payload)).rstrip(b"=")
    require(len(encoded) <= MAX_ENCODED_OUTPUT_BYTES, "encoded Bar comment output exceeds 8 KiB")
    return encoded.decode("ascii")


def poll_and_encode(
    investigation_ids: list[str],
    *,
    expected_run_id: int,
    expected_run_attempt: int,
    expected_pull_request_number: int,
    client_id: str,
    client_secret: str,
) -> str:
    payload = poll_summaries(
        investigation_ids,
        expected_run_id=expected_run_id,
        expected_run_attempt=expected_run_attempt,
        expected_pull_request_number=expected_pull_request_number,
        fetcher=lambda investigation_id: fetch_summary(
            investigation_id,
            client_id=client_id,
            client_secret=client_secret,
        ),
    )
    return encode_job_output(payload)


def write_github_output(path: str, name: str, encoded: str) -> None:
    require(bool(path), "GITHUB_OUTPUT is not configured")
    require(name == "bar_comment_payload", "unexpected output name")
    require(bool(encoded) and "\n" not in encoded and "\r" not in encoded, "job output is invalid")
    with Path(path).open("a", encoding="utf-8", newline="\n") as output:
        output.write(f"{name}={encoded}\n")
