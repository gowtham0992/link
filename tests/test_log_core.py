import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.log import DEFAULT_LOG_TEXT, append_log, read_log_entries, verify_log_integrity  # noqa: E402


class LogCoreTests(unittest.TestCase):
    def test_append_log_rotates_unbounded_operation_log(self):
        root = Path(tempfile.mkdtemp(prefix="link-log-core-"))
        wiki_dir = root / "wiki"
        wiki_dir.mkdir(parents=True)
        log_path = wiki_dir / "log.md"
        log_path.write_text(DEFAULT_LOG_TEXT + ("older entry\n" * 10), encoding="utf-8")

        append_log(
            wiki_dir,
            "2026-05-17T00:00:00Z",
            "remember",
            "Saved memory",
            ["Memory: testing Link"],
            max_bytes=80,
            backups=2,
        )

        current = log_path.read_text(encoding="utf-8")
        self.assertTrue(current.startswith(DEFAULT_LOG_TEXT))
        self.assertIn("remember | Saved memory", current)
        self.assertIn("- Memory: testing Link", current)
        self.assertIn("- log_previous_hash:", current)
        self.assertIn("- log_entry_hash:", current)
        self.assertIn("older entry", (wiki_dir / "log.md.1").read_text(encoding="utf-8"))

    def test_read_log_entries_parses_structured_log(self):
        root = Path(tempfile.mkdtemp(prefix="link-log-core-"))
        wiki_dir = root / "wiki"
        wiki_dir.mkdir(parents=True)

        append_log(
            wiki_dir,
            "2026-05-17T00:00:00Z",
            "remember",
            "Prefer local memory",
            ["Created: memories/prefer-local-memory.md", "Scope: user"],
        )

        entries = read_log_entries(wiki_dir)

        self.assertEqual(entries[-1]["operation"], "remember")
        self.assertEqual(entries[-1]["description"], "Prefer local memory")
        self.assertEqual(entries[-1]["details"], ["Created: memories/prefer-local-memory.md", "Scope: user"])
        self.assertIn("entry_hash", entries[-1])

    def test_verify_log_integrity_detects_tampered_entries(self):
        root = Path(tempfile.mkdtemp(prefix="link-log-core-"))
        wiki_dir = root / "wiki"
        wiki_dir.mkdir(parents=True)

        append_log(
            wiki_dir,
            "2026-05-17T00:00:00Z",
            "remember",
            "Prefer local memory",
            ["Created: memories/prefer-local-memory.md", "Scope: user"],
        )
        self.assertTrue(verify_log_integrity(wiki_dir)["passed"])

        log_path = wiki_dir / "log.md"
        log_path.write_text(
            log_path.read_text(encoding="utf-8").replace("Scope: user", "Scope: team"),
            encoding="utf-8",
        )

        integrity = verify_log_integrity(wiki_dir)
        self.assertFalse(integrity["passed"])
        self.assertIn("hash mismatch", "; ".join(integrity["findings"]))


if __name__ == "__main__":
    unittest.main()
