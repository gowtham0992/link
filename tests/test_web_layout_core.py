import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.web_layout import render_footer_html, render_header_html, render_layout, render_stat_grid  # noqa: E402


class WebLayoutCoreTests(unittest.TestCase):
    def test_header_has_primary_navigation_and_search(self):
        html = render_header_html()

        self.assertIn('<a href="/ingest">ingest</a>', html)
        self.assertIn('<a href="/health">health</a>', html)
        self.assertIn('<a href="/brief">brief</a>', html)
        self.assertIn('<a href="/propose">propose</a>', html)
        self.assertIn('<a href="/graph">graph</a>', html)
        self.assertIn('class="nav-more"', html)
        self.assertIn('<summary>more</summary>', html)
        self.assertIn('id="search-input"', html)
        self.assertIn('aria-label="Search Link"', html)
        self.assertIn("data-theme-toggle", html)

    def test_footer_points_to_github(self):
        html = render_footer_html()

        self.assertIn("local agent memory", html)
        self.assertIn("https://github.com/gowtham0992/link", html)

    def test_layout_escapes_title_and_page_class(self):
        html = render_layout('<Title>', "<main>Body</main>", page_class='graph" onclick="bad')
        from link_core.web_layout import viewer_assets
        html += "".join(text for text, _ in viewer_assets().values())

        self.assertIn("<title>&lt;Title&gt; — Link</title>", html)
        self.assertIn('class="graph&quot; onclick=&quot;bad"', html)
        self.assertIn("<main>Body</main>", html)
        self.assertIn("document.activeElement.id === 'search-input'", html)
        self.assertIn("window.location.href = '/search?q=' + encodeURIComponent(q);", html)
        self.assertIn("active.setAttribute('aria-current', 'page');", html)
        self.assertIn("current.indexOf('/page/') === 0", html)
        self.assertIn("localStorage.getItem('link-theme')", html)
        self.assertIn("navigator.clipboard.writeText", html)
        self.assertIn("/api/raw-source", html)

    def test_stat_grid_escapes_values_and_labels(self):
        html = render_stat_grid([("<2>", "raw <files>")])

        self.assertIn("home-stats", html)
        self.assertIn("&lt;2&gt;", html)
        self.assertIn("raw &lt;files&gt;", html)
        self.assertNotIn("<2>", html)


if __name__ == "__main__":
    unittest.main()
