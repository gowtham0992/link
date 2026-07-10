"""Generate docs/assets/link-truth.svg — the 1.7 sibling of link-aha.svg.

Scene 1: a new memory conflicts with an old one; Link refuses to pile up
truth and replaces it with lineage via --supersedes.
Scene 2: recall returns only the current truth; --as-of answers what was
true back then. Same visual language as link-aha.svg (terminal window,
typing clip-path for commands, fades for output).
"""
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs/assets/link-truth.svg"
T = 18.0  # loop seconds

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

SCENE1_OUT = (9.7, 10.1)   # fade window
SCENE2_OUT = (17.3, 17.7)


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
        name = f"t_{index}"
        hold, fade = (SCENE1_OUT if scene == 1 else SCENE2_OUT)
        type_secs = min(1.5, 0.032 * len(text))
        frames.append(keyframes(name, start, hold, fade, typed, type_secs))
        safe = text.replace("&", "&amp;").replace("<", "&lt;")
        texts.append(
            f'  <text x="30" y="{y}" class="{cls}" fill="{color}" '
            f'style="animation:{name} {T:.0f}s infinite;">{safe}</text>'
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 300" role="img"
     aria-label="Link demo: a new memory conflicts with an old one; Link replaces it with lineage, recall returns only the current truth, and --as-of answers what was true back then.">
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
  <text x="360" y="23" text-anchor="middle" fill="#8a8174" style="font-size:12px;opacity:1;letter-spacing:.08em;">lnk · memory that stays true</text>
{chr(10).join(texts)}
</svg>
"""
    OUT.write_text(svg, encoding="utf-8")
    print(f"wrote {OUT} ({len(svg)} bytes)")


if __name__ == "__main__":
    main()
