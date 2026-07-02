"""Static CSS and JavaScript assets for the local Link web UI."""
from __future__ import annotations

__all__ = [
    "CSS",
    "THEME_INIT_JS",
    "THEME_CONTROL_JS",
    "MEMORY_ACTION_JS",
    "COPY_BUTTON_JS",
    "RAW_SOURCE_JS",
    "PROPOSAL_UI_JS",
]

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  color-scheme: light;
  --bg: #faf9f5;
  --text: #221c12;
  --text-strong: #221c12;
  --muted: #5f574a;
  --subtle: #5f574a;
  --faint: #a3967f;
  --link: #a8492f;
  --border: rgba(34,28,18,0.12);
  --border-soft: rgba(34,28,18,0.08);
  --border-strong: rgba(34,28,18,0.25);
  --surface: #fffdf8;
  --surface-muted: rgba(34,28,18,0.04);
  --surface-code: rgba(34,28,18,0.04);
  --surface-code-ink: #221c12;
  --surface-code-inline: rgba(34,28,18,0.05);
  --surface-table: rgba(34,28,18,0.03);
  --surface-graph: #12100c;
  --surface-empty: #fffdf8;
  --mark-bg: rgba(154,110,32,0.18);
  --button-bg: #fffdf8;
  --button-hover: rgba(34,28,18,0.05);
  --button-text: #221c12;
  --button-disabled: #a3967f;
  --accent: #a8492f;
  --accent-fg: #fffdf8;
  --accent-soft: #c07a5f;
  --caution: #9a6e20;
  --caution-fg: #7c5a10;
  --caution-bg: rgba(154,110,32,0.08);
  --caution-bg-2: rgba(154,110,32,0.10);
  --caution-border: rgba(154,110,32,0.32);
  --ok: #4a7c59;
  --ok-fg: #3d6b47;
  --chip-bg: rgba(34,28,18,0.05);
  --meter-off: rgba(34,28,18,0.15);
  --meter-off-caution: rgba(154,110,32,0.20);
  --success-bg: rgba(74,124,89,0.08);
  --success-border: #4a7c59;
  --danger-bg: rgba(154,110,32,0.08);
  --danger-border: rgba(154,110,32,0.32);
  --quote-border: rgba(34,28,18,0.25);
  --quote-text: #5f574a;
  --shadow: rgba(34,28,18,0.10);
  --font-serif: 'Iowan Old Style','Palatino Linotype',Palatino,Georgia,serif;
  --font-sans: -apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
  --font-mono: ui-monospace,'SF Mono',Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg: #191309;
    --text: #dcd3c2;
    --text-strong: #f0e9dc;
    --muted: #a3967f;
    --subtle: #a3967f;
    --faint: #7d7260;
    --link: #cd7657;
    --border: rgba(240,233,220,0.14);
    --border-soft: rgba(240,233,220,0.08);
    --border-strong: rgba(240,233,220,0.25);
    --surface: #1e1810;
    --surface-muted: #171209;
    --surface-code: #171209;
    --surface-code-ink: #f0e9dc;
    --surface-code-inline: rgba(240,233,220,0.07);
    --surface-table: rgba(240,233,220,0.04);
    --surface-graph: #12100c;
    --surface-empty: #1e1810;
    --mark-bg: rgba(217,169,78,0.25);
    --button-bg: #1e1810;
    --button-hover: rgba(240,233,220,0.07);
    --button-text: #f0e9dc;
    --button-disabled: #7d7260;
    --accent: #cd7657;
    --accent-fg: #191309;
    --accent-soft: #cd7657;
    --caution: #d9a94e;
    --caution-fg: #d9a94e;
    --caution-bg: rgba(217,169,78,0.08);
    --caution-bg-2: rgba(217,169,78,0.12);
    --caution-border: rgba(217,169,78,0.32);
    --ok: #6da87e;
    --ok-fg: #8fbf9c;
    --chip-bg: rgba(240,233,220,0.07);
    --meter-off: rgba(240,233,220,0.18);
    --meter-off-caution: rgba(217,169,78,0.25);
    --success-bg: rgba(109,168,126,0.10);
    --success-border: #6da87e;
    --danger-bg: rgba(217,169,78,0.08);
    --danger-border: rgba(217,169,78,0.32);
    --quote-border: rgba(240,233,220,0.25);
    --quote-text: #a3967f;
    --shadow: rgba(0,0,0,0.45);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #191309;
  --text: #dcd3c2;
  --text-strong: #f0e9dc;
  --muted: #a3967f;
  --subtle: #a3967f;
  --faint: #7d7260;
  --link: #cd7657;
  --border: rgba(240,233,220,0.14);
  --border-soft: rgba(240,233,220,0.08);
  --border-strong: rgba(240,233,220,0.25);
  --surface: #1e1810;
  --surface-muted: #171209;
  --surface-code: #171209;
  --surface-code-ink: #f0e9dc;
  --surface-code-inline: rgba(240,233,220,0.07);
  --surface-table: rgba(240,233,220,0.04);
  --surface-graph: #12100c;
  --surface-empty: #1e1810;
  --mark-bg: rgba(217,169,78,0.25);
  --button-bg: #1e1810;
  --button-hover: rgba(240,233,220,0.07);
  --button-text: #f0e9dc;
  --button-disabled: #7d7260;
  --accent: #cd7657;
  --accent-fg: #191309;
  --accent-soft: #cd7657;
  --caution: #d9a94e;
  --caution-fg: #d9a94e;
  --caution-bg: rgba(217,169,78,0.08);
  --caution-bg-2: rgba(217,169,78,0.12);
  --caution-border: rgba(217,169,78,0.32);
  --ok: #6da87e;
  --ok-fg: #8fbf9c;
  --chip-bg: rgba(240,233,220,0.07);
  --meter-off: rgba(240,233,220,0.18);
  --meter-off-caution: rgba(217,169,78,0.25);
  --success-bg: rgba(109,168,126,0.10);
  --success-border: #6da87e;
  --danger-bg: rgba(217,169,78,0.08);
  --danger-border: rgba(217,169,78,0.32);
  --quote-border: rgba(240,233,220,0.25);
  --quote-text: #a3967f;
  --shadow: rgba(0,0,0,0.45);
}
:root[data-theme="light"] { color-scheme: light; }
html { overflow-x: hidden; background: var(--bg); }
body { font-family: var(--font-sans); background: var(--bg); color: var(--text);
       width: 100%; max-width: 920px; margin: 0 auto; padding: 20px 24px 28px;
       overflow-x: hidden; overflow-wrap: anywhere; }
body.graph-page { max-width: min(1440px, 100%); }
a { color: var(--link); }
a, p, li, code { overflow-wrap: anywhere; }
a:hover { text-decoration: underline; }

header { border-bottom: 1px solid var(--border); padding-bottom: 12px; margin-bottom: 24px; }
header .header-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 12px; }
header .logo { font-size: 24px; font-weight: bold; letter-spacing: 0; white-space: nowrap; flex: 0 0 auto; }
header .logo a { color: var(--text-strong); text-decoration: none; display: inline-flex; align-items: center; gap: 8px; }
header .logo img { width: 28px; height: 28px; border-radius: 7px; flex: none; }
header .logo small { font-weight: normal; font-size: 13px; color: var(--subtle); margin-left: 8px; }
header nav { display: flex; gap: 8px 14px; font-size: 14px; font-family: sans-serif; flex-wrap: wrap; min-width: 0; align-items: center; }
header nav a,
header nav summary { line-height: 1.35; }
header nav a[aria-current="page"],
header nav summary[aria-current="page"] { color: var(--text-strong); font-weight: 600; text-decoration: none; }
header .nav-more { position: relative; display: inline-flex; }
header .nav-more summary { color: var(--link); cursor: pointer; list-style: none; text-decoration: underline; }
header .nav-more summary::-webkit-details-marker { display: none; }
header .nav-more-menu { position: absolute; top: calc(100% + 6px); right: 0; z-index: 30;
                        display: grid; gap: 6px; min-width: 150px; padding: 10px 12px;
                        border: 1px solid var(--border); border-radius: 4px; background: var(--surface);
                        box-shadow: 0 8px 24px var(--shadow); }
header .nav-more:not([open]) .nav-more-menu { display: none; }
header .header-tools { display: grid; justify-items: end; gap: 7px; flex: 0 0 220px; min-width: 170px; max-width: 42vw; }
header form { display: block; width: 100%; }
header input { padding: 4px 8px; border: 1px solid var(--border); border-radius: 4px; font-size: 13px; width: 100%; background: var(--surface); color: var(--text); }
header .theme-toggle { border: 1px solid var(--border); background: var(--button-bg); color: var(--button-text);
                       border-radius: 999px; padding: 3px 8px; font: 12px -apple-system, BlinkMacSystemFont, sans-serif;
                       cursor: pointer; display: inline-flex; align-items: center; gap: 6px; max-width: 100%; }
header .theme-toggle:hover { background: var(--button-hover); }
header .theme-icon { width: 14px; height: 14px; border-radius: 50%; border: 1px solid currentColor;
                     background: linear-gradient(90deg, currentColor 0 50%, transparent 50% 100%); flex: none; }
header .theme-text { white-space: nowrap; }

.breadcrumb { font-size: 13px; color: var(--subtle); margin-bottom: 12px; font-family: sans-serif; }
.breadcrumb a { color: var(--link); }

.meta { font-size: 13px; color: var(--muted); margin-bottom: 16px; font-family: sans-serif; }
.meta .badge { color: var(--subtle); font-size: 12px; font-variant: all-small-caps; letter-spacing: 0.04em; }
.page-actions { display: flex; flex-wrap: wrap; gap: 8px; margin: -4px 0 18px; font-family: sans-serif; font-size: 13px; }
.button-link { border: 1px solid var(--border); border-radius: 4px; padding: 4px 9px; color: var(--button-text); background: var(--button-bg); text-decoration: none; display: inline-flex; align-items: center; }
.button-link:hover { background: var(--button-hover); text-decoration: none; }

h1 { font-family: var(--font-serif); font-size: 30px; margin-bottom: 4px; line-height: 1.25; }
h2 { font-family: var(--font-serif); font-size: 20px; margin-top: 28px; margin-bottom: 10px; border-bottom: 1px solid var(--border-soft); padding-bottom: 6px; }
h3 { font-family: var(--font-serif); font-size: 17px; margin-top: 20px; margin-bottom: 8px; }
p { line-height: 1.7; margin-bottom: 12px; }
ul, ol { margin: 8px 0 12px 28px; line-height: 1.7; }
li { margin-bottom: 3px; }
blockquote { border-left: 3px solid var(--quote-border); padding: 6px 16px; margin: 12px 0; color: var(--quote-text); }
pre { background: var(--surface-code); padding: 14px; border-radius: 4px; overflow-x: auto; margin: 12px 0;
      font-size: 13px; font-family: Menlo, monospace; }
code { font-family: var(--font-mono); font-size: 0.9em; }
p code { background: var(--surface-code-inline); padding: 1px 5px; border-radius: 3px; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 15px; }
th, td { border: 1px solid var(--border); padding: 7px 12px; text-align: left; }
th { background: var(--surface-table); }
hr { border: none; border-top: 1px solid var(--border); margin: 24px 0; }

.wiki-page-shell { display: grid; grid-template-columns: 150px minmax(0, 1fr); gap: 26px; align-items: start; }
.wiki-page-document { max-width: 760px; min-width: 0; }
.related-pages { margin-top: 28px; padding-top: 14px; border-top: 1px solid var(--border-soft); font-family: sans-serif; }
.related-pages h2 { font-family: var(--font-serif); font-size: 20px; margin-top: 0; }
.related-pages ul { list-style: none; padding: 0; margin: 0; display: grid; gap: 7px; }
.related-pages li { display: flex; gap: 8px; align-items: baseline; min-width: 0; }
.related-pages .relationship { color: var(--subtle); font-size: 12px; min-width: 58px; text-transform: lowercase; }
.page-outline { position: sticky; top: 14px; display: grid; gap: 7px; padding: 10px 12px 10px 0;
                border-right: 1px solid var(--border-soft); font: 12px -apple-system, BlinkMacSystemFont, sans-serif;
                color: var(--muted); }
.page-outline strong { color: var(--subtle); font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; }
.page-outline a { color: var(--muted); text-decoration: none; line-height: 1.3; }
.page-outline a:hover { color: var(--link); text-decoration: underline; }
.page-outline a.level-3 { padding-left: 10px; font-size: 11px; }

.home-stats { display: flex; gap: 24px; margin: 20px 0; font-family: sans-serif; font-size: 14px; }
.home-stats .stat { text-align: center; }
.home-stats .stat .num { font-size: 28px; font-weight: bold; color: var(--accent-soft); display: block; }
.home-stats .stat .label { color: var(--subtle); font-size: 12px; }
.product-lanes { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 18px 0 22px; }
.product-lane { border: 1px solid var(--border-soft); border-radius: 6px; background: var(--surface); padding: 12px; font-family: sans-serif; }
.product-lane h2 { border: 0; margin: 0 0 8px; padding: 0; font-size: 15px; font-family: sans-serif; }
.product-lane p { margin: 0; color: var(--muted); line-height: 1.45; font-size: 13px; }
.product-lane code { white-space: normal; overflow-wrap: anywhere; }

.page-list { list-style: none; padding: 0; margin: 12px 0; }
.page-list li { padding: 6px 0; border-bottom: 1px solid var(--border-soft); }
.page-list li:last-child { border-bottom: none; }
.page-list .type { font-size: 11px; color: var(--subtle); font-family: sans-serif; margin-left: 6px; }
.search-results small { color: var(--subtle); font-family: sans-serif; line-height: 1.35; }
.search-refine { margin: 0 0 14px; display: flex; gap: 8px; align-items: center; max-width: 620px; }
.search-refine input[type="search"] { flex: 1 1 auto; min-width: 150px; padding: 6px 8px;
  border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: var(--text); font-size: 14px; }
.search-refine button { flex: 0 0 auto; }
.catalog-summary { border: 1px solid var(--border-soft); border-radius: 4px; padding: 10px 12px;
                   background: var(--surface); margin: 12px 0 14px; font-family: sans-serif; }
.catalog-summary p { margin: 0 0 8px; color: var(--muted); font-size: 13px; line-height: 1.4; }
.catalog-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.catalog-chip { border: 1px solid var(--border-soft); border-radius: 999px; padding: 3px 8px;
                color: var(--muted); font-size: 12px; background: var(--surface-muted); text-decoration: none; }
.catalog-chip strong { color: var(--text-strong); margin-right: 5px; }
.catalog-chip:hover,
.catalog-chip.active { border-color: var(--accent-soft); color: var(--text-strong); text-decoration: none; }
.page-groups { display: grid; gap: 4px; margin-top: 6px; }
.page-group h2 { font-size: 15px; margin: 18px 0 2px; padding-bottom: 4px; font-family: sans-serif;
                 color: var(--text-strong); text-transform: lowercase; }
.page-group h2 span { color: var(--subtle); font-weight: normal; font-size: 12px; margin-left: 4px; }
.empty-state { color: var(--muted); font-family: sans-serif; }
.pager { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin: 12px 0; font-family: sans-serif; color: var(--muted); font-size: 13px; }
.pager .button-link.disabled { color: var(--button-disabled); background: transparent; cursor: default; }
.section-heading { display: flex; justify-content: space-between; align-items: baseline; gap: 12px;
                   margin-top: 28px; border-bottom: 1px solid var(--border-soft); }
.section-heading h2 { margin: 0; border: 0; padding-bottom: 4px; }
.section-heading a { font-size: 13px; font-family: sans-serif; font-weight: normal; }
.memory-profile { margin: 18px 0; }
.memory-profile .summary { color: var(--muted); font-family: sans-serif; margin-bottom: 16px; }
.memory-profile .memory-meta { color: var(--subtle); font-size: 12px; font-family: sans-serif; }
.brief-form { display: flex; gap: 8px; flex-wrap: wrap; margin: 14px 0; font-family: sans-serif; }
.brief-form input { flex: 1 1 220px; min-width: 0; padding: 6px 8px; border: 1px solid var(--border);
                    border-radius: 4px; background: var(--surface); color: var(--text); }
.brief-form button { border: 1px solid var(--border); background: var(--button-bg); color: var(--button-text);
                     border-radius: 4px; padding: 6px 10px; cursor: pointer; }
.brief-form button:hover { background: var(--button-hover); }
.raw-source-form { display: grid; gap: 10px; margin: 16px 0; padding: 12px;
                   border: 1px solid var(--border-soft); border-radius: 6px; background: var(--surface); font-family: sans-serif; }
.raw-source-form label { display: grid; gap: 4px; color: var(--muted); font-size: 12px; }
.raw-source-form input,
.raw-source-form textarea { width: 100%; min-width: 0; padding: 8px 9px; border: 1px solid var(--border);
                            border-radius: 4px; background: var(--bg); color: var(--text); font: inherit; }
.raw-source-form textarea { min-height: 150px; resize: vertical; line-height: 1.45; }
.raw-source-controls { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 8px; }
.raw-source-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.raw-source-actions button,
.raw-source-status button { border: 1px solid var(--border); background: var(--button-bg); color: var(--button-text);
                            border-radius: 4px; padding: 7px 10px; cursor: pointer; font: inherit; }
.raw-source-actions button:hover,
.raw-source-status button:hover { background: var(--button-hover); }
.raw-source-status { min-height: 1.4em; color: var(--muted); font-family: sans-serif; font-size: 13px; line-height: 1.45; }
.raw-source-status code { display: inline-block; margin: 4px 6px 4px 0; padding: 4px 6px; background: var(--surface-code); border-radius: 4px; }
.proposal-form { display: grid; gap: 10px; margin: 16px 0; font-family: sans-serif; }
.proposal-form textarea,
.proposal-form input { width: 100%; min-width: 0; padding: 8px 9px; border: 1px solid var(--border);
                       border-radius: 4px; background: var(--surface); color: var(--text); font: inherit; }
.proposal-form textarea { min-height: 190px; resize: vertical; line-height: 1.45; }
.proposal-controls { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) 92px auto; gap: 8px; align-items: end; }
.proposal-form label { display: grid; gap: 4px; color: var(--muted); font-size: 12px; }
.proposal-form button { border: 1px solid var(--border); background: var(--button-bg); color: var(--button-text);
                        border-radius: 4px; padding: 8px 10px; cursor: pointer; font: inherit; }
.proposal-form button:hover { background: var(--button-hover); }
.proposal-source-list { display: grid; gap: 10px; margin: 16px 0; }
.proposal-source-card { border: 1px solid var(--border-soft); border-radius: 6px; padding: 10px;
                        background: var(--surface); min-width: 0; display: grid; gap: 6px; }
.proposal-source-card strong { overflow-wrap: anywhere; }
.proposal-source-card button { justify-self: start; border: 1px solid var(--border); background: var(--button-bg);
                               color: var(--button-text); border-radius: 4px; padding: 6px 9px; cursor: pointer; }
.proposal-source-card button:disabled { color: var(--button-disabled); cursor: default; }
.proposal-status { min-height: 1.4em; color: var(--muted); font-family: sans-serif; }
.proposal-results { display: grid; gap: 12px; margin-top: 14px; }
.proposal-card { border: 1px solid var(--border-soft); border-radius: 6px; padding: 12px; background: var(--surface); min-width: 0; }
.proposal-card h3 { margin-top: 0; font-size: 16px; }
.proposal-checklist { display: grid; gap: 5px; margin: 10px 0; padding: 9px 10px;
                      border: 1px solid var(--border-soft); border-radius: 6px; background: var(--surface-soft);
                      color: var(--muted); font-family: sans-serif; font-size: 13px; line-height: 1.4; }
.proposal-checklist strong { color: var(--text); }
.proposal-warning { color: #8a6d3b; font-family: sans-serif; font-size: 13px; line-height: 1.45; }
.proposal-command { display: block; margin-top: 10px; padding: 8px; background: var(--surface-code);
                    border-radius: 4px; white-space: normal; overflow-wrap: anywhere; }
.proposal-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; font-family: sans-serif; }
.proposal-actions button { border: 1px solid var(--border); background: var(--button-bg); color: var(--button-text);
                           border-radius: 4px; padding: 5px 8px; cursor: pointer; font: inherit; }
.proposal-actions button:hover { background: var(--button-hover); }
.proposal-actions button:disabled { color: var(--button-disabled); cursor: default; }
.memory-issues { margin-top: 6px; }
.memory-issues li { border: none; padding: 0; color: var(--muted); font-size: 13px; }
.memory-issues .severity { font-family: sans-serif; font-size: 11px; text-transform: uppercase; color: #8a6d3b; }
.memory-dashboard { margin: 18px 0; }
.memory-dashboard .section-heading { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
.memory-dashboard .section-heading a { font-size: 13px; font-family: sans-serif; font-weight: normal; }
.memory-next { border-left: 3px solid var(--accent); padding: 10px 12px; margin: 12px 0 16px; background: var(--surface-muted); font-family: sans-serif; min-width: 0; }
.memory-next ul { margin: 8px 0 0; padding-left: 18px; }
.memory-next li { margin: 4px 0; }
.memory-next code { white-space: normal; overflow-wrap: anywhere; }
.memory-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; margin: 12px 0; }
.memory-card { border: 1px solid var(--border-soft); border-radius: 6px; padding: 12px; min-width: 0; background: var(--surface); }
.memory-card h3 { margin-top: 0; font-size: 16px; }
.memory-card .memory-metric { font-family: var(--font-serif); font-size: 32px; font-weight: 700; line-height: 1; margin: 4px 0 8px; color: var(--accent); }
.memory-card .summary { color: var(--muted); font-family: sans-serif; font-size: 13px; line-height: 1.5; margin: 8px 0; }
.memory-card .memory-meta { color: var(--subtle); font-size: 12px; font-family: sans-serif; }
.memory-actions { margin-top: 10px; display: grid; gap: 6px; }
.memory-actions div { font-size: 12px; font-family: sans-serif; }
.memory-actions code { display: block; margin-top: 2px; white-space: normal; overflow-wrap: anywhere; }
.memory-action-row { display: grid; gap: 4px; }
.memory-action-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.memory-actions button { border: 1px solid var(--border); background: var(--button-bg); color: var(--button-text);
                         border-radius: 4px; padding: 4px 8px; cursor: pointer; font: inherit; }
.memory-actions button:hover { background: var(--button-hover); }
.memory-actions button:disabled { color: var(--button-disabled); cursor: default; }
.memory-action-result { color: var(--muted); min-height: 1em; }
.copy-button { border: 1px solid var(--border); background: var(--button-bg); color: var(--button-text);
               border-radius: 4px; padding: 4px 8px; cursor: pointer; font: 12px -apple-system, BlinkMacSystemFont, sans-serif;
               margin-left: 8px; vertical-align: middle; }
.copy-button:hover { background: var(--button-hover); }
.copy-button:disabled { color: var(--button-disabled); cursor: default; }
.ingest-path { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; margin: 14px 0 18px; }
.ingest-step { border: 1px solid var(--border-soft); border-radius: 4px; background: var(--surface); padding: 12px; font-family: sans-serif; min-width: 0; }
.ingest-step .step-num { display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; border-radius: 50%; background: var(--accent); color: #fff; font-size: 12px; font-weight: 700; }
.ingest-step h3 { margin: 8px 0 5px; font-size: 15px; }
.ingest-step p { margin: 0 0 8px; color: var(--muted); line-height: 1.4; }
.ingest-step code { white-space: normal; overflow-wrap: anywhere; }
.ingest-progress { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; margin: 14px 0; font-family: sans-serif; }
.ingest-progress-step { border: 1px solid var(--border-soft); border-radius: 6px; padding: 10px; background: var(--surface); min-width: 0; }
.ingest-progress-step strong,
.ingest-progress-step span,
.ingest-progress-step small { display: block; overflow-wrap: anywhere; }
.ingest-progress-step strong { color: var(--text-strong); font-size: 13px; }
.ingest-progress-step span { margin: 4px 0; font-size: 12px; text-transform: uppercase; letter-spacing: 0; color: var(--muted); }
.ingest-progress-step small { color: var(--subtle); line-height: 1.35; }
.ingest-progress-step[data-state="done"] { border-color: var(--success-border); background: var(--success-bg); }
.ingest-progress-step[data-state="next"] { border-color: var(--accent-soft); }
.ingest-progress-step[data-state="blocked"] { border-color: var(--danger-border); background: var(--danger-bg); }
.ingest-completion-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; margin: 14px 0; }
.ingest-completion-card { border: 1px solid var(--border-soft); border-radius: 6px; background: var(--surface); padding: 12px; min-width: 0; font-family: sans-serif; }
.ingest-completion-card h3 { margin: 0 0 8px; font-size: 16px; overflow-wrap: anywhere; }
.ingest-completion-card p { margin: 6px 0; color: var(--muted); line-height: 1.45; font-size: 13px; }
.ingest-completion-card code { white-space: normal; overflow-wrap: anywhere; }
.ingest-completion-pages { display: flex; gap: 6px; flex-wrap: wrap; margin: 8px 0; }
.ingest-completion-pages a { border: 1px solid var(--border-soft); border-radius: 999px; padding: 3px 8px; background: var(--surface-soft); font-size: 12px; }
.ingest-completion-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 10px; }
.ingest-completion-actions a { font-size: 13px; }
.ingest-pending-item { display: grid; grid-template-columns: minmax(150px, 1fr) minmax(180px, 1.2fr) auto; gap: 8px; align-items: center; }
.ingest-pending-actions { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; align-items: center; font-family: sans-serif; font-size: 12px; }
.trust-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 16px 0; }
.trust-grid div { border: 1px solid var(--border-soft); border-radius: 4px; padding: 10px; font-family: sans-serif; background: var(--surface); }
.trust-grid strong { display: block; font-size: 12px; color: var(--subtle); margin-bottom: 4px; }
.prompt-strip { margin: 16px 0; padding: 12px; border: 1px solid var(--border-soft); border-radius: 4px; background: var(--surface-muted); }
.prompt-strip h2 { margin-top: 0; font-size: 17px; }
.prompt-strip p { color: var(--muted); margin-bottom: 10px; }
.prompt-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px; }
.prompt-chip { display: flex; align-items: flex-start; gap: 6px; min-width: 0; }
.prompt-chip code { flex: 1; display: block; padding: 8px; background: var(--surface-code); border-radius: 4px; white-space: normal; overflow-wrap: anywhere; }
.prompt-chip .copy-button { flex: 0 0 auto; }
.onboard-steps { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin: 16px 0 20px; }
.onboard-step { border: 1px solid var(--border-soft); border-radius: 6px; background: var(--surface); padding: 12px; min-width: 0; }
.onboard-step > span { display: inline-grid; place-items: center; width: 26px; height: 26px; border-radius: 999px;
                       border: 1px solid var(--border); background: var(--button-bg); color: var(--text-strong);
                       font: 700 13px -apple-system, BlinkMacSystemFont, sans-serif; margin-bottom: 8px; }
.onboard-step[data-state="done"] { border-color: var(--success-border); background: var(--success-bg); }
.onboard-step[data-state="next"] { border-color: var(--accent-soft); }
.onboard-step h2 { margin: 0 0 6px; border: 0; padding: 0; font: 700 15px -apple-system, BlinkMacSystemFont, sans-serif; }
.onboard-step p { margin: 0 0 10px; color: var(--muted); font: 13px/1.45 -apple-system, BlinkMacSystemFont, sans-serif; }
.onboard-agent-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; margin: 14px 0; }
.onboard-agent-card { border: 1px solid var(--border-soft); border-radius: 6px; background: var(--surface); padding: 12px; min-width: 0; }
.onboard-agent-card h3 { margin: 0 0 6px; font-size: 16px; }
.onboard-agent-card p { color: var(--muted); font: 13px/1.45 -apple-system, BlinkMacSystemFont, sans-serif; margin: 0 0 8px; }
.home-next { margin: 16px 0 20px; }
.home-next h2 { margin-top: 0; font-size: 17px; }
.home-next-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.home-next-card { border: 1px solid var(--border-soft); border-radius: 6px; padding: 11px; background: var(--surface);
                  color: var(--text); text-decoration: none; display: grid; gap: 5px; min-width: 0; }
.home-next-card:hover { background: var(--button-hover); text-decoration: none; }
.home-next-card strong { color: var(--text-strong); font-family: sans-serif; font-size: 14px; }
.home-next-card span { color: var(--muted); font-family: sans-serif; font-size: 12px; line-height: 1.4; }
.health-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; margin: 16px 0 18px; font-family: sans-serif; }
.health-card { border: 1px solid var(--border-soft); border-radius: 6px; background: var(--surface); padding: 12px; min-width: 0; }
.health-card strong,
.health-card span,
.health-card small { display: block; overflow-wrap: anywhere; }
.health-card strong { color: var(--subtle); font-size: 12px; text-transform: uppercase; letter-spacing: 0; }
.health-card span { color: var(--text-strong); font-size: 18px; font-weight: 700; margin: 5px 0 3px; }
.health-card small { color: var(--muted); line-height: 1.35; }
.health-card[data-state="done"] { border-color: var(--success-border); background: var(--success-bg); }
.health-card[data-state="next"] { border-color: var(--accent-soft); }
.health-card[data-state="blocked"] { border-color: var(--danger-border); background: var(--danger-bg); }
.health-next { border: 1px solid var(--border-soft); border-left: 3px solid var(--accent);
               border-radius: 6px; padding: 12px; margin: 14px 0 18px; background: var(--surface); font-family: sans-serif; }
.health-next h2 { margin: 0 0 8px; border: 0; padding: 0; font: 15px -apple-system, BlinkMacSystemFont, sans-serif; }
.health-next p { margin: 0 0 8px; line-height: 1.45; }
.health-next strong,
.health-next span { display: block; overflow-wrap: anywhere; }
.health-next span { color: var(--muted); font-size: 13px; }
.health-next code { display: inline-block; max-width: 100%; white-space: normal; overflow-wrap: anywhere; }
.command-list { list-style: none; margin: 12px 0; padding: 0; display: grid; gap: 8px; }
.command-list li { border: 1px solid var(--border-soft); border-radius: 6px; background: var(--surface); padding: 8px 10px; min-width: 0; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.command-list strong { flex: 1 1 180px; min-width: 0; overflow-wrap: anywhere; }
.command-list code { flex: 1 1 220px; min-width: 0; white-space: normal; overflow-wrap: anywhere; }
.log-entry { white-space: pre-wrap; font-size: 12px; }

mark { background: var(--mark-bg); color: inherit; border-radius: 2px; padding: 0 1px; }

#graph-canvas { width: 100%; height: min(74vh, 860px); min-height: 560px;
                border: 1px solid var(--border); border-radius: 4px; background: var(--surface-graph);
                cursor: grab; display: block; margin: 0; }
#graph-canvas:active { cursor: grabbing; }
#graph-canvas:focus { outline: 2px solid var(--accent-soft); outline-offset: 2px; }
.graph-frame { margin: 12px 0; }
.graph-frame.is-fullscreen { position: fixed; inset: 0; z-index: 200; background: var(--bg); padding: 18px;
                              display: flex; flex-direction: column; overflow: hidden; }
.graph-frame.is-fullscreen .graph-shell { flex: 1; min-height: 0; }
.graph-frame.is-fullscreen #graph-canvas { height: 100%; min-height: 0; }
.graph-frame.is-fullscreen .graph-inspector { max-height: 100%; overflow: auto; }
.graph-focus-note { border-left: 3px solid var(--accent-soft); padding-left: 10px; color: var(--muted); font-family: sans-serif; font-size: 13px; }
.graph-shell { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 12px; align-items: stretch; margin: 12px 0; }
.graph-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
                 margin: 12px 0 8px; font: 13px -apple-system, BlinkMacSystemFont, sans-serif; }
.graph-toolbar button { border: 1px solid var(--border); background: var(--button-bg); color: var(--button-text);
                        border-radius: 4px; padding: 5px 9px; cursor: pointer; }
.graph-toolbar button:hover { background: var(--button-hover); }
.graph-toolbar button[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: #fff; }
.graph-control { display: grid; gap: 3px; color: var(--muted); font-size: 11px; }
.graph-control input,
.graph-control select { border: 1px solid var(--border); background: var(--surface); color: var(--text);
                        border-radius: 4px; padding: 5px 8px; font: 13px -apple-system, BlinkMacSystemFont, sans-serif; }
.graph-control input { width: 180px; }
.graph-control select:disabled { color: var(--button-disabled); cursor: not-allowed; opacity: 0.65; }
.graph-status { color: var(--muted); margin-left: auto; }
.graph-inspector { border: 1px solid var(--border-soft); border-radius: 4px; padding: 12px; font: 13px -apple-system, BlinkMacSystemFont, sans-serif; color: var(--muted); background: var(--surface); }
.graph-inspector strong { display: block; color: var(--text-strong); font-size: 15px; margin-bottom: 6px; overflow-wrap: anywhere; }
.graph-inspector p { margin: 0 0 10px; line-height: 1.4; }
.graph-inspector-links { display: grid; gap: 5px; margin: 10px 0; max-height: 180px; overflow: auto; }
.graph-inspector-links a { overflow-wrap: anywhere; }
.graph-inspector button { border: 1px solid var(--border); background: var(--button-bg); color: var(--button-text); border-radius: 4px; padding: 6px 9px; cursor: pointer; }
.graph-inspector button:disabled { color: var(--button-disabled); cursor: default; }
.graph-tooltip { position: fixed; background: var(--surface); border: 1px solid var(--border); border-radius: 4px;
                 padding: 6px 10px; font-size: 13px; pointer-events: none; display: none;
                 box-shadow: 0 2px 8px var(--shadow); z-index: 100; }
.graph-legend { display: flex; flex-wrap: wrap; gap: 6px; font-size: 12px; color: var(--subtle); font-family: sans-serif; margin-top: 8px; }
.graph-legend-item { border: 1px solid transparent; background: transparent; color: var(--subtle);
                     border-radius: 999px; padding: 3px 7px; cursor: pointer; font: inherit; }
.graph-legend-item:hover,
.graph-legend-item[aria-pressed="true"] { border-color: var(--border); background: var(--button-bg); color: var(--text); }
.graph-legend span { display: inline-block; width: 10px; height: 10px; border-radius: 50%;
                     margin-right: 4px; vertical-align: -1px; }
.graph-empty { border: 1px solid var(--border-soft); border-radius: 4px; padding: 28px; background: var(--surface-empty);
               color: var(--muted); font-family: sans-serif; margin: 12px 0; }

footer { margin-top: 40px; padding-top: 12px; border-top: 1px solid var(--border-soft);
         font-size: 12px; color: var(--faint); font-family: sans-serif; }
@media (max-width: 760px) {
  body { padding: 20px; max-width: 100%; }
  header .header-top { align-items: flex-start; }
  header nav { gap: 10px 14px; }
  header .nav-more { display: inline-flex; }
  header .nav-more-menu { left: 0; right: auto; }
  .wiki-page-shell { display: block; }
  .wiki-page-document { max-width: none; }
  .page-outline { position: static; border: 1px solid var(--border-soft); border-radius: 4px;
                  padding: 10px 12px; margin: 0 0 18px; }
  header .header-tools { justify-items: end; }
  header .theme-toggle { justify-self: end; }
  .home-stats { flex-wrap: wrap; gap: 14px 22px; }
  .product-lanes { grid-template-columns: minmax(0, 1fr); }
  .home-next-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .memory-grid { grid-template-columns: minmax(0, 1fr); }
  .proposal-controls { grid-template-columns: minmax(0, 1fr); }
  .raw-source-controls { grid-template-columns: minmax(0, 1fr); }
  .ingest-pending-item { grid-template-columns: minmax(0, 1fr); align-items: start; }
  .ingest-pending-actions { justify-content: flex-start; }
  .section-heading,
  .memory-dashboard .section-heading { flex-wrap: wrap; }
  .memory-actions code, .memory-next code { word-break: break-word; }
  .graph-shell { grid-template-columns: 1fr; }
  #graph-canvas { min-height: 460px; }
  .graph-frame.is-fullscreen { padding: 12px; }
}
@media (max-width: 560px) {
  header .header-top { flex-wrap: wrap; }
  header .header-tools { flex-basis: 100%; max-width: none; justify-items: stretch; }
  .home-next-grid { grid-template-columns: minmax(0, 1fr); }
  header .theme-toggle { justify-self: end; }
}

/* ============================================================
   Design-handoff component layer (Link Console).
   Appended last so these treatments win the cascade.
   ============================================================ */

/* top nav -> brand + mono tab strip */
.logo a { display: inline-flex; align-items: baseline; gap: 8px; text-decoration: none; }
.logo a, .logo { font-family: var(--font-serif); font-size: 21px; font-weight: 700; color: var(--text-strong); }
.logo img { width: 22px; height: 22px; border: none; background: transparent; border-radius: 5px; align-self: center; }
.logo small { font-family: var(--font-mono); font-size: 10.5px; color: var(--muted); font-weight: 400; margin-left: 2px; }
header { border-bottom: none; padding-bottom: 0; }
header nav { display: flex; gap: 4px; font-family: var(--font-mono); font-size: 12px;
  border-bottom: 1px solid var(--border); margin-top: 10px; }
header nav a { padding: 7px 11px; color: var(--muted); text-decoration: none; border: none; }
header nav a:hover { color: var(--text-strong); }
header nav a[aria-current="page"] { color: var(--text-strong); border-bottom: 2px solid var(--accent);
  font-weight: 600; margin-bottom: -1px; }
header nav .nav-more summary { padding: 7px 11px; color: var(--muted); font-family: var(--font-mono); cursor: pointer; }
.theme-toggle { display: inline-flex; align-items: center; gap: 6px; font-family: var(--font-mono);
  font-size: 10.5px; color: var(--muted); background: transparent; border: 1px solid var(--border);
  border-radius: 99px; padding: 4px 10px; cursor: pointer; }
.theme-toggle:hover { border-color: var(--border-strong); color: var(--text-strong); }
.theme-icon { width: 9px; height: 9px; border-radius: 50%;
  background: linear-gradient(90deg, var(--text-strong) 50%, var(--bg) 50%); border: 1px solid var(--muted); }
#search-input, input[type="text"], input[type="search"] { font-family: var(--font-mono); font-size: 11.5px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 6px 10px; color: var(--text-strong); }
#search-input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(168,73,47,0.15); }
.breadcrumb { font-family: var(--font-mono); font-size: 11px; color: var(--muted); }
.breadcrumb a { color: var(--accent); text-decoration: none; }
.breadcrumb a:hover { text-decoration: underline; }

/* badges / chips / status */
.badge { font-family: var(--font-mono); font-size: 10.5px; color: var(--text-strong);
  border: 1px solid var(--border-strong); border-radius: 3px; padding: 2px 7px; background: transparent; }
.chip { font-family: var(--font-mono); font-size: 10.5px; color: var(--muted);
  background: var(--chip-bg); border-radius: 3px; padding: 3px 7px; }
.status { display: inline-flex; align-items: center; gap: 5px; font-family: var(--font-mono); font-size: 10.5px; }
.status .dot { width: 6px; height: 6px; border-radius: 50%; }
.status--ok { color: var(--ok-fg); }
.status--ok .dot { background: var(--ok); }
.status--caution { color: var(--caution-fg); background: var(--caution-bg-2);
  border: 1px solid var(--caution-border); border-radius: 3px; padding: 3px 8px; }
.status--caution .dot { background: var(--caution); }

/* confidence — segment meter */
.conf { display: inline-flex; align-items: center; gap: 6px; font-family: var(--font-mono);
  font-size: 10.5px; color: var(--text-strong); }
.conf .m { display: inline-flex; gap: 2px; }
.conf .m i { width: 9px; height: 4px; border-radius: 1px; background: var(--meter-off); }
.conf--strong .m i { background: var(--text-strong); }
.conf--moderate .m i:nth-child(-n+2) { background: var(--text-strong); }
.conf--weak { color: var(--caution-fg); }
.conf--weak .m i { background: var(--meter-off-caution); }
.conf--weak .m i:first-child { background: var(--caution); }
.verify-note { font-family: var(--font-mono); font-size: 11px; color: var(--caution-fg);
  background: var(--caution-bg); border-radius: 4px; padding: 7px 10px; }

/* memory cards -> ledger */
.memory-card { background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
  padding: 16px 18px; box-shadow: none; }
.memory-card:hover { border-color: var(--border-strong); }
.memory-card h3, .memory-card h4 { font-family: var(--font-serif); font-size: 17px; line-height: 1.25; }
.memory-card.needs-review, .memory-card.pending { border-color: var(--caution-border); }
.memory-meta { font-family: var(--font-mono); font-size: 10.5px; color: var(--muted); }

/* stat grid -> stat row */
.home-stats { display: flex; background: var(--surface); border: 1px solid var(--border);
  border-radius: 6px; padding: 16px 22px; gap: 0; }
.home-stats .stat { padding: 0 24px; border-left: 1px solid var(--border); background: transparent; border-top: none; border-right: none; border-bottom: none; }
.home-stats .stat:first-child { padding-left: 0; border-left: none; }
.home-stats .num { font-family: var(--font-serif); font-size: 30px; color: var(--text-strong); }
.home-stats .label { font-family: var(--font-mono); font-size: 10.5px; color: var(--muted); }
.home-stats .num--alert { color: var(--accent); }
.memory-action-row { justify-items: start; }
.memory-action-row button { width: auto; }

/* health data-state tints -> plain surface with colored border only */
.health-card[data-state="done"] { background: var(--surface); border-color: var(--border); }
.health-card[data-state="next"] { background: var(--surface); border-color: var(--caution-border); }
.health-card[data-state="blocked"] { background: var(--surface); border-color: var(--caution-border); }
/* readiness key/value rows */
.wiki-page-document li > strong + span, li > strong + span { margin-left: 8px; color: var(--muted); font-family: var(--font-mono); font-size: 12px; }


/* health cards */
.health-cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.health-card { background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
  padding: 15px 17px; box-shadow: none; }
.health-card.warn, .health-card.caution { border-color: var(--caution-border); background: var(--surface); }
.health-card .label, .health-card small { font-family: var(--font-mono); font-size: 10px;
  letter-spacing: 0.08em; color: var(--muted); text-transform: uppercase; }
.health-card strong, .health-card b { font-family: var(--font-serif); font-size: 20px;
  color: var(--text-strong); font-weight: 400; }

/* command blocks + copy */
pre { background: var(--surface-code); color: var(--surface-code-ink); border: 1px solid var(--border);
  border-radius: 5px; font-family: var(--font-mono); }
pre code { color: var(--surface-code-ink); background: transparent; }
.copy-button, .cmd-copy { font-family: var(--font-mono); font-size: 11px; background: var(--accent);
  color: var(--accent-fg); border: none; border-radius: 4px; padding: 4px 12px; cursor: pointer; font-weight: 600; }
.copy-button:hover, .cmd-copy:hover { filter: brightness(1.08); background: var(--accent); color: var(--accent-fg); }
.copy-button:active { transform: translateY(1px); }
.prompt-chip { display: flex; align-items: stretch; border: 1px solid var(--border); border-radius: 5px;
  overflow: hidden; background: var(--surface); box-shadow: none; }
.prompt-chip code, .prompt-chip .prompt-text { font-family: var(--font-mono); font-size: 11.5px;
  color: var(--text-strong); padding: 9px 11px; white-space: nowrap; overflow-x: auto; background: transparent; }
.prompt-chip .copy-button { background: transparent; color: var(--accent);
  border-left: 1px solid var(--border); border-radius: 0; font-weight: 400; }
.prompt-chip .copy-button:hover { background: var(--chip-bg); filter: none; }

/* empty states */
.empty-state { border: 1px dashed var(--border-strong); border-radius: 6px; background: transparent;
  padding: 18px; color: var(--muted); }

/* onboard checklist */
.onboard-step { background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
  padding: 12px 14px; box-shadow: none; }
.onboard-step .step-num { font-family: var(--font-mono); font-size: 10.5px; color: var(--muted); }

/* buttons */
.button-link, button:not(.copy-button):not(.theme-toggle):not(.cmd-copy):not(.graph-control) {
  font-family: var(--font-mono); font-size: 11px; border-radius: 4px; padding: 6px 12px; cursor: pointer;
  background: transparent; color: var(--text-strong); border: 1px solid var(--border-strong); }
.button-link:hover, button:not(.copy-button):not(.theme-toggle):not(.cmd-copy):not(.graph-control):hover {
  background: var(--chip-bg); }
"""

THEME_INIT_JS = """
(function() {
  try {
    var params = new URLSearchParams(window.location.search);
    var override = params.get('theme');
    if (override === 'dark' || override === 'light') {
      localStorage.setItem('link-theme', override);
    }
    var theme = localStorage.getItem('link-theme') || 'system';
    if (theme === 'dark' || theme === 'light') {
      document.documentElement.dataset.theme = theme;
    }
  } catch (err) {}
})();
"""

THEME_CONTROL_JS = """
(function() {
  var modes = ['system', 'dark', 'light'];
  var button = document.querySelector('[data-theme-toggle]');
  var media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  function systemTheme() {
    return media && media.matches ? 'dark' : 'light';
  }

  function storedTheme() {
    try {
      return localStorage.getItem('link-theme') || 'system';
    } catch (err) {
      return 'system';
    }
  }

  function saveTheme(theme) {
    try {
      localStorage.setItem('link-theme', theme);
    } catch (err) {}
  }

  function applyTheme(theme) {
    if (theme === 'dark' || theme === 'light') {
      document.documentElement.dataset.theme = theme;
    } else {
      delete document.documentElement.dataset.theme;
    }
    if (!button) return;
    var active = theme === 'system' ? systemTheme() : theme;
    var text = button.querySelector('[data-theme-text]');
    if (text) {
      text.textContent = theme;
    } else {
      button.textContent = theme;
    }
    button.title = 'Theme: ' + theme + ' (' + active + ')';
    button.setAttribute('aria-label', 'Theme: ' + theme + ' (' + active + '). Click to switch.');
  }

  applyTheme(storedTheme());

  if (button) {
    button.addEventListener('click', function() {
      var current = storedTheme();
      var next = modes[(modes.indexOf(current) + 1) % modes.length] || 'system';
      saveTheme(next);
      applyTheme(next);
    });
  }

  if (media && media.addEventListener) {
    media.addEventListener('change', function() {
      if (storedTheme() === 'system') applyTheme('system');
    });
  }
})();
"""

MEMORY_ACTION_JS = """
(function() {
  var endpoints = {
    review: '/api/review-memory',
    archive: '/api/archive-memory',
    restore: '/api/restore-memory'
  };
  var buttons = Array.from(document.querySelectorAll('[data-memory-action]'));
  if (!buttons.length) return;

  function resultFor(button) {
    var row = button.closest('.memory-action-row') || button.parentElement;
    var result = row ? row.querySelector('.memory-action-result') : null;
    if (!result && row) {
      result = document.createElement('span');
      result.className = 'memory-action-result';
      row.appendChild(result);
    }
    return result;
  }

  buttons.forEach(function(button) {
    button.addEventListener('click', async function() {
      var action = button.getAttribute('data-memory-action') || '';
      var endpoint = endpoints[action];
      var memory = button.getAttribute('data-memory') || '';
      var result = resultFor(button);
      if (!endpoint || !memory) return;

      var payload = {memory: memory};
      if (action === 'review' && !window.confirm('Mark this memory as reviewed?')) return;
      if (action === 'archive') {
        var reason = window.prompt('Archive reason', 'stale');
        if (reason === null) return;
        payload.reason = reason;
      }
      if (action === 'restore' && !window.confirm('Restore this memory to active recall?')) return;

      button.disabled = true;
      if (result) result.textContent = 'Updating...';
      try {
        var response = await fetch(endpoint, {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-Link-Local-Action': 'true'},
          body: JSON.stringify(payload)
        });
        var data = await response.json();
        if (!response.ok) {
          throw new Error(data.error || 'memory action failed');
        }
        if (result) result.textContent = 'Updated. Refreshing...';
        window.setTimeout(function() { window.location.reload(); }, 450);
      } catch (err) {
        if (result) result.textContent = err.message || 'memory action failed';
        button.disabled = false;
      }
    });
  });
})();
"""

COPY_BUTTON_JS = """
(function() {
  var buttons = Array.from(document.querySelectorAll('[data-copy-text]'));
  if (!buttons.length) return;

  async function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
    var textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', 'true');
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
  }

  buttons.forEach(function(button) {
    button.addEventListener('click', async function() {
      var label = button.textContent || 'Copy';
      var text = button.getAttribute('data-copy-text') || '';
      if (!text) return;
      button.disabled = true;
      try {
        await copyText(text);
        button.textContent = 'Copied';
      } catch (err) {
        button.textContent = 'Copy failed';
      }
      window.setTimeout(function() {
        button.textContent = label;
        button.disabled = false;
      }, 1200);
    });
  });
})();
"""

RAW_SOURCE_JS = """
(function() {
  var form = document.querySelector('[data-raw-source-form]');
  if (!form) return;
  var statusEl = document.querySelector('[data-raw-source-status]');

  function setStatus(text, tone) {
    if (!statusEl) return;
    statusEl.textContent = text || '';
    statusEl.dataset.tone = tone || '';
  }

  async function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
    var textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', 'true');
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
  }

  function renderSaved(data) {
    if (!statusEl) return;
    statusEl.textContent = '';
    var saved = document.createElement('span');
    saved.textContent = 'Saved ' + (data.path || 'raw source') + '. Next: ';
    statusEl.appendChild(saved);
    var code = document.createElement('code');
    code.textContent = data.next_prompt || '';
    statusEl.appendChild(code);
    var copy = document.createElement('button');
    copy.type = 'button';
    copy.textContent = 'Copy ingest prompt';
    copy.addEventListener('click', async function() {
      var label = copy.textContent;
      copy.disabled = true;
      try {
        await copyText(data.next_prompt || '');
        copy.textContent = 'Copied';
      } catch (err) {
        copy.textContent = 'Copy failed';
      }
      window.setTimeout(function() {
        copy.textContent = label;
        copy.disabled = false;
      }, 1200);
    });
    statusEl.appendChild(copy);
    var refresh = document.createElement('a');
    refresh.href = '/ingest';
    refresh.textContent = ' refresh ingest status';
    statusEl.appendChild(refresh);
  }

  form.addEventListener('submit', async function(event) {
    event.preventDefault();
    var button = form.querySelector('button[type=\"submit\"]');
    if (button) button.disabled = true;
    setStatus('Saving source locally...');
    try {
      var payload = {
        title: form.elements.title.value || '',
        filename: form.elements.filename.value || '',
        text: form.elements.text.value || ''
      };
      var response = await fetch('/api/raw-source', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Link-Local-Action': 'true'
        },
        body: JSON.stringify(payload)
      });
      var data = await response.json();
      if (!response.ok) throw new Error(data.error || 'source save failed');
      form.reset();
      renderSaved(data);
    } catch (error) {
      setStatus(error.message || 'source save failed', 'error');
    } finally {
      if (button) button.disabled = false;
    }
  });
})();
"""

PROPOSAL_UI_JS = """
(function() {
  var form = document.querySelector('[data-proposal-form]');
  if (!form) return;
  var statusEl = document.querySelector('[data-proposal-status]');
  var resultsEl = document.querySelector('[data-proposal-results]');
  var sourceListEl = document.querySelector('[data-proposal-sources]');

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text || '';
  }

  function addText(parent, tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = text || '';
    parent.appendChild(node);
    return node;
  }

  function candidateNames(items) {
    return (items || []).map(function(item) {
      return item.name || item.title || '';
    }).filter(Boolean).join(', ');
  }

  function renderSources(data) {
    if (!sourceListEl) return;
    sourceListEl.textContent = '';
    if (!data || !data.sources || !data.sources.length) {
      addText(sourceListEl, 'p', 'summary', 'No local raw text sources found yet.');
      return;
    }
    data.sources.forEach(function(source) {
      var card = document.createElement('article');
      card.className = 'proposal-source-card';
      addText(card, 'strong', '', source.title || source.path || 'raw source');
      addText(card, 'div', 'memory-meta', [
        source.path || '',
        source.size ? source.size + ' bytes' : '',
        source.warning_count ? source.warning_count + ' warning' + (source.warning_count === 1 ? '' : 's') : ''
      ].filter(Boolean).join(' · '));
      if (source.snippet) addText(card, 'p', 'summary', source.snippet);
      if (source.secret_warnings && source.secret_warnings.length) {
        addText(card, 'p', 'proposal-warning', 'Secret-looking values: ' + source.secret_warnings.join(', '));
      }
      if (source.error) {
        addText(card, 'p', 'proposal-warning', 'Cannot load source: ' + source.error);
      }
      if (source.truncated) {
        addText(card, 'p', 'proposal-warning', 'Large source: split or summarize it before loading into the proposal form.');
      }
      var button = document.createElement('button');
      button.type = 'button';
      button.textContent = source.action_label || (source.loadable ? 'Use in form' : (source.warning_count ? 'Redact first' : 'Too large'));
      button.disabled = !source.loadable;
      button.setAttribute('data-proposal-source', source.path || '');
      card.appendChild(button);
      sourceListEl.appendChild(card);
    });
  }

  async function loadSource(path) {
    setStatus('Loading ' + path + '...');
    try {
      var response = await fetch('/api/proposal-source?path=' + encodeURIComponent(path));
      var data = await response.json();
      if (!response.ok) throw new Error(data.error || 'source load failed');
      form.elements.text.value = data.text || '';
      form.elements.source.value = data.source || path;
      setStatus('Loaded ' + (data.path || path) + '. Nothing was written.');
    } catch (error) {
      setStatus(error.message || 'source load failed');
    }
  }

  function approvalPrompt(proposal) {
    if (proposal.primary_action && proposal.primary_action.prompt) {
      return proposal.primary_action.prompt;
    }
    var memory = proposal.memory || '';
    if (proposal.suggested_action === 'update-memory' && proposal.duplicate_candidates && proposal.duplicate_candidates.length) {
      var target = proposal.duplicate_candidates[0].name || proposal.duplicate_candidates[0].title || '<memory>';
      return 'Approve by asking: update memory ' + target + ' with "' + memory + '"';
    }
    return 'Approve by asking: remember that ' + memory;
  }

  function addCopyButton(parent, label, text) {
    if (!text) return;
    var button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.addEventListener('click', async function() {
      try {
        await navigator.clipboard.writeText(text);
        button.textContent = 'Copied';
        window.setTimeout(function() { button.textContent = label; }, 1200);
      } catch (error) {
        button.textContent = 'Select text above';
        window.setTimeout(function() { button.textContent = label; }, 1600);
      }
    });
    parent.appendChild(button);
  }

  function firstCandidateName(items) {
    if (!items || !items.length) return '';
    return items[0].name || items[0].title || '';
  }

  function approvalEndpoint(proposal) {
    var action = proposal.primary_action || {};
    if (action.kind === 'remember' && !(proposal.conflict_candidates && proposal.conflict_candidates.length)) {
      return '/api/remember-memory';
    }
    if (action.kind === 'update' && firstCandidateName(proposal.duplicate_candidates)) {
      return '/api/update-memory';
    }
    return '';
  }

  function approvalPayload(proposal) {
    var endpoint = approvalEndpoint(proposal);
    if (endpoint === '/api/update-memory') {
      return {
        memory: firstCandidateName(proposal.duplicate_candidates),
        text: proposal.memory || '',
        source: proposal.source || 'web approval',
        project: proposal.project || ''
      };
    }
    return {
      memory: proposal.memory || '',
      title: proposal.title || '',
      memory_type: proposal.memory_type || 'note',
      scope: proposal.scope || 'user',
      source: proposal.source || 'web approval',
      project: proposal.project || ''
    };
  }

  function addApproveButton(parent, proposal) {
    var endpoint = approvalEndpoint(proposal);
    if (!endpoint) {
      var blocked = document.createElement('button');
      blocked.type = 'button';
      blocked.disabled = true;
      blocked.textContent = 'Manual review required';
      blocked.title = 'Copy the approval prompt and resolve duplicates or conflicts with your agent.';
      parent.appendChild(blocked);
      return;
    }
    var button = document.createElement('button');
    button.type = 'button';
    button.textContent = endpoint === '/api/update-memory' ? 'Approve update' : 'Approve and save';
    button.title = 'Writes durable local memory only after this explicit approval.';
    button.addEventListener('click', async function() {
      var message = endpoint === '/api/update-memory'
        ? 'Update the existing memory with this proposal?'
        : 'Save this proposal as durable local memory?';
      if (!window.confirm(message)) return;
      button.disabled = true;
      button.textContent = 'Saving...';
      try {
        var response = await fetch(endpoint, {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-Link-Local-Action': 'true'},
          body: JSON.stringify(approvalPayload(proposal))
        });
        var data = await response.json();
        if (!response.ok) throw new Error(data.error || data.message || 'memory save failed');
        button.textContent = 'Saved';
        setStatus('Saved ' + (data.title || data.name || 'memory') + '. Review it in the memory inbox.');
      } catch (error) {
        button.disabled = false;
        button.textContent = endpoint === '/api/update-memory' ? 'Approve update' : 'Approve and save';
        setStatus(error.message || 'memory save failed');
      }
    });
    parent.appendChild(button);
  }

  function renderProposals(data) {
    if (!resultsEl) return;
    resultsEl.textContent = '';
    if (!data || data.error) {
      addText(resultsEl, 'p', 'summary', data && data.error ? data.error : 'No response.');
      return;
    }
    if (!data.proposals || !data.proposals.length) {
      addText(resultsEl, 'p', 'summary', 'No durable memory candidates found. Keep this as source-backed wiki knowledge unless there is a clear preference, decision, or project fact.');
      return;
    }
    data.proposals.forEach(function(proposal) {
      var card = document.createElement('article');
      card.className = 'proposal-card';
      addText(card, 'h3', '', proposal.title || 'Memory proposal');
      addText(card, 'div', 'memory-meta', [
        proposal.memory_type || 'note',
        proposal.scope || 'user',
        proposal.confidence || 'unknown confidence',
        proposal.suggested_action || 'remember'
      ].filter(Boolean).join(' · '));
      addText(card, 'p', 'summary', proposal.memory || '');
      if (proposal.reason) addText(card, 'p', 'summary', proposal.reason);
      var duplicates = candidateNames(proposal.duplicate_candidates);
      if (duplicates) addText(card, 'p', 'proposal-warning', 'Possible duplicate: ' + duplicates);
      var conflicts = candidateNames(proposal.conflict_candidates);
      if (conflicts) addText(card, 'p', 'proposal-warning', 'Possible conflict: ' + conflicts);
      var action = proposal.primary_action || {};
      if (action.label) addText(card, 'p', 'summary', action.label + ': ' + (action.description || ''));
      addText(card, 'p', 'proposal-warning', 'Proposal-only: no durable memory has been written yet.');
      var checklist = document.createElement('div');
      checklist.className = 'proposal-checklist';
      addText(checklist, 'strong', '', 'Review gate');
      addText(checklist, 'span', '', 'Save only if this is a durable preference, decision, fact, or project context.');
      addText(checklist, 'span', '', 'Check scope, project, source label, duplicates, and conflicts before approval.');
      addText(checklist, 'span', '', conflicts ? 'Conflict found: use the approval prompt instead of direct save.' : 'Direct save still requires explicit approval.');
      card.appendChild(checklist);
      var promptText = approvalPrompt(proposal);
      var prompt = addText(card, 'code', 'proposal-command', promptText);
      prompt.setAttribute('title', 'Copy this into your agent chat if you approve the memory.');
      if (action.command) {
        var command = addText(card, 'code', 'proposal-command', action.command);
        command.setAttribute('title', 'Equivalent local command.');
      }
      var actions = document.createElement('div');
      actions.className = 'proposal-actions';
      addApproveButton(actions, proposal);
      addCopyButton(actions, 'Copy approval prompt', promptText);
      addCopyButton(actions, 'Copy CLI command', action.command || '');
      card.appendChild(actions);
      resultsEl.appendChild(card);
    });
  }

  form.addEventListener('submit', async function(event) {
    event.preventDefault();
    var text = form.elements.text.value || '';
    if (!text.trim()) {
      setStatus('Paste source or session notes first.');
      return;
    }
    setStatus('Proposing memories...');
    if (resultsEl) resultsEl.textContent = '';
    try {
      var response = await fetch('/api/propose-memories', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          text: text,
          source: form.elements.source.value || 'web proposal',
          project: form.elements.project.value || '',
          limit: form.elements.limit.value || '10'
        })
      });
      var data = await response.json();
      if (!response.ok) throw new Error(data.error || 'proposal failed');
      setStatus(data.count + ' proposal' + (data.count === 1 ? '' : 's') + ' found. Nothing was written.');
      renderProposals(data);
    } catch (error) {
      setStatus(error.message || 'proposal failed');
    }
  });

  if (sourceListEl) {
    sourceListEl.addEventListener('click', function(event) {
      var button = event.target.closest('[data-proposal-source]');
      if (!button || button.disabled) return;
      loadSource(button.getAttribute('data-proposal-source') || '');
    });
    fetch('/api/proposal-sources')
      .then(function(response) { return response.json(); })
      .then(renderSources)
      .catch(function() {
        renderSources({sources: []});
      });
  }
  var initialSource = form.getAttribute('data-initial-source') || '';
  if (initialSource) {
    loadSource(initialSource);
  }
})();
"""
