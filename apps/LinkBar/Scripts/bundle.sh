#!/bin/sh
# Wrap the SPM executable in a minimal .app bundle (menu-bar agent app).
set -e
cd "$(dirname "$0")/.."
swift build -c release
APP=.build/LinkBar.app
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp .build/release/LinkBar "$APP/Contents/MacOS/LinkBar"
cp Sources/LinkBar/Resources/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"
cp -R .build/release/LinkBar_LinkBar.bundle "$APP/Contents/Resources/" 2>/dev/null || true
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key><string>io.github.gowtham0992.linkbar</string>
    <key>CFBundleName</key><string>LinkBar</string>
    <key>CFBundleDisplayName</key><string>LinkBar</string>
    <key>CFBundleExecutable</key><string>LinkBar</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>1.0.0</string>
    <key>LSMinimumSystemVersion</key><string>14.0</string>
    <key>LSUIElement</key><true/>
    <key>CFBundleIconFile</key><string>AppIcon</string>
</dict>
</plist>
PLIST
codesign --force --sign - "$APP" 2>/dev/null || true
echo "bundled: $APP"

# --release-zip: produce the distributable zip the cask points at.
if [ "$1" = "--release-zip" ]; then
  VERSION=$(grep -o 'static let version = "[^"]*"' Sources/LinkBar/DesignSystem.swift | grep -o '"[^"]*"' | tr -d '"')
  ZIP=".build/LinkBar-${VERSION}.0.zip"
  rm -f "$ZIP"
  ditto -c -k --keepParent "$APP" "$ZIP"
  shasum -a 256 "$ZIP"
  echo "release zip: $ZIP  (attach to the GitHub release; put the sha256 in the cask)"
  exit 0
fi

# --install: replace /Applications/LinkBar.app with this build and relaunch.
if [ "$1" = "--install" ]; then
  pkill -x LinkBar 2>/dev/null || true
  sleep 1
  rm -rf /Applications/LinkBar.app
  cp -R "$APP" /Applications/LinkBar.app
  open /Applications/LinkBar.app
  echo "installed: /Applications/LinkBar.app (running)"
fi
