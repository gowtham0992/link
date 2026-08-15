"""Stage the repo-root runtime files into the package before building.

`pip install link-mcp` must deliver the whole product: the MCP server,
the `lnk` CLI, the local viewer, and the schema/ignore files a workspace
needs. Those live at the repository root, one level above this package.

Referencing them as `../link.py` from the build config only works when
building in the source tree. `python -m build` deliberately builds the
sdist first and then builds the wheel *from the extracted sdist*, where
no parent directory exists - so a `../` reference fails there, which is
exactly how CI caught this.

This hook copies the files into the package directory before any file
collection happens, so both builds see local paths:

- source tree  -> copies from `../`, then the sdist carries the copies
- from a sdist -> the copies are already present, nothing to do

The copies are build artifacts, gitignored, and never edited by hand;
the repo root stays the single source of truth.
"""
from __future__ import annotations

import shutil
from pathlib import Path

try:
    from hatchling.builders.hooks.plugin.interface import BuildHookInterface
except ImportError:  # tests exercise the staging logic without the backend
    BuildHookInterface = object  # type: ignore[assignment,misc]

# repo-root file -> name inside the package
STAGED_RUNTIME_FILES = {
    "link.py": "link_cli.py",
    "serve.py": "serve.py",
    "LINK.md": "LINK.md",
    ".linkignore": ".linkignore",
}


class StageRuntimeFilesHook(BuildHookInterface):
    PLUGIN_NAME = "stage-runtime"

    def initialize(self, version: str, build_data: dict) -> None:
        package_dir = Path(self.root)
        repo_root = package_dir.parent
        missing: list[str] = []
        for source_name, staged_name in STAGED_RUNTIME_FILES.items():
            staged = package_dir / staged_name
            source = repo_root / source_name
            if source.is_file():
                shutil.copy2(source, staged)
            elif not staged.is_file():
                missing.append(staged_name)
        if missing:
            raise FileNotFoundError(
                "runtime files missing from both the repo root and the package: "
                + ", ".join(missing)
                + " - the sdist is incomplete, so the wheel would ship without the CLI"
            )
