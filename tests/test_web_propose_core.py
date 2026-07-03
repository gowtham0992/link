import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.web_propose import render_propose_page  # noqa: E402


def _layout(title: str, body: str) -> str:
    return f"<title>{title}</title>{body}"


def test_render_propose_page_shows_review_only_workflow():
    html = render_propose_page("link", "raw/first-memory.md", layout=_layout)

    assert "<title>Propose Memories</title>" in html
    assert "without writing anything" in html
    assert "Save only preferences" in html
    assert "Review Gate" in html
    assert "Before saving memory" in html
    assert "ordinary facts in wiki pages" in html
    assert "Memory proposal path" in html
    assert "Approve explicitly" in html
    assert "This step never writes durable memory" in html
    assert "After Approval" in html
    assert "Open memory inbox" in html
    assert "Open memory audit" in html
    assert 'data-copy-text="start with Link before we continue"' in html
    assert 'data-copy-text="query Link for what you remember about this task"' in html
    assert 'data-proposal-sources' in html
    assert 'data-proposal-form' in html
    assert 'data-initial-source="raw/first-memory.md"' in html
    assert 'data-proposal-results' in html
    assert 'value="link"' in html


def test_render_propose_page_escapes_seed_values():
    html = render_propose_page('<project>', 'raw/<source>.md', layout=_layout)

    assert 'value="&lt;project&gt;"' in html
    assert 'data-initial-source="raw/&lt;source&gt;.md"' in html
    assert "<project>" not in html
    assert "raw/<source>.md" not in html
