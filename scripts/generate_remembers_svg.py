"""Generate docs/assets/link-remembers.svg — the automatic-memory loop.

Scene 1: a normal agent session; the session hook injects the (empty)
brief, the user states a standing preference in passing, and session end
captures it as a proposal — nothing saved yet.
Scene 2: the review gate — one command turns the proposal into durable
memory, because the user said so.
Scene 3: a brand-new terminal the next day; the hook injects the memory,
the agent answers from it, and the punchline is the file path — memory
you can open. Rendered as SMIL via svg_anim (CSS animations do not run
inside <img> embeds).
"""
from pathlib import Path

from svg_anim import render_svg

OUT = Path(__file__).resolve().parents[1] / "docs/assets/link-remembers.svg"
T = 26.0

INK = "#f3ece0"
GREEN = "#86c79a"
RUST = "#e0955f"
AMBER = "#e0b34f"
DIM = "#8a8174"

# (scene, y, class, color, text, start, typed)
LINES = [
    (1, 66,  "dim",  DIM,   "— tuesday · a claude code session —",                          0.4,  False),
    (1, 94,  "note", RUST,  "◆ Link session-start · memory brief injected (empty, day one)", 1.2,  False),
    (1, 126, "cmd",  INK,   "> from now on I only push to develop — never straight to main", 2.4,  True),
    (1, 152, "dim",  DIM,   "understood — develop only.",                                    4.8,  False),
    (1, 184, "note", RUST,  "◆ Link session-end · captured 1 proposal for your review",      6.0,  False),
    (1, 210, "out",  AMBER, 'pending: "only push to develop, never straight to main"',       7.2,  False),
    (2, 78,  "cmd",  INK,   "$ lnk review-memory only-push-to-develop",                      11.4, True),
    (2, 106, "out",  GREEN, "✓ reviewed — durable memory now, because you approved it",      13.2, False),
    (2, 130, "note", RUST,  "→ agents propose · you decide",                                 14.0, False),
    (3, 66,  "dim",  DIM,   "— wednesday · brand-new terminal · zero context —",             16.4, False),
    (3, 94,  "note", RUST,  "◆ Link session-start · 1 memory injected",                      17.4, False),
    (3, 126, "cmd",  INK,   "> which branch do I push to?",                                  18.4, True),
    (3, 154, "out",  GREEN, "✓ develop only — never straight to main",                       20.0, False),
    (3, 180, "note", RUST,  "→ from wiki/memories/only-push-to-develop.md",                  21.0, False),
    (3, 216, "dim",  DIM,   "plain Markdown · reviewed by you · shared by every agent",      22.4, False),
]

SCENE_OUT = {
    1: (10.6, 11.0),
    2: (15.6, 16.0),
    3: (25.2, 25.6),
}


def main() -> None:
    lines = []
    for scene, y, cls, color, text, start, typed in LINES:
        hold, fade = SCENE_OUT[scene]
        lines.append({
            "y": y, "cls": cls, "color": color, "text": text,
            "start": start, "typed": typed, "hold": hold, "fade": fade,
            "resting": scene == 3,  # frozen contexts show the payoff scene
        })
    svg = render_svg(
        title="lnk · link remembers",
        aria=(
            "Link demo: a preference said once in an agent session is captured "
            "automatically, approved by the user, and recalled in a brand-new "
            "terminal the next day — from a plain Markdown file."
        ),
        T=T,
        lines=lines,
    )
    OUT.write_text(svg, encoding="utf-8")
    print(f"wrote {OUT} ({len(svg)} bytes)")


if __name__ == "__main__":
    main()
