"""A real Link 2.3.0 workspace, driven through the current CLI.

`tests/fixtures/link-2.3.0-workspace.tar.gz` was made by Link 2.3.0 itself
(demo + two `remember`s + one `session-end` capture + one query), and holds
only the data a user keeps: wiki/, raw/, .link-cache/ and the ignore files.
No 2.x runtime is in it, so every command below runs today's code against
yesterday's files - the upgrade path is tested, not assumed.
"""
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "link-2.3.0-workspace.tar.gz"
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.log import verify_log_integrity  # noqa: E402
from link_core.wiki import _persistent_fts_path as page_fts_path  # noqa: E402


def lnk(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "link.py"), *args],
        capture_output=True, text=True, timeout=120, check=False,
    )


class UpgradeFrom2xTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="link-upgrade-2x-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        with tarfile.open(FIXTURE) as archive:
            # filter= exists from 3.10.12/3.11.4; older patch releases lack it.
            safe = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
            archive.extractall(self.tmp, **safe)
        self.workspace = self.tmp
        self.wiki = self.tmp / "wiki"

    def json_of(self, *args: str) -> dict:
        result = lnk(*args, str(self.workspace), "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_fixture_is_the_2x_shape(self):
        # Guards the fixture itself: if someone regenerates it with a newer
        # Link, this test stops proving anything about 2.x.
        self.assertTrue((self.workspace / ".link-cache" / "page-fts-v1.sqlite").exists())
        self.assertFalse(page_fts_path(self.wiki).exists())
        self.assertFalse((self.workspace / ".link-cache" / "log-anchor.json").exists())
        for runtime in ("link.py", "serve.py", "link_core"):
            self.assertFalse((self.workspace / runtime).exists(), runtime)

    def test_migrate_status_validate(self):
        migrate = lnk("migrate", str(self.workspace))
        self.assertEqual(migrate.returncode, 0, migrate.stdout + migrate.stderr)

        status = self.json_of("status")
        self.assertTrue(status["ready"])
        self.assertEqual(status["memory_count"], 6)
        self.assertEqual(status["active_memory_count"], 6)
        self.assertEqual(status["schema"]["status"], "current")
        self.assertFalse(status["schema"]["needs_migration"])
        self.assertEqual(status["search_backend"], "sqlite-fts")
        # The 2.x FTS cache is not reused; the current one is built beside it.
        self.assertFalse(status["fts_index"]["reused"])
        self.assertEqual(Path(status["fts_index"]["path"]), page_fts_path(self.wiki))
        self.assertTrue(page_fts_path(self.wiki).exists())

        validate = lnk("validate", str(self.workspace))
        self.assertEqual(validate.returncode, 0, validate.stdout + validate.stderr)
        self.assertIn("0 errors", validate.stdout)

    def test_recall_and_search_find_2x_content(self):
        recall = self.json_of("recall", "deploy day")
        names = [memory["name"] for memory in recall["memories"]]
        self.assertIn("payments-deploy-day", names)
        top = recall["memories"][0]
        self.assertEqual(top["name"], "payments-deploy-day")
        self.assertIn("Tuesdays", top["tldr"])
        # Written by `remember` in 2.x, never reviewed: still gated today.
        self.assertEqual(top["recall"]["state"], "needs_review")

        port = self.json_of("recall", "staging port")
        self.assertIn("staging-port", [memory["name"] for memory in port["memories"]])

        query = lnk("query", "transformers attention", str(self.workspace), "--budget", "micro", "--json")
        self.assertEqual(query.returncode, 0, query.stdout + query.stderr)
        packet = json.loads(query.stdout)
        self.assertTrue(packet["found"])
        self.assertIn("transformers", [item["name"] for item in packet["recall_capsule"]["items"]])

    def test_2x_capture_is_reviewable(self):
        inbox = self.json_of("capture-inbox")
        self.assertEqual(inbox["count"], 1)
        capture = inbox["captures"][0]
        self.assertEqual(capture["path"], "raw/memory-captures/20260927T031609Z-session-end.md")
        self.assertGreaterEqual(capture["proposal_count"], 1)
        self.assertEqual(capture["secret_warnings"], [])

    def test_2x_log_verifies_and_first_write_anchors_it(self):
        before = verify_log_integrity(self.wiki)
        self.assertTrue(before["passed"], before)
        self.assertEqual(before["anchor"], "missing")  # 2.x never wrote one

        remember = lnk("remember", "Release notes live in CHANGELOG.md", str(self.workspace),
                       "--type", "fact", "--title", "Release notes location")
        self.assertEqual(remember.returncode, 0, remember.stdout + remember.stderr)

        after = verify_log_integrity(self.wiki)
        self.assertTrue(after["passed"], after)
        self.assertEqual(after["anchor"], "ok")
        self.assertEqual(after["legacy_entries"], before["legacy_entries"])
        self.assertEqual(after["hashed_entries"], before["hashed_entries"] + 1)
        self.assertEqual(self.json_of("status")["memory_count"], 7)


if __name__ == "__main__":
    unittest.main()
