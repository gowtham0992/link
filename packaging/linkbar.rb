# LinkBar cask template - mirror of the live tap cask with placeholders.
# At release: fill version, the sha256 from `bundle.sh --release-zip`, and
# the Link release tag in the url (three lines change, always three).
# Source of truth is the live tap: gowtham0992/homebrew-link:Casks/linkbar.rb
cask "linkbar" do
  version "REPLACE_WITH_LINKBAR_VERSION"
  sha256 "REPLACE_WITH_ZIP_SHA256"

  url "https://github.com/gowtham0992/link/releases/download/vREPLACE_WITH_LINK_VERSION/LinkBar-#{version}.zip"
  name "LinkBar"
  desc "Link's agent memory, ambient in the menu bar"
  homepage "https://github.com/gowtham0992/link"

  depends_on formula: "gowtham0992/link/link"
  depends_on macos: :sonoma

  app "LinkBar.app"

  # LinkBar ships unsigned (open source, no Apple Developer certificate).
  # Homebrew quarantines staged apps by default, which would block first
  # launch of an unsigned bundle; clearing the flag here restores the normal
  # double-click experience. Verified on macOS 15 and 26.
  postflight do
    system_command "/usr/bin/xattr",
                   args: ["-dr", "com.apple.quarantine", "#{appdir}/LinkBar.app"]
  end

  zap trash: []
end
