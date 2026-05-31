#!/bin/bash
# Scaffold or update the Link wiki structure.
#
# Fresh install: creates everything from scratch.
# Update (wiki already exists): updates code/config files only, never touches wiki data.
#
# Usage:
#   bash scaffold.sh              → ~/link/ (central wiki)
#   bash scaffold.sh --project    → current directory

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LINK_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MODE="${1:---global}"

if [ "$MODE" = "--project" ]; then
    TARGET_DIR="$(pwd)"
else
    TARGET_DIR="$HOME/link"
    mkdir -p "$TARGET_DIR"
fi

shell_quote() {
    printf "'%s'" "$(printf "%s" "$1" | sed "s/'/'\\\\''/g")"
}

install_link_cli_wrapper() {
    if [ "$MODE" = "--project" ] || [ ! -f "$TARGET_DIR/link.py" ]; then
        return
    fi

    LINK_CLI_DIR="${LINK_CLI_DIR:-$HOME/.local/bin}"
    LINK_CLI_BIN="$LINK_CLI_DIR/lnk"
    LEGACY_LINK_CLI_BIN="$LINK_CLI_DIR/link"
    LINK_CLI_MARKER="# Link command wrapper"

    mkdir -p "$LINK_CLI_DIR"

    if [ -e "$LEGACY_LINK_CLI_BIN" ] && grep -q "$LINK_CLI_MARKER" "$LEGACY_LINK_CLI_BIN" 2>/dev/null; then
        rm -f "$LEGACY_LINK_CLI_BIN"
        echo "  Removed old Link wrapper: $LEGACY_LINK_CLI_BIN"
    fi

    if [ -e "$LINK_CLI_BIN" ] && ! grep -q "$LINK_CLI_MARKER" "$LINK_CLI_BIN" 2>/dev/null; then
        echo "  · $LINK_CLI_BIN already exists and is not a Link wrapper; not overwriting."
        echo "    Fallback: cd \"$TARGET_DIR\" && python3 link.py health"
        return
    fi

    TARGET_DIR_Q="$(shell_quote "$TARGET_DIR")"
    LINK_PY_Q="$(shell_quote "$TARGET_DIR/link.py")"
    cat > "$LINK_CLI_BIN" <<EOF
#!/bin/sh
$LINK_CLI_MARKER
cd $TARGET_DIR_Q || exit 1
LINK_CLI_COMMAND=lnk exec python3 $LINK_PY_Q "\$@"
EOF
    chmod +x "$LINK_CLI_BIN"

    echo "  ✓ Link command: $LINK_CLI_BIN"

    RESOLVED_LINK="$(command -v lnk 2>/dev/null || true)"
    if [ "$RESOLVED_LINK" != "$LINK_CLI_BIN" ]; then
        echo "  · Add $LINK_CLI_DIR to the front of PATH to run: lnk health"
    fi
}

# ── Detect: fresh install or update? ─────────────────────────────────
# A wiki exists if wiki/index.md is present (created on first ingest or scaffold)
IS_UPDATE=false
if [ -f "$TARGET_DIR/wiki/index.md" ] || [ -f "$TARGET_DIR/wiki/log.md" ]; then
    IS_UPDATE=true
fi

if [ "$IS_UPDATE" = true ]; then
    echo "  Existing wiki detected at $TARGET_DIR — updating code only, wiki data untouched."
else
    echo "  Fresh install at $TARGET_DIR."
fi

# ── Code files: always update ─────────────────────────────────────────
# These are developer-maintained and should always reflect the latest version.
cp "$LINK_ROOT/serve.py" "$TARGET_DIR/serve.py"
echo "  Updated serve.py"

cp "$LINK_ROOT/LINK.md" "$TARGET_DIR/LINK.md"
echo "  Updated LINK.md"

if [ -f "$LINK_ROOT/link.py" ]; then
    cp "$LINK_ROOT/link.py" "$TARGET_DIR/link.py"
    echo "  Updated link.py"
fi

if [ -d "$LINK_ROOT/mcp_package/link_core" ]; then
    mkdir -p "$TARGET_DIR/link_core"
    cp "$LINK_ROOT/mcp_package/link_core/"*.py "$TARGET_DIR/link_core/"
    echo "  Updated link_core"
fi

if [ -f "$LINK_ROOT/logo.png" ]; then
    cp "$LINK_ROOT/logo.png" "$TARGET_DIR/logo.png"
fi

if [ -f "$LINK_ROOT/logo.svg" ]; then
    cp "$LINK_ROOT/logo.svg" "$TARGET_DIR/logo.svg"
fi

cp "$LINK_ROOT/.linkignore" "$TARGET_DIR/.linkignore"

# ── Wiki structure: only on fresh install ────────────────────────────
# Never overwrite wiki data (index.md, log.md, _backlinks.json, page files).
if [ "$IS_UPDATE" = false ]; then
    for dir in raw wiki/sources wiki/concepts wiki/entities wiki/memories wiki/comparisons wiki/explorations; do
        mkdir -p "$TARGET_DIR/$dir"
        touch "$TARGET_DIR/$dir/.gitkeep"
    done

    python3 "$TARGET_DIR/link.py" doctor --fix "$TARGET_DIR" >/dev/null
    echo "  Wiki structure created at $TARGET_DIR"
else
    # On update: ensure directory structure exists (in case new dirs were added)
    for dir in raw wiki/sources wiki/concepts wiki/entities wiki/memories wiki/comparisons wiki/explorations; do
        mkdir -p "$TARGET_DIR/$dir"
    done
fi

echo "  Wiki ready at $TARGET_DIR"

install_link_cli_wrapper

# ── MCP server: install link-mcp package ─────────────────────────────
echo ""
echo "  Setting up MCP server..."

if [ -d "$LINK_ROOT/mcp_package" ]; then
    echo "  Installing/upgrading link-mcp from local checkout..."
    LINK_MCP_PACKAGE="$LINK_ROOT/mcp_package"
else
    echo "  Installing/upgrading link-mcp from PyPI..."
    LINK_MCP_PACKAGE="link-mcp"
fi

LINK_MCP_PYTHON="python3"
LINK_MCP_VENV="${LINK_MCP_VENV:-$HOME/.link-mcp-venv}"
LINK_MCP_VENV_PYTHON="$LINK_MCP_VENV/bin/python"
LINK_MCP_MARKER="$TARGET_DIR/.link-mcp-python"
LINK_MCP_INSTALLED=false
LINK_MCP_REUSED=false

if python3 -m pip install --upgrade "$LINK_MCP_PACKAGE" -q 2>/dev/null; then
    LINK_MCP_PYTHON="python3"
    LINK_MCP_INSTALLED=true
elif python3 -m venv "$LINK_MCP_VENV" 2>/dev/null \
    && "$LINK_MCP_VENV_PYTHON" -m pip install --upgrade pip -q 2>/dev/null \
    && "$LINK_MCP_VENV_PYTHON" -m pip install --upgrade "$LINK_MCP_PACKAGE" -q 2>/dev/null; then
    LINK_MCP_PYTHON="$LINK_MCP_VENV_PYTHON"
    LINK_MCP_INSTALLED=true
fi

if [ "$LINK_MCP_INSTALLED" = false ] && [ -f "$LINK_MCP_MARKER" ]; then
    LINK_MCP_MARKER_PYTHON="$(cat "$LINK_MCP_MARKER")"
    if [ -n "$LINK_MCP_MARKER_PYTHON" ] && "$LINK_MCP_MARKER_PYTHON" -c "import link_mcp" 2>/dev/null; then
        LINK_MCP_PYTHON="$LINK_MCP_MARKER_PYTHON"
        LINK_MCP_INSTALLED=true
        LINK_MCP_REUSED=true
    fi
elif [ "$LINK_MCP_INSTALLED" = false ] && [ -x "$LINK_MCP_VENV_PYTHON" ] && "$LINK_MCP_VENV_PYTHON" -c "import link_mcp" 2>/dev/null; then
    LINK_MCP_PYTHON="$LINK_MCP_VENV_PYTHON"
    LINK_MCP_INSTALLED=true
    LINK_MCP_REUSED=true
fi

if [ "$LINK_MCP_INSTALLED" = true ] && "$LINK_MCP_PYTHON" -c "import link_mcp" 2>/dev/null; then
    printf '%s\n' "$LINK_MCP_PYTHON" > "$LINK_MCP_MARKER"
    if [ "$LINK_MCP_REUSED" = true ]; then
        echo "  ✓ existing link-mcp available"
    else
        echo "  ✓ link-mcp installed"
    fi
    if [ "$LINK_MCP_PYTHON" != "python3" ]; then
        echo "  ✓ MCP Python: $LINK_MCP_PYTHON"
    fi
    if [ "$LINK_MCP_REUSED" = true ]; then
        echo "  · Automatic upgrade did not complete; run verify-mcp to confirm the installed version."
    fi
    echo ""
    echo "  Add to your MCP client config:"
    echo '  {'
    echo '    "mcpServers": {'
    echo '      "link": {'
    echo "        \"command\": \"$LINK_MCP_PYTHON\","
    echo "        \"args\": [\"-m\", \"link_mcp\", \"--wiki\", \"$TARGET_DIR/wiki\"]"
    echo '      }'
    echo '    }'
    echo '  }'
else
    echo "  · Could not install link-mcp automatically."
    echo "  Manual options:"
    echo "    python3 -m pip install --upgrade link-mcp"
    echo "    python3 -m venv ~/.link-mcp-venv"
    echo "    ~/.link-mcp-venv/bin/python -m pip install --upgrade pip link-mcp"
    echo "  If using the venv, set your MCP command to ~/.link-mcp-venv/bin/python."
fi

if [ -f "$TARGET_DIR/link.py" ]; then
    echo ""
    if [ "$MODE" = "--project" ]; then
        echo "  Check Link readiness:"
        echo "    python3 link.py health"
        echo "  Print starter prompts:"
        echo "    python3 link.py next"
        echo "  Check wiki health:"
        echo "    python3 link.py doctor"
        echo "  Create a local backup:"
        echo "    python3 link.py backup"
        echo "  Validate ingest output:"
        echo "    python3 link.py validate"
        echo "  Verify MCP setup:"
        echo "    python3 link.py verify-mcp"
        echo "  Repair stale graph index:"
        echo "    python3 link.py rebuild-backlinks"
    else
        echo "  Check Link readiness:"
        echo "    lnk health"
        echo "  Print starter prompts:"
        echo "    lnk next"
        echo "  Check wiki health:"
        echo "    lnk doctor"
        echo "  Create a local backup:"
        echo "    lnk backup"
        echo "  Validate ingest output:"
        echo "    lnk validate"
        echo "  Verify MCP setup:"
        echo "    lnk verify-mcp"
        echo "  Repair stale graph index:"
        echo "    lnk rebuild-backlinks"
    fi
fi
