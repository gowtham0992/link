#!/bin/bash
# Helpers for safely installing Link instruction blocks into existing files.

# Link's section starts at its own heading and ends at the next heading of
# any level, so nothing the person wrote after it is ever taken with it.
# The file's other bytes and line endings are kept, the write is atomic,
# and a file that is not UTF-8 is left alone. Paths travel in the
# environment, never pasted into the program text.
_LINK_SECTION_PY='
import os, re, stat, tempfile
from pathlib import Path

HEADERS = ["## Link — Local Agent Memory", "## Link — Personal Knowledge Wiki"]
PATTERN = re.compile(r"(^|\n)(?:" + "|".join(re.escape(h) for h in HEADERS) + r")\r?\n.*?(?=\r?\n#{1,6}[ \t]|\Z)", re.DOTALL)


def read(path):
    if not path.exists():
        return None
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise SystemExit(f"  · {path} is not UTF-8 text; left alone. Edit Link'"'"'s section out by hand.")


def write(path, text):
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".")
    with os.fdopen(fd, "wb") as handle:
        handle.write(text.encode("utf-8"))
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


def remove(text):
    match = PATTERN.search(text)
    if not match:
        return text
    rest = text[match.end():]
    rest = rest[2:] if rest.startswith("\r\n") else rest[1:] if rest.startswith("\n") else rest
    head = text[:match.start()] + match.group(1)
    while head.endswith(("\n\n", "\r\n\r\n")) and not rest:
        head = head[:-2] if head.endswith("\r\n\r\n") else head[:-1]
    return head + rest
'

link_upsert_instructions() {
    local target="$1"
    local source_file="$2"
    local label="$3"

    LINK_TARGET="$target" LINK_SOURCE="$source_file" python3 -c "$_LINK_SECTION_PY"'
target = Path(os.environ["LINK_TARGET"]).expanduser()
source = Path(os.environ["LINK_SOURCE"]).read_text(encoding="utf-8").rstrip("\r\n")
existing = read(target)
if existing is None or not existing.strip():
    updated = source + "\n"
else:
    newline = "\r\n" if "\r\n" in existing else "\n"
    block = source.replace("\n", newline)
    match = PATTERN.search(existing)
    if match:
        updated = existing[:match.start()] + match.group(1) + block + existing[match.end():]
    else:
        separator = "" if existing.endswith(newline * 2) else newline if existing.endswith(newline) else newline * 2
        updated = existing + separator + block + newline
if updated != existing:
    write(target, updated)
'
    echo "$label → $target"
}

link_remove_instructions() {
    local target="$1"
    LINK_TARGET="$target" python3 -c "$_LINK_SECTION_PY"'
target = Path(os.environ["LINK_TARGET"]).expanduser()
text = read(target)
if text is None:
    print(f"No {target} found")
elif not PATTERN.search(text):
    print(f"No Link section in {target}")
else:
    cleaned = remove(text)
    if cleaned.strip():
        write(target, cleaned)
        print(f"Link section removed from {target}")
    else:
        target.unlink()
        print(f"{target} held only Link'"'"'s section; deleted")
'
}

link_print_next_steps() {
    local mode="${1:---global}"

    echo ""
    echo "Done."
    if [ "$mode" = "--project" ]; then
        echo "  Drop sources into raw/."
        echo "  View wiki: python3 link.py serve"
        echo "  Print starter prompts: python3 link.py next"
        echo "  Try in your agent:"
        echo "    is Link ready?"
        echo "    start with Link before we continue"
        echo "    remember that this project uses Link for local agent memory"
        echo "    what does Link remember about this project?"
        echo "    ingest raw/<file> into Link"
    else
        echo "  Drop sources into ~/link/raw/."
        echo "  View wiki: lnk serve"
        echo "  Print starter prompts: lnk next"
        echo "  Try in your agent:"
        echo "    is Link ready?"
        echo "    start with Link before we continue"
        echo "    remember that I prefer local-first agent memory"
        echo "    what does Link know about me?"
        echo "    ingest raw/<file> into Link"
    fi
}

# Prefer Link's own `connect` and `disconnect`. They verify that the chosen
# Python can actually serve link-mcp, edit JSON-with-comments configs without
# deleting comments, create the config file when it does not exist yet, and
# install session hooks for the agents that have them. The inline fallbacks
# below each installer only run when no Link CLI is reachable.
link_cli() {
    local repo_cli="$SCRIPT_DIR/../../link.py"
    if [ -f "$repo_cli" ] && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
        python3 "$repo_cli" "$@"
    elif command -v lnk >/dev/null 2>&1; then
        lnk "$@"
    else
        return 127
    fi
}

# link_connect <agent> <workspace-root> [extra flags...]; sets LINK_CONNECTED=1 on success.
link_connect() {
    local agent="$1"
    local root="$2"
    shift 2
    LINK_CONNECTED=""
    if link_cli connect "$agent" "$root" --write "$@"; then
        LINK_CONNECTED=1
    else
        echo "  · lnk connect was not available or failed; using the built-in registration"
    fi
}
