# Releasing LinkBar

The full, current release procedure lives as a Link procedure memory
(`lnk recall "cutting a Link release"`) and is exercised every release.
This file keeps only the LinkBar-specific mechanics:

1. Bump the version in `apps/LinkBar/Sources/LinkBar/DesignSystem.swift`
   (`static let version`) and in `apps/LinkBar/Scripts/bundle.sh`
   (both `CFBundleShortVersionString` and `CFBundleVersion`).
2. Build the distributable zip:

   ```
   bash apps/LinkBar/Scripts/bundle.sh --release-zip
   ```

   It prints the zip path and its sha256.
3. Attach the zip to the GitHub release for the Link tag. The release
   with the zip must exist before the tap push, because the cask
   downloads from it.
4. Update the tap cask (`gowtham0992/homebrew-link:Casks/linkbar.rb`):
   version, sha256, and the release tag inside the url. Three lines
   change, always three - check `git diff` before pushing.
5. The cask clears macOS quarantine in a postflight because the app is
   ad-hoc signed. If LinkBar is ever notarized, remove that postflight.

Template: `packaging/linkbar.rb` (placeholders, mirrors the live cask).
