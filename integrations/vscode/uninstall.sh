#!/bin/bash
# Remove Link instructions from VS Code settings (preserves other instructions)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/../_shared/instructions.sh"
# Take Link out of the agent itself: its MCP server entry and session
# hooks. Uninstalling used to remove only the instruction block, so new
# sessions kept trying to start a workspace that was gone.
link_cli disconnect vscode --write || echo "  · Could not run lnk disconnect; remove the \"link\" MCP entry by hand"

TARGET=".vscode/settings.json"
if [ ! -f "$TARGET" ]; then echo "No $TARGET found"; exit 0; fi

python3 -c "
import json
settings = json.load(open('$TARGET'))
instructions = settings.get('github.copilot.chat.codeGeneration.instructions', [])
filtered = [
    i for i in instructions
    if '## Link — Local Agent Memory' not in i.get('text', '')
    and '## Link — Personal Knowledge Wiki' not in i.get('text', '')
    and 'Link, an LLM-maintained knowledge wiki' not in i.get('text', '')
]
if len(filtered) < len(instructions):
    if filtered:
        settings['github.copilot.chat.codeGeneration.instructions'] = filtered
    else:
        del settings['github.copilot.chat.codeGeneration.instructions']
    json.dump(settings, open('$TARGET', 'w'), indent=2)
    print('Link instructions removed from $TARGET')
else:
    print('No Link instructions found in $TARGET')
"
