"""Shared web graph rendering helpers."""
from __future__ import annotations

import html
from typing import Any, Mapping

from .web_ingest import copy_button


GRAPH_INITIAL_FULL_NODE_LIMIT = 900
GRAPH_INITIAL_SUMMARY_NODE_LIMIT = 250
GRAPH_INITIAL_SUMMARY_EDGE_LIMIT = 1000

GRAPH_CATEGORY_COLORS = {
    "concepts": "#4e79a7",
    "entities": "#f28e2b",
    "memories": "#edc948",
    "sources": "#59a14f",
    "comparisons": "#e15759",
    "explorations": "#76b7b2",
    "root": "#bab0ac",
}


def _visible_graph_parts(graph: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        dict(node)
        for node in graph.get("nodes", [])
        if str(node.get("category") or "") != "root"
    ]
    ids = {str(node.get("id") or "") for node in nodes}
    edges = [
        {"source": str(edge.get("source") or ""), "target": str(edge.get("target") or "")}
        for edge in graph.get("edges", [])
        if str(edge.get("source") or "") in ids and str(edge.get("target") or "") in ids
    ]
    return nodes, edges


def graph_needs_bounded_overview(
    full_graph: Mapping[str, Any],
    full_node_limit: int = GRAPH_INITIAL_FULL_NODE_LIMIT,
) -> bool:
    """Return whether the graph page should start with a bounded overview."""
    nodes, _ = _visible_graph_parts(full_graph)
    return len(nodes) > full_node_limit


def graph_initial_payload(
    full_graph: Mapping[str, Any],
    summary_graph: Mapping[str, Any] | None = None,
    full_node_limit: int = GRAPH_INITIAL_FULL_NODE_LIMIT,
) -> dict[str, Any]:
    """Build the initial browser graph payload and total counts.

    The full graph remains available through the HTTP API. This helper decides
    whether the page should embed the full graph immediately or a bounded
    high-signal overview first.
    """
    full_nodes, full_edges = _visible_graph_parts(full_graph)
    total_node_count = len(full_nodes)
    total_edge_count = len(full_edges)
    graph_mode = "full"
    graph_note = ""
    visible_nodes = full_nodes
    visible_edges = full_edges

    if total_node_count > full_node_limit and summary_graph is not None:
        visible_nodes, visible_edges = _visible_graph_parts(summary_graph)
        graph_mode = "summary"
        graph_note = (
            f" Showing a fast overview of {len(visible_nodes)} high-signal nodes first; "
            f"load graph data when you need to search or filter across every page."
        )

    return {
        "nodes": visible_nodes,
        "edges": visible_edges,
        "node_count": len(visible_nodes),
        "edge_count": len(visible_edges),
        "total_node_count": total_node_count,
        "total_edge_count": total_edge_count,
        "graph_mode": graph_mode,
        "graph_note": graph_note,
    }


def graph_category_options(nodes: list[Mapping[str, Any]]) -> str:
    categories = sorted({
        str(node.get("category") or "")
        for node in nodes
        if str(node.get("category") or "") and str(node.get("category") or "") != "root"
    })
    return '<option value="all">all types</option>' + "".join(
        f'<option value="{html.escape(category, quote=True)}">{html.escape(category)}</option>'
        for category in categories
    )


def graph_legend_items(colors: Mapping[str, str] = GRAPH_CATEGORY_COLORS) -> str:
    return "".join(
        '<button type="button" class="graph-legend-item" aria-pressed="false" '
        f'data-graph-category="{html.escape(str(category), quote=True)}" '
        f'title="Filter graph to {html.escape(str(category), quote=True)}">'
        f'<span style="background:{html.escape(str(color), quote=True)}"></span>'
        f'{html.escape(str(category))}</button>'
        for category, color in colors.items()
        if category != "root"
    )


def render_graph_script(
    *,
    nodes_json: str,
    edges_json: str,
    cat_colors_json: str,
    graph_mode_json: str,
    focus_id_json: str = "null",
    focus_depth: int = 2,
    search_json: str = '""',
    category_json: str = '"all"',
    size_json: str = '"category"',
    label_json: str = '"sparse"',
    total_node_count: int,
    total_edge_count: int,
) -> str:
    """Render the browser-side graph simulation script."""
    return f"""
<script>
(function() {{
  var nodes = {nodes_json};
  var edges = {edges_json};
  var catColors = {cat_colors_json};

  var canvas = document.getElementById('graph-canvas');
  var ctx = canvas.getContext('2d');
  var tooltip = document.getElementById('graph-tooltip');
  var resetButton = document.getElementById('graph-reset');
  var fitButton = document.getElementById('graph-fit');
  var labelsButton = document.getElementById('graph-labels');
  var motionButton = document.getElementById('graph-motion');
  var fullscreenButton = document.getElementById('graph-fullscreen');
  var loadFullButton = document.getElementById('graph-load-full');
  var copyLinkButton = document.getElementById('graph-copy-link');
  var searchInput = document.getElementById('graph-search');
  var categoryFilter = document.getElementById('graph-category');
  var sizeFilter = document.getElementById('graph-size');
  var labelFilter = document.getElementById('graph-label-density');
  var displayLimitFilter = document.getElementById('graph-display-limit');
  var depthFilter = document.getElementById('graph-depth');
  var frameEl = document.getElementById('graph-frame');
  var status = document.getElementById('graph-status');
  var legend = document.getElementById('graph-legend');
  var inspector = document.getElementById('graph-inspector');
  var inspectorTitle = document.getElementById('graph-inspector-title');
  var inspectorMeta = document.getElementById('graph-inspector-meta');
  var inspectorLinks = document.getElementById('graph-inspector-links');
  var inspectorOpen = document.getElementById('graph-open');
  var inspectorFocus = document.getElementById('graph-focus');
  var inspectorLocal = document.getElementById('graph-local');
  var W, H;

  // Compact neural-map sizing: concepts lead, sources recede.
  var NODE_R = 6;
  var LABEL_FONT = '11px -apple-system, sans-serif';
  var LARGE_GRAPH_LIMIT = 350;
  var LARGE_LABEL_LIMIT = 160;
  var FAST_RENDER_NODE_LIMIT = 450;
  var FAST_RENDER_EDGE_LIMIT = 1200;
  var DEFAULT_OVERVIEW_NODE_LIMIT = 650;
  var DISPLAY_LIMIT_OPTIONS = [250, 650, 1000];
  var SEARCH_LABEL_LIMIT = 60;
  var initialGraphMode = {graph_mode_json};
  var initialFocusId = {focus_id_json};
  var initialFocusDepth = {max(0, min(3, int(focus_depth)))};
  var initialSearchTerm = {search_json};
  var initialCategoryValue = {category_json};
  var initialSizeValue = {size_json};
  var initialLabelMode = {label_json};
  var totalNodeCount = {total_node_count};
  var totalEdgeCount = {total_edge_count};
  var fullGraphLoaded = initialGraphMode === 'full';
  var fullGraphLoading = false;
  var nodeById = {{}};
  var GRAPH_STORAGE_KEY = 'link.graph.controls.v1';

  function readGraphSettings() {{
    try {{
      return JSON.parse(window.localStorage.getItem(GRAPH_STORAGE_KEY) || '{{}}') || {{}};
    }} catch (error) {{
      return {{}};
    }}
  }}

  function saveGraphSettings() {{
    try {{
      window.localStorage.setItem(GRAPH_STORAGE_KEY, JSON.stringify({{
        showAllLabels: showAllLabels,
        motionPaused: motionPaused,
        searchTerm: searchTerm,
        categoryValue: categoryValue,
        sizeMode: sizeMode,
        labelMode: labelMode,
        displayLimit: overviewNodeLimit
      }}));
    }} catch (error) {{
      // Local storage can be disabled; graph controls should still work.
    }}
  }}

  var storedGraphSettings = readGraphSettings();

  function stableNoise(id, salt) {{
    var h = salt * 2166136261;
    for (var i = 0; i < id.length; i++) {{
      h ^= id.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }}
    return ((h >>> 0) % 1000) / 1000;
  }}

  function categorySeedAngle(category) {{
    var angles = {{
      concepts: -0.25,
      entities: 0.85,
      memories: -1.15,
      sources: 2.35,
      comparisons: -2.45,
      explorations: 1.75
    }};
    return angles[category] || 0;
  }}

  function categoryClusterCenter(category, total) {{
    var scale = total > 2500 ? 1.22 : 1;
    var centers = {{
      concepts: {{ x: -40, y: 0 }},
      sources: {{ x: 210, y: 115 }},
      memories: {{ x: 118, y: -145 }},
      entities: {{ x: -230, y: -100 }},
      comparisons: {{ x: -240, y: 135 }},
      explorations: {{ x: 18, y: 188 }}
    }};
    var center = centers[category] || {{ x: 0, y: 0 }};
    return {{ x: center.x * scale, y: center.y * scale }};
  }}

  function seedLargeGraphPosition(n, i, total) {{
    var center = categoryClusterCenter(n.category, total);
    var angle = stableNoise(n.id, 11) * Math.PI * 2 + categorySeedAngle(n.category);
    var clusterRadius = total > 2500 ? 260 : 195;
    var centrality = Math.min(0.7, Math.log2((degree[n.id] || 0) + 1) / 8);
    var r = 18 + Math.sqrt(stableNoise(n.id, 17)) * clusterRadius * (1 - centrality);
    pos[n.id] = {{
      x: center.x + Math.cos(angle) * r * 1.04,
      y: center.y + Math.sin(angle) * r * 0.82
    }};
    vel[n.id] = {{ x: 0, y: 0 }};
  }}

  // Small graphs start in a loose two-lobe silhouette and settle with physics.
  // Large graphs skip physics, so they use stable category clusters instead of global rings.
  var pos = {{}}, vel = {{}}, pinned = {{}};
  function seedNodePosition(n, i, total) {{
    if (total > LARGE_GRAPH_LIMIT) {{
      seedLargeGraphPosition(n, i, total);
      return;
    }}
    var lobe = i % 2 === 0 ? -1 : 1;
    var a = i * 2.399963 + stableNoise(n.id, 7) * 0.7;
    var r = 50 + Math.sqrt((i + 1) / Math.max(total, 1)) * 155;
    var categoryDrop = n.category === 'sources' ? 58 : (n.category === 'memories' ? -34 : (n.category === 'entities' ? 24 : -6));
    pos[n.id] = {{
      x: lobe * 78 + Math.cos(a) * r * 0.78,
      y: Math.sin(a) * r * 0.58 + categoryDrop
    }};
    vel[n.id] = {{ x: 0, y: 0 }};
  }}

  function seedMissingPositions() {{
    nodes.forEach(function(n, i) {{
      if (!pos[n.id]) seedNodePosition(n, i, nodes.length);
      if (!vel[n.id]) vel[n.id] = {{ x: 0, y: 0 }};
    }});
  }}

  function reseedVisiblePositions() {{
    var currentNodes = visibleNodes();
    currentNodes.forEach(function(n, i) {{
      if (!pinned[n.id]) seedNodePosition(n, i, currentNodes.length);
    }});
  }}

  // Adjacency
  var adj = {{}}, degree = {{}};
  function rebuildGraphIndexes() {{
    nodeById = {{}};
    adj = {{}};
    degree = {{}};
    nodes.forEach(function(n) {{
      nodeById[n.id] = n;
      adj[n.id] = [];
      degree[n.id] = 0;
    }});
    edges.forEach(function(e) {{
      if (adj[e.source]) {{ adj[e.source].push(e.target); degree[e.source]++; }}
      if (adj[e.target]) {{ adj[e.target].push(e.source); degree[e.target]++; }}
    }});
  }}

  rebuildGraphIndexes();
  seedMissingPositions();
  var lockedOverviewIds = null;
  if (initialGraphMode !== 'full') {{
    lockedOverviewIds = {{}};
    nodes.forEach(function(n) {{ lockedOverviewIds[n.id] = true; }});
  }}

  var dragging = null, dragOffX = 0, dragOffY = 0, hoverNode = null, selectedNode = null;
  var panX = 0, panY = 0, panStartX = 0, panStartY = 0, panning = false, didPan = false;
  var downX = 0, downY = 0, didDrag = false, suppressClick = false;
  var zoom = 1;
  var frame = 0;
  var prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var motionPaused = prefersReducedMotion || nodes.length > LARGE_GRAPH_LIMIT || storedGraphSettings.motionPaused === true;
  var SETTLE = 200; // frames of physics
  var searchTerm = String(initialSearchTerm || storedGraphSettings.searchTerm || '').trim().toLowerCase();
  var cachedSearchTerm = '';
  var cachedSearchMatches = 0;
  var categoryValue = String(
    initialCategoryValue && initialCategoryValue !== 'all'
      ? initialCategoryValue
      : (storedGraphSettings.categoryValue || initialCategoryValue || 'all')
  ).trim() || 'all';
  var sizeMode = String(
    initialSizeValue && initialSizeValue !== 'category'
      ? initialSizeValue
      : (storedGraphSettings.sizeMode || initialSizeValue || 'category')
  ).trim() || 'category';
  if (['category', 'degree'].indexOf(sizeMode) === -1) sizeMode = 'category';
  var labelMode = String(
    initialLabelMode && initialLabelMode !== 'sparse'
      ? initialLabelMode
      : (storedGraphSettings.labelMode || (storedGraphSettings.showAllLabels ? 'all' : initialLabelMode) || 'sparse')
  ).trim() || 'sparse';
  if (['sparse', 'neighbors', 'all'].indexOf(labelMode) === -1) labelMode = 'sparse';
  function normalizeDisplayLimit(value) {{
    var parsed = parseInt(value, 10);
    if (DISPLAY_LIMIT_OPTIONS.indexOf(parsed) !== -1) return parsed;
    return DEFAULT_OVERVIEW_NODE_LIMIT;
  }}
  var overviewNodeLimit = normalizeDisplayLimit(storedGraphSettings.displayLimit || DEFAULT_OVERVIEW_NODE_LIMIT);
  var showAllLabels = labelMode === 'all';
  var depthValue = 'all';
  var visibleCache = null;
  var renderQueued = false;
  var animationRunning = false;

  function resize() {{
    W = canvas.clientWidth; H = canvas.clientHeight;
    canvas.width = W * devicePixelRatio; canvas.height = H * devicePixelRatio;
    ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  }}

  function nodeColor(n) {{ return catColors[n.category] || '#8b949e'; }}
  function pageHref(id) {{ return '/page/' + encodeURIComponent(id); }}
  function graphHref(id, depth) {{
    var params = new URLSearchParams();
    params.set('focus', id);
    params.set('depth', String(depth || 2));
    if (searchTerm) params.set('q', searchTerm);
    if (categoryValue && categoryValue !== 'all') params.set('type', categoryValue);
    if (sizeMode && sizeMode !== 'category') params.set('size', sizeMode);
    if (labelMode && labelMode !== 'sparse') params.set('labels', labelMode);
    return '/graph?' + params.toString();
  }}
  function graphStateUrl() {{
    var params = new URLSearchParams();
    if (selectedNode) params.set('focus', selectedNode.id);
    if (searchTerm) params.set('q', searchTerm);
    if (categoryValue && categoryValue !== 'all') params.set('type', categoryValue);
    if (sizeMode && sizeMode !== 'category') params.set('size', sizeMode);
    if (labelMode && labelMode !== 'sparse') params.set('labels', labelMode);
    if (selectedNode && depthValue !== 'all') params.set('depth', depthValue);
    return window.location.origin + window.location.pathname + (params.toString() ? '?' + params.toString() : '');
  }}
  function fallbackCopy(text) {{
    var area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.left = '-9999px';
    document.body.appendChild(area);
    area.select();
    try {{ document.execCommand('copy'); }} finally {{ document.body.removeChild(area); }}
  }}
  async function copyGraphLink() {{
    if (!copyLinkButton) return;
    var previous = copyLinkButton.textContent;
    var text = graphStateUrl();
    try {{
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
      else fallbackCopy(text);
      copyLinkButton.textContent = 'Copied link';
    }} catch (error) {{
      copyLinkButton.textContent = 'Copy failed';
    }}
    window.setTimeout(function() {{ copyLinkButton.textContent = previous || 'Copy link'; }}, 1400);
  }}
  function invalidateFilters() {{ visibleCache = null; }}
  function invalidateSearchCache() {{ cachedSearchTerm = ''; cachedSearchMatches = 0; }}
  function escapeHtml(value) {{
    return String(value).replace(/[&<>"']/g, function(ch) {{
      return {{ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }}[ch];
    }});
  }}
  function syncCategoryOptions() {{
    if (!categoryFilter) return;
    var categories = [];
    nodes.forEach(function(n) {{
      if (n.category && n.category !== 'root' && categories.indexOf(n.category) === -1) categories.push(n.category);
    }});
    categories.sort();
    categoryFilter.innerHTML = '<option value="all">all types</option>' + categories.map(function(category) {{
      return '<option value="' + escapeHtml(category) + '">' + escapeHtml(category) + '</option>';
    }}).join('');
    if (categories.indexOf(categoryValue) === -1) categoryValue = 'all';
    categoryFilter.value = categoryValue;
  }}
  function nodeSearchText(n) {{
    return (n.title + ' ' + n.id + ' ' + n.category).toLowerCase();
  }}
  function searchMatches(n) {{
    return searchTerm && nodeSearchText(n).indexOf(searchTerm) !== -1;
  }}
  function totalSearchMatches() {{
    if (!searchTerm) return 0;
    if (cachedSearchTerm === searchTerm) return cachedSearchMatches;
    cachedSearchTerm = searchTerm;
    cachedSearchMatches = nodes.filter(searchMatches).length;
    return cachedSearchMatches;
  }}
  function depthMap() {{
    if (!selectedNode || depthValue === 'all') return null;
    var maxDepth = parseInt(depthValue, 10);
    if (!Number.isFinite(maxDepth)) return null;
    var seen = {{}};
    var queue = [selectedNode.id];
    seen[selectedNode.id] = 0;
    while (queue.length) {{
      var current = queue.shift();
      var nextDepth = seen[current] + 1;
      if (nextDepth > maxDepth) continue;
      (adj[current] || []).forEach(function(next) {{
        if (seen[next] === undefined) {{
          seen[next] = nextDepth;
          queue.push(next);
        }}
      }});
    }}
    return seen;
  }}
  function capEligibleNodes(eligible) {{
    if (eligible.length <= overviewNodeLimit) return eligible;
    if (fullGraphLoaded && lockedOverviewIds && !searchTerm && categoryValue === 'all' && depthValue === 'all' && !selectedNode) {{
      var locked = eligible.filter(function(n) {{ return lockedOverviewIds[n.id]; }});
      if (locked.length) return locked;
    }}
    var keep = {{}};
    var keepCount = 0;
    function markKeep(n) {{
      if (n && !keep[n.id]) {{
        keep[n.id] = true;
        keepCount++;
      }}
    }}
    var highSignalLimit = Math.floor(overviewNodeLimit * 0.65);
    var sampleLimit = Math.max(0, overviewNodeLimit - highSignalLimit);
    eligible
      .slice()
      .sort(function(a, b) {{
        var degreeDiff = (degree[b.id] || 0) - (degree[a.id] || 0);
        if (degreeDiff) return degreeDiff;
        return String(a.title || a.id).localeCompare(String(b.title || b.id));
      }})
      .slice(0, highSignalLimit)
      .forEach(markKeep);
    for (var i = 0; i < sampleLimit; i++) {{
      var sampled = eligible[Math.floor((i + 0.5) * eligible.length / Math.max(sampleLimit, 1))];
      markKeep(sampled);
    }}
    var fillIndex = 0;
    while (keepCount < overviewNodeLimit && fillIndex < eligible.length) {{
      markKeep(eligible[fillIndex]);
      fillIndex++;
    }}
    eligible.forEach(function(n) {{
      if (searchMatches(n)) markKeep(n);
      if (selectedNode && (n.id === selectedNode.id || isNeighbor(selectedNode.id, n.id))) markKeep(n);
    }});
    return eligible.filter(function(n) {{ return keep[n.id]; }});
  }}
  function visibleIds() {{
    if (visibleCache) return visibleCache;
    var byDepth = depthMap();
    var ids = {{}};
    var eligible = [];
    nodes.forEach(function(n) {{
      var categoryOk = categoryValue === 'all' || n.category === categoryValue;
      var depthOk = !byDepth || byDepth[n.id] !== undefined;
      var keepSelected = selectedNode && selectedNode.id === n.id;
      if ((categoryOk || keepSelected) && depthOk) eligible.push(n);
    }});
    capEligibleNodes(eligible).forEach(function(n) {{
      ids[n.id] = true;
    }});
    visibleCache = ids;
    return ids;
  }}
  function visibleNodes() {{
    var ids = visibleIds();
    return nodes.filter(function(n) {{ return ids[n.id]; }});
  }}
  function visibleEdges() {{
    var ids = visibleIds();
    return edges.filter(function(e) {{ return ids[e.source] && ids[e.target]; }});
  }}
  function graphTooLargeForMotion() {{
    return visibleNodes().length > LARGE_GRAPH_LIMIT;
  }}
  function graphTooLargeForDefaultLabels() {{
    return visibleNodes().length > LARGE_LABEL_LIMIT;
  }}
  function graphNeedsFastRender(currentNodes, currentEdges) {{
    return currentNodes.length > FAST_RENDER_NODE_LIMIT || currentEdges.length > FAST_RENDER_EDGE_LIMIT;
  }}
  function syncLabelsButton() {{
    if (!labelsButton) return;
    showAllLabels = labelMode === 'all';
    labelsButton.setAttribute('aria-pressed', labelMode === 'sparse' ? 'false' : 'true');
    labelsButton.textContent = labelMode === 'all' ? 'Labels all' : (labelMode === 'neighbors' ? 'Labels local' : 'Labels sparse');
    if (labelFilter && labelFilter.value !== labelMode) labelFilter.value = labelMode;
  }}
  function syncDisplayLimitControl() {{
    if (!displayLimitFilter) return;
    displayLimitFilter.value = String(overviewNodeLimit);
    displayLimitFilter.disabled = nodes.length <= DEFAULT_OVERVIEW_NODE_LIMIT;
    displayLimitFilter.title = displayLimitFilter.disabled
      ? 'The full graph fits within the default overview.'
      : 'Choose how many nodes the canvas may draw before you narrow the graph.';
  }}
  function syncLegendButtons() {{
    if (!legend) return;
    Array.from(legend.querySelectorAll('[data-graph-category]')).forEach(function(button) {{
      var category = button.getAttribute('data-graph-category') || '';
      button.setAttribute('aria-pressed', categoryValue === category ? 'true' : 'false');
    }});
  }}
  function cycleLabelMode() {{
    labelMode = labelMode === 'sparse' ? 'neighbors' : (labelMode === 'neighbors' ? 'all' : 'sparse');
    showAllLabels = labelMode === 'all';
    syncLabelsButton();
    updateStatus();
    saveGraphSettings();
    drawSoon();
  }}
  function nodeRadius(n) {{
    if (sizeMode === 'degree') {{
      return Math.max(4.5, Math.min(12, 4.2 + Math.log2((degree[n.id] || 0) + 1) * 1.8));
    }}
    if (n.category === 'sources') return 4.5;
    if (n.category === 'memories') return 6.4;
    if (n.category === 'entities') return 6.8;
    return NODE_R;
  }}
  function isNeighbor(a, b) {{
    return (adj[a] || []).indexOf(b) !== -1;
  }}
  function isActiveNode(n) {{
    return !hoverNode || n.id === hoverNode.id || isNeighbor(hoverNode.id, n.id);
  }}
  function pinnedCount() {{
    var count = 0;
    Object.keys(pinned).forEach(function(id) {{ if (pinned[id]) count++; }});
    return count;
  }}
  function updateStatus() {{
    if (!status) return;
    syncDepthControl();
    var currentNodes = visibleNodes();
    var currentEdges = visibleEdges();
    var parts = [
      currentNodes.length + '/' + totalNodeCount + ' nodes',
      currentEdges.length + '/' + totalEdgeCount + ' edges',
      Math.round(zoom * 100) + '%'
    ];
    if (!fullGraphLoaded) parts.push('fast overview');
    if (categoryValue !== 'all') parts.push(categoryValue);
    if (sizeMode !== 'category') parts.push('size ' + sizeMode);
    if (labelMode !== 'sparse') parts.push('labels ' + labelMode);
    if (depthValue !== 'all') parts.push('depth ' + depthValue);
    if (graphTooLargeForMotion()) parts.push('motion capped');
    if (graphTooLargeForDefaultLabels() && labelMode === 'sparse') parts.push('labels sparse');
    if (graphNeedsFastRender(currentNodes, currentEdges)) parts.push('fast render');
    if (nodes.length > overviewNodeLimit && currentNodes.length < nodes.length) parts.push('display capped ' + overviewNodeLimit);
    if (fullGraphLoaded && initialGraphMode !== 'full') parts.push('data loaded');
    if (fullGraphLoading) parts.push('loading graph data');
    if (searchTerm) {{
      var matches = totalSearchMatches();
      parts.push(matches + ' match' + (matches === 1 ? '' : 'es'));
      if (matches > SEARCH_LABEL_LIMIT) parts.push('match labels capped');
    }}
    var locked = pinnedCount();
    if (locked) parts.push(locked + ' placed');
    if (selectedNode) parts.push('selected ' + selectedNode.id);
    status.textContent = parts.join(' · ');
    syncLabelsButton();
    syncDisplayLimitControl();
    syncLegendButtons();
  }}

  function syncDepthControl() {{
    if (!depthFilter) return;
    if (!selectedNode && depthValue !== 'all') {{
      depthValue = 'all';
      depthFilter.value = 'all';
      invalidateFilters();
    }}
    depthFilter.disabled = !selectedNode;
    depthFilter.title = selectedNode ? 'Limit graph to the selected node neighborhood.' : 'Select a node before filtering by neighborhood.';
  }}

  function updateInspector() {{
    if (!inspector || !inspectorTitle || !inspectorMeta || !inspectorLinks || !inspectorOpen || !inspectorFocus || !inspectorLocal) return;
    inspectorLinks.textContent = '';
    if (!selectedNode) {{
      inspectorTitle.textContent = 'Select a node';
      inspectorMeta.textContent = 'Click a node to inspect it. Drag a node to place it. Double-click a node, or use Open page, to navigate.';
      inspectorOpen.disabled = true;
      inspectorFocus.disabled = true;
      inspectorLocal.disabled = true;
      return;
    }}
    var neighbors = (adj[selectedNode.id] || []).slice().sort(function(a, b) {{
      return (nodeById[a] ? nodeById[a].title : a).localeCompare(nodeById[b] ? nodeById[b].title : b);
    }});
    inspectorTitle.textContent = selectedNode.title;
    inspectorMeta.textContent = selectedNode.category + ' · ' + neighbors.length + ' linked page' + (neighbors.length === 1 ? '' : 's');
    inspectorOpen.disabled = false;
    inspectorFocus.disabled = false;
    inspectorLocal.disabled = false;
    neighbors.slice(0, 10).forEach(function(id) {{
      var target = nodeById[id];
      var link = document.createElement('a');
      link.href = pageHref(id);
      link.textContent = target ? target.title : id;
      inspectorLinks.appendChild(link);
    }});
    if (neighbors.length > 10) {{
      var more = document.createElement('span');
      more.textContent = '+' + (neighbors.length - 10) + ' more';
      inspectorLinks.appendChild(more);
    }}
  }}

  function selectNode(node) {{
    selectedNode = node;
    hoverNode = node;
    invalidateFilters();
    syncDepthControl();
    updateInspector();
    updateStatus();
    drawSoon();
  }}

  function openNode(node) {{
    if (node) window.location.href = pageHref(node.id);
  }}
  function openLocalGraph(node, depth) {{
    if (node) window.location.href = graphHref(node.id, depth || 2);
  }}

  function toScreen(x, y) {{
    return {{ x: (x + panX) * zoom + W/2, y: (y + panY) * zoom + H/2 }};
  }}
  function toWorld(sx, sy) {{
    return {{ x: (sx - W/2) / zoom - panX, y: (sy - H/2) / zoom - panY }};
  }}

  function simulate() {{
    var simNodes = visibleNodes();
    if (simNodes.length > LARGE_GRAPH_LIMIT) return;
    var simIds = visibleIds();
    // Tuned for a brain-like neural map: broad lobes, readable spacing, gentle drift.
    var springLen = 135, springK = 0.032, repel = 13500, gravity = 0.005, damp = 0.84;
    simNodes.forEach(function(n) {{
      if (pinned[n.id]) return;
      var fx = 0, fy = 0;
      var p = pos[n.id];
      // Repulsion between all pairs
      simNodes.forEach(function(m) {{
        if (m.id === n.id) return;
        var q = pos[m.id];
        var dx = p.x - q.x, dy = p.y - q.y;
        var d2 = Math.max(dx*dx + dy*dy, 100);
        var f = repel / d2;
        fx += f * dx / Math.sqrt(d2);
        fy += f * dy / Math.sqrt(d2);
      }});
      // Spring attraction along edges (toward natural length)
      (adj[n.id] || []).forEach(function(mid) {{
        if (!simIds[mid]) return;
        var q = pos[mid];
        var dx = q.x - p.x, dy = q.y - p.y;
        var d = Math.sqrt(dx*dx + dy*dy) + 0.01;
        var f = springK * (d - springLen);
        fx += f * dx / d; fy += f * dy / d;
      }});
      // Weak center gravity plus a two-lobe bias so the map feels organic.
      fx -= p.x * gravity; fy -= p.y * gravity;
      var lobeX = p.x < 0 ? -95 : 95;
      fx += (lobeX - p.x) * 0.0018;
      fy += ((n.category === 'sources' ? 40 : -8) - p.y) * 0.0012;
      vel[n.id].x = (vel[n.id].x + fx * 0.016) * damp;
      vel[n.id].y = (vel[n.id].y + fy * 0.016) * damp;
      pos[n.id].x += vel[n.id].x;
      pos[n.id].y += vel[n.id].y;
    }});
  }}

  // Auto-fit: after physics settles, zoom/pan so all nodes are visible and centered
  function autoFit() {{
    var currentNodes = visibleNodes();
    if (currentNodes.length === 0) return;
    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    currentNodes.forEach(function(n) {{
      minX = Math.min(minX, pos[n.id].x); maxX = Math.max(maxX, pos[n.id].x);
      minY = Math.min(minY, pos[n.id].y); maxY = Math.max(maxY, pos[n.id].y);
    }});
    var pad = 60;
    var gw = maxX - minX + pad*2, gh = maxY - minY + pad*2;
    zoom = Math.min(W / gw, H / gh, 2);
    panX = -(minX + maxX) / 2;
    panY = -(minY + maxY) / 2;
    updateStatus();
  }}

  var fitted = false;

  function strokeEdgeBatch(edgeList, strokeStyle, lineWidth) {{
    if (!edgeList.length) return;
    ctx.beginPath();
    edgeList.forEach(function(e) {{
      var a = toScreen(pos[e.source].x, pos[e.source].y);
      var b = toScreen(pos[e.target].x, pos[e.target].y);
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
    }});
    ctx.strokeStyle = strokeStyle;
    ctx.lineWidth = lineWidth;
    ctx.stroke();
  }}

  function draw() {{
    ctx.clearRect(0, 0, W, H);
    var time = frame * 0.018;
    var currentNodes = visibleNodes();
    var currentEdges = visibleEdges();
    var animateFlow = !motionPaused && !graphTooLargeForMotion();
    var largeLabelSet = currentNodes.length > LARGE_LABEL_LIMIT;
    var fastRender = graphNeedsFastRender(currentNodes, currentEdges);

    if (fastRender) {{
      if (hoverNode) {{
        var activeEdges = [];
        var inactiveEdges = [];
        currentEdges.forEach(function(e) {{
          if (e.source === hoverNode.id || e.target === hoverNode.id) activeEdges.push(e);
          else inactiveEdges.push(e);
        }});
        strokeEdgeBatch(inactiveEdges, 'rgba(139,148,158,0.035)', 0.45);
        strokeEdgeBatch(activeEdges, 'rgba(88,166,255,0.42)', 1.1);
      }} else {{
        strokeEdgeBatch(currentEdges, 'rgba(88,166,255,0.07)', 0.45);
      }}
    }} else {{
      // Detailed edges for smaller or focused graph neighborhoods.
      currentEdges.forEach(function(e) {{
        var a = toScreen(pos[e.source].x, pos[e.source].y);
        var b = toScreen(pos[e.target].x, pos[e.target].y);
        var activeEdge = !hoverNode || e.source === hoverNode.id || e.target === hoverNode.id;
        var alpha = hoverNode ? (activeEdge ? 0.42 : 0.035) : 0.14;

        // Glow layer
        ctx.save();
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = 'rgba(88,166,255,' + (alpha * 0.55) + ')';
        ctx.lineWidth = 3;
        ctx.filter = 'blur(2px)';
        ctx.stroke();
        ctx.restore();

        // Sharp line
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = 'rgba(139,148,158,' + alpha + ')';
        ctx.lineWidth = 0.8;
        ctx.stroke();

        // Flow particle
        if (activeEdge && animateFlow) {{
          var flowT = ((time * 0.5 + (a.x + b.y) * 0.001) % 2) / 2;
          var px = a.x + (b.x - a.x) * flowT;
          var py = a.y + (b.y - a.y) * flowT;
          var pa = Math.sin(flowT * Math.PI) * (hoverNode ? 0.6 : 0.32);
          ctx.beginPath(); ctx.arc(px, py, 1.5, 0, Math.PI*2);
          ctx.fillStyle = 'rgba(45,212,191,' + pa + ')';
          ctx.fill();
        }}
      }});
    }}

    // Nodes
    currentNodes.forEach(function(n) {{
      var s = toScreen(pos[n.id].x, pos[n.id].y);
      var r = nodeRadius(n) * Math.max(0.65, Math.min(1.2, zoom));
      var color = nodeColor(n);
      var pulse = fastRender ? 1 : Math.sin(time * 1.2 + (pos[n.id].x + pos[n.id].y) * 0.01) * 0.12 + 0.88;
      var activeNode = isActiveNode(n);
      var selected = selectedNode && selectedNode.id === n.id;
      var matched = searchMatches(n);
      ctx.save();
      ctx.globalAlpha = (hoverNode && !activeNode) || (searchTerm && !matched) ? 0.28 : 1;

      if (!fastRender || selected || matched || (hoverNode && activeNode)) {{
        // Radial glow stays off in large overview mode except for focused nodes.
        var glowR = r * 3.5 * pulse;
        var grad = ctx.createRadialGradient(s.x, s.y, r * 0.3, s.x, s.y, glowR);
        grad.addColorStop(0, color + '30');
        grad.addColorStop(1, color + '00');
        ctx.beginPath(); ctx.arc(s.x, s.y, glowR, 0, Math.PI*2);
        ctx.fillStyle = grad; ctx.fill();
      }}

      // Node body
      ctx.beginPath(); ctx.arc(s.x, s.y, r, 0, Math.PI*2);
      ctx.fillStyle = fastRender ? color + '28' : color + '40'; ctx.fill();

      // Node border
      ctx.beginPath(); ctx.arc(s.x, s.y, r, 0, Math.PI*2);
      ctx.strokeStyle = selected || matched ? '#ffffff' : color; ctx.lineWidth = selected || matched ? 2.4 : (fastRender ? 0.75 : 1.5);
      ctx.globalAlpha = 0.85; ctx.stroke(); ctx.globalAlpha = 1;

      // Inner bright core
      if (!fastRender || selected || matched || (hoverNode && activeNode)) {{
        ctx.beginPath(); ctx.arc(s.x, s.y, r * 0.35, 0, Math.PI*2);
        ctx.fillStyle = color + 'cc'; ctx.fill();
      }}

      // Labels stay sparse until a node is hovered.
      var label = n.title.length > 22 ? n.title.slice(0, 20) + '…' : n.title;
      var defaultSparseLabel = !largeLabelSet && n.category !== 'sources' && degree[n.id] >= 2;
      var showMatchLabel = matched && totalSearchMatches() <= SEARCH_LABEL_LIMIT;
      var showNeighborLabel = labelMode === 'neighbors' && selectedNode && (selected || isNeighbor(selectedNode.id, n.id));
      var showLabel = labelMode === 'all' || showNeighborLabel || selected || showMatchLabel || (hoverNode ? activeNode : defaultSparseLabel);
      if (showLabel) {{
        ctx.font = LABEL_FONT;
        ctx.textAlign = 'center'; ctx.textBaseline = 'top';
        ctx.shadowColor = 'rgba(0,0,0,0.9)'; ctx.shadowBlur = 4;
        ctx.fillStyle = '#dce7f2';
        var labelWidth = ctx.measureText(label).width;
        var labelX = Math.max(labelWidth / 2 + 4, Math.min(W - labelWidth / 2 - 4, s.x));
        ctx.fillText(label, labelX, s.y + r + 5);
        ctx.shadowBlur = 0;
      }}
      ctx.restore();
    }});
  }}

  function shouldRunContinuously() {{
    return !motionPaused && !graphTooLargeForMotion();
  }}

  function drawSoon() {{
    if (renderQueued) return;
    renderQueued = true;
    requestAnimationFrame(function() {{
      renderQueued = false;
      draw();
    }});
  }}

  function startLoop() {{
    if (animationRunning) return;
    animationRunning = true;
    requestAnimationFrame(loop);
  }}

  function loop() {{
    if (!shouldRunContinuously()) {{
      animationRunning = false;
      drawSoon();
      return;
    }}
    if (frame < SETTLE) {{
      simulate();
      // Auto-fit once physics has mostly settled
      if (frame === SETTLE - 1) {{ autoFit(); fitted = true; }}
    }}
    frame++;
    draw();
    requestAnimationFrame(loop);
  }}

  function hitTest(sx, sy) {{
    var w = toWorld(sx, sy);
    var currentNodes = visibleNodes();
    for (var i = currentNodes.length - 1; i >= 0; i--) {{
      var n = currentNodes[i];
      var p = pos[n.id];
      var r = nodeRadius(n) + 6; // slightly larger hit area
      var dx = w.x - p.x, dy = w.y - p.y;
      if (dx*dx + dy*dy <= r*r) return n;
    }}
    return null;
  }}

  function movedPastThreshold(sx, sy) {{
    var dx = sx - downX, dy = sy - downY;
    return dx * dx + dy * dy > 9;
  }}

  function resetView() {{
    pinned = {{}};
    selectedNode = null;
    hoverNode = null;
    searchTerm = '';
    invalidateSearchCache();
    categoryValue = 'all';
    sizeMode = 'category';
    labelMode = 'sparse';
    showAllLabels = false;
    depthValue = 'all';
    if (searchInput) searchInput.value = '';
    if (categoryFilter) categoryFilter.value = 'all';
    if (sizeFilter) sizeFilter.value = 'category';
    if (labelFilter) labelFilter.value = 'sparse';
    if (depthFilter) depthFilter.value = 'all';
    invalidateFilters();
    reseedVisiblePositions();
    frame = SETTLE;
    autoFit();
    updateInspector();
    updateStatus();
    saveGraphSettings();
    drawSoon();
  }}

  function fitCurrentView() {{
    autoFit();
    fitted = true;
    updateStatus();
    drawSoon();
  }}

  function setMotionPaused(next) {{
    motionPaused = next || graphTooLargeForMotion();
    if (motionButton) {{
      motionButton.setAttribute('aria-pressed', motionPaused ? 'true' : 'false');
      motionButton.textContent = graphTooLargeForMotion() ? 'Motion capped' : (motionPaused ? 'Motion paused' : 'Motion on');
    }}
    updateStatus();
    if (shouldRunContinuously()) startLoop();
    else drawSoon();
  }}

  function setFullscreen(next) {{
    if (!frameEl || !fullscreenButton) return;
    frameEl.classList.toggle('is-fullscreen', next);
    fullscreenButton.setAttribute('aria-pressed', next ? 'true' : 'false');
    fullscreenButton.textContent = next ? 'Exit fullscreen' : 'Fullscreen';
    window.setTimeout(function() {{
      resize();
      autoFit();
      updateStatus();
      drawSoon();
    }}, 0);
  }}

  function applyGraphPayload(payload) {{
    var previousSelectedId = selectedNode ? selectedNode.id : null;
    var previousDepthValue = depthValue;
    var nextNodes = (payload.nodes || []).filter(function(n) {{ return n.category !== 'root'; }});
    var ids = {{}};
    nextNodes.forEach(function(n) {{ ids[n.id] = true; }});
    var nextEdges = (payload.edges || []).filter(function(e) {{ return ids[e.source] && ids[e.target]; }});
    nodes = nextNodes;
    edges = nextEdges;
    totalNodeCount = nodes.length;
    totalEdgeCount = edges.length;
    fullGraphLoaded = true;
    fullGraphLoading = false;
    pinned = {{}};
    rebuildGraphIndexes();
    selectedNode = previousSelectedId && nodeById[previousSelectedId] ? nodeById[previousSelectedId] : null;
    hoverNode = selectedNode;
    depthValue = selectedNode ? previousDepthValue : 'all';
    if (depthFilter) depthFilter.value = depthValue;
    syncCategoryOptions();
    seedMissingPositions();
    invalidateSearchCache();
    invalidateFilters();
    if (!lockedOverviewIds) reseedVisiblePositions();
    frame = SETTLE;
    autoFit();
    updateInspector();
    setMotionPaused(true);
    if (loadFullButton) {{
      loadFullButton.disabled = true;
      loadFullButton.textContent = 'All data ready; overview capped';
    }}
  }}

  function applyInitialFocus() {{
    if (!initialFocusId || !nodeById[initialFocusId]) return;
    selectedNode = nodeById[initialFocusId];
    hoverNode = selectedNode;
    depthValue = String(initialFocusDepth || 2);
    if (depthFilter) depthFilter.value = depthValue;
    invalidateFilters();
    reseedVisiblePositions();
    frame = SETTLE;
    fitted = true;
    autoFit();
    updateInspector();
  }}

  function loadFullGraph() {{
    if (fullGraphLoaded || fullGraphLoading) return;
    fullGraphLoading = true;
    if (loadFullButton) {{
      loadFullButton.disabled = true;
      loadFullButton.textContent = 'Loading all data...';
    }}
    updateStatus();
    fetch('/api/graph')
      .then(function(response) {{
        if (!response.ok) throw new Error('graph load failed');
        return response.json();
      }})
      .then(function(payload) {{
        applyGraphPayload(payload);
        updateStatus();
        drawSoon();
      }})
      .catch(function() {{
        fullGraphLoading = false;
        if (loadFullButton) {{
          loadFullButton.disabled = false;
          loadFullButton.textContent = 'Retry all data';
        }}
        if (status) status.textContent = 'Graph data load failed; local API did not return graph data.';
      }});
  }}

  canvas.addEventListener('mousedown', function(e) {{
    var rect = canvas.getBoundingClientRect();
    var sx = e.clientX - rect.left, sy = e.clientY - rect.top;
    downX = sx; downY = sy; didDrag = false; didPan = false; suppressClick = false;
    var hit = hitTest(sx, sy);
    if (hit) {{
      dragging = hit; pinned[hit.id] = true;
      canvas.style.cursor = 'grabbing';
      var w = toWorld(sx, sy);
      dragOffX = pos[hit.id].x - w.x; dragOffY = pos[hit.id].y - w.y;
    }} else {{
      panning = true; didPan = false;
      canvas.style.cursor = 'grabbing';
      panStartX = sx - panX * zoom; panStartY = sy - panY * zoom;
    }}
  }});

  canvas.addEventListener('mousemove', function(e) {{
    var rect = canvas.getBoundingClientRect();
    var sx = e.clientX - rect.left, sy = e.clientY - rect.top;
    if (dragging) {{
      if (movedPastThreshold(sx, sy)) didDrag = true;
      var w = toWorld(sx, sy);
      pos[dragging.id].x = w.x + dragOffX; pos[dragging.id].y = w.y + dragOffY;
      updateStatus();
      drawSoon();
    }} else if (panning) {{
      panX = (sx - panStartX) / zoom; panY = (sy - panStartY) / zoom;
      if (movedPastThreshold(sx, sy)) didPan = true;
      updateStatus();
      drawSoon();
    }} else {{
      var hit = hitTest(sx, sy);
      hoverNode = hit;
      if (hit) {{
        tooltip.style.display = 'block';
        tooltip.style.left = (e.clientX + 14) + 'px';
        tooltip.style.top = (e.clientY - 10) + 'px';
        tooltip.textContent = hit.title + ' · ' + hit.category;
        canvas.style.cursor = 'pointer';
      }} else {{
        tooltip.style.display = 'none';
        canvas.style.cursor = 'grab';
      }}
      drawSoon();
    }}
  }});

  canvas.addEventListener('mouseup', function() {{
    if (dragging) {{
      pinned[dragging.id] = didDrag;
      dragging = null;
      suppressClick = didDrag;
      updateStatus();
      drawSoon();
    }}
    if (panning) {{ suppressClick = didPan; }}
    panning = false;
    canvas.style.cursor = hoverNode ? 'pointer' : 'grab';
  }});

  canvas.addEventListener('mouseleave', function() {{
    hoverNode = null;
    if (tooltip) tooltip.style.display = 'none';
    drawSoon();
  }});

  canvas.addEventListener('click', function(e) {{
    if (suppressClick) {{ suppressClick = false; return; }}
    var rect = canvas.getBoundingClientRect();
    var hit = hitTest(e.clientX - rect.left, e.clientY - rect.top);
    if (hit) selectNode(hit);
  }});

  canvas.addEventListener('dblclick', function(e) {{
    e.preventDefault();
    var rect = canvas.getBoundingClientRect();
    var hit = hitTest(e.clientX - rect.left, e.clientY - rect.top);
    if (hit) openNode(hit);
  }});

  canvas.addEventListener('wheel', function(e) {{
    e.preventDefault();
    var rect = canvas.getBoundingClientRect();
    var sx = e.clientX - rect.left, sy = e.clientY - rect.top;
    var before = toWorld(sx, sy);
    var factor = e.deltaY < 0 ? 1.12 : 0.9;
    zoom = Math.max(0.15, Math.min(6, zoom * factor));
    var after = toWorld(sx, sy);
    panX += after.x - before.x;
    panY += after.y - before.y;
    updateStatus();
    drawSoon();
  }}, {{ passive: false }});

  canvas.addEventListener('keydown', function(e) {{
    if (e.key === '+' || e.key === '=') {{ zoom = Math.min(6, zoom * 1.12); updateStatus(); drawSoon(); e.preventDefault(); }}
    if (e.key === '-' || e.key === '_') {{ zoom = Math.max(0.15, zoom * 0.9); updateStatus(); drawSoon(); e.preventDefault(); }}
    if (e.key === '0') {{ resetView(); e.preventDefault(); }}
    if (e.key === 'f' || e.key === 'F') {{ fitCurrentView(); e.preventDefault(); }}
    if (e.key === 'Enter' && hoverNode) {{ openNode(hoverNode); e.preventDefault(); }}
    if (e.key === 'Escape') {{
      if (frameEl && frameEl.classList.contains('is-fullscreen')) {{
        setFullscreen(false);
      }} else {{
        selectedNode = null; invalidateFilters(); updateInspector(); updateStatus(); drawSoon();
      }}
      e.preventDefault();
    }}
    if (e.key === 'l' || e.key === 'L') {{
      cycleLabelMode();
      e.preventDefault();
    }}
  }});

  if (resetButton) resetButton.addEventListener('click', resetView);
  if (fitButton) fitButton.addEventListener('click', fitCurrentView);
  if (labelsButton) labelsButton.addEventListener('click', function() {{
    cycleLabelMode();
  }});
  if (motionButton) motionButton.addEventListener('click', function() {{
    setMotionPaused(!motionPaused);
    saveGraphSettings();
  }});
  if (fullscreenButton) fullscreenButton.addEventListener('click', function() {{
    setFullscreen(!frameEl.classList.contains('is-fullscreen'));
  }});
  if (copyLinkButton) copyLinkButton.addEventListener('click', copyGraphLink);
  if (loadFullButton) loadFullButton.addEventListener('click', loadFullGraph);
  if (inspectorOpen) inspectorOpen.addEventListener('click', function() {{ openNode(selectedNode); }});
  if (inspectorLocal) inspectorLocal.addEventListener('click', function() {{ openLocalGraph(selectedNode, 2); }});
  if (inspectorFocus) inspectorFocus.addEventListener('click', function() {{
    if (!selectedNode) return;
    depthValue = '1';
    if (depthFilter) depthFilter.value = '1';
    invalidateFilters();
    reseedVisiblePositions();
    setMotionPaused(motionPaused);
    autoFit();
    updateStatus();
    drawSoon();
  }});
  if (searchInput) {{
    searchInput.addEventListener('input', function() {{
      searchTerm = searchInput.value.trim().toLowerCase();
      invalidateSearchCache();
      invalidateFilters();
      if (searchTerm && !fullGraphLoaded) loadFullGraph();
      reseedVisiblePositions();
      autoFit();
      updateStatus();
      saveGraphSettings();
      drawSoon();
    }});
    searchInput.addEventListener('keydown', function(e) {{
      if (e.key !== 'Enter') return;
      var match = visibleNodes().find(searchMatches);
      if (match) selectNode(match);
      e.preventDefault();
    }});
  }}
  if (categoryFilter) categoryFilter.addEventListener('change', function() {{
    categoryValue = categoryFilter.value || 'all';
    invalidateFilters();
    reseedVisiblePositions();
    setMotionPaused(motionPaused);
    autoFit();
    updateStatus();
    saveGraphSettings();
    drawSoon();
  }});
  if (legend) legend.addEventListener('click', function(e) {{
    var button = e.target.closest ? e.target.closest('[data-graph-category]') : null;
    if (!button) return;
    var nextCategory = button.getAttribute('data-graph-category') || 'all';
    categoryValue = categoryValue === nextCategory ? 'all' : nextCategory;
    if (categoryFilter) categoryFilter.value = categoryValue;
    invalidateFilters();
    reseedVisiblePositions();
    setMotionPaused(motionPaused);
    autoFit();
    updateStatus();
    saveGraphSettings();
    drawSoon();
  }});
  if (sizeFilter) sizeFilter.addEventListener('change', function() {{
    sizeMode = sizeFilter.value || 'category';
    updateStatus();
    saveGraphSettings();
    drawSoon();
  }});
  if (labelFilter) labelFilter.addEventListener('change', function() {{
    labelMode = labelFilter.value || 'sparse';
    showAllLabels = labelMode === 'all';
    syncLabelsButton();
    updateStatus();
    saveGraphSettings();
    drawSoon();
  }});
  if (displayLimitFilter) displayLimitFilter.addEventListener('change', function() {{
    overviewNodeLimit = normalizeDisplayLimit(displayLimitFilter.value);
    invalidateFilters();
    reseedVisiblePositions();
    setMotionPaused(motionPaused);
    autoFit();
    updateStatus();
    saveGraphSettings();
    drawSoon();
  }});
  if (depthFilter) depthFilter.addEventListener('change', function() {{
    depthValue = depthFilter.value || 'all';
    invalidateFilters();
    reseedVisiblePositions();
    setMotionPaused(motionPaused);
    autoFit();
    updateStatus();
    saveGraphSettings();
    drawSoon();
  }});

  window.addEventListener('resize', function() {{ resize(); if (fitted) autoFit(); updateStatus(); drawSoon(); }});
  resize();
  if (motionPaused) {{ reseedVisiblePositions(); autoFit(); fitted = true; frame = SETTLE; }}
  setMotionPaused(motionPaused);
  syncCategoryOptions();
  if (sizeFilter) sizeFilter.value = sizeMode;
  if (labelFilter) labelFilter.value = labelMode;
  if (searchInput) searchInput.value = searchTerm;
  applyInitialFocus();
  if (searchTerm && !fullGraphLoaded) loadFullGraph();
  syncLabelsButton();
  syncLegendButtons();
  updateInspector();
  updateStatus();
  if (shouldRunContinuously()) startLoop();
  else drawSoon();
}})();
</script>"""


def render_graph_empty_body() -> str:
    """Render the graph page empty state."""
    return (
        '<div class="breadcrumb"><a href="/">Link</a> / graph</div>'
        "<h1>Knowledge Graph</h1>"
        '<div class="graph-empty">'
        "<strong>No graph pages yet.</strong><br>"
        "Add sources, ingest them, then rebuild backlinks."
        '<div class="page-actions">'
        '<a class="button-link" href="/ingest">Open ingest</a>'
        f"{copy_button('ingest the new raw Link files', 'Copy ingest prompt')}"
        "</div>"
        "</div>"
    )


def render_graph_page_body(
    *,
    graph_js: str,
    node_count: int,
    edge_count: int,
    total_node_count: int,
    total_edge_count: int,
    graph_mode: str,
    graph_note: str,
    category_options: str,
    legend_items: str,
    focus_label: str = "",
    focus_depth: int = 2,
    search_label: str = "",
    category_label: str = "",
    size_label: str = "",
    label_label: str = "",
) -> str:
    """Render the graph page shell around the browser simulation script."""
    load_full_button = ""
    if graph_mode != "full":
        load_full_button = (
            '<button id="graph-load-full" type="button" '
            'title="Loads all graph data for search, filters, and focused neighborhoods; '
            'the canvas remains capped until you narrow it.">'
            f"Load all data ({total_node_count} nodes)</button>"
        )
    focus_html = ""
    state_parts = []
    if focus_label:
        state_parts.append(f'Focused on <strong>{html.escape(focus_label)}</strong> · depth {html.escape(str(focus_depth))}')
    if search_label:
        state_parts.append(f'Search <strong>{html.escape(search_label)}</strong>')
    if category_label and category_label != "all":
        state_parts.append(f'Type <strong>{html.escape(category_label)}</strong>')
    if size_label and size_label != "category":
        state_parts.append(f'Size <strong>{html.escape(size_label)}</strong>')
    if label_label and label_label != "sparse":
        state_parts.append(f'Labels <strong>{html.escape(label_label)}</strong>')
    if state_parts:
        focus_html = (
            '<p class="graph-focus-note">'
            f'{". ".join(state_parts)}. '
            '<a href="/graph">Clear filters</a>'
            "</p>"
        )
    bounded_html = ""
    if graph_mode != "full":
        bounded_html = (
            '<p class="graph-focus-note">'
            "<strong>Bounded overview:</strong> "
            f"showing {html.escape(str(node_count))} of {html.escape(str(total_node_count))} nodes. "
            "Use search, type filters, focused neighborhoods, or Load all data before asking the "
            "browser to draw the whole graph."
            "</p>"
        )

    return (
        '<div class="breadcrumb"><a href="/">Link</a> / graph</div>'
        "<h1>Knowledge Graph</h1>"
        '<p class="meta">For large wikis, use fullscreen, zoom, pan, and sparse labels. '
        "The graph is for exploring neighborhoods, not reading every label at once."
        f"{html.escape(graph_note)}</p>"
        f"{bounded_html}"
        f"{focus_html}"
        '<section id="graph-frame" class="graph-frame">'
        '<div class="graph-toolbar" aria-label="Graph controls">'
        '<button id="graph-reset" type="button">Reset</button>'
        '<button id="graph-fit" type="button">Fit view</button>'
        '<button id="graph-labels" type="button" aria-pressed="false">Labels</button>'
        '<button id="graph-motion" type="button" aria-pressed="false">Motion on</button>'
        '<button id="graph-fullscreen" type="button" aria-pressed="false">Fullscreen</button>'
        '<button id="graph-copy-link" type="button">Copy link</button>'
        f"{load_full_button}"
        '<label class="graph-control">Find'
        '<input id="graph-search" type="search" placeholder="node title"></label>'
        '<label class="graph-control">Type'
        f'<select id="graph-category">{category_options}</select></label>'
        '<label class="graph-control">Size'
        '<select id="graph-size"><option value="category">category</option>'
        '<option value="degree">degree</option></select></label>'
        '<label class="graph-control">Labels'
        '<select id="graph-label-density"><option value="sparse">sparse</option>'
        '<option value="neighbors">neighbors</option><option value="all">all</option></select></label>'
        '<label class="graph-control">Display'
        '<select id="graph-display-limit"><option value="250">250 nodes</option>'
        '<option value="650" selected>650 nodes</option><option value="1000">1000 nodes</option></select></label>'
        '<label class="graph-control">Neighborhood'
        '<select id="graph-depth"><option value="all">all</option><option value="1">1 hop</option>'
        '<option value="2">2 hops</option><option value="3">3 hops</option></select></label>'
        '<span id="graph-status" class="graph-status" aria-live="polite">'
        f"{node_count}/{total_node_count} nodes · {edge_count}/{total_edge_count} edges</span>"
        "</div>"
        '<div class="graph-shell">'
        '<canvas id="graph-canvas" tabindex="0" role="img" '
        f'aria-label="Knowledge graph with {node_count} nodes and {edge_count} edges"></canvas>'
        '<aside id="graph-inspector" class="graph-inspector" aria-live="polite">'
        '<strong id="graph-inspector-title">Select a node</strong>'
        '<p id="graph-inspector-meta">Click a node to inspect it. Drag a node to place it. '
        "Double-click a node, or use Open page, to navigate.</p>"
        '<div id="graph-inspector-links" class="graph-inspector-links"></div>'
        '<button id="graph-focus" type="button" disabled>Focus neighborhood</button>'
        '<button id="graph-local" type="button" disabled>Open local graph</button>'
        '<button id="graph-open" type="button" disabled>Open page</button>'
        "</aside>"
        "</div>"
        f'<div id="graph-legend" class="graph-legend">{legend_items}</div>'
        "</section>"
        f"{graph_js}"
    )
