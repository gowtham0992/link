#!/usr/bin/env python3
"""Generate small, reproducible GIF assets for the public docs."""

from __future__ import annotations

from pathlib import Path
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
SIZE = (860, 484)


COLORS = {
    "bg": "#050607",
    "panel": "#0e1116",
    "panel_2": "#17120c",
    "paper": "#fff4b8",
    "paper_2": "#fffdf1",
    "ink": "#f7f0d8",
    "muted": "#9ca3af",
    "blue": "#5b8cff",
    "green": "#54c79d",
    "yellow": "#ffd342",
    "red": "#ff6d5f",
    "border": "#17120c",
}


def _font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if mono:
        candidates.extend(
            [
                "/System/Library/Fonts/Menlo.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            ]
        )
    if bold:
        candidates.extend(
            [
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
        )
    candidates.extend(
        [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


FONT_TITLE = _font(24, bold=True)
FONT_SUBTITLE = _font(15)
FONT_MONO = _font(16, mono=True)
FONT_MONO_SMALL = _font(13, mono=True)
FONT_MONO_BOLD = _font(16, bold=True, mono=True)


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if draw.textbbox((0, 0), candidate, font=font)[2] <= width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def _draw_text_block(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: str,
    max_width: int,
    line_gap: int = 6,
) -> int:
    x, y = xy
    for line in _fit_text(draw, text, font, max_width):
        draw.text((x, y), line, font=font, fill=fill)
        y += draw.textbbox((0, 0), line, font=font)[3] + line_gap
    return y


def _save_gif(frames: list[Image.Image], path: Path, duration: int = 1350) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    palette_frames = [frame.convert("P", palette=Image.Palette.ADAPTIVE) for frame in frames]
    palette_frames[0].save(
        path,
        save_all=True,
        append_images=palette_frames[1:],
        duration=duration,
        loop=0,
        optimize=True,
        disposal=2,
    )


def _window_frame(title: str, subtitle: str = "") -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", SIZE, COLORS["paper"])
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, SIZE[0] - 1, SIZE[1] - 1), fill=COLORS["paper"], outline=COLORS["border"], width=4)
    draw.rectangle((4, 4, SIZE[0] - 5, 54), fill=COLORS["paper_2"], outline=COLORS["border"], width=2)
    for x, color in [(24, COLORS["red"]), (48, COLORS["yellow"]), (72, COLORS["green"])]:
        draw.ellipse((x, 21, x + 13, 34), fill=color, outline=COLORS["border"], width=2)
    draw.text((102, 18), title, font=FONT_TITLE, fill=COLORS["border"])
    if subtitle:
        draw.text((102, 56), subtitle, font=FONT_SUBTITLE, fill=COLORS["muted"])
    return image, draw


def _make_ui_tour() -> None:
    shots = [
        ("Start with prompts", "The local viewer gives a human-readable front door.", "link-home-dark.png"),
        ("Ingest safely", "Raw files are scanned, represented, and validated.", "link-ingest-dark.png"),
        ("Brief before work", "Agents get compact, source-backed context.", "link-brief-dark.png"),
        ("Review memory", "Memories are inspectable, explainable, and reversible.", "link-memory-dashboard-dark.png"),
        ("Explore the graph", "Large graphs open bounded first, then expand on demand.", "link-graph-dark.png"),
    ]
    frames: list[Image.Image] = []
    for title, caption, filename in shots:
        screenshot = Image.open(ASSETS / filename).convert("RGB").resize(SIZE)
        overlay = Image.new("RGBA", SIZE, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        draw.rectangle((0, 0, SIZE[0], 76), fill=(0, 0, 0, 220))
        draw.text((28, 15), title, font=FONT_TITLE, fill=COLORS["ink"])
        draw.text((28, 45), caption, font=FONT_SUBTITLE, fill="#d1d5db")
        frames.append(Image.alpha_composite(screenshot.convert("RGBA"), overlay).convert("RGB"))
    _save_gif(frames, ASSETS / "link-ui-tour.gif")
    _save_gif(frames, ASSETS / "link-product-tour-dark.gif")


def _terminal_frame(title: str, lines: list[tuple[str, str]]) -> Image.Image:
    image, draw = _window_frame(title, "CLI commands stay local and scriptable.")
    draw.rectangle((34, 96, SIZE[0] - 34, SIZE[1] - 34), fill=COLORS["bg"], outline=COLORS["border"], width=3)
    y = 122
    for kind, line in lines:
        color = {
            "prompt": COLORS["green"],
            "cmd": "#93c5fd",
            "ok": COLORS["ink"],
            "muted": "#9ca3af",
            "warn": COLORS["yellow"],
        }.get(kind, COLORS["ink"])
        prefix = "$ " if kind == "cmd" else "  "
        for wrapped in wrap(line, width=78) or [""]:
            draw.text((58, y), prefix + wrapped if wrapped == line else "  " + wrapped, font=FONT_MONO, fill=color)
            y += 25
        y += 4
    return image


def _make_cli_tour() -> None:
    frames = [
        _terminal_frame(
            "1. Check readiness",
            [
                ("cmd", "link status --validate"),
                ("ok", "Ready: yes"),
                ("ok", "Pages: 25 · Memories: 1 active · Search: sqlite-fts"),
                ("muted", "Next: query, brief, ingest, or serve the local viewer."),
            ],
        ),
        _terminal_frame(
            "2. Ask for compact context",
            [
                ("cmd", 'link query "why does Link help agents?" --budget small'),
                ("ok", "Answer-ready packet: 3 memories, 5 pages, graph neighborhood."),
                ("muted", "has_more: true · follow_up: widen budget or open context."),
            ],
        ),
        _terminal_frame(
            "3. Prime an agent",
            [
                ("cmd", 'link brief "working on Link release" --project link'),
                ("ok", "Relevant decisions, preferences, open review items, and project context."),
                ("muted", "Local Markdown. No hosted memory service."),
            ],
        ),
        _terminal_frame(
            "4. Prove scale locally",
            [
                ("cmd", 'link benchmark "agent memory"'),
                ("ok", "cache 0.10s · search 0.009s · query 0.018s · graph 0.022s"),
                ("ok", "Verdict: interactive"),
            ],
        ),
    ]
    _save_gif(frames, ASSETS / "link-cli-tour.gif", duration=1450)


def _chat_bubble(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    width: int,
    label: str,
    body: str,
    *,
    align: str,
) -> int:
    x, y = xy
    fill = "#2563eb" if align == "right" else "#1f2937"
    outline = "#60a5fa" if align == "right" else "#374151"
    body_color = "#ffffff"
    label_color = "#bfdbfe" if align == "right" else "#86efac"
    lines = _fit_text(draw, body, FONT_SUBTITLE, width - 34)
    height = 50 + (len(lines) * 23)
    draw.rounded_rectangle((x, y, x + width, y + height), radius=16, fill=fill, outline=outline, width=2)
    draw.text((x + 16, y + 12), label, font=FONT_MONO_SMALL, fill=label_color)
    text_y = y + 34
    for line in lines:
        draw.text((x + 16, text_y), line, font=FONT_SUBTITLE, fill=body_color)
        text_y += 23
    return y + height


def _tool_card(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    tool: str,
    args: str,
    result: str,
    *,
    active: bool = True,
) -> int:
    x, y = xy
    width = 738
    fill = "#101827" if active else "#111111"
    outline = COLORS["green"] if active else "#374151"
    draw.rounded_rectangle((x, y, x + width, y + 128), radius=14, fill=fill, outline=outline, width=3)
    draw.rectangle((x, y, x + width, y + 38), fill="#172033", outline=outline, width=0)
    draw.text((x + 18, y + 10), "MCP tool", font=FONT_MONO_SMALL, fill="#9ca3af")
    draw.text((x + 108, y + 9), f"link / {tool}", font=FONT_MONO_BOLD, fill="#86efac")
    draw.text((x + width - 88, y + 9), "ready", font=FONT_MONO_SMALL, fill=COLORS["yellow"])
    draw.text((x + 18, y + 54), "{", font=FONT_MONO_SMALL, fill="#9ca3af")
    draw.text((x + 34, y + 76), f'"arguments": {args}', font=FONT_MONO_SMALL, fill="#d1d5db")
    draw.text((x + 18, y + 100), f"→ {result}", font=FONT_MONO_SMALL, fill="#bfdbfe")
    return y + 128


def _mcp_chat_frame(title: str, user_prompt: str, tool: str, args: str, result: str, answer: str) -> Image.Image:
    image = Image.new("RGB", SIZE, COLORS["paper"])
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, SIZE[0] - 1, SIZE[1] - 1), fill=COLORS["paper"], outline=COLORS["border"], width=4)
    draw.rectangle((20, 20, SIZE[0] - 20, SIZE[1] - 20), fill="#080b10", outline=COLORS["border"], width=4)
    draw.rectangle((24, 24, SIZE[0] - 24, 70), fill="#151923")
    for x, color in [(44, COLORS["red"]), (66, COLORS["yellow"]), (88, COLORS["green"])]:
        draw.ellipse((x, 40, x + 11, 51), fill=color)
    draw.text((116, 38), "Agent chat", font=FONT_MONO_BOLD, fill=COLORS["ink"])
    draw.text((SIZE[0] - 280, 38), title, font=FONT_MONO_SMALL, fill="#9ca3af")

    _chat_bubble(draw, (500, 92), 298, "User", user_prompt, align="right")
    _chat_bubble(draw, (58, 166), 408, "Agent", "I'll ask Link first so I do not guess from chat history.", align="left")
    _tool_card(draw, (58, 246), tool, args, result)
    _chat_bubble(draw, (58, 392), 560, "Agent", answer, align="left")

    return image


def _make_mcp_tour() -> None:
    frames = [
        _mcp_chat_frame(
            "1 / readiness",
            "is Link ready?",
            "link_status",
            "{}",
            "ready: yes · pages: 25 · search: sqlite-fts",
            "Link is ready. I can query, brief, ingest, or remember from here.",
        ),
        _mcp_chat_frame(
            "2 / brief",
            "start with Link before we continue",
            "memory_brief",
            '{"query": "current task", "project": "link"}',
            "2 memories · 4 pages · 1 review warning",
            "I have the relevant preferences, project context, and review notes.",
        ),
        _mcp_chat_frame(
            "3 / smart query",
            "query Link for release process",
            "query_link",
            '{"query": "release process", "budget": "small"}',
            "why_selected · 3 memories · 5 pages · follow-ups",
            "Here is the compact release context. I did not dump the whole wiki.",
        ),
        _mcp_chat_frame(
            "4 / reviewed memory",
            "remember that I prefer short release notes",
            "remember_memory",
            '{"memory_type": "preference", "scope": "user"}',
            "saved · pending review · duplicate check passed",
            "Saved locally as Markdown. You can review, update, archive, or forget it.",
        ),
    ]
    _save_gif(frames, ASSETS / "link-mcp-agent-chat.gif", duration=1650)


def main() -> None:
    _make_ui_tour()
    _make_cli_tour()
    _make_mcp_tour()
    print("Generated docs GIFs:")
    for name in ["link-ui-tour.gif", "link-cli-tour.gif", "link-mcp-agent-chat.gif", "link-product-tour-dark.gif"]:
        print(f"- docs/assets/{name}")


if __name__ == "__main__":
    main()
