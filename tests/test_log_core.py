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


class LogChainHardeningTests(unittest.TestCase):
    """The chain survives concurrency and odd input, and notices cuts."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="link-log-")
        self.wiki = Path(self.temp.name) / "wiki"
        self.wiki.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_concurrent_writers_do_not_fork_the_chain(self):
        import subprocess
        script = (
            "import sys; sys.path.insert(0, %r)\n"
            "from pathlib import Path\n"
            "from link_core.log import append_log\n"
            "for i in range(15):\n"
            "    append_log(Path(%r), '2026-09-26T00:00:00Z', 'test', f'writer {sys.argv[1]} entry {i}', [])\n"
        ) % (str(ROOT / "mcp_package"), str(self.wiki))
        procs = [subprocess.Popen([sys.executable, "-c", script, str(n)]) for n in range(4)]
        for proc in procs:
            self.assertEqual(proc.wait(timeout=60), 0)
        report = verify_log_integrity(self.wiki)
        self.assertTrue(report["passed"], report["findings"])
        self.assertEqual(report["hashed_entries"], 60)

    def test_newline_in_a_description_keeps_the_entry_verifiable(self):
        append_log(self.wiki, "2026-09-26T00:00:00Z", "remember", "Title line one\nline two", ["reason\nsecond line"])
        report = verify_log_integrity(self.wiki)
        self.assertTrue(report["passed"], report["findings"])

    def _three_entries(self):
        for i in range(3):
            append_log(self.wiki, f"2026-09-26T00:00:0{i}Z", "remember", f"entry {i}", [f"detail {i}"])

    def test_cutting_the_head_of_the_log_is_detected(self):
        self._three_entries()
        text = (self.wiki / "log.md").read_text(encoding="utf-8")
        blocks = text.split("## [")
        (self.wiki / "log.md").write_text(blocks[0] + "## [" + "## [".join(blocks[2:]), encoding="utf-8")
        report = verify_log_integrity(self.wiki)
        self.assertFalse(report["passed"])
        self.assertTrue(any("mid-chain" in f for f in report["findings"]), report["findings"])

    def test_cutting_the_tail_of_the_log_is_detected(self):
        self._three_entries()
        text = (self.wiki / "log.md").read_text(encoding="utf-8")
        (self.wiki / "log.md").write_text(text[: text.rindex("## [")], encoding="utf-8")
        report = verify_log_integrity(self.wiki)
        self.assertFalse(report["passed"])
        self.assertEqual(report["anchor"], "mismatch")

    def test_forget_redacts_rotated_logs_and_keeps_the_chain(self):
        from link_core.log import redact_log_references
        for i in range(40):
            append_log(self.wiki, "2026-09-26T00:00:00Z", "remember", f"Secret project Bluebird note {i}",
                       ["x" * 200], max_bytes=4000, backups=5)
        rotated = sorted(self.wiki.glob("log.md.*"))
        self.assertTrue(rotated, "test needs at least one rotated file")
        redact_log_references(self.wiki, ["Secret project Bluebird"], "2026-09-26T01:00:00Z", "forget")
        for path in [self.wiki / "log.md", *rotated]:
            self.assertNotIn("Bluebird", path.read_text(encoding="utf-8"), path.name)
        report = verify_log_integrity(self.wiki)
        self.assertTrue(report["passed"], report["findings"])
