# Link "memory that stays true" demo — conflict → supersede with lineage →
# current truth + as-of time travel. The 1.7 sibling of link-aha.tape.
#
# Runs the repo's development runtime (brew lnk may predate --supersedes).
# One-time render (needs vhs; `brew install vhs`):
#   cd docs/media && vhs link-truth.tape

Output ../assets/link-truth.gif

Require lnk

Set Shell bash
Set FontSize 20
Set Width 1280
Set Height 560
Set Padding 44
Set Theme { "background": "#221c12", "foreground": "#f3ece0", "cursor": "#e0955f", "black": "#221c12", "green": "#86c79a", "brightBlack": "#8a8174", "white": "#f3ece0", "blue": "#e0955f", "brightBlue": "#e0955f", "cyan": "#d9b48c", "brightCyan": "#d9b48c", "yellow": "#e0b34f", "brightYellow": "#e0b34f" }

# ── prep off-screen: workspace with a backdated deploy decision ──
Hide
Type "O=$PWD; L=$O/.truth-demo; rm -rf $L; mkdir -p $L; cd $L" Enter
Type `lnk() { python3 $O/../../link.py "$@"; }` Enter
Type "lnk init . >/dev/null 2>&1" Enter
Type "lnk remember 'we deploy from main every Friday' . --type decision >/dev/null 2>&1" Enter
Type `sed -i '' 's/^date_captured: .*/date_captured: "2026-04-02T09:00:00Z"/' wiki/memories/we-deploy-from-main-every-friday.md` Enter
Type "clear" Enter
Show

# ── act 1: the facts change; Link refuses to hold two truths ──
Sleep 900ms
Type@70ms "lnk remember 'no longer Fridays - deploys ship Tuesdays' . --type decision"
Sleep 500ms
Enter
Sleep 3200ms
Hide
Type "clear" Enter
Show
Type@70ms "lnk remember 'no longer Fridays - deploys ship Tuesdays' . --type decision --supersedes we-deploy-from-main-every-friday"
Sleep 500ms
Enter
Sleep 2800ms
Hide
Type "clear" Enter
Show

# ── act 2: only the current truth; the past still answerable ──
Type@70ms "lnk recall 'when do we deploy' ."
Sleep 500ms
Enter
Sleep 2600ms
Type@70ms "lnk recall 'when do we deploy' . --as-of 2026-05-01"
Sleep 500ms
Enter
Sleep 3200ms
Type@70ms "# the facts changed - the old truth is archived, not erased"
Sleep 2600ms

# ── cleanup off-screen ──
Hide
Type "cd $O; rm -rf $L" Enter
Show
