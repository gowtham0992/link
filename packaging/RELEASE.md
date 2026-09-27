# Releasing Link

The whole procedure, in the order that works. `scripts/prepare_release.py`
does the local file changes and prints the exact commands below with the
version filled in; this page explains them and the traps each step avoids.

Nothing here runs from CI: a release is a person's decision, and several
steps need that person's credentials (PyPI token, GitHub login for the MCP
registry, push access to the tap).

## 0. Before you start

- `develop` holds everything for the release, and its CI is green on the
  exact commit you are releasing (`gh run list --branch develop -L 1`).
- `main` is protected: it only accepts pull requests. The version bump
  therefore travels on `develop` like any other change.
- A release venv exists for build and upload. Homebrew's Python refuses
  `pip install twine` (PEP 668), so do not use it:

  ```bash
  python3 -m venv ~/.link-release-venv && ~/.link-release-venv/bin/pip install -U build twine
  ```

## 1. Prepare the files (on develop)

```bash
python3 scripts/prepare_release.py X.Y.Z --banner "three highlights of this release"
```

It bumps `pyproject.toml`, `link_mcp/__init__.py`, `link_core/version.py`
and `server.json`, dates the `Unreleased` changelog section, and stamps the
homepage banner. The banner words are required: 3.0.0 shipped announcing
itself with 2.2's features because this used to be a warning. Use
`--keep-banner` only if `docs/index.html` already says the right thing.

If `apps/LinkBar` changed since the last tag, the script refuses to run
until you pass `--linkbar-version A.B.C` (it bumps `DesignSystem.swift` and
both plist keys in `bundle.sh`), so a changed app never ships under an old
version number.

Review the diff, then commit and push to `develop`.

## 2. Merge to main and tag

```bash
gh pr create --base main --head develop --title "Release Link vX.Y.Z"
```

Wait for CI on the PR, merge it with a merge commit (not a squash: it keeps
contributors' authorship), then tag the merge commit:

```bash
git switch main && git pull --ff-only origin main
git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z
```

The tag push runs CI again, so the release tag has its own CI record.

## 3. PyPI

```bash
cd mcp_package
python3 -c "import shutil; shutil.rmtree('dist', ignore_errors=True)"
~/.link-release-venv/bin/python -m build
~/.link-release-venv/bin/twine check dist/*
TWINE_USERNAME=__token__ ~/.link-release-venv/bin/twine upload dist/link_mcp-X.Y.Z*
```

Check: `curl -s https://pypi.org/pypi/link-mcp/json` reports X.Y.Z.

## 4. GitHub release (and the LinkBar zip)

```bash
bash apps/LinkBar/Scripts/bundle.sh --release-zip     # prints the zip's sha256
gh release create vX.Y.Z apps/LinkBar/.build/LinkBar-A.B.C.zip --title "Link X.Y.Z" --notes-file notes.md --latest
```

Release notes are the changelog section plus the install lines. The release
must exist before the tap push, because the cask downloads the zip from it.
Check the downloaded asset's sha256 matches what `bundle.sh` printed.

## 5. Homebrew tap

In `gowtham0992/homebrew-link`:

- `Formula/link.rb`: two lines - the tag in the `url`, and the `sha256` of
  `https://github.com/gowtham0992/link/archive/refs/tags/vX.Y.Z.tar.gz`.
- `Casks/linkbar.rb` (only when LinkBar changed): three lines - `version`,
  `sha256` of the zip, and `download/vX.Y.Z/` in the `url`.

`git diff` before pushing: two lines, or five. The tap's own CI runs
`brew test-bot`; Homebrew deprecations land there first (3.0 hit the
`postflight` → `postflight_steps` change), so check it after pushing.

Verify the real install path: `brew update && brew upgrade gowtham0992/link/link`
and `lnk --version`; `brew reinstall --cask gowtham0992/link/linkbar` and the
app's version.

## 6. MCP registry

```bash
cd mcp_package && mcp-publisher validate && mcp-publisher login github && mcp-publisher publish
```

Check the registry lists X.Y.Z as `isLatest`.

## 7. Back-merge

`develop` is one merge commit behind `main`; fast-forward it:

```bash
git switch develop && git merge --ff-only origin/main && git push origin develop
```
