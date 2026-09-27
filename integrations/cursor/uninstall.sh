#!/bin/bash
# Remove Link from Cursor
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/../_shared/instructions.sh"
# Take Link out of the agent itself: its MCP server entry and session
# hooks. Uninstalling used to remove only the instruction block, so new
# sessions kept trying to start a workspace that was gone.
link_cli disconnect cursor --write || echo "  · Could not run lnk disconnect; remove the \"link\" MCP entry by hand"

MODE="${1:---global}"

if [ "$MODE" = "--global" ]; then
    TARGET="$HOME/.cursor/rules/link.mdc"
else
    TARGET=".cursor/rules/link.mdc"
fi

if [ -f "$TARGET" ]; then
    rm "$TARGET"
    echo "Removed $TARGET"
else
    echo "No Link Cursor rule found at $TARGET"
fi
