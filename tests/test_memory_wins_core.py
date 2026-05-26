import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.memory_wins import memory_wins_payload  # noqa: E402


def write_memory(
    wiki: Path,
    name: str,
    *,
    title: str,
    review_status: str = "reviewed",
    project: str = "",
    source: str = "unit test",
    review_after: str = "",
) -> None:
    project_line = f'project: "{project}"\n' if project else ""
    review_after_line = f'review_after: "{review_after}"\n' if review_after else ""
    path = wiki / "memories" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "type: memory\n"
        f'title: "{title}"\n'
        "memory_type: project\n"
        "scope: project\n"
        f"{project_line}"
        "status: active\n"
        'date_captured: "2026-05-25T00:00:00Z"\n'
        'updated_at: "2026-05-25T00:01:00Z"\n'
        "update_count: 1\n"
        f'source: "{source}"\n'
        f"review_status: {review_status}\n"
        f"{review_after_line}"
        "---\n\n"
        f"# {title}\n\n"
        f"> **TLDR:** {title} should be reusable across agents.\n\n"
        "## Memory\n\n"
        f"{title} should be reusable across agents.\n",
        encoding="utf-8",
    )


class MemoryWinsCoreTests(unittest.TestCase):
    def test_memory_wins_payload_summarizes_local_signals_without_telemetry(self):
        root = Path(tempfile.mkdtemp(prefix="link-memory-wins-"))
        wiki = root / "wiki"
        wiki.mkdir(parents=True)
        write_memory(wiki, "alpha", title="Alpha continuity", project="alpha", review_after="2026-12-01")
        write_memory(wiki, "pending", title="Pending memory", review_status="pending")

        payload = memory_wins_payload(wiki)

        self.assertEqual(payload["schema"], "link-memory-wins-v1")
        self.assertEqual(payload["active_count"], 2)
        self.assertEqual(payload["reviewed_active_count"], 1)
        self.assertEqual(payload["review_count"], 1)
        self.assertEqual(payload["project_count"], 1)
        self.assertEqual(payload["guardrail_count"], 1)
        self.assertIn("not telemetry", payload["honest_note"])
        self.assertEqual(payload["wins"][0]["code"], "reusable_context")
        self.assertEqual(payload["wins"][0]["count"], 2)
        recent_names = {memory["name"] for memory in payload["recent_memories"]}
        self.assertIn("alpha", recent_names)
        self.assertNotIn("body", payload["recent_memories"][0])

    def test_memory_wins_project_filter_keeps_global_memory_and_matching_project(self):
        root = Path(tempfile.mkdtemp(prefix="link-memory-wins-project-"))
        wiki = root / "wiki"
        wiki.mkdir(parents=True)
        write_memory(wiki, "alpha", title="Alpha continuity", project="alpha")
        write_memory(wiki, "beta", title="Beta continuity", project="beta")

        payload = memory_wins_payload(wiki, project="alpha")

        self.assertEqual(payload["project"], "alpha")
        self.assertEqual(payload["active_count"], 1)
        self.assertEqual(payload["recent_memories"][0]["name"], "alpha")


if __name__ == "__main__":
    unittest.main()
