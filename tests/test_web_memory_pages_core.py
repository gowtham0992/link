import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.web_memory_pages import (  # noqa: E402
    render_brief_page,
    render_captures_page,
    render_inbox_page,
    render_memory_explanation_page,
    render_memory_log_page,
    render_memory_audit_page,
    render_memory_dashboard_page,
    render_profile_page,
)


def _layout(title: str, body: str) -> str:
    return f"<title>{title}</title>{body}"


def _page_href(name: str) -> str:
    return f"/page/{name}"


def _action_hints(_record: dict[str, object]) -> list[dict[str, object]]:
    return []


def test_render_brief_page_escapes_query_and_project():
    payload = {
        "project": "<alpha>",
        "profile": {"active_count": 2},
        "captures": {"count": 0, "items": []},
        "review": {"count": 1, "items": []},
        "relevant_count": 1,
        "agent_guidance": ["Use <Link> first"],
        "relevant_memories": [],
    }

    html = render_brief_page(payload, "<task>", page_href=_page_href, action_hints=_action_hints, layout=_layout)

    assert "<title>Memory Brief</title>" in html
    assert "value=\"&lt;task&gt;\"" in html
    assert 'data-copy-text="brief me from Link about &lt;task&gt; for project &lt;alpha&gt;"' in html
    assert "Copy brief prompt" in html
    assert 'data-copy-text="query Link for &lt;task&gt;"' in html
    assert "Copy query prompt" in html
    assert "Project:</strong> &lt;alpha&gt;" in html
    assert "Use &lt;Link&gt; first" in html
    assert "<task>" not in html


def test_render_brief_page_guides_empty_memory_recovery():
    payload = {
        "project": "",
        "profile": {"active_count": 0},
        "captures": {"count": 0, "items": []},
        "review": {"count": 0, "items": []},
        "relevant_count": 0,
        "agent_guidance": [],
        "relevant_memories": [],
    }

    html = render_brief_page(payload, "release notes", page_href=_page_href, action_hints=_action_hints, layout=_layout)

    assert "No relevant memories yet." in html
    assert "Teach Link before the next brief" in html
    assert 'href="/ingest"' in html
    assert 'href="/propose"' in html
    assert 'data-copy-text="propose memories about release notes from Link raw sources"' in html
    assert "Copy memory proposal prompt" in html


def test_render_memory_dashboard_page_shows_counts_next_actions_and_sections():
    payload = {
        "project": "alpha",
        "memory_count": 3,
        "active_count": 2,
        "review_count": 1,
        "updated_count": 1,
        "capture_count": 0,
        "archived_count": 0,
        "by_type": {"preference": 2},
        "by_scope": {"project": 1},
        "next_actions": [{"label": "Review", "detail": "Confirm memory", "command": "link memory-inbox"}],
        "review": [],
        "captures": [],
        "recent_updates": [],
        "active": [],
        "archived": [],
    }

    html = render_memory_dashboard_page(payload, page_href=_page_href, action_hints=_action_hints, layout=_layout)

    assert "Memory Dashboard" in html
    assert '<span class="num">3</span><span class="label">memories</span>' in html
    assert 'data-copy-text="what does Link remember about project alpha?"' in html
    assert 'data-copy-text="brief me from Link for project alpha"' in html
    assert 'data-copy-text="audit Link memory for project alpha"' in html
    assert "<strong>Types:</strong> preference: 2" in html
    assert "link memory-inbox" in html
    assert "No memories need review." in html


def test_render_profile_page_lists_memory_sections_and_explain_links():
    record = {
        "name": "prefer-short-notes",
        "title": "Prefer short notes",
        "memory_type": "preference",
        "scope": "user",
        "tldr": "Keep release notes short.",
    }
    payload = {
        "project": "",
        "memory_count": 1,
        "active_count": 1,
        "review_count": 0,
        "by_type": {"preference": 1},
        "by_scope": {"user": 1},
        "by_status": {"active": 1},
        "recent": [record],
        "preferences": [record],
        "decisions": [],
        "projects": [],
        "archived": [],
    }

    html = render_profile_page(payload, page_href=_page_href, layout=_layout)

    assert "Memory Profile" in html
    assert 'data-copy-text="what does Link remember about me?"' in html
    assert 'data-copy-text="brief me from Link before we continue"' in html
    assert "/page/prefer-short-notes" in html
    assert "/explain-memory?memory=prefer-short-notes" in html
    assert "Keep release notes short." in html


def test_render_profile_page_guides_first_memory_recovery():
    payload = {
        "project": "alpha",
        "memory_count": 0,
        "active_count": 0,
        "review_count": 0,
        "by_type": {},
        "by_scope": {},
        "by_status": {},
        "recent": [],
        "preferences": [],
        "decisions": [],
        "projects": [],
        "archived": [],
    }

    html = render_profile_page(payload, page_href=_page_href, layout=_layout)

    assert "No durable memories yet" in html
    assert 'href="/ingest"' in html
    assert 'href="/propose"' in html
    assert 'data-copy-text="remember that &lt;preference or decision&gt; for project alpha"' in html
    assert "Copy remember prompt" in html


def test_render_memory_audit_page_reports_risks():
    payload = {
        "project": "alpha",
        "status": "needs_attention",
        "profile": {"memory_count": 1, "active_count": 1, "review_count": 1},
        "captures": {"count": 0, "warning_count": 0, "read_warning_count": 0, "items": []},
        "risk_factors": [{"code": "stale", "message": "Review <memory>"}],
        "next_actions": [],
        "inbox": {"items": []},
    }

    html = render_memory_audit_page(payload, page_href=_page_href, action_hints=_action_hints, layout=_layout)

    assert "Memory Audit" in html
    assert 'data-copy-text="audit Link memory for project alpha"' in html
    assert 'data-copy-text="review Link memory inbox for project alpha"' in html
    assert "needs_attention" in html
    assert "Review &lt;memory&gt;" in html


def test_render_memory_log_page_shows_lifecycle_events():
    payload = {
        "count": 1,
        "total_matching": 1,
        "privacy_note": "Memory bodies are not included.",
        "entries": [
            {
                "timestamp": "2026-05-25T00:00:00Z",
                "operation": "remember",
                "category": "memory",
                "description": "Prefer local memory",
                "summary": "Created memory: wiki/memories/prefer-local-memory.md",
                "memory_paths": ["wiki/memories/prefer-local-memory.md"],
                "details": ["Created: memories/prefer-local-memory.md"],
            }
        ],
    }

    html = render_memory_log_page(payload, layout=_layout)

    assert "Memory Changelog" in html
    assert "Prefer local memory" in html
    assert "Memory bodies are not included" in html


def test_render_captures_page_shows_redaction_and_read_warnings():
    payload = {
        "project": "alpha",
        "count": 1,
        "warning_count": 1,
        "read_warning_count": 1,
        "captures": [],
        "read_warnings": [{"capture": "raw/memory-captures/bad.md", "error": "<denied>"}],
    }

    html = render_captures_page(payload, layout=_layout)

    assert "Raw Capture Inbox" in html
    assert 'data-copy-text="review Link raw captures for project alpha"' in html
    assert "1 raw capture contains secret-looking values" in html
    assert "raw/memory-captures/bad.md" in html
    assert "&lt;denied&gt;" in html


def test_render_inbox_page_lists_review_items_and_actions():
    payload = {
        "project": "",
        "review_count": 1,
        "counts_by_severity": {"warning": 1},
        "items": [
            {
                "name": "memory-one",
                "title": "Memory <One>",
                "memory_type": "preference",
                "scope": "user",
                "status": "pending",
                "tldr": "Needs review.",
                "issues": [{"severity": "warning", "code": "pending", "message": "Needs <review>"}],
                "primary_action": {"label": "Review", "description": "Confirm it"},
                "actions": [{"label": "Mark reviewed", "command": "link review-memory memory-one"}],
            }
        ],
    }

    html = render_inbox_page(payload, page_href=_page_href, layout=_layout)

    assert "Memory Review Inbox" in html
    assert 'data-copy-text="review Link memory inbox"' in html
    assert "Memory &lt;One&gt;" in html
    assert "Needs &lt;review&gt;" in html
    assert "/explain-memory?memory=memory-one" in html
    assert "link review-memory memory-one" in html


def test_render_memory_explanation_page_shows_trust_context_actions_and_body():
    payload = {
        "memory": {
            "name": "prefer-reviewable-memory",
            "title": "Prefer <reviewable> memory",
            "tldr": "User prefers visible memory actions.",
        },
        "recall": {"state": "needs_review", "reason": "Pending review"},
        "review": {
            "status": "pending",
            "issue_count": 1,
            "issues": [{"severity": "warning", "code": "pending", "message": "Needs <review>"}],
            "primary_action": {"label": "Review", "description": "Confirm it"},
            "actions": [{"label": "Forget", "command": "link forget-memory prefer-reviewable-memory"}],
        },
        "provenance": {
            "source": "<unit test>",
            "date_captured": "2026-05-05T00:00:00Z",
            "path": "wiki/memories/prefer-reviewable-memory.md",
        },
        "lifecycle": {"status": "active"},
        "graph": {"forward": ["agent-memory"], "inbound": [], "wikilinks": ["agent-memory"]},
        "log_entries": ["2026-05-05 remember <memory>"],
    }

    html = render_memory_explanation_page(payload, body_html="<p>Trusted body</p>", layout=_layout)

    assert "<h1>Prefer &lt;reviewable&gt; memory</h1>" in html
    assert "User prefers visible memory actions." in html
    assert "needs_review" in html
    assert "Needs &lt;review&gt;" in html
    assert "Next:</strong> Review" in html
    assert "link forget-memory prefer-reviewable-memory" in html
    assert "/graph?focus=prefer-reviewable-memory&amp;depth=2" in html
    assert "Open local graph" in html
    assert "agent-memory" in html
    assert "2026-05-05 remember &lt;memory&gt;" in html
    assert "<p>Trusted body</p>" in html
    assert "<unit test>" not in html
