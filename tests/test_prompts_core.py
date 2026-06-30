import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.prompts import starter_prompt_payload, welcome_payload  # noqa: E402


class PromptsCoreTests(unittest.TestCase):
    def make_wiki(self, parent: Path) -> Path:
        wiki = parent / "wiki"
        wiki.mkdir(parents=True, exist_ok=True)
        (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
        return wiki

    def test_global_wiki_gets_personal_memory_prompts(self):
        root = Path(tempfile.mkdtemp(prefix="link-prompts-core-"))
        wiki = self.make_wiki(root)

        payload = starter_prompt_payload(wiki)
        prompts = [str(item["prompt"]) for item in payload["prompts"]]

        self.assertEqual(payload["project"], "")
        self.assertIn("remember that I prefer local-first agent memory", prompts)
        self.assertIn("what does Link know about me?", prompts)
        self.assertIn("propose memories from raw/<file>", prompts)
        self.assertTrue(str(payload["shortcut"]).startswith("lnk next "))
        self.assertTrue(any(command.startswith("lnk health ") for command in payload["commands"]))
        self.assertTrue(any(str(root.resolve()) in command for command in payload["commands"]))

    def test_git_project_gets_project_memory_prompts(self):
        root = Path(tempfile.mkdtemp(prefix="link-prompts-core-"))
        project = root / "Client Launch"
        (project / ".git").mkdir(parents=True)
        wiki = self.make_wiki(project)

        payload = starter_prompt_payload(wiki)
        prompts = [str(item["prompt"]) for item in payload["prompts"]]

        self.assertEqual(payload["project"], "client-launch")
        self.assertIn("remember that this project uses Link for local agent memory", prompts)
        self.assertIn("what does Link remember about this project?", prompts)

    def test_explicit_project_is_normalized(self):
        root = Path(tempfile.mkdtemp(prefix="link-prompts-core-"))
        wiki = self.make_wiki(root)

        payload = starter_prompt_payload(wiki, project="Client Launch")

        self.assertEqual(payload["project"], "client-launch")

    def test_welcome_payload_returns_short_proof_path(self):
        root = Path(tempfile.mkdtemp(prefix="link-prompts-core-"))
        wiki = self.make_wiki(root)

        payload = welcome_payload(wiki, project="Client Launch")

        self.assertEqual(payload["project"], "client-launch")
        self.assertEqual(len(payload["steps"]), 3)
        self.assertEqual(payload["steps"][0]["prompt"], "is Link ready?")
        self.assertIn("Agent can find Link", payload["steps"][0]["proves"])
        self.assertTrue(any(command.startswith("lnk serve ") for command in payload["commands"]))
        self.assertTrue(any(str(root.resolve()) in command for command in payload["commands"]))
        self.assertIn("http://127.0.0.1:3000/onboard", payload["urls"])
        self.assertIn("http://127.0.0.1:3000/health", payload["urls"])


if __name__ == "__main__":
    unittest.main()
