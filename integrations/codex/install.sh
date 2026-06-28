#!/bin/bash
# Link integration for Codex / OpenCode
# One command: AGENTS.md + wiki scaffold + link-mcp install
#
# Usage:
#   bash install.sh             → global: ~/AGENTS.md + central wiki at ~/link/
#   bash install.sh --project   → project-local: ./AGENTS.md + wiki in current dir
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODE="${1:---global}"
. "$SCRIPT_DIR/../_shared/instructions.sh"

if [ "$MODE" = "--global" ]; then
    INSTRUCTIONS_FILE="$SCRIPT_DIR/../_shared/link-instructions.md"
    TARGET="$HOME/AGENTS.md"
    WIKI_PATH="$HOME/link/wiki"
elif [ "$MODE" = "--project" ]; then
    INSTRUCTIONS_FILE="$SCRIPT_DIR/../_shared/link-instructions-project.md"
    TARGET="AGENTS.md"
    WIKI_PATH="$(pwd)/wiki"
else
    echo "Usage: bash install.sh [--project]"
    exit 1
fi

# Instructions
link_upsert_instructions "$TARGET" "$INSTRUCTIONS_FILE" "Link instructions"

# Wiki scaffold + link-mcp install
if [ "$MODE" = "--global" ]; then
    bash "$SCRIPT_DIR/../_shared/scaffold.sh"
else
    bash "$SCRIPT_DIR/../_shared/scaffold.sh" --project
fi

MCP_PYTHON="python3"
MCP_MARKER="${WIKI_PATH%/wiki}/.link-mcp-python"
if [ -f "$MCP_MARKER" ]; then
    MCP_PYTHON="$(cat "$MCP_MARKER")"
fi

# Auto-register MCP in ~/.codex/config.toml
CODEX_CONFIG="$HOME/.codex/config.toml"
if [ -f "$CODEX_CONFIG" ]; then
    LINK_CODEX_CONFIG="$CODEX_CONFIG" LINK_MCP_PYTHON="$MCP_PYTHON" LINK_WIKI_PATH="$WIKI_PATH" python3 - << 'PYEOF'
import json, os, re
from pathlib import Path

path = Path(os.environ["LINK_CODEX_CONFIG"])
mcp_python = os.environ["LINK_MCP_PYTHON"]
wiki_path = os.environ["LINK_WIKI_PATH"]
block = (
    "[mcp_servers.link]\n"
    f"command = {json.dumps(mcp_python)}\n"
    f"args = [\"-m\", \"link_mcp\", \"--wiki\", {json.dumps(wiki_path)}, \"--surface\", \"slim\"]\n"
)
text = path.read_text(encoding="utf-8", errors="replace")
pattern = re.compile(r"(?ms)^\[mcp_servers\.link\]\n.*?(?=^\[|\Z)")
if pattern.search(text):
    text = pattern.sub(block, text)
    if not text.endswith("\n"):
        text += "\n"
else:
    text = text.rstrip() + "\n\n" + block
path.write_text(text, encoding="utf-8")
PYEOF
    echo "  ✓ Link MCP registered in ~/.codex/config.toml"
elif [ ! -f "$CODEX_CONFIG" ]; then
    echo "  MCP config: add to ~/.codex/config.toml:"
    echo "  [mcp_servers.link]"
    echo "  command = \"$MCP_PYTHON\""
    echo "  args = [\"-m\", \"link_mcp\", \"--wiki\", \"$WIKI_PATH\", \"--surface\", \"slim\"]"
fi

link_print_next_steps "$MODE"
