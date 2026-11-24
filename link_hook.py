"""Link's pre-tool and post-tool hooks, without loading the CLI.

Agents run these around every shell command and file access, so they must
be quick. `link.py` is a large file that Python recompiles on every run (a
script's bytecode is never cached), which used to be most of a hook call's
cost. Installed hooks point here instead; anything this entry point does not
recognise is handed to the full CLI unchanged.

    python link_hook.py hook pre-tool <workspace> [--emit cursor] [--project P]
    python link_hook.py hook post-tool <workspace>

The arguments are the CLI's own (`link.py hook ...`), so an installed hook
reads the same either way and setup and disconnect recognise both.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _candidate in (_HERE / "mcp_package", _HERE):
    if (_candidate / "link_core").is_dir():
        sys.path.insert(0, str(_candidate))
        break


def _full_cli(argv: list[str]) -> int:
    """Run `link.py hook <argv>` (or the installed `lnk` module) for anything unusual."""
    script = _HERE / "link.py"
    if script.is_file():
        import runpy

        sys.argv = [str(script), "hook", *argv]
        try:
            runpy.run_path(str(script), run_name="__main__")
        except SystemExit as exit_:
            return exit_.code if isinstance(exit_.code, int) else 0
        return 0
    from link_cli import main  # a pip install ships the CLI as this module

    return main(["hook", *argv])


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["hook"]:
        args = args[1:]
    from link_core.tool_hooks import fast_tool_hook

    code = fast_tool_hook(args)
    return _full_cli(args) if code is None else code


if __name__ == "__main__":
    sys.exit(main())
