#!/bin/bash
# Link integration for GitHub Copilot
# One command: instructions + wiki scaffold + link-mcp install
#
# Usage:
#   bash install.sh             → .github/copilot-instructions.md + central wiki at ~/link/
#   bash install.sh --project   → .github/copilot-instructions.md + wiki in current dir
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODE="${1:---global}"
. "$SCRIPT_DIR/../_shared/instructions.sh"

if [ "$MODE" = "--project" ]; then
    INSTRUCTIONS_FILE="$SCRIPT_DIR/../_shared/link-instructions-project.md"
    WIKI_PATH="$(pwd)/wiki"
else
    INSTRUCTIONS_FILE="$SCRIPT_DIR/../_shared/link-instructions.md"
    WIKI_PATH="$HOME/link/wiki"
fi

TARGET=".github/copilot-instructions.md"

link_upsert_instructions "$TARGET" "$INSTRUCTIONS_FILE" "Link instructions"

if [ "$MODE" = "--project" ]; then
    bash "$SCRIPT_DIR/../_shared/scaffold.sh" --project
else
    bash "$SCRIPT_DIR/../_shared/scaffold.sh"
fi

MCP_PYTHON="python3"
MCP_MARKER="${WIKI_PATH%/wiki}/.link-mcp-python"
if [ -f "$MCP_MARKER" ]; then
    MCP_PYTHON="$(cat "$MCP_MARKER")"
fi

echo ""
echo "  MCP: add to your Copilot MCP config:"
echo "  { \"mcpServers\": { \"link\": { \"command\": \"$MCP_PYTHON\", \"args\": [\"-m\", \"link_mcp\", \"--wiki\", \"$WIKI_PATH\", \"--surface\", \"slim\"] } } }"

link_print_next_steps "$MODE"
