"""Local security hygiene helpers for Link."""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path


SECRET_VALUE_PATTERNS = (
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("OpenAI API key", re.compile(r"\bsk-(?!ant-)[A-Za-z0-9_-]{20,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("AWS access key", re.compile(r"\bA[SK]IA[0-9A-Z]{16}\b")),
    ("PyPI token", re.compile(r"\bpypi-[A-Za-z0-9_-]{20,}\b")),
    ("Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{20,}\b")),
    ("npm token", re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b")),
    ("Vercel token", re.compile(r"\bvercel_[A-Za-z0-9]{20,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("Stripe live secret key", re.compile(r"\bsk_live_[A-Za-z0-9]{20,}\b")),
    ("Azure storage account key", re.compile(r"(?i)\b(?:AccountKey|AZURE_STORAGE_KEY)\s*[:=]\s*[A-Za-z0-9+/=]{40,}\b")),
    ("Datadog API key", re.compile(r"(?i)\b(?:DD_API_KEY|DATADOG_API_KEY)\s*[:=]\s*[0-9a-f]{32}\b")),
    ("Sentry DSN", re.compile(r"\bhttps://[0-9a-f]{32}@[A-Za-z0-9.-]+/[0-9]+\b")),
    ("JWT token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("Docker registry auth", re.compile(r'(?is)"auths"\s*:\s*\{.{0,2000}?"auth"\s*:\s*"[A-Za-z0-9+/=]{20,}"')),
    ("Private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)


def clean_text_input(value: object, max_len: int = 500) -> str:
    """Normalize optional user/tool text input to a stripped, bounded string."""
    if value is None:
        return ""
    return str(value).strip()[:max_len]


_PASSWORD_KEYWORD_RE = re.compile(r"(?i)\b(password|passwd|passcode|pass code|otp|2fa code|pin)\b")


def looks_like_password_note(text: str) -> str | None:
    """Heuristic for human credentials that token patterns cannot catch.

    Memory pages are plain files injected into every connected agent's
    context; a password saved as memory leaks by design. Conservative on
    purpose: a lone credential-shaped token, or a credential keyword next
    to one.
    """
    value = str(text or "").strip()
    if not value:
        return None
    token = value if " " not in value else ""
    if token and 6 <= len(token) <= 40:
        has_letter = any(c.isalpha() for c in token)
        has_digit = any(c.isdigit() for c in token)
        has_symbol = any(not c.isalnum() for c in token)
        mixed_case = token != token.lower() and token != token.upper()
        if has_letter and has_digit and (has_symbol or mixed_case):
            return "password-like value"
    if _PASSWORD_KEYWORD_RE.search(value):
        for word in re.findall(r"\S+", value):
            if 6 <= len(word) <= 40 and any(c.isdigit() for c in word) and any(c.isalpha() for c in word):
                if any(not c.isalnum() for c in word) or word != word.lower():
                    return "password mentioned alongside a credential-shaped value"
            if word.isdigit() and 4 <= len(word) <= 12:
                return "password/PIN mentioned alongside a numeric code"
    return None


def secret_value_warnings(text: str) -> list[str]:
    """Return labels for secret-looking values found in text."""
    warnings: list[str] = []
    for label, pattern in SECRET_VALUE_PATTERNS:
        if pattern.search(text):
            warnings.append(label)
    return warnings


def secret_file_warnings(path: Path, chunk_size: int = 65536, tail_size: int = 512) -> list[str]:
    """Return secret-looking labels from a file without loading it all at once."""
    return list(secret_file_scan(path, chunk_size=chunk_size, tail_size=tail_size)["labels"])


def secret_file_scan(path: Path, chunk_size: int = 65536, tail_size: int = 512) -> dict[str, object]:
    """Scan a file for secret-looking values and report read failures explicitly."""
    found: set[str] = set()
    read_size = max(1, chunk_size)
    tail_len = max(0, tail_size)
    tail = ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            while True:
                chunk = handle.read(read_size)
                if not chunk:
                    break
                text = tail + chunk
                found.update(secret_value_warnings(text))
                if len(found) == len(SECRET_VALUE_PATTERNS):
                    break
                tail = text[-tail_len:] if tail_len else ""
    except OSError as exc:
        return {
            "labels": [],
            "readable": False,
            "error": str(exc),
        }
    return {
        "labels": [label for label, _pattern in SECRET_VALUE_PATTERNS if label in found],
        "readable": True,
        "error": "",
    }


def redact_secret_values(text: str, replacement: str = "[redacted-secret]") -> tuple[str, list[str], int]:
    """Replace secret-looking values and return redacted text, labels, and count."""
    labels: list[str] = []
    total = 0
    redacted = text
    for label, pattern in SECRET_VALUE_PATTERNS:
        redacted, count = pattern.subn(replacement, redacted)
        if count:
            labels.append(label)
            total += count
    return redacted, labels, total


def find_sensitive_filenames(
    target: Path,
    *,
    skip_dirs: set[str],
    patterns: tuple[str, ...],
) -> list[str]:
    """Find secret-looking filenames under a Link root."""
    root = target.expanduser().resolve()
    matches: list[str] = []
    stack = [root]
    while stack:
        current = stack.pop()
        for path in current.iterdir():
            if path.is_dir():
                if path.name not in skip_dirs:
                    stack.append(path)
                continue
            if not path.is_file():
                continue
            if any(fnmatch.fnmatch(path.name, pattern) for pattern in patterns):
                matches.append(path.relative_to(root).as_posix())
    return sorted(matches)


def iter_scannable_files(
    target: Path,
    *,
    skip_dirs: set[str],
    skip_suffixes: set[str],
) -> list[Path]:
    """Return text-like files worth scanning for secret-looking values."""
    root = target.expanduser().resolve()
    files: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        for path in current.iterdir():
            if path.is_dir():
                if path.name not in skip_dirs:
                    stack.append(path)
                continue
            if not path.is_file() or path.suffix.lower() in skip_suffixes:
                continue
            files.append(path)
    return sorted(files)


def find_sensitive_values(
    target: Path,
    *,
    skip_dirs: set[str],
    skip_suffixes: set[str],
) -> tuple[list[str], list[str]]:
    """Find secret-looking file contents and read errors under a Link root."""
    root = target.expanduser().resolve()
    matches: list[str] = []
    read_errors: list[str] = []
    for path in iter_scannable_files(root, skip_dirs=skip_dirs, skip_suffixes=skip_suffixes):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            read_errors.append(f"{path.relative_to(root)} ({exc})")
            continue
        warnings = secret_value_warnings(text)
        if warnings:
            matches.append(f"{path.relative_to(root)} ({warnings[0]})")
    return sorted(matches), sorted(read_errors)
