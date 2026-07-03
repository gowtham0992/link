"""HTML renderer for Link's memory proposal page."""
from __future__ import annotations

import html
from collections.abc import Callable

from .web_ingest import copy_button


PageLayout = Callable[[str, str], str]


def render_propose_page(project: str = "", source: str = "", *, layout: PageLayout) -> str:
    body = (
        '<div class="breadcrumb"><a href="/">Link</a> / propose</div>'
        '<h1>Propose Memories</h1>'
        '<p class="summary">Paste source notes, session notes, or a raw excerpt. Link returns memory candidates without writing anything.</p>'
        '<div class="memory-next"><strong>Trust rule</strong>'
        '<p>Source-backed wiki knowledge and durable agent memory are separate. Save only preferences, decisions, or project facts you approve.</p></div>'
        '<section><h2>Review Gate</h2><div class="proposal-checklist">'
        '<strong>Before saving memory</strong>'
        '<span>Keep ordinary facts in wiki pages; save only durable preferences, decisions, project context, or user facts.</span>'
        '<span>Check source label, scope, project, duplicate candidates, and conflict warnings.</span>'
        '<span>Use direct approval only when the proposal is clean; otherwise copy the approval prompt into your agent chat.</span>'
        '</div></section>'
        f'{_render_proposal_path()}'
        f'{_render_after_approval()}'
        '<section><div class="section-heading"><h2>Local Raw Sources</h2><a href="/captures">captures</a></div>'
        '<div class="proposal-source-list" data-proposal-sources aria-live="polite"></div></section>'
        f'<form class="proposal-form" data-proposal-form data-initial-source="{html.escape(source, quote=True)}">'
        '<label>Source or session notes'
        '<textarea name="text" placeholder="Paste notes here. Example: I prefer short release notes. We decided to keep Link local-first."></textarea>'
        '</label>'
        '<div class="proposal-controls">'
        '<label>Source label<input name="source" value="web proposal" autocomplete="off"></label>'
        f'<label>Project<input name="project" value="{html.escape(project, quote=True)}" placeholder="optional" autocomplete="off"></label>'
        '<label>Limit<input name="limit" type="number" min="1" max="20" value="10"></label>'
        '<button type="submit">Propose</button>'
        '</div>'
        '<div class="proposal-status" data-proposal-status aria-live="polite"></div>'
        '</form>'
        '<section class="proposal-results" data-proposal-results aria-live="polite"></section>'
    )
    return layout("Propose Memories", body)


def _render_proposal_path() -> str:
    return (
        '<section class="ingest-path" aria-label="Memory proposal path">'
        '<article class="ingest-step"><span class="step-num">1</span>'
        '<h3>Load source</h3><p>Paste notes or load a safe local raw file. The source stays local.</p>'
        '<code>raw/file.md</code></article>'
        '<article class="ingest-step"><span class="step-num">2</span>'
        '<h3>Propose</h3><p>Link returns candidates only. This step never writes durable memory.</p>'
        '<code>Propose</code></article>'
        '<article class="ingest-step"><span class="step-num">3</span>'
        '<h3>Approve explicitly</h3><p>Copy the approval prompt into your agent chat only for memories you want kept.</p>'
        '<code>remember that ...</code></article>'
        '<article class="ingest-step"><span class="step-num">4</span>'
        '<h3>Review later</h3><p>Use the inbox and explain views to review, archive, update, or forget memories.</p>'
        '<code>lnk memory-inbox</code></article>'
        '</section>'
    )


def _render_after_approval() -> str:
    return (
        '<section><h2>After Approval</h2>'
        '<div class="memory-next"><strong>Keep memory reviewable</strong>'
        '<p>Saved memories stay pending until reviewed. Use the inbox to confirm, explain, archive, update, or forget them.</p>'
        '<div class="page-actions">'
        '<a class="button-link" href="/inbox">Open memory inbox</a>'
        '<a class="button-link" href="/audit">Open memory audit</a>'
        f'{copy_button("start with Link before we continue", "Copy brief prompt")}'
        f'{copy_button("query Link for what you remember about this task", "Copy query prompt")}'
        '</div></div></section>'
    )
