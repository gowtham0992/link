#!/usr/bin/env python3
"""Check tracked files for release-blocking credential leaks."""
from __future__ import annotations

import fnmatch
import json
import re
import subprocess
from pathlib import Path


SECRET_NAME_PATTERNS = (
    ".env",
    ".env.*",
    ".envrc",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "*.token",
    ".mcpregistry_*",
    "*.key",
    "*.pem",
    "*.p8",
    "*.p12",
    "*.jks",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
    "service-account*.json",
)

BUILD_ARTIFACT_PATTERNS = (
    "dist/*",
    "*/dist/*",
    "*.whl",
    "*.tar.gz",
    "*.egg-info",
    "*.egg-info/*",
)

SECRET_VALUE_PATTERNS = (
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("OpenAI API key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("AWS access key", re.compile(r"\bA[SK]IA[0-9A-Z]{16}\b")),
    ("PyPI token", re.compile(r"\bpypi-[A-Za-z0-9_-]{20,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("Stripe live secret key", re.compile(r"\bsk_live_[A-Za-z0-9]{20,}\b")),
    ("Private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)

OUTBOUND_NETWORK_CODE_SUFFIXES = {".py", ".sh"}
OUTBOUND_NETWORK_ALLOWLIST = {
    Path("scripts/smoke_http_viewer.py"),
}
OUTBOUND_NETWORK_PATTERNS = (
    ("requests import", re.compile(r"^\s*(?:import\s+requests\b|from\s+requests\b)", re.MULTILINE)),
    ("httpx import", re.compile(r"^\s*(?:import\s+httpx\b|from\s+httpx\b)", re.MULTILINE)),
    ("http.client import", re.compile(r"^\s*(?:import\s+http\.client\b|from\s+http\.client\b)", re.MULTILINE)),
    ("urllib.request import", re.compile(r"^\s*(?:import\s+urllib\.request\b|from\s+urllib\.request\b)", re.MULTILINE)),
    ("urllib request import", re.compile(r"^\s*from\s+urllib\s+import\s+request\b", re.MULTILINE)),
    ("socket import", re.compile(r"^\s*(?:import\s+socket\b|from\s+socket\b)", re.MULTILINE)),
    ("urlopen call", re.compile(r"\burlopen\s*\(")),
    ("http.client connection", re.compile(r"\b(?:http\.client\.)?HTTPS?Connection\s*\(")),
    ("requests call", re.compile(r"\brequests\.(?:get|post|put|patch|delete|request)\s*\(")),
    ("httpx call", re.compile(r"\bhttpx\.(?:get|post|put|patch|delete|request)\s*\(")),
    ("curl command", re.compile(r"(^|[;&|]\s*)curl\s+(?:-[^\s]+\s+)*https?://", re.MULTILINE)),
    ("wget command", re.compile(r"(^|[;&|]\s*)wget\s+(?:-[^\s]+\s+)*https?://", re.MULTILINE)),
)

BINARY_SUFFIXES = {
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".pyc",
    ".tar",
    ".webp",
    ".whl",
    ".zip",
}

CHANGELOG_VERSION_RE = re.compile(r"^## \[([^\]]+)\](?: - \d{4}-\d{2}-\d{2})?\s*$", re.MULTILINE)

AGENT_CONTRACT_REQUIREMENTS = {
    Path("LINK.md"): (
        "status",
        "recall",
        "remember",
        "ingest",
        "review",
        "admin",
    ),
    Path("README.md"): (
        "status",
        "recall",
        "remember",
        "ingest",
        "review",
        "admin",
    ),
    Path("mcp_package/README.md"): (
        "status",
        "recall",
        "remember",
        "ingest",
        "review",
        "admin",
    ),
    Path("integrations/_shared/link-instructions.md"): (
        "status",
        "recall",
        "remember",
        "ingest",
        "review",
        "admin",
    ),
    Path("integrations/_shared/link-instructions-project.md"): (
        "status",
        "recall",
        "remember",
        "ingest",
        "review",
        "admin",
    ),
}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    )
    names = result.stdout.decode("utf-8").split("\0")
    return [Path(name) for name in names if name]


def read_pyproject_version(path: Path) -> str | None:
    match = re.search(r'^version\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    return match.group(1) if match else None


def read_init_version(path: Path) -> str | None:
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    return match.group(1) if match else None


def read_core_version(path: Path) -> str | None:
    match = re.search(r'^LINK_VERSION\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    return match.group(1) if match else None


def check_version_values(
    findings: list[str],
    versions: dict[str, str | None],
    package_versions: set[str | None],
) -> None:
    if not package_versions:
        findings.append("version mismatch: server.json has no link-mcp package version")
    if len(set(versions.values()) | package_versions) != 1:
        for label, version in versions.items():
            findings.append(f"version mismatch: {label} is {version!r}")
        findings.append(f"version mismatch: server.json package versions are {sorted(package_versions)!r}")


def check_version_consistency(findings: list[str]) -> str | None:
    pyproject_version = read_pyproject_version(Path("mcp_package/pyproject.toml"))
    init_version = read_init_version(Path("mcp_package/link_mcp/__init__.py"))
    core_version = read_core_version(Path("mcp_package/link_core/version.py"))
    server = json.loads(Path("mcp_package/server.json").read_text(encoding="utf-8"))
    server_version = server.get("version")
    package_versions = {
        package.get("version")
        for package in server.get("packages", [])
        if package.get("identifier") == "link-mcp"
    }
    versions = {
        "mcp_package/pyproject.toml": pyproject_version,
        "mcp_package/link_mcp/__init__.py": init_version,
        "mcp_package/link_core/version.py": core_version,
        "mcp_package/server.json": server_version,
    }
    check_version_values(findings, versions, package_versions)
    return pyproject_version


def read_changelog_versions(path: Path) -> list[str]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    return CHANGELOG_VERSION_RE.findall(text)


def check_changelog(findings: list[str], current_version: str | None, path: Path = Path("CHANGELOG.md")) -> None:
    versions = read_changelog_versions(path)
    if not versions:
        findings.append("missing or empty CHANGELOG.md version sections")
        return
    if "Unreleased" not in versions:
        findings.append("CHANGELOG.md missing ## [Unreleased] section")
    if not current_version:
        findings.append("could not determine current package version for CHANGELOG.md check")
    elif current_version not in versions:
        findings.append(f"CHANGELOG.md missing current package version: {current_version}")


def check_agent_contract(
    findings: list[str],
    requirements: dict[Path, tuple[str, ...]] = AGENT_CONTRACT_REQUIREMENTS,
) -> None:
    for path, required_terms in requirements.items():
        rel = path.as_posix()
        if not path.exists():
            findings.append(f"agent contract file missing: {rel}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for term in required_terms:
            if term not in text:
                findings.append(f"agent contract missing {term!r} in {rel}")


def check_tracked_path_hygiene(findings: list[str], path: Path) -> bool:
    """Check release-blocking tracked path patterns. Return true when caller should skip content scan."""
    rel = path.as_posix()
    if any(fnmatch.fnmatch(rel, pattern) for pattern in BUILD_ARTIFACT_PATTERNS):
        findings.append(f"build artifact should not be tracked: {rel}")
        return True

    name = path.name
    if any(fnmatch.fnmatch(name, pattern) for pattern in SECRET_NAME_PATTERNS):
        findings.append(f"sensitive-looking tracked filename: {rel}")
        return True

    return False


def check_outbound_network_hygiene(findings: list[str], path: Path, text: str) -> None:
    """Block accidental outbound network code in Link's local-first runtime."""
    rel = path.as_posix()
    if path.suffix.lower() not in OUTBOUND_NETWORK_CODE_SUFFIXES:
        return
    if path in OUTBOUND_NETWORK_ALLOWLIST:
        return
    for label, pattern in OUTBOUND_NETWORK_PATTERNS:
        if pattern.search(text):
            findings.append(f"outbound network code in {rel}: {label}")
            return


def main() -> int:
    findings: list[str] = []
    current_version = check_version_consistency(findings)
    check_changelog(findings, current_version)
    check_agent_contract(findings)

    for path in tracked_files():
        if check_tracked_path_hygiene(findings, path):
            continue

        if path.suffix.lower() in BINARY_SUFFIXES:
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            findings.append(f"could not read tracked file {path.as_posix()}: {exc}")
            continue

        for label, pattern in SECRET_VALUE_PATTERNS:
            if pattern.search(text):
                findings.append(f"sensitive-looking content in {path.as_posix()}: {label}")
                break
        check_outbound_network_hygiene(findings, path, text)

    if findings:
        print("Release hygiene check failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1

    print("Release hygiene check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
