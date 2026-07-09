# Link "aha" demo — the paraphrase-recall moment, for the GitHub README.
#
# Renders a crisp, deterministic GIF (no synthetic frames) with charmbracelet vhs.
#
# One-time render (needs ffmpeg, which most machines have):
#   brew install vhs          # or: go install github.com/charmbracelet/vhs@latest
#   pip install model2vec     # the fast local semantic tier
#   cd docs/media && vhs link-aha.tape
# Then wire it into README.md:
#   <img src="docs/assets/link-aha.gif" alt="Link recall finds a memory phrased in different words" width="720">
# and add "link-aha.gif" to REQUIRED_ASSETS in scripts/generate_docs_media.py.

Output ../assets/link-aha.gif

Require lnk

Set Shell bash
Set FontSize 22
Set Width 1240
Set Height 560
Set Padding 44
Set Theme { "background": "#221c12", "foreground": "#f3ece0", "cursor": "#e0955f", "black": "#221c12", "green": "#86c79a", "brightBlack": "#8a8174", "white": "#f3ece0" }

# ── prep the demo workspace off-screen ──
Hide
Type "export L=$PWD/.aha-demo; rm -rf $L; lnk init $L >/dev/null 2>&1" Enter
Type "lnk remember 'I like feature branches named feat/short-topic, never long ones' $L --type preference >/dev/null 2>&1" Enter
Type "lnk semantic $L --setup >/dev/null 2>&1" Enter
Type "clear" Enter
Show

# ── the moment: ask in totally different words, it finds it ──
Sleep 800ms
Type@85ms "lnk recall 'how should I name my git branches'"
Sleep 600ms
Enter
Sleep 2600ms
Type@85ms "# different words, same memory — matched by meaning, not keywords"
Sleep 2200ms

# ── cleanup off-screen ──
Hide
Type "rm -rf $L" Enter
