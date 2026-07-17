"""Generate docs/assets/link-truth.svg — the 1.7 sibling of link-aha.svg.

Scene 1: a new memory conflicts with an old one; Link refuses to pile up
truth and replaces it with lineage via --supersedes.
Scene 2: recall returns only the current truth; --as-of answers what was
true back then. Rendered as SMIL via svg_anim (CSS animations do not run
inside <img> embeds).
"""
from pathlib import Path

from svg_anim import render_svg

OUT = Path(__file__).resolve().parents[1] / "docs/assets/link-truth.svg"
T = 18.0

INK = "#f3ece0"
GREEN = "#86c79a"
RUST = "#e0955f"
AMBER = "#e0b34f"
DIM = "#8a8174"

# (scene, y, class, color, text, start, typed)
LINES = [
    (1, 66,  "cmd",  INK,   '$ lnk remember "we deploy from main every Friday"',            0.5,  True),
    (1, 92,  "out",  GREEN, "✓ saved to local memory",                                      2.0,  False),
    (1, 124, "dim",  DIM,   "— weeks later —",                                              2.8,  False),
    (1, 152, "cmd",  INK,   '$ lnk remember "no longer Fridays - deploys ship Tuesdays"',   3.5,  True),
    (1, 178, "out",  AMBER, "⚠ conflicts with an active memory",                            5.1,  False),
    (1, 202, "note", RUST,  "→ replace it: rerun with --supersedes deploy-…-friday",        5.8,  False),
    (1, 234, "cmd",  INK,   "$ lnk remember … --supersedes deploy-from-main-every-friday",  6.8,  True),
    (1, 262, "out",  GREEN, "✓ saved · old memory archived with lineage",                   8.6,  False),
    (2, 78,  "cmd",  INK,   '$ lnk recall "when do we deploy"',                             10.6, True),
    (2, 106, "out",  GREEN, "✓ no longer Fridays - deploys ship Tuesdays",                  11.9, False),
    (2, 130, "note", RUST,  "→ only the current truth",                                     12.5, False),
    (2, 176, "cmd",  INK,   '$ lnk recall "when do we deploy" --as-of 2026-05-01',          13.4, True),
    (2, 204, "out",  GREEN, "✓ we deploy from main every Friday",                           15.1, False),
    (2, 228, "note", RUST,  "→ what was true back then · history is never lost",            15.7, False),
]

SCENE_OUT = {
    1: (9.7, 10.1),
    2: (17.3, 17.7),
}


def main() -> None:
    lines = []
    for scene, y, cls, color, text, start, typed in LINES:
        hold, fade = SCENE_OUT[scene]
        lines.append({
            "y": y, "cls": cls, "color": color, "text": text,
            "start": start, "typed": typed, "hold": hold, "fade": fade,
            "resting": scene == 2,  # frozen contexts show the payoff scene
        })
    svg = render_svg(
        title="lnk · memory that stays true",
        aria=(
            "Link demo: a new memory conflicts with an old one; Link replaces it "
            "with lineage, recall returns only the current truth, and --as-of "
            "answers what was true back then."
        ),
        T=T,
        lines=lines,
    )
    OUT.write_text(svg, encoding="utf-8")
    print(f"wrote {OUT} ({len(svg)} bytes)")


if __name__ == "__main__":
    main()
