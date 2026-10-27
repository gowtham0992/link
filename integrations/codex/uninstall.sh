#!/bin/bash
# Remove Link from Codex
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/../_shared/instructions.sh"
# Take Link out of the agent itself: its MCP server entry and session
# hooks. Uninstalling used to remove only the instruction block, so new
# sessions kept trying to start a workspace that was gone.
link_cli disconnect codex --write || echo "  · Could not run lnk disconnect; remove the \"link\" MCP entry by hand"

MODE="${1:---global}"

if [ "$MODE" = "--global" ]; then
    TARGET="${CODEX_HOME:-$HOME/.codex}/AGENTS.md"
else
    TARGET="AGENTS.md"
fi

link_remove_instructions "$TARGET"

# Link once put Codex's section in ~/AGENTS.md, which Codex never read.
# Claude Code does read that file, so the old copy is only removed when
# Claude Code has Link's instructions of its own (or is not installed).
if [ "$MODE" = "--global" ] && [ -f "$HOME/AGENTS.md" ]; then
    if [ ! -d "$HOME/.claude" ] || grep -q "^## Link — " "$HOME/.claude/CLAUDE.md" 2>/dev/null; then
        link_remove_instructions "$HOME/AGENTS.md"
    elif grep -q "^## Link — " "$HOME/AGENTS.md"; then
        echo "  · Kept Link's section in ~/AGENTS.md: Claude Code reads it there"
    fi
fi
