"""Shared emitter for Link's animated terminal SVGs — SMIL, not CSS.

CSS keyframe animations do not run when an SVG is loaded through an
<img> element (how the homepage figures and the GitHub README embed
them), which left the demos rendering as empty terminal windows. SMIL
<animate> elements run everywhere an SVG renders, so every generator
routes through this module.
"""
from __future__ import annotations


def _kt(t: float, T: float) -> float:
    return max(0.0, min(t / T, 1.0))


def _keytimes(points: list[float], T: float) -> str:
    """Normalize to strictly increasing keyTimes in [0, 1]."""
    fractions = [_kt(p, T) for p in points]
    out = [0.0]
    for value in fractions:
        out.append(max(value, out[-1] + 1e-4))
    out.append(1.0)
    if out[-2] >= 1.0:
        # squeeze the tail below 1.0
        out[-2] = 1.0 - 1e-4
    return ";".join(f"{v:.5f}" for v in [out[0], *out[1:-1], out[-1]])


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;")


def render_svg(
    *,
    title: str,
    aria: str,
    T: float,
    lines: list[dict],
    caret: dict | None = None,
) -> str:
    """Render the terminal-window SVG.

    Each line dict: {x?, y, cls, color, text, start, typed, hold, fade,
    resting?}. `hold` is when the line starts fading, `fade` when it is
    gone. Lines marked `resting` are visible in the SVG's base state, so
    contexts that freeze image animations (reduced motion, some embeds)
    show the closing scene instead of an empty terminal; while SMIL runs,
    the animate values override the base entirely.
    """
    defs: list[str] = []
    texts: list[str] = []
    for index, line in enumerate(lines):
        x = line.get("x", 30)
        text = line["text"]
        typed = bool(line["typed"])
        resting = bool(line.get("resting"))
        start, hold, fade = line["start"], line["hold"], line["fade"]
        ramp = 0.02 if typed else 0.35
        if resting:
            # Closing-scene lines are visible at t=0 AND t=T: contexts that
            # freeze image animations at the first frame show the payoff
            # instead of an empty terminal, and the loop point is seamless
            # (the quick 0.12s dip happens as the first scene fades in).
            key_times = _keytimes([0.12, start, start + ramp], T)
            values = "1;0;0;1;1"
        else:
            key_times = _keytimes([start, start + ramp, hold, fade], T)
            values = "0;0;1;1;0;0"
        opacity_anim = (
            f'<animate attributeName="opacity" dur="{T:g}s" repeatCount="indefinite" '
            f'calcMode="linear" values="{values}" keyTimes="{key_times}"/>'
        )
        clip_attr = ""
        if typed:
            type_secs = min(1.5, 0.032 * len(text))
            width = int(len(text) * 9.2 + 14)
            if resting:
                width_times = _keytimes([0.12, start, start + type_secs], T)
                width_values = f"{width};0;0;{width};{width}"
            else:
                width_times = _keytimes([start, start + type_secs], T)
                width_values = f"0;0;{width};{width}"
            defs.append(
                f'<clipPath id="tw{index}">'
                f'<rect x="{x - 2}" y="{line["y"] - 17}" height="24" width="{width if resting else 0}">'
                f'<animate attributeName="width" dur="{T:g}s" repeatCount="indefinite" '
                f'calcMode="linear" values="{width_values}" keyTimes="{width_times}"/>'
                f"</rect></clipPath>"
            )
            clip_attr = f' clip-path="url(#tw{index})"'
        texts.append(
            f'  <text x="{x}" y="{line["y"]}" class="{line["cls"]}" fill="{line["color"]}" '
            f'opacity="{1 if resting else 0}"{clip_attr}>{_escape(text)}{opacity_anim}</text>'
        )

    caret_markup = ""
    if caret:
        caret_markup = (
            f'\n  <rect x="{caret["x"]}" y="{caret["y"]}" width="{caret.get("width", 9)}" '
            f'height="{caret.get("height", 16)}" fill="{caret.get("color", "#e0955f")}">'
            '<animate attributeName="opacity" dur="1s" repeatCount="indefinite" '
            'calcMode="discrete" values="1;0" keyTimes="0;0.5"/></rect>'
        )

    defs_markup = f"\n  <defs>\n    {chr(10).join(defs)}\n  </defs>" if defs else ""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 300" role="img"
     aria-label="{aria}">
  <style>
    .win {{ fill:#221c12; stroke:#3b342a; }}
    text {{ font-family:'SF Mono','Menlo','Consolas',ui-monospace,monospace; font-size:15px; }}
    .cmd {{ font-weight:500; }}
  </style>{defs_markup}
  <rect class="win" x="1" y="1" width="718" height="298" rx="12"/>
  <rect x="1" y="1" width="718" height="34" rx="12" fill="#1a150d"/>
  <circle cx="24" cy="18" r="5" fill="#e06c60"/>
  <circle cx="44" cy="18" r="5" fill="#e0b34f"/>
  <circle cx="64" cy="18" r="5" fill="#7fae8f"/>
  <text x="360" y="23" text-anchor="middle" fill="#8a8174" style="font-size:12px;letter-spacing:.08em;">{_escape(title)}</text>{caret_markup}
{chr(10).join(texts)}
</svg>
"""
