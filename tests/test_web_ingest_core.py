import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.web_ingest import copy_button, render_ingest_page  # noqa: E402


def _layout(title: str, body: str) -> str:
    return f"<title>{title}</title>{body}"


def _page_href(name: str) -> str:
    return f"/page/{name}"


def test_copy_button_escapes_text_and_label():
    html = copy_button('lnk "<raw>"', "<Copy>")

    assert 'data-copy-text="lnk &quot;&lt;raw&gt;&quot;"' in html
    assert "&lt;Copy&gt;" in html
    assert "<raw>" not in html


def test_render_ingest_page_shows_pending_workflow():
    payload = {
        "raw_count": 1,
        "represented_count": 0,
        "pending_count": 1,
        "stale_count": 0,
        "backlinks_status": "current",
        "guidance": {
            "state": "pending_raw",
            "summary": "1 raw file needs ingest.",
            "agent_prompt": "ingest raw/new-source.md into Link",
            "commands": ["lnk validate"],
            "notes": ["After ingest, validate."],
        },
        "safety": {"status": "clear", "summary": "No secret-looking values detected in raw sources.", "labels": []},
        "pending_raw": [{"raw": "raw/new-source.md", "size_bytes": 123}],
        "represented_raw": [],
        "plan": {
            "title": "Ingest pending raw sources",
            "summary": "Start with raw/new-source.md.",
            "memory_prompt": "propose memories from raw/new-source.md",
            "steps": ["Read each raw file."],
            "batch": [{"raw": "raw/new-source.md", "suggested_source_page": "wiki/sources/new-source.md"}],
            "post_checks": ["lnk validate"],
        },
    }

    html = render_ingest_page(payload, page_href=_page_href, layout=_layout)

    assert "<title>Ingest</title>" in html
    assert "Add Raw Source" in html
    assert "Raw safety: clear" in html
    assert 'aria-label="Ingest progress"' in html
    assert '<strong>Source</strong><span>done</span><small>1 raw file</small>' in html
    assert '<strong>Ingest</strong><span>next</span><small>0 represented · 1 pending</small>' in html
    assert '<strong>Validate</strong><span>wait</span><small>graph current</small>' in html
    assert "Copy this into your agent chat" in html
    assert 'data-copy-text="ingest raw/new-source.md into Link"' in html
    assert 'data-copy-text="lnk validate"' in html
    assert "Ingest path" in html
    assert "Ingest pending raw sources" in html
    assert "wiki/sources/new-source.md" in html
    assert "/propose?source=raw/new-source.md" in html
    assert "Copy ingest prompt" in html
    assert 'data-copy-text="ingest raw/new-source.md into Link"' in html
    assert "After ingest, validate." in html


def test_render_ingest_page_shows_completion_with_page_links():
    payload = {
        "raw_count": 1,
        "represented_count": 1,
        "pending_count": 0,
        "stale_count": 0,
        "backlinks_status": "current",
        "guidance": {"state": "ready", "summary": "All raw files are represented."},
        "safety": {"status": "clear", "summary": "No warnings.", "labels": []},
        "pending_raw": [],
        "represented_raw": [{"raw": "raw/represented-source.md"}],
        "completion": {
            "title": "Ingest completion",
            "summary": "All 1 raw source(s) are represented.",
            "items": [
                {
                    "raw": "raw/represented-source.md",
                    "size_bytes": 42,
                    "source_pages": [
                        {"name": "represented-source", "title": "Represented Source", "path": "wiki/sources/represented-source.md"}
                    ],
                    "memory_prompt": "propose memories from raw/represented-source.md",
                    "query_prompt": "query Link for represented source",
                }
            ],
            "next_prompt": "start with Link before we continue",
        },
    }

    html = render_ingest_page(payload, page_href=_page_href, layout=_layout)

    assert "Ingest completion" in html
    assert '<strong>Ingest</strong><span>done</span><small>1 represented · 0 pending</small>' in html
    assert '<strong>Validate</strong><span>done</span><small>graph current</small>' in html
    assert '<strong>Memory</strong><span>next</span><small>proposal review optional</small>' in html
    assert "All 1 raw source(s) are represented." in html
    assert "/page/represented-source" in html
    assert "Represented Source" in html
    assert "/propose?source=raw/represented-source.md" in html
    assert 'data-copy-text="propose memories from raw/represented-source.md"' in html
    assert 'data-copy-text="query Link for represented source"' in html
    assert "start with Link before we continue" in html


def test_render_ingest_page_targets_next_step_commands():
    payload = {
        "target": "/tmp/link",
        "raw_count": 0,
        "represented_count": 0,
        "pending_count": 0,
        "stale_count": 0,
        "backlinks_status": "current",
        "guidance": {
            "state": "empty",
            "summary": "Link is ready, but raw/ has no source files yet.",
            "commands": ["lnk ingest-status /tmp/link"],
        },
        "safety": {"status": "clear", "summary": "No warnings.", "labels": []},
        "pending_raw": [],
        "represented_raw": [],
        "plan": {"state": "empty", "title": "Add first sources", "steps": [], "batch": [], "post_checks": []},
    }

    html = render_ingest_page(payload, page_href=_page_href, layout=_layout)

    assert 'data-copy-text="lnk ingest-status /tmp/link"' in html
    assert "<code>lnk validate /tmp/link</code>" in html


def test_render_ingest_page_blocks_secret_raw_without_proposal_link():
    payload = {
        "raw_count": 1,
        "represented_count": 0,
        "pending_count": 1,
        "stale_count": 0,
        "backlinks_status": "current",
        "guidance": {"state": "blocked_secrets", "summary": "Redact raw sources before ingest."},
        "safety": {"status": "blocked", "summary": "Secret-looking values detected.", "labels": ["OpenAI API key"]},
        "pending_raw": [
            {"raw": "raw/secret-note.md", "size_bytes": 10, "secret_warnings": ["OpenAI API key"]},
        ],
        "represented_raw": [],
    }

    html = render_ingest_page(payload, page_href=_page_href, layout=_layout)

    assert "Raw safety: blocked" in html
    assert '<strong>Source</strong><span>blocked</span><small>1 raw file</small>' in html
    assert '<strong>Ingest</strong><span>blocked</span><small>0 represented · 1 pending</small>' in html
    assert 'data-copy-text="edit raw/secret-note.md"' in html
    assert "redact secret-looking values in raw/secret-note.md before ingest" in html
    assert "Copy redaction prompt" in html
    assert "secret warning: OpenAI API key" in html
    assert "/propose?source=raw/secret-note.md" not in html
