import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.web_graph import (  # noqa: E402
    GRAPH_CATEGORY_COLORS,
    graph_category_options,
    graph_initial_payload,
    graph_legend_items,
    graph_needs_bounded_overview,
    render_graph_empty_body,
    render_graph_page_body,
    render_graph_script,
)


class WebGraphCoreTests(unittest.TestCase):
    def test_graph_initial_payload_uses_full_graph_under_limit(self):
        graph = {
            "nodes": [
                {"id": "root", "category": "root"},
                {"id": "a", "title": "A", "category": "concepts"},
                {"id": "b", "title": "B", "category": "sources"},
            ],
            "edges": [
                {"source": "a", "target": "b"},
                {"source": "root", "target": "a"},
            ],
        }

        payload = graph_initial_payload(graph, full_node_limit=10)

        self.assertEqual(payload["graph_mode"], "full")
        self.assertEqual(payload["node_count"], 2)
        self.assertEqual(payload["edge_count"], 1)
        self.assertEqual(payload["total_node_count"], 2)
        self.assertEqual(payload["total_edge_count"], 1)

    def test_graph_initial_payload_uses_summary_for_large_graph(self):
        full_graph = {
            "nodes": [{"id": f"n-{index}", "category": "concepts"} for index in range(5)],
            "edges": [{"source": "n-0", "target": "n-1"}],
        }
        summary_graph = {
            "nodes": [{"id": "n-0", "category": "concepts"}, {"id": "n-1", "category": "concepts"}],
            "edges": [{"source": "n-0", "target": "n-1"}],
        }

        payload = graph_initial_payload(full_graph, summary_graph=summary_graph, full_node_limit=2)

        self.assertEqual(payload["graph_mode"], "summary")
        self.assertEqual(payload["node_count"], 2)
        self.assertEqual(payload["edge_count"], 1)
        self.assertEqual(payload["total_node_count"], 5)
        self.assertIn("fast overview", payload["graph_note"])
        self.assertTrue(graph_needs_bounded_overview(full_graph, full_node_limit=2))

    def test_graph_category_options_and_legend_escape_content(self):
        nodes = [
            {"id": "a", "category": "concepts"},
            {"id": "b", "category": 'weird"type'},
            {"id": "root", "category": "root"},
        ]

        options = graph_category_options(nodes)
        legend = graph_legend_items({**GRAPH_CATEGORY_COLORS, "<bad>": '"red"'})

        self.assertIn('<option value="concepts">concepts</option>', options)
        self.assertIn('<option value="weird&quot;type">weird&quot;type</option>', options)
        self.assertNotIn(">root<", options)
        self.assertIn('data-graph-category="concepts"', legend)
        self.assertIn("&lt;bad&gt;", legend)
        self.assertIn("&quot;red&quot;", legend)

    def test_render_graph_empty_body(self):
        html = render_graph_empty_body()

        self.assertIn("Knowledge Graph", html)
        self.assertIn("No graph pages yet.", html)
        self.assertIn('href="/ingest"', html)
        self.assertIn('data-copy-text="ingest the new raw Link files"', html)
        self.assertIn("Copy ingest prompt", html)
        self.assertNotIn('id="graph-canvas"', html)

    def test_render_graph_page_body_includes_controls_and_escapes_note(self):
        html = render_graph_page_body(
            graph_js="<script>var resetButton = true;</script>",
            node_count=3,
            edge_count=2,
            total_node_count=10,
            total_edge_count=20,
            graph_mode="summary",
            graph_note=' <fast & "bounded">',
            category_options='<option value="concepts">concepts</option>',
            legend_items="<span></span>concepts",
        )

        self.assertIn('id="graph-reset"', html)
        self.assertIn('id="graph-fit"', html)
        self.assertIn('id="graph-labels"', html)
        self.assertIn('id="graph-motion"', html)
        self.assertIn('id="graph-fullscreen"', html)
        self.assertIn('id="graph-copy-link"', html)
        self.assertIn("Load all data (10 nodes)", html)
        self.assertIn("the canvas remains capped until you narrow it.", html)
        self.assertIn("<strong>Bounded overview:</strong>", html)
        self.assertIn("showing 3 of 10 nodes", html)
        self.assertIn("Use search, type filters, focused neighborhoods, or Load all data", html)
        self.assertIn('id="graph-search"', html)
        self.assertIn('id="graph-category"', html)
        self.assertIn('id="graph-size"', html)
        self.assertIn('id="graph-label-density"', html)
        self.assertIn('id="graph-display-limit"', html)
        self.assertIn('<option value="degree">degree</option>', html)
        self.assertIn('<option value="neighbors">neighbors</option>', html)
        self.assertIn('<option value="1000">1000 nodes</option>', html)
        self.assertIn('<option value="concepts">concepts</option>', html)
        self.assertIn('id="graph-depth"', html)
        self.assertIn('id="graph-status"', html)
        self.assertIn('id="graph-legend"', html)
        self.assertIn("3/10 nodes · 2/20 edges", html)
        self.assertIn('role="img"', html)
        self.assertIn("Focus neighborhood", html)
        self.assertIn("Open local graph", html)
        self.assertIn("Open page", html)
        self.assertIn("&lt;fast &amp; &quot;bounded&quot;&gt;", html)
        self.assertIn("<script>var resetButton = true;</script>", html)

    def test_render_graph_page_body_includes_graph_state_note(self):
        html = render_graph_page_body(
            graph_js="<script></script>",
            node_count=3,
            edge_count=2,
            total_node_count=3,
            total_edge_count=2,
            graph_mode="full",
            graph_note="",
            category_options="",
            legend_items="",
            focus_label='Memory <One>',
            focus_depth=2,
            search_label='agent <memory>',
            category_label="memories",
            size_label="degree",
            label_label="neighbors",
        )

        self.assertIn("Focused on <strong>Memory &lt;One&gt;</strong> · depth 2", html)
        self.assertIn("Search <strong>agent &lt;memory&gt;</strong>", html)
        self.assertIn("Type <strong>memories</strong>", html)
        self.assertIn("Size <strong>degree</strong>", html)
        self.assertIn("Labels <strong>neighbors</strong>", html)
        self.assertIn('<a href="/graph">Clear filters</a>', html)

    def test_render_graph_page_body_omits_load_button_for_full_graph(self):
        html = render_graph_page_body(
            graph_js="<script></script>",
            node_count=3,
            edge_count=2,
            total_node_count=3,
            total_edge_count=2,
            graph_mode="full",
            graph_note="",
            category_options="",
            legend_items="",
        )

        self.assertNotIn("Load all data", html)
        self.assertNotIn("Bounded overview", html)

    def test_render_graph_script_uses_supplied_json_payloads(self):
        script = render_graph_script(
            nodes_json='[{"id":"a","title":"A","category":"concepts"}]',
            edges_json='[{"source":"a","target":"b"}]',
            cat_colors_json='{"concepts":"#fff"}',
            graph_mode_json='"summary"',
            focus_id_json='"a"',
            focus_depth=2,
            search_json='"memory"',
            category_json='"concepts"',
            size_json='"degree"',
            label_json='"neighbors"',
            total_node_count=10,
            total_edge_count=20,
        )

        self.assertIn('var nodes = [{"id":"a","title":"A","category":"concepts"}];', script)
        self.assertIn('var edges = [{"source":"a","target":"b"}];', script)
        self.assertIn('var catColors = {"concepts":"#fff"};', script)
        self.assertIn('var initialGraphMode = "summary";', script)
        self.assertIn('var initialFocusId = "a";', script)
        self.assertIn("var initialFocusDepth = 2;", script)
        self.assertIn('var initialSearchTerm = "memory";', script)
        self.assertIn('var initialCategoryValue = "concepts";', script)
        self.assertIn('var initialSizeValue = "degree";', script)
        self.assertIn('var initialLabelMode = "neighbors";', script)
        self.assertIn("var totalNodeCount = 10;", script)
        self.assertIn("var totalEdgeCount = 20;", script)
        self.assertIn("var GRAPH_STORAGE_KEY = 'link.graph.controls.v1';", script)
        self.assertIn("var fitButton = document.getElementById('graph-fit');", script)
        self.assertIn("function categoryClusterCenter(category, total)", script)
        self.assertIn("Large graphs skip physics, so they use stable category clusters instead of global rings.", script)
        self.assertIn("function readGraphSettings()", script)
        self.assertIn("function saveGraphSettings()", script)
        self.assertIn("function fitCurrentView()", script)
        self.assertIn("var storedGraphSettings = readGraphSettings();", script)
        self.assertIn("var showAllLabels = labelMode === 'all';", script)
        self.assertIn("storedGraphSettings.categoryValue", script)
        self.assertIn("storedGraphSettings.sizeMode", script)
        self.assertIn("storedGraphSettings.labelMode", script)
        self.assertIn("var sizeFilter = document.getElementById('graph-size');", script)
        self.assertIn("var labelFilter = document.getElementById('graph-label-density');", script)
        self.assertIn("var displayLimitFilter = document.getElementById('graph-display-limit');", script)
        self.assertIn("function normalizeDisplayLimit(value)", script)
        self.assertIn("displayLimit: overviewNodeLimit", script)
        self.assertIn("display capped", script)
        self.assertIn("if (sizeMode && sizeMode !== 'category') params.set('size', sizeMode);", script)
        self.assertIn("if (labelMode && labelMode !== 'sparse') params.set('labels', labelMode);", script)
        self.assertIn("if (sizeMode === 'degree')", script)
        self.assertIn("function cycleLabelMode()", script)
        self.assertIn("labelFilter.addEventListener('change'", script)
        self.assertIn("displayLimitFilter.addEventListener('change'", script)
        self.assertIn("if (fitButton) fitButton.addEventListener('click', fitCurrentView);", script)
        self.assertIn("if (searchInput) searchInput.value = searchTerm;", script)
        self.assertIn("var copyLinkButton = document.getElementById('graph-copy-link');", script)
        self.assertIn("var legend = document.getElementById('graph-legend');", script)
        self.assertIn("function syncLegendButtons()", script)
        self.assertIn("if (legend) legend.addEventListener('click'", script)
        self.assertIn("function visibleNodes()", script)
        self.assertIn("function graphStateUrl()", script)
        self.assertIn("function graphHref(id, depth)", script)
        self.assertIn("params.set('focus', id);", script)
        self.assertIn("params.set('depth', String(depth || 2));", script)
        self.assertIn("return '/graph?' + params.toString();", script)
        self.assertIn("canvas.addEventListener('dblclick'", script)


if __name__ == "__main__":
    unittest.main()
