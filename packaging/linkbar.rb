# LinkBar cask — copy into gowtham0992/homebrew-link:Casks/linkbar.rb at
# release time, filling in the sha256 printed by `bundle.sh --release-zip`.
cask "linkbar" do
  version "1.0.0"
  sha256 "REPLACE_WITH_ZIP_SHA256"

  url "https://github.com/gowtham0992/link/releases/download/v2.0.0/LinkBar-#{version}.zip"
  name "LinkBar"
  desc "Link's agent memory, ambient in the menu bar"
  homepage "https://github.com/gowtham0992/link"

  depends_on formula: "gowtham0992/link/link"
  depends_on macos: ">= :sonoma"

  app "LinkBar.app"

  # LinkBar ships unsigned (open source, no Apple Developer certificate).
  # Homebrew quarantines staged apps by default, which would block first
  # launch of an unsigned bundle; stripping the flag here restores the
  # normal double-click experience. Verified on macOS 15 and 26.
  postflight do
    system_command "/usr/bin/xattr",
                   args: ["-dr", "com.apple.quarantine", "#{appdir}/LinkBar.app"]
  end

  zap trash: []
end
