#!/bin/bash
# Link integration for VS Code (Copilot Chat)
# One command: settings.json + wiki scaffold + link-mcp install
#
# Usage:
#   bash install.sh             → .vscode/settings.json + central wiki at ~/link/
#   bash install.sh --project   → .vscode/settings.json + wiki in current dir
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODE="${1:---global}"
. "$SCRIPT_DIR/../_shared/instructions.sh"
TARGET=".vscode/settings.json"
mkdir -p .vscode

if [ "$MODE" = "--project" ]; then
    INSTRUCTIONS_FILE="$SCRIPT_DIR/../_shared/link-instructions-project.md"
    WIKI_PATH="$(pwd)/wiki"
else
    INSTRUCTIONS_FILE="$SCRIPT_DIR/../_shared/link-instructions.md"
    WIKI_PATH="$HOME/link/wiki"
fi

# Write to .vscode/settings.json
LINK_INSTRUCTIONS_FILE="$INSTRUCTIONS_FILE" python3 - << 'PYEOF'
import json, os
target = ".vscode/settings.json"
instructions_text = open(os.environ["LINK_INSTRUCTIONS_FILE"], encoding="utf-8").read()
settings = {}
if os.path.exists(target):
    try:
        with open(target) as f:
            settings = json.load(f)
    except Exception:
        pass
key = 'github.copilot.chat.codeGeneration.instructions'
instructions = settings.get(key, [])
if not isinstance(instructions, list):
    instructions = []
instructions = [
    i for i in instructions
    if '## Link — Local Agent Memory' not in i.get('text', '')
    and '## Link — Personal Knowledge Wiki' not in i.get('text', '')
    and 'Link, an LLM-maintained knowledge wiki' not in i.get('text', '')
]
instructions.append({'text': instructions_text})
settings[key] = instructions
with open(target, 'w') as f:
    json.dump(settings, f, indent=2)
print(f"Link instructions → {target}")
PYEOF

if [ "$MODE" = "--project" ]; then
    bash "$SCRIPT_DIR/../_shared/scaffold.sh" --project
else
    bash "$SCRIPT_DIR/../_shared/scaffold.sh"
fi

MCP_PYTHON="python3"
MCP_MARKER="${WIKI_PATH%/wiki}/.link-mcp-python"
if [ -f "$MCP_MARKER" ]; then
    MCP_PYTHON="$(cat "$MCP_MARKER")"
fi

echo ""
echo "  MCP: add to .vscode/mcp.json:"
echo "  { \"servers\": { \"link\": { \"type\": \"stdio\", \"command\": \"$MCP_PYTHON\", \"args\": [\"-m\", \"link_mcp\", \"--wiki\", \"$WIKI_PATH\", \"--surface\", \"slim\"] } } }"

link_print_next_steps "$MODE"
