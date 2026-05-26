import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.log import append_log  # noqa: E402
from link_core.memory_log import memory_log_payload  # noqa: E402


class MemoryLogCoreTests(unittest.TestCase):
    def test_memory_log_filters_lifecycle_entries(self):
        root = Path(tempfile.mkdtemp(prefix="link-memory-log-"))
        wiki = root / "wiki"
        wiki.mkdir(parents=True)
        append_log(wiki, "2026-05-25T00:00:00Z", "rebuild-index", "Rebuilt index", ["Pages: 3"])
        append_log(
            wiki,
            "2026-05-25T00:01:00Z",
            "remember",
            "Prefer local memory",
            ["Created: memories/prefer-local-memory.md", "Scope: user"],
        )

        payload = memory_log_payload(wiki)

        self.assertEqual(payload["schema"], "link-memory-log-v1")
        self.assertEqual(payload["count"], 1)
        entry = payload["entries"][0]
        self.assertEqual(entry["operation"], "remember")
        self.assertEqual(entry["memory_paths"], ["wiki/memories/prefer-local-memory.md"])
        self.assertIn("Memory bodies", payload["privacy_note"])

    def test_memory_log_can_hide_capture_events(self):
        root = Path(tempfile.mkdtemp(prefix="link-memory-log-"))
        wiki = root / "wiki"
        wiki.mkdir(parents=True)
        append_log(wiki, "2026-05-25T00:00:00Z", "capture-session", "Captured raw/memory-captures/a.md", [])

        payload = memory_log_payload(wiki, include_captures=False)

        self.assertEqual(payload["count"], 0)

    def test_memory_log_includes_nonstandard_operations_that_touch_memories(self):
        root = Path(tempfile.mkdtemp(prefix="link-memory-log-"))
        wiki = root / "wiki"
        wiki.mkdir(parents=True)
        append_log(
            wiki,
            "2026-05-25T00:00:00Z",
            "demo",
            "create first-run sample wiki",
            ["Created: memories/prefer-local-memory.md"],
        )

        payload = memory_log_payload(wiki)

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["entries"][0]["operation"], "demo")
        self.assertEqual(payload["entries"][0]["memory_paths"], ["wiki/memories/prefer-local-memory.md"])


if __name__ == "__main__":
    unittest.main()
