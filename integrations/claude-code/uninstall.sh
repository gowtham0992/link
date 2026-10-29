#!/bin/bash
# Remove Link from Claude Code
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/../_shared/instructions.sh"

MODE="${1:---global}"

# Take Link out of the agent itself: its MCP server entry and session
# hooks. Uninstalling used to remove only the instruction block, so new
# sessions kept trying to start a workspace that was gone. Both are the
# agent's global config, so a --project uninstall leaves them alone.
if [ "$MODE" = "--global" ]; then
    link_cli disconnect claude-code --write || echo "  · Could not run lnk disconnect; remove the \"link\" MCP entry by hand"
fi

if [ "$MODE" = "--global" ]; then
    TARGET="$HOME/.claude/CLAUDE.md"
else
    TARGET="CLAUDE.md"
fi

link_remove_instructions "$TARGET"
