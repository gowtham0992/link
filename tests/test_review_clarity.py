"""What Link says at the moments a person decides: a missed name, a review that switches a rule on,
a recall that finds nothing because a teammate's memory is still waiting."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.frontmatter import update_frontmatter_fields  # noqa: E402
from link_core.memory import resolve_memory_page  # noqa: E402


class ReviewClarityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="link-clarity-")
        self.home = Path(os.path.realpath(self.temp.name)) / "home"
        self.home.mkdir()
        self.target = self.home / "link"
        self.env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home)}
        self.env.pop("LINK_WORKSPACE", None)
        self.env.pop("LINK_CLI_COMMAND", None)
        self.link("init", str(self.target))

    def tearDown(self):
        self.temp.cleanup()

    def link(self, *args: str, code: int = 0) -> subprocess.CompletedProcess:
        result = subprocess.run([sys.executable, str(ROOT / "link.py"), *args],
                                capture_output=True, text=True, env=self.env, timeout=120, cwd=str(self.home))
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def test_a_missed_name_offers_the_memories_that_hold_those_words(self):
        self.link("remember", "The staging API rate limit is 100 requests per minute", str(self.target), "--type", "fact")
        self.link("remember", "I prefer tabs over spaces in Go code", str(self.target), "--type", "preference")
        missed = self.link("archive-memory", "rate limit", str(self.target), code=1).stderr
        self.assertIn("Did you mean: the-staging-api-rate-limit-is-100-requests-per-minute?", missed)
        # Named, never acted on: the memory is still active.
        self.assertIn("status: active", (self.target / "wiki" / "memories"
                                         / "the-staging-api-rate-limit-is-100-requests-per-minute.md").read_text())
        nothing = self.link("archive-memory", "kubernetes", str(self.target), code=1).stderr
        self.assertNotIn("Did you mean", nothing)
        # A path is a path: no guessing around a traversal.
        _, _, error = resolve_memory_page(self.target / "wiki", "../log.md")
        self.assertEqual(error, "memory not found: ../log.md")

    def test_review_says_which_rules_it_puts_in_force(self):
        saved = self.link("remember", "Never run database migrations on Friday", str(self.target),
                          "--type", "preference", "--enforce", "ask command: make migrate*").stdout
        self.assertIn("ask command: make migrate*", saved)
        name = "never-run-database-migrations-on-friday"
        inbox = self.link("memory-inbox", str(self.target)).stdout
        self.assertIn("Reviewing it puts these rules on agent tool calls: ask command: make migrate*", inbox)
        waiting = self.link("explain-memory", name, str(self.target)).stdout
        self.assertIn("Rules waiting for your review: ask command: make migrate*", waiting)
        self.assertNotIn("Rules in force", waiting)
        reviewed = self.link("review-memory", name, str(self.target)).stdout
        self.assertIn("Rules now in force on agent tool calls: ask command: make migrate*", reviewed)
        explained = self.link("explain-memory", name, str(self.target)).stdout
        self.assertIn("Rules in force: ask command: make migrate*", explained)
        self.assertNotIn("Reviewing it puts", self.link("memory-inbox", str(self.target)).stdout)
        payload = json.loads(self.link("explain-memory", name, str(self.target), "--json").stdout)
        self.assertEqual(payload["rules"]["in_force"], ["ask command: make migrate*"])
        # A memory with no rule says nothing about rules.
        self.link("remember", "I prefer short commit subjects", str(self.target), "--type", "preference")
        plain = self.link("review-memory", "i-prefer-short-commit-subjects", str(self.target)).stdout
        self.assertNotIn("Rules", plain)

    def test_a_plainly_worded_rule_is_suggested_when_the_memory_is_saved(self):
        saved = self.link("remember", "Never force push to main", str(self.target), "--type", "preference").stdout
        self.assertIn("ask command: git push --force", saved)
        none = self.link("enforce", "never-force-push-to-main", str(self.target), "--suggest").stdout
        self.assertIn("ask command: git push -f", none)
        self.link("remember", "We decided to use Postgres for billing", str(self.target), "--type", "decision")
        told = self.link("enforce", "we-decided-to-use-postgres-for-billing", str(self.target), "--suggest").stdout
        self.assertIn("Write one yourself", told)

    def test_recall_says_when_the_only_match_is_a_teammates_memory_awaiting_review(self):
        self.link("remember", "Deploys happen on Tuesdays only", str(self.target), "--type", "decision")
        page = self.target / "wiki" / "memories" / "deploys-happen-on-tuesdays-only.md"
        page.write_text(update_frontmatter_fields(
            page.read_text(encoding="utf-8"), {"imported_from": "team", "review_status": "pending"}), encoding="utf-8")
        missed = self.link("recall", "deploys tuesdays", str(self.target)).stdout
        self.assertIn("No matching memories found.", missed)
        self.assertIn("1 memory from your team matches but is waiting for your review", missed)
        self.assertIn("memory-inbox", missed)
        self.assertNotIn("Try different words", missed)
        self.assertIn("Shared by your team", self.link("memory-inbox", str(self.target)).stdout)
        other = self.link("recall", "kubernetes ingress", str(self.target)).stdout
        self.assertNotIn("from your team", other)
        self.link("review-memory", "deploys-happen-on-tuesdays-only", str(self.target))
        self.assertIn("Deploys happen on Tuesdays only", self.link("recall", "deploys tuesdays", str(self.target)).stdout)
        self.assertIn("Shared by: your team",
                      self.link("explain-memory", "deploys-happen-on-tuesdays-only", str(self.target)).stdout)

    def test_a_sentence_is_reworded_whole_or_left_in_the_persons_words(self):
        from link_core.memory import normalize_proposed_memory as reword

        self.assertEqual(reword("I prefer tabs over spaces", "preference"), "User prefers tabs over spaces.")
        self.assertEqual(reword("We decided to use Kong", "decision"), "Project decided to use Kong.")
        # Rewording only the opening would speak as two people.
        self.assertEqual(reword("My name is Sam and I work at Acme", "fact"), "My name is Sam and I work at Acme.")
        self.assertEqual(reword("I prefer tabs because my editor handles them", "preference"),
                         "I prefer tabs because my editor handles them.")

    def test_a_dated_recall_that_finds_nothing_says_it_is_the_date(self):
        self.link("remember", "I prefer tabs over spaces", str(self.target), "--type", "preference")
        text = self.link("recall", "tabs", str(self.target), "--as-of", "2020-01-01").stdout
        self.assertIn("Nothing matching was active on 2020-01-01", text)
        self.assertNotIn("Try different words", text)

    def test_next_steps_name_a_command_that_exists_for_an_installed_user(self):
        self.link("remember", "I prefer tabs", str(self.target), "--type", "preference")
        for command in ("memory-audit", "brief"):
            text = self.link(command, *(["session start"] if command == "brief" else []), str(self.target)).stdout
            self.assertNotIn("python3 link.py", text, command)


if __name__ == "__main__":
    unittest.main()
