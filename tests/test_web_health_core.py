import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.web_health import render_health_page  # noqa: E402


def _layout(title: str, body: str) -> str:
    return f"<title>{title}</title>{body}"


def test_render_health_page_shows_readiness_operations_and_commands(tmp_path):
    wiki = tmp_path / "wiki"
    html = render_health_page(
        {
            "wiki": str(wiki),
            "ready": False,
            "content_page_count": 12,
            "memory_count": 2,
            "active_memory_count": 2,
            "needs_review_count": 1,
            "search_backend": "sqlite-fts",
            "persistent_cache": {"enabled": True, "reused_records": 10, "total_records": 12},
            "schema": {"status": "current"},
            "validation": {"checked": True, "passed": False},
            "warnings": [{"code": "stale_operations", "message": "1 operation needs review.", "detail": "remember"}],
            "next_actions": [{"label": "validate wiki", "tool": "validate_wiki"}],
        },
        {
            "wiki": str(wiki),
            "operation_count": 1,
            "stale_count": 1,
            "active_count": 0,
            "next_actions": [
                {
                    "label": "inspect operation marker files before deleting them",
                    "command": f"lnk operations {tmp_path}",
                }
            ],
            "operations": [{"operation": "remember", "description": "Save memory", "marker": "remember-1.json"}],
        },
        layout=_layout,
    )

    assert "<h1>Health</h1>" in html
    assert 'aria-label="Health summary"' in html
    assert '<strong>Readiness</strong><span>needs attention</span><small>12 content pages</small>' in html
    assert '<strong>Validation</strong><span>failed</span><small>0 errors · 0 warnings</small>' in html
    assert '<strong>Operations</strong><span>needs review</span><small>1 stale · 0 active</small>' in html
    assert '<strong>Memory Review</strong><span>1 pending</span><small>2 active memories</small>' in html
    assert "Next Safe Action" in html
    assert "Interrupted writes should be inspected before more repairs." in html
    assert "sqlite-fts" in html
    assert "Persistent cache" in html
    assert "10/12 pages reused" in html
    assert "stale_operations" in html
    assert "remember-1.json" in html
    assert "Operation Next Actions" in html
    assert str(tmp_path) in html
    assert "lnk operations" in html
    assert "lnk benchmark" in html
    assert "agent memory" in html


def test_render_health_page_maps_ready_actions_to_targeted_commands(tmp_path):
    wiki = tmp_path / "wiki"
    html = render_health_page(
        {
            "wiki": str(wiki),
            "ready": True,
            "content_page_count": 4,
            "memory_count": 1,
            "active_memory_count": 1,
            "needs_review_count": 0,
            "search_backend": "sqlite-fts",
            "schema": {"status": "current"},
            "validation": {"checked": True, "passed": True},
            "warnings": [],
            "next_actions": [{"label": "answer with compact local context", "tool": "query_link"}],
        },
        {
            "wiki": str(wiki),
            "operation_count": 0,
            "stale_count": 0,
            "active_count": 0,
            "next_actions": [],
            "operations": [],
        },
        layout=_layout,
    )

    assert "Next Safe Action" in html
    assert "lnk query" in html
    assert "what should I know before continuing?" in html
    assert str(tmp_path) in html


def test_render_health_page_targets_memory_review_command(tmp_path):
    wiki = tmp_path / "wiki"
    html = render_health_page(
        {
            "wiki": str(wiki),
            "ready": True,
            "content_page_count": 4,
            "memory_count": 1,
            "active_memory_count": 1,
            "needs_review_count": 1,
            "search_backend": "sqlite-fts",
            "schema": {"status": "current"},
            "validation": {"checked": True, "passed": True},
            "warnings": [],
            "next_actions": [],
        },
        {
            "wiki": str(wiki),
            "operation_count": 0,
            "stale_count": 0,
            "active_count": 0,
            "next_actions": [],
            "operations": [],
        },
        layout=_layout,
    )

    assert "Review pending memories" in html
    assert "lnk memory-inbox" in html
    assert str(tmp_path) in html
