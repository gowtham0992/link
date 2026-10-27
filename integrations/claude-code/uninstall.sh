#!/bin/bash
# Remove Link from Claude Code
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/../_shared/instructions.sh"
# Take Link out of the agent itself: its MCP server entry and session
# hooks. Uninstalling used to remove only the instruction block, so new
# sessions kept trying to start a workspace that was gone.
link_cli disconnect claude-code --write || echo "  · Could not run lnk disconnect; remove the \"link\" MCP entry by hand"

MODE="${1:---global}"

if [ "$MODE" = "--global" ]; then
    TARGET="$HOME/.claude/CLAUDE.md"
else
    TARGET="CLAUDE.md"
fi

link_remove_instructions "$TARGET"
