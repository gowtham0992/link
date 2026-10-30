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

# Copilot's MCP entry is per project (.vscode/mcp.json); its hooks are
# global (~/.copilot/hooks/link.json), so only a global install adds them.
LINK_CONNECTED=""
if [ "$MODE" = "--project" ]; then
    link_connect copilot "${WIKI_PATH%/wiki}"
else
    link_connect copilot "${WIKI_PATH%/wiki}" --hooks-only
    if [ "$LINK_CONNECTED" = 1 ]; then LINK_CONNECTED=""; fi  # the MCP entry is still each project's
fi
# Built-in registration, used only when lnk connect is unavailable.
if [ -z "$LINK_CONNECTED" ]; then
MCP_PYTHON="python3"
MCP_MARKER="${WIKI_PATH%/wiki}/.link-mcp-python"
if [ -f "$MCP_MARKER" ]; then
    MCP_PYTHON="$(cat "$MCP_MARKER")"
fi

echo ""
echo "  MCP: in each project run lnk connect copilot --write, or add to its .vscode/mcp.json:"
echo "  { \"mcpServers\": { \"link\": { \"command\": \"$MCP_PYTHON\", \"args\": [\"-m\", \"link_mcp\", \"--wiki\", \"$WIKI_PATH\", \"--surface\", \"slim\"] } } }"

fi

link_print_next_steps "$MODE"
