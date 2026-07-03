#!/bin/bash
# Link integration for Kiro
#
# Fresh install: sets up steering + scaffolds wiki at ~/link/
# Update (re-run after git pull): updates steering + code files, never touches wiki data
#
# Usage:
#   bash install.sh             → global: ~/.kiro/steering + central wiki at ~/link/
#   bash install.sh --project   → project-local: .kiro/steering + wiki in current dir
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODE="${1:---global}"
. "$SCRIPT_DIR/../_shared/instructions.sh"

if [ "$MODE" = "--global" ]; then
    INSTRUCTIONS=$(cat "$SCRIPT_DIR/../_shared/link-instructions.md")
    TARGET="$HOME/.kiro/steering/link.md"
    WIKI_PATH="$HOME/link/wiki"
    mkdir -p "$HOME/.kiro/steering"

    # Always update steering — it may have changed
    echo "$INSTRUCTIONS" > "$TARGET"
    echo "Link steering → $TARGET"

    bash "$SCRIPT_DIR/../_shared/scaffold.sh"

    MCP_PYTHON="python3"
    if [ -f "$HOME/link/.link-mcp-python" ]; then
        MCP_PYTHON="$(cat "$HOME/link/.link-mcp-python")"
    fi

    # Auto-register Link MCP server in Kiro's mcp.json
    MCP_CONFIG="$HOME/.kiro/settings/mcp.json"
    if [ -f "$MCP_CONFIG" ]; then
        LINK_MCP_PYTHON="$MCP_PYTHON" LINK_WIKI_PATH="$WIKI_PATH" python3 - << 'PYEOF'
import json, os
config_path = os.path.expanduser("~/.kiro/settings/mcp.json")
wiki_path = os.environ["LINK_WIKI_PATH"]
mcp_python = os.environ["LINK_MCP_PYTHON"]
try:
    with open(config_path) as f:
        config = json.load(f)
    config.setdefault("mcpServers", {})["link"] = {
        "command": mcp_python,
        "args": ["-m", "link_mcp", "--wiki", wiki_path, "--surface", "slim"],
        "disabled": False
    }
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print("  ✓ Link MCP server registered in ~/.kiro/settings/mcp.json")
except Exception as e:
    print(f"  · Could not auto-register MCP: {e}")
    print(f"    Add manually: {mcp_python} -m link_mcp --wiki {wiki_path} --surface slim")
PYEOF
    fi

    link_print_next_steps "$MODE"

elif [ "$MODE" = "--project" ]; then
    INSTRUCTIONS=$(cat "$SCRIPT_DIR/../_shared/link-instructions-project.md")
    TARGET=".kiro/steering/link.md"
    mkdir -p .kiro/steering

    echo "$INSTRUCTIONS" > "$TARGET"
    echo "Link steering → $TARGET"

    bash "$SCRIPT_DIR/../_shared/scaffold.sh" --project
    link_print_next_steps "$MODE"
else
    echo "Usage: bash install.sh [--project]"
    exit 1
fi
