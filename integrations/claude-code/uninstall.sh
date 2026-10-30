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
    link_cli disconnect claude-code --write || echo "  · lnk disconnect did not finish; remove the \"link\" MCP entry and Link's hooks it names by hand"
fi

if [ "$MODE" = "--global" ]; then
    TARGET="$HOME/.claude/CLAUDE.md"
else
    TARGET="CLAUDE.md"
fi

link_remove_instructions "$TARGET"

# Older Link put Codex's section in ~/AGENTS.md, which only Claude Code
# reads (Codex never does): with Claude Code uninstalled nothing needs it.
if [ "$MODE" = "--global" ] && [ -f "$HOME/AGENTS.md" ] && grep -q "^## Link — " "$HOME/AGENTS.md"; then
    link_remove_instructions "$HOME/AGENTS.md"
fi
