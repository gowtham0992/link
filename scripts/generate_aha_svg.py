"""Generate docs/assets/link-aha.svg — the original recall-by-meaning demo.

Scene 1: a memory is saved, then recalled with a completely different
phrasing — matched by meaning, not keywords.
Scene 2: a brand-new agent session is greeted with memory automatically.
Data extracted from the original hand-written CSS-keyframes SVG and
re-rendered as SMIL via svg_anim (CSS animations do not run inside
<img> embeds, which is how the site and README show this file).
"""
from pathlib import Path

from svg_anim import render_svg

OUT = Path(__file__).resolve().parents[1] / "docs/assets/link-aha.svg"
T = 14.0

INK = "#f3ece0"
GREEN = "#86c79a"
RUST = "#e0955f"
DIM = "#8a8174"

# (x, y, class, color, text, start, typed, hold, fade)
LINES = [
    (30, 78,  "cmd",  INK,   '$ lnk remember "feat/short-topic branch names"',    0.5,  True,  6.1,  6.48),
    (30, 106, "out",  GREEN, "✓ saved to local memory",                           1.92, False, 6.1,  6.48),
    (30, 150, "cmd",  INK,   '$ lnk recall "how should I name my git branches"',  2.5,  True,  6.1,  6.48),
    (30, 178, "out",  GREEN, "✓ feat/short-topic branch names",                   4.12, False, 6.1,  6.48),
    (52, 204, "note", RUST,  "→ matched by meaning, not keywords",                4.72, False, 6.1,  6.48),
    (30, 96,  "dim",  DIM,   "— you open a new agent session —",                  7.32, False, 13.2, 13.58),
    (30, 140, "out",  RUST,  "Link memory · injected automatically",              8.22, False, 13.2, 13.58),
    (30, 168, "out",  INK,   "• prefers feat/short-topic branch names",           9.02, False, 13.2, 13.58),
    (30, 196, "out",  INK,   "• keep PR descriptions short",                      9.72, False, 13.2, 13.58),
    (52, 240, "note", RUST,  "no one asked. it just remembered.",                 10.92, False, 13.2, 13.58),
]


def main() -> None:
    lines = [
        {
            "x": x, "y": y, "cls": cls, "color": color, "text": text,
            "start": start, "typed": typed, "hold": hold, "fade": fade,
            "resting": hold > 13,  # frozen contexts show the closing scene
        }
        for x, y, cls, color, text, start, typed, hold, fade in LINES
    ]
    svg = render_svg(
        title="lnk · local agent memory",
        aria=(
            "Link demo: recall finds a memory phrased in different words, and a "
            "new agent session is greeted with memory automatically."
        ),
        T=T,
        lines=lines,
        caret={"x": 30, "y": 270},
    )
    OUT.write_text(svg, encoding="utf-8")
    print(f"wrote {OUT} ({len(svg)} bytes)")


if __name__ == "__main__":
    main()
