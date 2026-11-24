#!/bin/bash
# Remove Link from Google Antigravity
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/../_shared/instructions.sh"

MODE="${1:---global}"

# Take Link out of the agent itself: its MCP server entry and session
# hooks. Uninstalling used to remove only the instruction block, so new
# sessions kept trying to start a workspace that was gone. Both are the
# agent's global config, so a --project uninstall leaves them alone.
if [ "$MODE" = "--global" ]; then
    link_cli disconnect antigravity --write || echo "  · lnk disconnect did not finish; remove the \"link\" MCP entry and Link's hooks it names by hand"
fi

if [ "$MODE" = "--global" ]; then
    TARGET="$HOME/.gemini/GEMINI.md"
else
    TARGET="GEMINI.md"
fi

link_remove_instructions "$TARGET"
