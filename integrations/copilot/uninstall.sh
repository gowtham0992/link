#!/bin/bash
# Remove Link from Copilot
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/../_shared/instructions.sh"

MODE="${1:---global}"

# Take Link out of the agent itself: the project's MCP entry
# (.vscode/mcp.json) and, in global mode only, the session hooks in
# ~/.copilot, which every project shares.
HOOKS_FLAG=""
if [ "$MODE" != "--global" ]; then HOOKS_FLAG="--no-hooks"; fi
link_cli disconnect copilot --write $HOOKS_FLAG || echo "  · lnk disconnect did not finish; remove the \"link\" MCP entry and Link's hooks it names by hand"

TARGET=".github/copilot-instructions.md"
link_remove_instructions "$TARGET"
