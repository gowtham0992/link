"""What a session capture proposes as durable memory, and what it must not.

Measured on real developer sessions before these filters: 58 proposals from
12 transcripts, about 3 worth keeping. The junk shapes below are paraphrased
from that run; each must stay out, and the durable shapes must stay in.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.memory import (  # noqa: E402
    classify_memory_segment,
    extract_procedure_candidates,
    non_durable_reason,
)

JUNK = {
    "task instruction": "Do not edit any files.",
    "task instruction, long": "Do not modify files, deploy anything, commit anything or push anything.",
    "task instruction, no pointer": "Do not score the quality of the submission package.",
    "request to the agent": "I want you to look at the readme and the demo video.",
    "request, normalized": "User wants you to check again so you can see where we are.",
    "intention": "I want to know if this is ready for an external user.",
    "conversation goal": "I want a brutally honest review of the product.",
    "vague want": "User wants everything.",
    "throwaway": "Everything should be free lol.",
    "hypothetical": "What if I want to have one with my mom and another with my sister.",
    "someone else's habit": "She has told me she never knows what message these things will send.",
    "description, not a rule": "The pages update the version whenever we do, but the words always stay the same.",
    "tied to today": "I am willing to spend today building and record a new demo tomorrow.",
    "echo of a Link listing": "I release features to the develop branch, never to main (preference · user)",
}

DURABLE = {
    "always rule": "We always commit to the develop branch after we finish a feature.",
    "never rule": "Never push to main directly.",
    "stated preference": "I prefer small commits with a one-line summary.",
    "decision": "We decided to keep memory in local Markdown files.",
    "from now on": "From now on, run the linter before every commit.",
    "do not, standing": "Do not use em dashes in commit messages, ever.",
    "by default": "By default, deploy to staging first.",
    "whenever": "Whenever the containers start, the UI should be available too.",
    "always imperative": "Always show the full diff before committing.",
    "always be": "Always be explicit about assumptions.",
    "never imperative": "Never show emoji in commit messages.",
}


class NonDurableTests(unittest.TestCase):
    def test_junk_shapes_are_not_proposed(self):
        for label, text in JUNK.items():
            with self.subTest(label=label):
                self.assertIsNone(classify_memory_segment(text), text)

    def test_junk_has_a_reason(self):
        for label, text in JUNK.items():
            with self.subTest(label=label):
                self.assertTrue(non_durable_reason(text), text)

    def test_durable_shapes_are_still_proposed(self):
        for label, text in DURABLE.items():
            with self.subTest(label=label):
                self.assertIsNotNone(classify_memory_segment(text), text)


class ExplicitRememberTests(unittest.TestCase):
    """A sentence someone chose to save keeps its type; capture stays strict."""

    RULES = (
        "Do not use tabs in YAML files.",
        "Avoid mocking the database in integration tests.",
        "Deploys are risky late in the week; it should never happen on Fridays.",
    )

    def test_explicit_rules_are_typed_as_rules(self):
        for text in self.RULES:
            with self.subTest(text=text):
                classified = classify_memory_segment(text, explicit=True)
                self.assertIsNotNone(classified, text)
                self.assertNotEqual(classified["memory_type"], "note")

    def test_capture_still_drops_task_instructions(self):
        self.assertIsNone(classify_memory_segment("Do not score the quality of the submission package."))


class ProcedureLeadTests(unittest.TestCase):
    def test_a_numbered_prompt_is_not_a_recipe(self):
        text = "Act as three people at once:\n1. A skeptical judge\n2. A strategist\n3. A researcher\n"
        self.assertEqual(extract_procedure_candidates(text), [])

    def test_a_task_shaped_list_is_a_recipe(self):
        text = "To cut a release:\n1. Merge develop into main\n2. Tag the version\n3. Publish to PyPI\n"
        (recipe,) = extract_procedure_candidates(text)
        self.assertEqual(recipe["trigger"], "To cut a release")


if __name__ == "__main__":
    unittest.main()
