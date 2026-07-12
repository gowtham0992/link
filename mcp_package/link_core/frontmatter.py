"""Shared frontmatter parsing and formatting helpers for Link."""
from __future__ import annotations

import csv
import re
from collections.abc import Iterable, Mapping


FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _csv_list(value: str) -> list[str]:
    try:
        row = next(csv.reader([value], skipinitialspace=True))
    except csv.Error:
        row = value.split(",")
    return [_unquote(item).strip() for item in row if _unquote(item).strip()]


def parse_frontmatter_value(value: str) -> object:
    raw = value.strip()
    if raw.startswith("[") and raw.endswith("]"):
        return _csv_list(raw[1:-1])
    return _unquote(raw)


def parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    meta: dict[str, object] = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = parse_frontmatter_value(value)
    return meta, text[match.end():]


def frontmatter_string(value: object) -> str:
    """Escape a value for a double-quoted single-line frontmatter field.

    Newlines and control characters must never reach the file raw: a title
    containing "\\ntitle: injected" would otherwise write extra frontmatter
    lines that the parser then honors (field injection). Collapse whitespace
    runs to single spaces and drop remaining non-printable characters.
    """
    text = " ".join(str(value).split())
    text = "".join(ch for ch in text if ch.isprintable())
    return text.replace("\\", "\\\\").replace('"', '\\"')


def csv_values(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def meta_tags(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip().strip("\"'") for item in csv_values(str(value).strip("[]"))]


def _needs_quotes(value: str) -> bool:
    return not value or any(char in value for char in ",[]{}:#\"'\n\r\t")


def _format_list_item(value: object) -> str:
    text = str(value).strip()
    if not _needs_quotes(text):
        return text
    return '"' + frontmatter_string(text) + '"'


def yaml_list(values: Iterable[object]) -> str:
    return "[" + ", ".join(_format_list_item(value) for value in values) + "]"


def format_frontmatter_value(value: object) -> str:
    if isinstance(value, (list, tuple, set)):
        return yaml_list(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def update_frontmatter_fields(
    text: str,
    updates: Mapping[str, object],
    remove: set[str] | None = None,
) -> str:
    remove = remove or set()
    formatted = {key: format_frontmatter_value(value) for key, value in updates.items()}
    match = FRONTMATTER_RE.match(text)
    if not match:
        frontmatter = [f"{key}: {value}" for key, value in formatted.items()]
        return "---\n" + "\n".join(frontmatter) + "\n---\n\n" + text.lstrip("\n")

    seen: set[str] = set()
    lines: list[str] = []
    for line in match.group(1).splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            lines.append(line)
            continue
        key = line.split(":", 1)[0].strip()
        if key in remove:
            continue
        if key in formatted:
            lines.append(f"{key}: {formatted[key]}")
            seen.add(key)
        else:
            lines.append(line)
    for key, value in formatted.items():
        if key not in seen:
            lines.append(f"{key}: {value}")
    return "---\n" + "\n".join(lines) + "\n---\n" + text[match.end():].lstrip("\n")


def frontmatter_int(value: object) -> int:
    try:
        return int(str(value or "0").strip())
    except ValueError:
        return 0
