# Docs media

- `link-aha.svg` (in `../assets/`) — the animated "aha" demo used on the
  Getting Started page. Self-contained SVG (plain text, no external runtime),
  animates in any modern browser. Regenerate by editing the generator snippet
  in the 1.6 changelog history or hand-editing the SVG.
- `link-aha.tape` — charmbracelet [vhs](https://github.com/charmbracelet/vhs)
  script that renders the README GIF (`../assets/link-aha.gif`) from real `lnk`
  commands. See the header of the tape for the one-time render command; the GIF
  is not checked in until rendered.

Other GIFs/screenshots under `../assets/` are real product captures, verified
(not generated) by `scripts/generate_docs_media.py`.
