#!/bin/bash
# Link integration for Claude Code
# One command: steering + wiki scaffold + MCP registration
#
# Usage:
#   bash install.sh             → global: ~/.claude/CLAUDE.md + central wiki at ~/link/
#   bash install.sh --project   → project-local: ./CLAUDE.md + wiki in current dir
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODE="${1:---global}"
. "$SCRIPT_DIR/../_shared/instructions.sh"

if [ "$MODE" = "--global" ]; then
    INSTRUCTIONS_FILE="$SCRIPT_DIR/../_shared/link-instructions.md"
    TARGET="$HOME/.claude/CLAUDE.md"
    WIKI_PATH="$HOME/link/wiki"
elif [ "$MODE" = "--project" ]; then
    INSTRUCTIONS_FILE="$SCRIPT_DIR/../_shared/link-instructions-project.md"
    TARGET="CLAUDE.md"
    WIKI_PATH="$(pwd)/wiki"
else
    echo "Usage: bash install.sh [--project]"
    exit 1
fi

# Steering
link_upsert_instructions "$TARGET" "$INSTRUCTIONS_FILE" "Link steering"

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

# Auto-register MCP server in Claude Code's config
# Claude Code uses ~/.claude.json for global MCP config
MCP_CONFIG="$HOME/.claude.json"
if [ -f "$MCP_CONFIG" ]; then
    LINK_WIKI_PATH="$WIKI_PATH" LINK_MCP_PYTHON="$MCP_PYTHON" python3 - << 'PYEOF'
import json, os
config_path = os.path.expanduser("~/.claude.json")
wiki_path = os.environ["LINK_WIKI_PATH"]
mcp_python = os.environ["LINK_MCP_PYTHON"]
try:
    with open(config_path) as f:
        config = json.load(f)
    config.setdefault("mcpServers", {})["link"] = {
        "command": mcp_python,
        "args": ["-m", "link_mcp", "--wiki", wiki_path, "--surface", "slim"]
    }
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print("  ✓ Link MCP registered in ~/.claude.json")
except Exception as e:
    print(f"  · Could not auto-register MCP: {e}")
PYEOF
else
    echo ""
    echo "  MCP config: add to ~/.claude.json or .mcp.json at project root:"
    echo "  { \"mcpServers\": { \"link\": { \"command\": \"$MCP_PYTHON\", \"args\": [\"-m\", \"link_mcp\", \"--wiki\", \"$WIKI_PATH\", \"--surface\", \"slim\"] } } }"
fi

link_print_next_steps "$MODE"
