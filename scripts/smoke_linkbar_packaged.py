#!/usr/bin/env python3
"""Launch the packaged LinkBar with every build path hidden.

This is the harness that would have caught issue #58, where the shipped
app crashed at launch on every machine except the one that built it.
SPM's generated `Bundle.module` accessor calls fatalError() when it
cannot find its resource bundle, and it only looks in the app root and
the *absolute build directory compiled into the binary*. On the build
host that second path resolves, so every test run there passed while
every real install was broken - silently, because an LSUIElement app has
no window in which to show a crash.

The only way to catch that class of bug is to make the build environment
unavailable and then run the artifact. This script:

1. bundles the app with Scripts/bundle.sh,
2. moves every *_LinkBar.bundle under .build out of the way - simulating
   a machine that never built anything,
3. launches the packaged binary in snapshot mode and requires it to
   render,
4. restores the moved bundles no matter what happened.

Run:  python3 scripts/smoke_linkbar_packaged.py
Exit: non-zero if the packaged app fails to launch and render.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "apps" / "LinkBar"
LAUNCH_TIMEOUT_SECONDS = 90


def _bundle_app() -> Path:
    result = subprocess.run(
        ["bash", str(APP_DIR / "Scripts" / "bundle.sh")],
        cwd=APP_DIR, capture_output=True, text=True, timeout=900,
    )
    if result.returncode != 0:
        raise SystemExit(f"bundle.sh failed:\n{result.stdout}\n{result.stderr}")
    app = APP_DIR / ".build" / "LinkBar.app"
    if not (app / "Contents" / "MacOS" / "LinkBar").is_file():
        raise SystemExit(f"bundle.sh did not produce a binary at {app}")
    return app


def main() -> int:
    if sys.platform != "darwin":
        print("skipped: LinkBar is macOS only")
        return 0
    if shutil.which("swift") is None:
        print("skipped: swift toolchain not available")
        return 0

    app = _bundle_app()
    build_dir = APP_DIR / ".build"
    # Every resource bundle the compiled-in fallback path could resolve.
    hidden: list[tuple[Path, Path]] = []
    stash = Path(tempfile.mkdtemp(prefix="linkbar-smoke-"))
    try:
        for index, bundle in enumerate(sorted(build_dir.rglob("*_LinkBar.bundle"))):
            # Never hide the copy inside the packaged app: that one is the
            # artifact under test.
            if str(app) in str(bundle):
                continue
            target = stash / f"{index}-{bundle.name}"
            shutil.move(str(bundle), str(target))
            hidden.append((bundle, target))
        print(f"hid {len(hidden)} build resource bundle(s); launching the packaged app")

        snapshot = stash / "packaged.png"
        env = dict(os.environ)
        env["LINKBAR_SNAPSHOT"] = str(snapshot)
        env["LINKBAR_SNAPSHOT_WAIT"] = "3"
        process = subprocess.Popen(
            [str(app / "Contents" / "MacOS" / "LinkBar")],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        deadline = time.time() + LAUNCH_TIMEOUT_SECONDS
        while time.time() < deadline and not snapshot.exists():
            if process.poll() is not None:
                break
            time.sleep(0.5)
        output = ""
        if process.poll() is None:
            process.terminate()
            try:
                output = (process.communicate(timeout=15)[0] or "")
            except subprocess.TimeoutExpired:
                process.kill()
        else:
            output = (process.communicate()[0] or "")

        if not snapshot.exists():
            print("FAILED: the packaged app did not render with build paths hidden")
            print("This is issue #58's failure mode: a user's machine has no")
            print("build directory, so anything resolved through it is absent.")
            if output.strip():
                print("--- app output ---")
                print(output[:2000])
            return 1
        size = snapshot.stat().st_size
        print(f"packaged LinkBar launched and rendered ({size} bytes) with no build paths")
        return 0
    finally:
        for original, moved in hidden:
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(moved), str(original))
        shutil.rmtree(stash, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
