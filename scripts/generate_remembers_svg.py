"""Generate docs/assets/link-remembers.svg — the automatic-memory loop.

Scene 1: a normal agent session; the session hook injects the (empty)
brief, the user states a standing preference in passing, and session end
captures it as a proposal — nothing saved yet.
Scene 2: the review gate — one command turns the proposal into durable
memory, because the user said so.
Scene 3: a brand-new terminal the next day; the hook injects the memory,
the agent answers from it, and the punchline is the file path — memory
you can open. Same visual language as link-truth.svg.
"""
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs/assets/link-remembers.svg"
T = 26.0  # loop seconds

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


def pct(t: float) -> str:
    return f"{t / T * 100:.3f}%"


def keyframes(name: str, start: float, end_hold: float, end_fade: float, typed: bool, type_secs: float) -> str:
    if typed:
        return (
            f"@keyframes {name} {{\n"
            f"  0%,{pct(max(0.0, start - 0.01))} {{ opacity:0; clip-path:inset(0 100% 0 0); }}\n"
            f"  {pct(start)} {{ opacity:1; clip-path:inset(0 100% 0 0); }}\n"
            f"  {pct(start + type_secs)} {{ opacity:1; clip-path:inset(0 0 0 0); }}\n"
            f"  {pct(end_hold)} {{ opacity:1; clip-path:inset(0 0 0 0); }}\n"
            f"  {pct(end_fade)},100% {{ opacity:0; clip-path:inset(0 0 0 0); }}\n"
            f"}}"
        )
    return (
        f"@keyframes {name} {{\n"
        f"  0%,{pct(max(0.0, start - 0.01))} {{ opacity:0; }}\n"
        f"  {pct(start + 0.35)} {{ opacity:1; }}\n"
        f"  {pct(end_hold)} {{ opacity:1; }}\n"
        f"  {pct(end_fade)},100% {{ opacity:0; }}\n"
        f"}}"
    )


def main() -> None:
    frames, texts = [], []
    for index, (scene, y, cls, color, text, start, typed) in enumerate(LINES):
        name = f"r_{index}"
        hold, fade = SCENE_OUT[scene]
        type_secs = min(1.5, 0.032 * len(text))
        frames.append(keyframes(name, start, hold, fade, typed, type_secs))
        safe = text.replace("&", "&amp;").replace("<", "&lt;")
        texts.append(
            f'  <text x="30" y="{y}" class="{cls}" fill="{color}" '
            f'style="animation:{name} {T:.0f}s infinite;">{safe}</text>'
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 300" role="img"
     aria-label="Link demo: a preference said once in an agent session is captured automatically, approved by the user, and recalled in a brand-new terminal the next day — from a plain Markdown file.">
  <style>
    .win {{ fill:#221c12; stroke:#3b342a; }}
    text {{ font-family:'SF Mono','Menlo','Consolas',ui-monospace,monospace; font-size:15px; opacity:0; }}
    .cmd {{ font-weight:500; }}
{chr(10).join(frames)}
  </style>
  <rect class="win" x="1" y="1" width="718" height="298" rx="12"/>
  <rect x="1" y="1" width="718" height="34" rx="12" fill="#1a150d"/>
  <circle cx="24" cy="18" r="5" fill="#e06c60"/>
  <circle cx="44" cy="18" r="5" fill="#e0b34f"/>
  <circle cx="64" cy="18" r="5" fill="#7fae8f"/>
  <text x="360" y="23" text-anchor="middle" fill="#8a8174" style="font-size:12px;opacity:1;letter-spacing:.08em;">lnk · link remembers</text>
{chr(10).join(texts)}
</svg>
"""
    OUT.write_text(svg, encoding="utf-8")
    print(f"wrote {OUT} ({len(svg)} bytes)")


if __name__ == "__main__":
    main()
