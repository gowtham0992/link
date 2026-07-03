import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.web_home import plural_type_label, render_home_page  # noqa: E402


def _layout(title: str, body: str) -> str:
    return f"<title>{title}</title>{body}"


def test_plural_type_label_handles_irregular_labels():
    assert plural_type_label("source") == "sources"
    assert plural_type_label("concept") == "concepts"
    assert plural_type_label("entity") == "entities"
    assert plural_type_label("memory") == "memories"


def test_render_home_page_shows_stats_sections_and_prompts():
    pages = [
        {"name": "index", "title": "Index", "type": "", "category": "root"},
        {
            "name": "agent-memory",
            "title": "Agent Memory",
            "type": "concept",
            "category": "concepts",
            "date_updated": "2026-05-01",
        },
        {
            "name": "local-memory",
            "title": "Local Memory",
            "type": "memory",
            "category": "memories",
            "date_updated": "2026-05-02",
        },
    ]
    prompts = {"prompts": [{"prompt": "is Link ready?"}, {"prompt": "ingest raw/<file> into Link"}]}

    html = render_home_page(
        pages,
        starter_prompts=prompts,
        page_href=lambda name: f"/page/{name}",
        layout=_layout,
    )

    assert "<title>Link</title>" in html
    assert "Local agent memory. Knowledge compounds here." in html
    assert '<span class="label">memories</span>' in html
    assert '<h2>concepts</h2>' in html
    assert "/page/agent-memory" in html
    assert "Try These Prompts" in html
    assert "is Link ready?" in html
    assert 'data-copy-text="is Link ready?"' in html
    assert "ingest raw/&lt;file&gt; into Link" in html
    assert 'data-copy-text="ingest raw/&lt;file&gt; into Link"' in html
    assert "Next Steps" in html
    assert "Recently Updated" in html
    assert html.index("Local Memory") < html.index("Agent Memory")
    assert "updated 2026-05-02" in html
    assert 'href="/onboard"' in html
    assert 'href="/health"' in html
    assert 'href="/ingest"' in html
    assert 'href="/memory"' in html
    assert 'href="/graph"' in html
    assert "Index" not in html


def test_render_home_page_escapes_page_fields():
    pages = [
        {"name": "bad", "title": "<script>", "type": "<concept>", "category": "<concepts>"},
    ]

    html = render_home_page(pages, starter_prompts={"prompts": []}, page_href=lambda name: f"/page/{name}", layout=_layout)

    assert "&lt;concepts&gt;" in html
    assert "&lt;script&gt;" in html
    assert "&lt;concept&gt;" in html
    assert "<script>" not in html


def test_render_home_page_handles_empty_wiki():
    html = render_home_page([], starter_prompts={"prompts": []}, page_href=lambda name: f"/page/{name}", layout=_layout)

    assert "Wiki is empty" in html
    assert 'href="/ingest"' in html
    assert 'data-copy-text="ingest the new raw Link files"' in html
    assert "Copy ingest prompt" in html
