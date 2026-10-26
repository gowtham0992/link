"""Anchors reach memory records, the recall packet and `lnk stale`."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.memory import memory_records, write_memory_page  # noqa: E402

SOURCE = "import os\n\n\ndef parse_config(path):\n    return path\n"


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.test"},
    )


class AnchorWiringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "src" / "app.py").write_text(SOURCE, encoding="utf-8")
        _git(self.repo, "init", "--initial-branch", "main")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-m", "seed")
        self.workspace = Path(self.temp.name) / "ws"
        self.wiki = self.workspace / "wiki"
        (self.wiki / "memories").mkdir(parents=True)
        (self.wiki / "index.md").write_text("# Index\n", encoding="utf-8")
        (self.wiki / "log.md").write_text("# Log\n", encoding="utf-8")
        cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            write_memory_page(
                self.wiki, "`parse_config` in src/app.py must stay side-effect free.", title=None,
                memory_type="decision", scope="user", tags=None, source="test",
                timestamp="2026-09-26T00:00:00Z", records=[],
                log_writer=lambda *a: None, rebuild_backlinks=lambda: True,
            )
        finally:
            os.chdir(cwd)

    def tearDown(self):
        self.temp.cleanup()

    def test_record_exposes_anchors(self):
        # The anchor names the repository it belongs to (its root commit).
        anchors = memory_records(self.wiki)[0]["anchors"]
        self.assertEqual(len(anchors), 1)
        self.assertRegex(anchors[0], r"^src/app\.py:4 parse_config @[0-9a-f]{12}$")

    def test_lnk_stale_reports_a_removed_symbol(self):
        (self.repo / "src" / "app.py").write_text(SOURCE.replace("parse_config", "load_settings"), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(ROOT / "link.py"), "stale", str(self.workspace), "--repo", str(self.repo)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("parse_config", result.stdout)


if __name__ == "__main__":
    unittest.main()
