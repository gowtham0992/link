# LinkBar

The review gate in your menu bar. Link's promise is that nothing becomes
durable memory without your approval; LinkBar makes approving ambient
instead of a chore.

- Badge: pending-review count · Popover: the review inbox with one-click
  approve (mark reviewed) and archive
- Quick recall ("What do I know about…") with honest abstention — when the
  memory has nothing reliable, it says so
- Backend: the `lnk` CLI's `--json` output. No server, no sockets, no new
  API surface. Workspace: `LINK_WORKSPACE` or `~/link`.

## Build & run

```
cd apps/LinkBar
swift build                 # debug binary
./Scripts/bundle.sh         # release .app bundle at .build/LinkBar.app
open .build/LinkBar.app
```

Requires macOS 14+, Swift 5.10+, and Link installed (`brew install
gowtham0992/link/link`). Status: early preview on the feature/menubar
branch — not yet part of a release.
