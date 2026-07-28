#!/usr/bin/env python3
"""Prepare local files for a Link MCP release.

This script updates version files and moves CHANGELOG.md Unreleased notes into a
dated version section. It does not commit, tag, upload to PyPI, or publish to the
MCP Registry.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
CHANGELOG_HEADING_RE = re.compile(r"^## \[([^\]]+)\](?: - \d{4}-\d{2}-\d{2})?\s*$", re.MULTILINE)


@dataclass(frozen=True)
class ReleaseFiles:
    pyproject: Path
    init: Path
    core_version: Path
    server_json: Path
    changelog: Path
    homepage: Path


def release_files(root: Path = ROOT) -> ReleaseFiles:
    return ReleaseFiles(
        pyproject=root / "mcp_package/pyproject.toml",
        init=root / "mcp_package/link_mcp/__init__.py",
        core_version=root / "mcp_package/link_core/version.py",
        server_json=root / "mcp_package/server.json",
        changelog=root / "CHANGELOG.md",
        homepage=root / "docs/index.html",
    )


def normalize_version(raw: str) -> str:
    match = VERSION_RE.match(raw.strip())
    if not match:
        raise ValueError("version must look like 1.2.3 or v1.2.3")
    return ".".join(match.groups())


def version_tuple(version: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in normalize_version(version).split("."))  # type: ignore[return-value]


def normalize_date(raw: str) -> str:
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise ValueError("date must use YYYY-MM-DD") from exc


def read_pyproject_version(path: Path) -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    if not match:
        raise ValueError(f"could not read version from {path}")
    return match.group(1)


def read_init_version(path: Path) -> str:
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    if not match:
        raise ValueError(f"could not read __version__ from {path}")
    return match.group(1)


def read_core_version(path: Path) -> str:
    match = re.search(r'^LINK_VERSION\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    if not match:
        raise ValueError(f"could not read LINK_VERSION from {path}")
    return match.group(1)


def read_server_versions(path: Path) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    versions = {str(data.get("version", ""))}
    versions.update(
        str(package.get("version", ""))
        for package in data.get("packages", [])
        if package.get("identifier") == "link-mcp"
    )
    return versions


def read_current_versions(files: ReleaseFiles) -> set[str]:
    versions = {
        read_pyproject_version(files.pyproject),
        read_init_version(files.init),
        read_core_version(files.core_version),
    }
    versions.update(read_server_versions(files.server_json))
    return versions


def ensure_current_versions_match(files: ReleaseFiles) -> str:
    versions = read_current_versions(files)
    if len(versions) != 1:
        raise ValueError(f"current version files disagree: {sorted(versions)}")
    return versions.pop()


def replace_one(pattern: str, replacement: str, text: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise ValueError(f"could not update {label}")
    return updated


def update_pyproject(text: str, version: str) -> str:
    return replace_one(r'^version\s*=\s*"[^"]+"', f'version = "{version}"', text, "pyproject version")


def update_init(text: str, version: str) -> str:
    return replace_one(r'^__version__\s*=\s*"[^"]+"', f'__version__ = "{version}"', text, "__version__")


def update_core_version(text: str, version: str) -> str:
    return replace_one(r'^LINK_VERSION\s*=\s*"[^"]+"', f'LINK_VERSION = "{version}"', text, "LINK_VERSION")


def update_server_json(text: str, version: str) -> str:
    data = json.loads(text)
    data["version"] = version
    for package in data.get("packages", []):
        if package.get("identifier") == "link-mcp":
            package["version"] = version
    return json.dumps(data, indent=2) + "\n"


def extract_unreleased(changelog: str) -> tuple[str, str, str]:
    match = CHANGELOG_HEADING_RE.search(changelog)
    if not match or match.group(1) != "Unreleased":
        raise ValueError("CHANGELOG.md must start its release sections with ## [Unreleased]")
    next_match = CHANGELOG_HEADING_RE.search(changelog, match.end())
    if not next_match:
        raise ValueError("CHANGELOG.md needs at least one released version section after Unreleased")
    prefix = changelog[: match.end()]
    unreleased = changelog[match.end() : next_match.start()]
    rest = changelog[next_match.start() :]
    return prefix, unreleased, rest


def has_release_notes(section: str) -> bool:
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            return True
    return False


def update_changelog(text: str, version: str, release_date: str) -> str:
    if re.search(rf"^## \[{re.escape(version)}\](?: - \d{{4}}-\d{{2}}-\d{{2}})?\s*$", text, flags=re.MULTILINE):
        raise ValueError(f"CHANGELOG.md already has a section for {version}")

    prefix, unreleased, rest = extract_unreleased(text)
    if not has_release_notes(unreleased):
        raise ValueError("CHANGELOG.md Unreleased section has no bullet notes to release")

    header = prefix.rstrip() + "\n\n"
    released = f"## [{version}] - {release_date}\n{unreleased.rstrip()}\n\n"
    return header + released + rest.lstrip()


HOMEPAGE_BANNER_RE = re.compile(r"(New \\u00b7 Link )\d+\.\d+\.\d+( is out)")
HOMEPAGE_TAG_RE = re.compile(r"(releases\\u002Ftag\\u002Fv)\d+\.\d+\.\d+")


def update_homepage(text: str, version: str) -> str:
    """Point the site's release banner at the version being released.

    The banner advertises a download, so a stale number sends visitors to a
    tag that does not exist yet — keep it in the release step, not in a
    human's memory.
    """
    text = HOMEPAGE_BANNER_RE.sub(rf"\g<1>{version}\g<2>", text)
    return HOMEPAGE_TAG_RE.sub(rf"\g<1>{version}", text)


def prepare_release(root: Path, version: str, release_date: str, dry_run: bool = False) -> list[Path]:
    files = release_files(root)
    version = normalize_version(version)
    release_date = normalize_date(release_date)
    current = ensure_current_versions_match(files)
    if version_tuple(version) <= version_tuple(current):
        raise ValueError(f"new version {version} must be greater than current version {current}")

    updates = {
        files.pyproject: update_pyproject(files.pyproject.read_text(encoding="utf-8"), version),
        files.init: update_init(files.init.read_text(encoding="utf-8"), version),
        files.core_version: update_core_version(files.core_version.read_text(encoding="utf-8"), version),
        files.server_json: update_server_json(files.server_json.read_text(encoding="utf-8"), version),
        files.changelog: update_changelog(files.changelog.read_text(encoding="utf-8"), version, release_date),
    }
    # The homepage is presentation, not a package artifact: update it when
    # present (the real repo), skip it in minimal trees/tests.
    if files.homepage.exists():
        updates[files.homepage] = update_homepage(
            files.homepage.read_text(encoding="utf-8"), version
        )

    changed = [path for path, text in updates.items() if path.read_text(encoding="utf-8") != text]
    if not dry_run:
        for path, text in updates.items():
            path.write_text(text, encoding="utf-8")
    return changed


def release_commands(version: str) -> list[str]:
    version = normalize_version(version)
    return [
        "git switch main",
        "git pull --ff-only",
        f'git tag -a v{version} -m "v{version}"',
        f"git push origin v{version}",
        "cd mcp_package",
        'python3 -c "from pathlib import Path; import shutil; shutil.rmtree(\'dist\', ignore_errors=True); [shutil.rmtree(p, ignore_errors=True) for p in Path(\'.\').glob(\'*.egg-info\')]"',
        "python3 -m build",
        "python3 -m twine check dist/*",
        f"TWINE_USERNAME=__token__ python3 -m twine upload dist/link_mcp-{version}*",
        "mcp-publisher validate",
        "mcp-publisher publish",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare Link MCP release files.")
    parser.add_argument("version", help="new release version, e.g. 1.0.6")
    parser.add_argument("--date", default=date.today().isoformat(), help="release date in YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="validate and list files without writing")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args()

    try:
        changed = prepare_release(args.root.resolve(), args.version, args.date, dry_run=args.dry_run)
    except ValueError as exc:
        parser.exit(1, f"error: {exc}\n")

    action = "Would update" if args.dry_run else "Updated"
    print(f"{action} {len(changed)} release file{'s' if len(changed) != 1 else ''}:")
    for path in changed:
        print(f"- {path.relative_to(args.root.resolve())}")

    print("")
    print("After the PR merges and CI passes, publish with:")
    for command in release_commands(args.version):
        print(command)
    print("")
    print(
        "Then bump the Homebrew tap (gowtham0992/homebrew-link) to "
        f"{normalize_version(args.version)} so `brew install` serves this "
        "version — otherwise new users get an older Link than the docs describe."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
