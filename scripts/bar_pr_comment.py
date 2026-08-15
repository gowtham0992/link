#!/usr/bin/env python3
"""Create or update one bounded Bar result comment on a Link pull request."""

from __future__ import annotations

import base64
import http.client
import json
import math
import os
import re
import ssl
import sys
import unicodedata
from typing import Any, Mapping, Protocol


REPOSITORY = "gowtham0992/link"
GITHUB_API_HOST = "api.github.com"
GITHUB_API_VERSION = "2026-03-10"
COMMENT_MARKER = "<!-- bar-ci-investigation-summary:v1 -->"
BAR_INVESTIGATION_ORIGIN = "https://bar-private.gowthamsarveswaran.com"
MAX_ENCODED_OUTPUT_BYTES = 8 * 1024
MAX_COMMENT_BYTES = 12 * 1024
MAX_GITHUB_RESPONSE_BYTES = 1024 * 1024
MAX_CHECK_TEXT = 80
MAX_DIAGNOSIS_TEXT = 200
MAX_COMMENT_PAGES = 10

INVESTIGATION_ID_RE = re.compile(r"^[a-f0-9]{64}$")
EVIDENCE_ID_RE = re.compile(r"^E-[A-Z0-9][A-Z0-9-]{0,62}$")
BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")
URL_RE = re.compile(r"(?i)(?:https?://|ftp://|mailto:|javascript:|data:|file://|www\.)[^\s<>]+")
BARE_DOMAIN_RE = re.compile(
    r"(?i)\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})(?:/[^\s<>]*)?"
)
MARKDOWN_ESCAPE_RE = re.compile(r"([\\`*_{}\[\]()#+\-.!|>])")
LINE_BREAK_RE = re.compile("[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]")


class CommentIntegrationError(RuntimeError):
    """A safe-to-display comment integration failure."""


class AmbiguousWriteError(CommentIntegrationError):
    """A write may have succeeded even though its response was lost."""


class CommentsClient(Protocol):
    def list_comments(self, pull_request_number: int) -> list[dict[str, Any]]: ...

    def create_comment(self, pull_request_number: int, body: str) -> dict[str, Any]: ...

    def update_comment(self, comment_id: int, body: str) -> dict[str, Any]: ...


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CommentIntegrationError(message)


def positive_integer(value: Any, field: str) -> int:
    require(isinstance(value, int) and not isinstance(value, bool) and value > 0, f"{field} is invalid")
    return value


def bounded_string(value: Any, field: str, maximum: int) -> str:
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= maximum, f"{field} is invalid")
    return value.strip()


def validate_diagnosis(value: Any) -> dict[str, Any]:
    require(isinstance(value, dict), "diagnosis is invalid")
    require(
        set(value) == {"outcome", "summary", "confidence", "uncertainty", "evidenceIds"},
        "diagnosis shape is invalid",
    )
    require(value.get("outcome") in {"diagnosed", "insufficient_evidence"}, "diagnosis outcome is invalid")
    confidence = value.get("confidence")
    require(
        isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and math.isfinite(confidence)
        and 0 <= confidence <= 1,
        "diagnosis confidence is invalid",
    )
    evidence_ids = value.get("evidenceIds")
    require(
        isinstance(evidence_ids, list)
        and 1 <= len(evidence_ids) <= 8
        and len(set(evidence_ids)) == len(evidence_ids)
        and all(isinstance(item, str) and bool(EVIDENCE_ID_RE.fullmatch(item)) for item in evidence_ids),
        "diagnosis evidence IDs are invalid",
    )
    return {
        "outcome": value["outcome"],
        "summary": bounded_string(value.get("summary"), "diagnosis summary", MAX_DIAGNOSIS_TEXT),
        "confidence": float(confidence),
        "uncertainty": bounded_string(value.get("uncertainty"), "diagnosis uncertainty", MAX_DIAGNOSIS_TEXT),
        "evidenceIds": evidence_ids,
    }


def decode_comment_payload(encoded: str) -> dict[str, Any]:
    require(
        isinstance(encoded, str)
        and 0 < len(encoded.encode()) <= MAX_ENCODED_OUTPUT_BYTES
        and bool(BASE64URL_RE.fullmatch(encoded)),
        "Bar comment output is invalid",
    )
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CommentIntegrationError("Bar comment output is invalid") from error
    expected = {
        "schemaVersion",
        "repository",
        "runId",
        "runAttempt",
        "pullRequestNumber",
        "summaries",
        "unavailable",
    }
    require(isinstance(payload, dict) and set(payload) == expected, "Bar comment payload shape is invalid")
    require(payload.get("schemaVersion") == 1, "Bar comment schema version is invalid")
    require(payload.get("repository") == REPOSITORY, "Bar comment repository is invalid")
    run_id = positive_integer(payload.get("runId"), "run ID")
    run_attempt = positive_integer(payload.get("runAttempt"), "run attempt")
    pull_request_number = positive_integer(payload.get("pullRequestNumber"), "pull request number")
    summaries = payload.get("summaries")
    unavailable = payload.get("unavailable")
    require(isinstance(summaries, list) and len(summaries) <= 4, "Bar comment summaries are invalid")
    require(isinstance(unavailable, list) and len(unavailable) <= 4, "Bar unavailable summaries are invalid")
    # A payload with no terminal summaries is legitimate: it reports that
    # diagnosis has not landed yet, and a later rerun updates the comment.
    require(bool(summaries) or bool(unavailable), "Bar comment payload reports nothing")

    validated_summaries = []
    ids: set[str] = set()
    for item in summaries:
        require(
            isinstance(item, dict) and set(item) == {"id", "status", "jobName", "failedStep", "diagnosis"},
            "Bar comment summary shape is invalid",
        )
        investigation_id = item.get("id")
        require(
            isinstance(investigation_id, str)
            and bool(INVESTIGATION_ID_RE.fullmatch(investigation_id))
            and investigation_id not in ids,
            "Bar comment investigation ID is invalid",
        )
        ids.add(investigation_id)
        status = item.get("status")
        require(status in {"complete", "failed"}, "Bar comment status is invalid")
        diagnosis = validate_diagnosis(item.get("diagnosis")) if status == "complete" else None
        require(status == "complete" or item.get("diagnosis") is None, "failed investigation included a diagnosis")
        validated_summaries.append(
            {
                "id": investigation_id,
                "status": status,
                "jobName": bounded_string(item.get("jobName"), "job name", MAX_CHECK_TEXT),
                "failedStep": bounded_string(item.get("failedStep"), "failed step", MAX_CHECK_TEXT),
                "diagnosis": diagnosis,
            }
        )

    validated_unavailable = []
    for item in unavailable:
        require(isinstance(item, dict), "unavailable summary is invalid")
        require(set(item) in ({"id", "reason"}, {"id", "jobName", "reason"}), "unavailable shape is invalid")
        investigation_id = item.get("id")
        require(
            isinstance(investigation_id, str)
            and bool(INVESTIGATION_ID_RE.fullmatch(investigation_id))
            and investigation_id not in ids,
            "unavailable investigation ID is invalid",
        )
        ids.add(investigation_id)
        reason = item.get("reason")
        require(
            reason in {"timeout", "invalid_response", "tls_error"}
            or (isinstance(reason, str) and bool(re.fullmatch(r"http_[1-5][0-9]{2}", reason))),
            "unavailable reason is invalid",
        )
        projected = {"id": investigation_id, "reason": reason}
        if "jobName" in item:
            projected["jobName"] = bounded_string(item["jobName"], "unavailable job name", MAX_CHECK_TEXT)
        validated_unavailable.append(projected)
    require(len(ids) <= 4, "Bar comment payload exceeds four investigations")
    return {
        "schemaVersion": 1,
        "repository": REPOSITORY,
        "runId": run_id,
        "runAttempt": run_attempt,
        "pullRequestNumber": pull_request_number,
        "summaries": validated_summaries,
        "unavailable": validated_unavailable,
    }


def neutralize(value: str, maximum: int) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    # Line breaks become spaces so wrapped prose does not glue words together
    # ("line1\nline2" must not read as "line1line2"). Every other control and
    # format character is deleted rather than spaced: zero-width and bidi
    # characters are obfuscation, and collapsing them to spaces would let
    # "ev<ZWSP>il.te<ZWSP>st" survive as separate harmless-looking words
    # instead of resolving to a domain the URL rules then strip.
    normalized = LINE_BREAK_RE.sub(" ", normalized)
    visible = "".join(
        character for character in normalized if unicodedata.category(character) not in {"Cc", "Cf", "Cs"}
    )
    visible = URL_RE.sub(" URL removed ", visible)
    visible = BARE_DOMAIN_RE.sub(" URL removed ", visible)
    visible = visible.replace("@", "＠").replace("<", "‹").replace(">", "›").replace("&", "＆")
    visible = " ".join(visible.split())[:maximum].rstrip()
    escaped = MARKDOWN_ESCAPE_RE.sub(r"\\\1", visible)
    return escaped or "Unavailable"


def investigation_url(investigation_id: str) -> str:
    require(bool(INVESTIGATION_ID_RE.fullmatch(investigation_id)), "invalid investigation ID")
    return f"{BAR_INVESTIGATION_ORIGIN}/private/investigations/{investigation_id}"


def render_comment(payload: dict[str, Any]) -> str:
    lines = [
        COMMENT_MARKER,
        "## Bar CI investigation",
        "",
        f"Run `{payload['runId']}` · attempt `{payload['runAttempt']}`",
    ]
    for item in payload["summaries"]:
        job = neutralize(item["jobName"], MAX_CHECK_TEXT)
        step = neutralize(item["failedStep"], MAX_CHECK_TEXT)
        lines.extend(["", f"### {job}", "", f"Failed step: {step}"])
        if item["status"] == "failed":
            lines.append("Diagnosis: Bar ended without a diagnosis.")
        else:
            diagnosis = item["diagnosis"]
            confidence = round(diagnosis["confidence"] * 100)
            evidence = ", ".join(f"`{evidence_id}`" for evidence_id in diagnosis["evidenceIds"])
            lines.extend(
                [
                    f"Diagnosis: {neutralize(diagnosis['summary'], MAX_DIAGNOSIS_TEXT)}",
                    f"Confidence: {confidence}%",
                    f"Remaining uncertainty: {neutralize(diagnosis['uncertainty'], MAX_DIAGNOSIS_TEXT)}",
                    f"Evidence: {evidence}",
                ]
            )
        lines.append(f"[Open protected investigation]({investigation_url(item['id'])})")
    count = len(payload["unavailable"])
    noun = "investigation" if count == 1 else "investigations"
    if count and payload["summaries"]:
        lines.extend(["", f"_{count} additional {noun} did not return a usable terminal summary._"])
    elif count:
        # Nothing reached a terminal state in time. Evidence ingestion still
        # succeeded, so say so plainly rather than implying a failure, and
        # note that a rerun updates this same comment in place.
        lines.extend(
            [
                "",
                f"Diagnosis is still unavailable: {count} {noun} did not reach a "
                "terminal state before the polling timeout.",
                "",
                "_Evidence was delivered to Bar. Re-running this workflow updates "
                "this comment once a diagnosis is available._",
            ]
        )
    body = "\n".join(lines) + "\n"
    require(len(body.encode()) <= MAX_COMMENT_BYTES, "Bar comment exceeds the final size limit")
    return body


class GitHubCommentsClient:
    def __init__(
        self,
        token: str,
        *,
        connection_factory: Any = http.client.HTTPSConnection,
    ) -> None:
        require(bool(token), "GITHUB_TOKEN is not configured")
        self.token = token
        self.connection_factory = connection_factory

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
        require(method in {"GET", "POST", "PATCH"}, "unsupported GitHub method")
        require(path.startswith(f"/repos/{REPOSITORY}/"), "GitHub path is not allowlisted")
        encoded = None if body is None else json.dumps(body, separators=(",", ":")).encode()
        connection = self.connection_factory(GITHUB_API_HOST, 443, timeout=20.0)
        try:
            connection.putrequest(method, path)
            connection.putheader("Accept", "application/vnd.github+json")
            connection.putheader("Authorization", f"Bearer {self.token}")
            connection.putheader("User-Agent", "link-bar-pr-comment/v1")
            connection.putheader("X-GitHub-Api-Version", GITHUB_API_VERSION)
            if encoded is not None:
                connection.putheader("Content-Type", "application/json")
                connection.putheader("Content-Length", str(len(encoded)))
            connection.endheaders(encoded)
            response = connection.getresponse()
            response_body = response.read(MAX_GITHUB_RESPONSE_BYTES + 1)
            require(len(response_body) <= MAX_GITHUB_RESPONSE_BYTES, "GitHub response exceeded the limit")
            try:
                result = json.loads(response_body) if response_body else None
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise CommentIntegrationError("GitHub returned invalid JSON") from error
            return response.status, result
        except ssl.SSLCertVerificationError as error:
            raise CommentIntegrationError("GitHub TLS certificate verification failed") from error
        except (http.client.HTTPException, OSError, TimeoutError) as error:
            if method in {"POST", "PATCH"}:
                raise AmbiguousWriteError("GitHub comment write response was ambiguous") from error
            raise CommentIntegrationError("GitHub comment lookup failed") from error
        finally:
            connection.close()

    def list_comments(self, pull_request_number: int) -> list[dict[str, Any]]:
        positive_integer(pull_request_number, "pull request number")
        comments: list[dict[str, Any]] = []
        for page in range(1, MAX_COMMENT_PAGES + 1):
            path = f"/repos/{REPOSITORY}/issues/{pull_request_number}/comments?per_page=100&page={page}"
            status, result = self.request("GET", path)
            require(status == 200 and isinstance(result, list), f"GitHub comment lookup returned HTTP {status}")
            require(all(isinstance(item, dict) for item in result), "GitHub comment lookup shape is invalid")
            comments.extend(result)
            if len(result) < 100:
                return comments
        raise CommentIntegrationError("GitHub comment lookup exceeded the page limit")

    def create_comment(self, pull_request_number: int, body: str) -> dict[str, Any]:
        path = f"/repos/{REPOSITORY}/issues/{positive_integer(pull_request_number, 'pull request number')}/comments"
        status, result = self.request("POST", path, {"body": body})
        if status in {408, 429, 500, 502, 503, 504}:
            raise AmbiguousWriteError(f"GitHub comment create returned HTTP {status}")
        require(status == 201 and isinstance(result, dict), f"GitHub comment create returned HTTP {status}")
        return result

    def update_comment(self, comment_id: int, body: str) -> dict[str, Any]:
        path = f"/repos/{REPOSITORY}/issues/comments/{positive_integer(comment_id, 'comment ID')}"
        status, result = self.request("PATCH", path, {"body": body})
        if status in {408, 429, 500, 502, 503, 504}:
            raise AmbiguousWriteError(f"GitHub comment update returned HTTP {status}")
        require(status == 200 and isinstance(result, dict), f"GitHub comment update returned HTTP {status}")
        return result


def is_bot_author(record: dict[str, Any]) -> bool:
    user = record.get("user")
    return isinstance(user, dict) and user.get("login") == "github-actions[bot]" and user.get("type") == "Bot"


def marker_comments(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bar's own marker comments, ignoring everyone else's.

    The marker is public text, so any user who can comment on the pull
    request can paste it. Counting those would let one comment permanently
    wedge Bar's updates, so a marker only registers when
    github-actions[bot] wrote it. Two bot-authored markers is a genuine
    ambiguity and still fails closed.
    """
    return [
        record
        for record in records
        if isinstance(record.get("body"), str)
        and COMMENT_MARKER in record["body"]
        and is_bot_author(record)
    ]


def validate_bot_comment(record: dict[str, Any], *, expected_body: str | None = None) -> int:
    require(isinstance(record.get("id"), int) and record["id"] > 0, "GitHub comment ID is invalid")
    require(is_bot_author(record), "existing Bar comment was not authored by github-actions[bot]")
    require(isinstance(record.get("body"), str) and COMMENT_MARKER in record["body"], "Bar comment marker is missing")
    if expected_body is not None:
        require(record["body"] == expected_body, "GitHub returned a different Bar comment body")
    return record["id"]


def find_existing(client: CommentsClient, pull_request_number: int) -> dict[str, Any] | None:
    matches = marker_comments(client.list_comments(pull_request_number))
    require(len(matches) <= 1, "multiple Bar marker comments exist; refusing to choose one")
    if not matches:
        return None
    validate_bot_comment(matches[0])
    return matches[0]


def upsert_comment(client: CommentsClient, pull_request_number: int, body: str) -> str:
    require(body.startswith(COMMENT_MARKER + "\n"), "Bar comment marker is invalid")
    require(len(body.encode()) <= MAX_COMMENT_BYTES, "Bar comment exceeds the final size limit")
    existing = find_existing(client, pull_request_number)
    if existing is None:
        try:
            validate_bot_comment(client.create_comment(pull_request_number, body), expected_body=body)
            return "created"
        except AmbiguousWriteError:
            after = find_existing(client, pull_request_number)
            if after is not None:
                validate_bot_comment(after, expected_body=body)
                return "created"
            validate_bot_comment(client.create_comment(pull_request_number, body), expected_body=body)
            return "created"

    comment_id = validate_bot_comment(existing)
    if existing["body"] == body:
        return "unchanged"
    try:
        validate_bot_comment(client.update_comment(comment_id, body), expected_body=body)
        return "updated"
    except AmbiguousWriteError:
        after = find_existing(client, pull_request_number)
        require(after is not None, "Bar comment disappeared after an ambiguous update")
        after_id = validate_bot_comment(after)
        require(after_id == comment_id, "Bar comment identity changed after an ambiguous update")
        if after["body"] == body:
            return "updated"
        validate_bot_comment(client.update_comment(comment_id, body), expected_body=body)
        return "updated"


def comment_main(environment: Mapping[str, str]) -> int:
    try:
        payload = decode_comment_payload(environment.get("BAR_COMMENT_PAYLOAD", ""))
        body = render_comment(payload)
        outcome = upsert_comment(
            GitHubCommentsClient(environment.get("GITHUB_TOKEN", "")),
            payload["pullRequestNumber"],
            body,
        )
        print(f"Bar pull request comment {outcome}.")
        return 0
    except CommentIntegrationError as error:
        print(f"Bar comment failed: {error}", file=sys.stderr)
        return 1


def main(arguments: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if arguments != ["comment"]:
        print("Usage: bar_pr_comment.py comment", file=sys.stderr)
        return 2
    return comment_main(os.environ)


if __name__ == "__main__":
    raise SystemExit(main())
