#!/usr/bin/env python3
"""Type-error ratchet: the mypy error count may only go down.

A full typing cleanup of an existing codebase lands in one of two ways:
a heroic branch that never merges, or a ratchet. This is the ratchet.

- `mypy --config-file mypy.ini` runs in lenient mode over link_core and
  link_mcp; TYPE_ERROR_BASELINE pins the current count.
- CI fails when the count RISES (new code added new type errors).
- When the count drops, this script says so — lower the baseline in the
  same commit that earned it.

The baseline is defined for one exact environment — a dependency-free
interpreter with mypy>=1.20,<1.21 (what the CI lint job builds). Installed
product dependencies change what mypy can resolve and therefore the count;
treat CI as the referee and local runs as advisory.

Run:  python3 scripts/check_type_ratchet.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TYPE_ERROR_BASELINE = 385


def main() -> int:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "mypy", "--config-file", str(ROOT / "mypy.ini")],
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=600,
        )
    except FileNotFoundError:
        print("mypy is not installed; skipping type ratchet (CI runs it).")
        return 0
    output = result.stdout.strip().splitlines()
    if result.returncode == 0:
        count = 0
    else:
        summary = output[-1] if output else ""
        match = re.search(r"Found (\d+) errors?", summary)
        if not match:
            print("Could not parse mypy output; failing safe.", file=sys.stderr)
            print("\n".join(output[-5:]), file=sys.stderr)
            return 2
        count = int(match.group(1))

    if count > TYPE_ERROR_BASELINE:
        print(
            f"Type ratchet FAILED: {count} mypy errors > baseline {TYPE_ERROR_BASELINE}.\n"
            "New code introduced new type errors — fix them (or annotate with a "
            "reasoned `# type: ignore[...]`); do not raise the baseline.",
            file=sys.stderr,
        )
        return 1
    if count < TYPE_ERROR_BASELINE:
        print(
            f"Type ratchet passed: {count} errors (baseline {TYPE_ERROR_BASELINE}). "
            f"You earned a lower baseline — set TYPE_ERROR_BASELINE = {count}."
        )
        return 0
    print(f"Type ratchet passed: {count} errors (== baseline).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
