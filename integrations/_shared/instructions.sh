#!/bin/bash
# Helpers for safely installing Link instruction blocks into existing files.

link_upsert_instructions() {
    local target="$1"
    local source_file="$2"
    local label="$3"

    mkdir -p "$(dirname "$target")"
    LINK_TARGET="$target" LINK_SOURCE="$source_file" python3 - <<'PYEOF'
import os
import re
from pathlib import Path

target = Path(os.environ["LINK_TARGET"]).expanduser()
source = Path(os.environ["LINK_SOURCE"]).read_text(encoding="utf-8").rstrip()
headers = ["## Link — Local Agent Memory", "## Link — Personal Knowledge Wiki"]

existing = ""
if target.exists():
    existing = target.read_text(encoding="utf-8", errors="replace")

header_pattern = "|".join(re.escape(header) for header in headers)
pattern = re.compile(rf"(^|\n)(?:{header_pattern})\n.*?(?=\n## |\Z)", re.DOTALL)
match = pattern.search(existing)
if match:
    prefix = "\n" if match.group(1) else ""
    updated = pattern.sub(prefix + source, existing).rstrip() + "\n"
else:
    separator = "\n\n" if existing.strip() else ""
    updated = existing.rstrip() + separator + source + "\n"

target.write_text(updated, encoding="utf-8")
PYEOF
    echo "$label → $target"
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
