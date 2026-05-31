# Link Integrations

One-step setup for local agents. The default mode creates one central Link wiki
at `~/link/` and teaches your agent how to use it as local personal memory.

## Quick start

```bash
git clone https://github.com/gowtham0992/link.git ~/link-repo
bash ~/link-repo/integrations/codex/install.sh
```

On Windows PowerShell:

```powershell
git clone https://github.com/gowtham0992/link.git $HOME\link-repo
& $HOME\link-repo\integrations\codex\install.ps1
```

Pick the installer that matches your agent. After install, try:

```text
is Link ready?
brief me from Link before we continue
query Link for what you know about this project
```

## All integrations

| Tool | macOS/Linux | Windows PowerShell | Global location |
|------|-------------|--------------------|-----------------|
| Kiro | `bash integrations/kiro/install.sh` | `.\integrations\kiro\install.ps1` | `~/.kiro/steering/link.md` |
| Claude Code | `bash integrations/claude-code/install.sh` | `.\integrations\claude-code\install.ps1` | `~/.claude/CLAUDE.md` |
| Antigravity | `bash integrations/antigravity/install.sh` | `.\integrations\antigravity\install.ps1` | `~/.gemini/GEMINI.md` |
| Codex | `bash integrations/codex/install.sh` | `.\integrations\codex\install.ps1` | `~/AGENTS.md` |
| Cursor | `bash integrations/cursor/install.sh` | `.\integrations\cursor\install.ps1` | `~/.cursor/rules/link.mdc` |
| Copilot | `bash integrations/copilot/install.sh` | `.\integrations\copilot\install.ps1` | `.github/copilot-instructions.md` |
| VS Code | `bash integrations/vscode/install.sh` | `.\integrations\vscode\install.ps1` | `.vscode/settings.json` |

## Two modes

- **Default (global):** `bash install.sh` or `.\install.ps1` — installs tool instructions globally + scaffolds central wiki at `~/link/`. One wiki for everything.

- **Project-local:** `bash install.sh --project` or `.\install.ps1 -Project` — installs instructions in current project + scaffolds wiki here. For team projects that need their own wiki.

## What the install does

1. Upserts a small Link instruction block without overwriting your existing instructions.
2. Scaffolds wiki structure at `~/link/` or the current directory with `--project`.
3. Installs or upgrades `link-mcp`, using `~/.link-mcp-venv` when system Python is externally managed.
4. Writes `.link-mcp-python` so clients can use the Python that actually has `link-mcp`.
5. Adds a short `lnk` command wrapper for global installs, so checks are short: `lnk health`.
6. Prints next prompts and verification commands for your install mode.

The instruction file is intentionally small. It tells the agent to check
`link_status`, use `query_link` for compact context, use `memory_brief` before
personalized/project work, validate after ingest, and read `LINK.md` only when it
needs the full local protocol.

## Uninstall

Each folder has an `uninstall.sh`. Same `--project` flag applies. PowerShell
uninstall scripts are not needed yet because `install.ps1` only writes the same
small instruction/config files listed above; remove those files or delete the
`link` MCP entry from the relevant JSON config if you need to undo it manually.

## Maintainer checklist

Agent integrations are part of the product surface. Treat installer changes like
runtime changes: they affect the first ten minutes, MCP readiness, and whether an
agent knows how to use Link without wasting context.

Before changing an installer:

1. Keep the agent instruction small. It should point the agent to Link tools,
   not paste the whole protocol into every prompt file.
2. Preserve existing user instructions. Upsert Link blocks or config entries;
   never rewrite the whole agent config file.
3. Keep global and project mode behavior explicit. Global mode uses `~/link/`;
   project mode uses the current directory.
4. Keep CLI and MCP independent from the web viewer. `serve.py` is only for the
   local UI. CLI commands and MCP tools must work without the server running.
5. Reuse `.link-mcp-python` when possible. MCP clients should run the Python
   environment that actually has `link-mcp` installed.
6. Avoid outbound install scripts. Do not add `curl | sh`, telemetry, or hidden
   network calls to integration scripts.
7. Update both macOS/Linux and PowerShell installers together when an integration
   behavior changes.
8. Update README/docs examples when a new integration or command path is added.

When adding a new integration:

1. Create `integrations/<agent>/install.sh` and `uninstall.sh`.
2. Create `integrations/<agent>/install.ps1`.
3. Source the shared scaffold and next-step helpers instead of duplicating setup
   logic:

   ```bash
   . "$SCRIPT_DIR/../_shared/scaffold.sh"
   . "$SCRIPT_DIR/../_shared/instructions.sh"
   ```

   ```powershell
   . "$PSScriptRoot\..\_shared\scaffold.ps1"
   . "$PSScriptRoot\..\_shared\instructions.ps1"
   ```

4. Add the integration to this table, `README.md`, `docs/getting-started.html`,
   and `docs/mcp.html`.
5. Add or update tests in `tests/test_installers.py`.
6. Run the installer checks before opening a PR:

   ```bash
   bash -n integrations/*/install.sh integrations/*/uninstall.sh integrations/_shared/*.sh
   python3 -m pytest tests/test_installers.py -q
   python3 scripts/check_release_hygiene.py
   git diff --check
   ```

   On Windows or a machine with PowerShell:

   ```powershell
   pwsh -NoProfile -Command "Get-ChildItem integrations -Recurse -Include *.ps1 | ForEach-Object { [scriptblock]::Create((Get-Content -Raw $_.FullName)) | Out-Null }"
   ```
