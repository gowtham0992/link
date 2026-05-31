# Homebrew Tap Packaging

This directory contains the tap-ready Formula for Link. Publish it in a
separate repository named `homebrew-link` so users can install Link with:

```bash
brew tap gowtham0992/link
brew install link
```

The Formula installs Link's CLI and local web runtime. It does not bundle the
MCP SDK; MCP clients should keep using the existing `link-mcp` PyPI package or
the agent installers, which create the managed `~/.link-mcp-venv`.

## Publish The Tap

Create the tap repository once:

```bash
brew tap-new gowtham0992/link
```

Copy the Formula into the tap:

```bash
cp packaging/homebrew/Formula/link.rb "$(brew --repo gowtham0992/link)/Formula/link.rb"
```

Validate locally:

```bash
brew audit --strict --online gowtham0992/link/link
brew install --build-from-source gowtham0992/link/link
brew test gowtham0992/link/link
lnk --version
lnk demo
```

Then push the tap repo:

```bash
cd "$(brew --repo gowtham0992/link)"
git status --short
git add Formula/link.rb
git commit -m "Add Link formula"
git push origin main
```

## Update For A New Release

1. Tag the Link repo release.
2. Update `tag` and `revision` in `Formula/link.rb`.
3. Copy the Formula into the tap repo.
4. Run `brew audit`, `brew install --build-from-source`, and `brew test`.
5. Push the tap repo.
