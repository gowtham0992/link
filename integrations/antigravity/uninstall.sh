#!/bin/bash
# Remove Link from Google Antigravity
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/../_shared/instructions.sh"
# Take Link out of the agent itself: its MCP server entry and session
# hooks. Uninstalling used to remove only the instruction block, so new
# sessions kept trying to start a workspace that was gone.
link_cli disconnect antigravity --write || echo "  · Could not run lnk disconnect; remove the \"link\" MCP entry by hand"

MODE="${1:---global}"

if [ "$MODE" = "--global" ]; then
    TARGET="$HOME/.gemini/GEMINI.md"
else
    TARGET="GEMINI.md"
fi

if [ ! -f "$TARGET" ]; then echo "No $TARGET found"; exit 0; fi

python3 -c "
import re, os
text = open('$TARGET').read()
cleaned = re.sub(r'\n*## Link — (?:Local Agent Memory|Personal Knowledge Wiki)\n.*?(?=\n## |\Z)', '', text, flags=re.DOTALL).rstrip()
if cleaned:
    open('$TARGET', 'w').write(cleaned + '\n')
    print('Link section removed from $TARGET')
else:
    os.remove('$TARGET')
    print('$TARGET was empty after removal — deleted')
"
