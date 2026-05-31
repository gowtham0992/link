import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.web_prompts import render_prompts_page  # noqa: E402


def _layout(title: str, body: str) -> str:
    return f"<title>{title}</title>{body}"


def test_render_prompts_page_shows_project_and_commands():
    payload = {
        "project": "client-launch",
        "shortcut": "lnk next /tmp/link",
        "prompts": [{"label": "Readiness", "prompt": "is Link ready?", "when": "Before work"}],
        "commands": ["lnk health"],
    }

    html = render_prompts_page(payload, layout=_layout)

    assert "<title>Starter Prompts</title>" in html
    assert "Project examples are scoped to <code>client-launch</code>" in html
    assert "One Command" in html
    assert "Use this any time you forget what to ask next." in html
    assert "lnk next /tmp/link" in html
    assert 'data-copy-text="lnk next /tmp/link"' in html
    assert "Ask Your Agent" in html
    assert "Local Checks" in html
    assert "is Link ready?" in html
    assert 'data-copy-text="is Link ready?"' in html
    assert "Before work" in html
    assert "lnk health" in html
    assert 'data-copy-text="lnk health"' in html


def test_render_prompts_page_escapes_payload_fields():
    payload = {
        "project": "<project>",
        "prompts": [{"label": "<label>", "prompt": "ingest raw/<file>", "when": "<when>"}],
        "commands": ["lnk query '<topic>'"],
    }

    html = render_prompts_page(payload, layout=_layout)

    assert "&lt;project&gt;" in html
    assert "&lt;label&gt;" in html
    assert "ingest raw/&lt;file&gt;" in html
    assert 'data-copy-text="ingest raw/&lt;file&gt;"' in html
    assert "&lt;when&gt;" in html
    assert "lnk query &#x27;&lt;topic&gt;&#x27;" in html
    assert "<project>" not in html


def test_render_prompts_page_uses_personal_copy_without_project():
    html = render_prompts_page({"prompts": [], "commands": []}, layout=_layout)

    assert "personal Link wiki" in html
    assert "?project=slug" in html
