# LinkBar

The review gate in your menu bar. Link's promise is that nothing becomes
durable memory without your approval; LinkBar makes approving ambient
instead of a chore.

- Badge: pending-review count · Popover: the review inbox with one-click
  approve (mark reviewed) and archive
- Quick recall ("What do I know about…") with honest abstention — when the
  memory has nothing reliable, it says so
- Status dashboard: every Link surface's health, including memories that
  name files your repository no longer has (`lnk stale`, Link 3.0+)
- Backend: the `lnk` CLI's `--json` output. No server, no sockets, no new
  API surface. Workspace: chosen in Settings, or `LINK_WORKSPACE` for a
  launch, defaulting to `~/link`.

## Build & run

```
cd apps/LinkBar
swift build                 # debug binary
./Scripts/bundle.sh         # release .app bundle at .build/LinkBar.app
open .build/LinkBar.app
```

Requires macOS 14+, Swift 5.10+, and Link installed (`brew install
gowtham0992/link/link`). Ships with each Link release as the `linkbar`
cask; `Scripts/bundle.sh --release-zip` produces the artifact.

Snapshot harness (no menu-bar clicks needed): `LINKBAR_SNAPSHOT=/path.png`
renders the popover and exits; `LINKBAR_TAB=inbox|memory|status|settings`,
`LINKBAR_APPEARANCE=light|dark`, `LINKBAR_PALETTE=1`, `LINKBAR_STALE_REPO=<repo>`
and `LINK_CLI=<launcher>` shape what it renders.
