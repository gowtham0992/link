#!/bin/bash
# Remove Link from Kiro
#
# Usage:
#   bash uninstall.sh             → removes global ~/.kiro/steering/link.md
#   bash uninstall.sh --project   → removes project .kiro/steering/link.md
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/../_shared/instructions.sh"
# Take Link out of the agent itself: its MCP server entry and session
# hooks. Uninstalling used to remove only the instruction block, so new
# sessions kept trying to start a workspace that was gone.
link_cli disconnect kiro --write || echo "  · Could not run lnk disconnect; remove the \"link\" MCP entry by hand"

MODE="${1:---global}"

if [ "$MODE" = "--global" ]; then
    TARGET="$HOME/.kiro/steering/link.md"
else
    TARGET=".kiro/steering/link.md"
fi

if [ -f "$TARGET" ]; then
    rm "$TARGET"
    echo "Removed $TARGET"
else
    echo "No Link steering found at $TARGET"
fi
