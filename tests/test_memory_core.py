import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.memory import (  # noqa: E402
    slugify,
    add_capture_review_to_brief,
    default_project_for_target,
    extract_wikilinks,
    forget_memory_page,
    mark_memory_reviewed,
    memory_audit_report,
    memory_audit_next_actions,
    memory_brief,
    memory_conflict_candidates,
    memory_explanation,
    memory_inbox,
    memory_log_entries,
    memory_profile,
    memory_review_issues,
    memory_records,
    memory_durability_rank,
    propose_memories_from_text,
    recall_memories,
    recall_state,
    resolve_memory_page,
    set_memory_status,
    set_memory_visibility,
    update_memory_page,
    write_memory_page,
)
from link_core.operations import pending_operations  # noqa: E402


class MemoryCoreTests(unittest.TestCase):
    def test_default_project_for_target_uses_git_root_name(self):
        root = Path(tempfile.mkdtemp(prefix="link-memory-project-")) / "Link Product"
        wiki = root / "wiki"
        wiki.mkdir(parents=True)
        (root / ".git").mkdir()
        (wiki / "index.md").write_text("# Index\n", encoding="utf-8")

        self.assertEqual(default_project_for_target(root), "link-product")
        self.assertEqual(default_project_for_target(wiki), "link-product")
        self.assertEqual(default_project_for_target(Path(tempfile.mkdtemp(prefix="link-no-project-"))), "")

    def test_memory_records_profile_and_recall(self):
        root = Path(tempfile.mkdtemp(prefix="link-memory-core-"))
        wiki = root / "wiki"
        memories = wiki / "memories"
        memories.mkdir(parents=True)
        (memories / "prefer-release-branches.md").write_text(
            "---\n"
            "type: memory\n"
            "title: \"Prefer release branches\"\n"
            "memory_type: preference\n"
            "scope: project\n"
            "project: \"Link Product\"\n"
            "status: active\n"
            "date_captured: \"2026-05-05T00:00:00Z\"\n"
            "source: \"unit test\"\n"
            "review_status: reviewed\n"
            "tags: [memory, release, workflow]\n"
            "---\n\n"
            "# Prefer release branches\n\n"
            "> **TLDR:** User prefers release branches for Link work.\n\n"
            "## Memory\n\nUser prefers release branches for Link work.\n",
            encoding="utf-8",
        )
        (memories / "old-branch-rule.md").write_text(
            "---\n"
            "type: memory\n"
            "title: \"Old branch rule\"\n"
            "memory_type: preference\n"
            "scope: project\n"
            "status: archived\n"
            "date_captured: \"2026-05-04T00:00:00Z\"\n"
            "source: \"unit test\"\n"
            "review_status: reviewed\n"
            "tags: [memory, archive]\n"
            "---\n\n"
            "# Old branch rule\n\n"
            "> **TLDR:** User previously used direct main pushes.\n",
            encoding="utf-8",
        )

        records = memory_records(wiki)
        profile = memory_profile(records)
        brief = memory_brief(records, query="release branches")
        inbox = memory_inbox(records)
        recalled = recall_memories(records, "release branches")

        self.assertEqual(len(records), 2)
        self.assertIn("body", records[0])
        self.assertEqual(profile["memory_count"], 2)
        self.assertEqual(profile["active_count"], 1)
        release_memory = next(record for record in records if record["name"] == "prefer-release-branches")
        self.assertEqual(release_memory["project"], "link-product")
        self.assertEqual(profile["by_project"], {"link-product": 1})
        self.assertEqual(profile["archived"][0]["name"], "old-branch-rule")
        self.assertEqual(brief["selection"], "query")
        self.assertEqual(brief["relevant_memories"][0]["name"], "prefer-release-branches")
        self.assertNotIn("body", brief["relevant_memories"][0])
        self.assertIn("agent_guidance", brief)
        self.assertEqual(inbox["review_count"], 0)
        self.assertEqual(recalled[0]["name"], "prefer-release-branches")
        self.assertEqual(recalled[0]["recall"]["state"], "ready")
        self.assertEqual(recalled[0]["review_issue_count"], 0)
        self.assertEqual(recalled[0]["highest_review_severity"], "none")
        self.assertNotIn("body", recalled[0])

    def test_retrieval_context_finds_memory_but_stays_out_of_claim_and_output(self):
        # `context` is retrieval fuel from around a memory's origin (e.g.
        # neighboring dialogue turns). It must make the memory findable,
        # but never leak into recall output or count as part of the claim
        # for echo detection.
        record = {
            "name": "inspiring-stories",
            "path": "wiki/memories/inspiring-stories.md",
            "title": "Stories felt inspiring",
            "memory_type": "note",
            "scope": "user",
            "status": "active",
            "review_status": "reviewed",
            "tags": [],
            "tldr": "The stories were so inspiring.",
            "body": "The stories were so inspiring, I felt thankful for the support.",
            "context": "Caroline: I gave a talk about my transgender journey at the school event.",
        }

        results = recall_memories([record], "transgender journey school event", limit=3)
        self.assertTrue(results, "context tokens must make the memory findable")
        self.assertEqual(results[0]["name"], "inspiring-stories")
        self.assertNotIn("context", results[0], "context must not leak into recall output")
        self.assertNotIn("body", results[0])

        # Text that only restates the CONTEXT is not an echo of the claim.
        from link_core.memory import is_existing_memory_echo
        self.assertFalse(
            is_existing_memory_echo(
                [record],
                "Caroline gave a talk about her transgender journey at the school event.",
            ),
            "context must not count as the memory's own claim",
        )

    def test_abstention_verdict_matches_evidence(self):
        # The don't-know contract: empty or weak-confidence results must
        # yield abstention.recommended=True so agents say "my memory has
        # nothing on this" instead of dressing a weak match up as an answer.
        from link_core.memory import recall_abstention

        self.assertTrue(recall_abstention([])["recommended"])
        weak = [{"name": "m", "confidence": "weak"}]
        verdict = recall_abstention(weak)
        self.assertTrue(verdict["recommended"])
        self.assertIn("weak", verdict["reason"])
        strong = [{"name": "m", "confidence": "strong"}]
        self.assertFalse(recall_abstention(strong)["recommended"])

    def test_recall_matches_common_developer_paraphrases(self):
        records = [
            {
                "name": "login-flow",
                "path": "wiki/memories/login-flow.md",
                "title": "Login flow",
                "memory_type": "project",
                "scope": "project",
                "project": "link",
                "status": "active",
                "date_captured": "2026-05-05T00:00:00Z",
                "review_status": "reviewed",
                "tags": ["authentication"],
                "tldr": "Use OAuth login configuration for the project.",
                "body": "Use OAuth login configuration for the project.",
            },
            {
                "name": "release-flow",
                "path": "wiki/memories/release-flow.md",
                "title": "Release flow",
                "memory_type": "project",
                "scope": "project",
                "project": "link",
                "status": "active",
                "date_captured": "2026-05-05T00:00:00Z",
                "review_status": "reviewed",
                "tags": ["release"],
                "tldr": "Use tags for package publishing.",
                "body": "Use tags for package publishing.",
            },
        ]

        recalled = recall_memories(records, "auth setup", project="link")

        self.assertEqual(recalled[0]["name"], "login-flow")
        self.assertGreater(recalled[0]["score"], 0)

    def test_recall_ignores_weak_generic_body_matches(self):
        records = [{
            "name": "prefer-local-personal-memory",
            "path": "wiki/memories/prefer-local-personal-memory.md",
            "title": "Prefer local personal memory",
            "memory_type": "preference",
            "scope": "user",
            "status": "active",
            "date_captured": "2026-05-05T00:00:00Z",
            "review_status": "pending",
            "tags": ["memory"],
            "tldr": "The user wants local personal memory for agents.",
            "body": "The user wants local personal memory for agents.",
        }]

        self.assertEqual(recall_memories(records, "auth setup"), [])

    def test_recall_labels_incidental_word_matches_as_weak(self):
        # A single shared word ("format" in "storage format") must not read
        # like a known preference about response formatting.
        records = [{
            "name": "prefer-local-personal-memory",
            "path": "wiki/memories/prefer-local-personal-memory.md",
            "title": "Prefer local personal memory",
            "memory_type": "preference",
            "scope": "user",
            "status": "active",
            "date_captured": "2026-05-05T00:00:00Z",
            "review_status": "pending",
            "tags": ["memory"],
            "tldr": "The user wants the wiki as the inspectable storage format.",
            "body": "The user wants the wiki as the inspectable storage format.",
        }]

        recalled = recall_memories(records, "how should I format my responses")

        self.assertTrue(all(item["confidence"] == "weak" for item in recalled))

    def test_recall_confidence_strong_for_head_coverage(self):
        records = [{
            "name": "staging-db-port",
            "path": "wiki/memories/staging-db-port.md",
            "title": "The staging database lives on port 5433",
            "memory_type": "fact",
            "scope": "project",
            "status": "active",
            "date_captured": "2026-05-05T00:00:00Z",
            "review_status": "reviewed",
            "tags": ["database"],
            "tldr": "The staging database lives on port 5433, not the default.",
            "body": "The staging database lives on port 5433, not the default.",
        }]

        recalled = recall_memories(records, "staging database port")

        self.assertEqual(recalled[0]["confidence"], "strong")

    def test_recall_confidence_moderate_for_title_token_match(self):
        records = [{
            "name": "run-checks-before-committing",
            "path": "wiki/memories/run-checks-before-committing.md",
            "title": "Always run ruff and pytest before committing",
            "memory_type": "preference",
            "scope": "project",
            "status": "active",
            "date_captured": "2026-05-05T00:00:00Z",
            "review_status": "reviewed",
            "tags": ["workflow"],
            "tldr": "Always run ruff and pytest before committing python changes.",
            "body": "Always run ruff and pytest before committing python changes.",
        }]

        recalled = recall_memories(records, "checks before committing code")

        self.assertEqual(recalled[0]["confidence"], "moderate")

    def test_recall_stemming_matches_close_paraphrases(self):
        # "commits" should still find a memory phrased with "committing".
        records = [{
            "name": "run-checks-before-committing",
            "path": "wiki/memories/run-checks-before-committing.md",
            "title": "Always run ruff and pytest before committing",
            "memory_type": "preference",
            "scope": "project",
            "status": "active",
            "date_captured": "2026-05-05T00:00:00Z",
            "review_status": "reviewed",
            "tags": ["workflow"],
            "tldr": "Always run ruff and pytest before committing python changes.",
            "body": "Always run ruff and pytest before committing python changes.",
        }]

        recalled = recall_memories(records, "rules for commits")

        self.assertEqual(len(recalled), 1)
        self.assertEqual(recalled[0]["name"], "run-checks-before-committing")

    def test_review_after_marks_memory_due(self):
        record = {
            "name": "review-me",
            "memory_type": "preference",
            "scope": "user",
            "status": "active",
            "date_captured": "2026-05-01T00:00:00Z",
            "source": "unit test",
            "review_status": "reviewed",
            "review_after": "2026-05-20",
            "tldr": "Review me later.",
        }

        issues = memory_review_issues(record, today="2026-05-25")
        inbox = memory_inbox([record])

        self.assertIn("review_due", [issue["code"] for issue in issues])
        self.assertEqual(inbox["review_count"], 1)
        self.assertEqual(inbox["items"][0]["primary_action"]["kind"], "review")

    def test_expires_at_disables_default_recall_and_marks_inbox(self):
        record = {
            "name": "expired-context",
            "memory_type": "project",
            "scope": "user",
            "status": "active",
            "date_captured": "2026-05-01T00:00:00Z",
            "source": "unit test",
            "review_status": "reviewed",
            "expires_at": "2000-01-01",
            "tldr": "Temporary launch context.",
            "snippet": "Temporary launch context.",
        }

        issues = memory_review_issues(record, today="2026-05-25")
        inbox = memory_inbox([record])
        recall = recall_memories([record], "temporary launch")
        state = recall_state(record, issues)

        self.assertIn("expired", [issue["code"] for issue in issues])
        self.assertEqual(inbox["review_count"], 1)
        self.assertEqual(inbox["items"][0]["primary_action"]["kind"], "archive")
        self.assertEqual(recall, [])
        self.assertEqual(state["state"], "disabled")
        self.assertIn("expired", state["reason"])

    def test_review_after_rejects_invalid_dates(self):
        record = {
            "name": "bad-review-date",
            "memory_type": "preference",
            "scope": "user",
            "status": "active",
            "date_captured": "2026-05-01T00:00:00Z",
            "source": "unit test",
            "review_status": "reviewed",
            "review_after": "tomorrow",
            "tldr": "Invalid review date.",
        }

        issues = memory_review_issues(record)

        self.assertIn("invalid_review_after", [issue["code"] for issue in issues])

    def test_expires_at_rejects_invalid_dates(self):
        record = {
            "name": "bad-expires-date",
            "memory_type": "preference",
            "scope": "user",
            "status": "active",
            "date_captured": "2026-05-01T00:00:00Z",
            "source": "unit test",
            "review_status": "reviewed",
            "expires_at": "later",
            "tldr": "Invalid expiry date.",
        }

        issues = memory_review_issues(record)

        self.assertIn("invalid_expires_at", [issue["code"] for issue in issues])

    def test_memory_inbox_returns_action_plan(self):
        records = [
            {
                "name": "needs-review",
                "path": "wiki/memories/needs-review.md",
                "title": "Needs review",
                "memory_type": "preference",
                "scope": "user",
                "status": "active",
                "date_captured": "2026-05-05T00:00:00Z",
                "source": "unit test",
                "review_status": "pending",
                "tags": ["memory"],
                "tldr": "User prefers reviewed memory.",
                "snippet": "User prefers reviewed memory.",
            }
        ]

        inbox = memory_inbox(records)
        item = inbox["items"][0]

        self.assertEqual(item["primary_action"]["kind"], "review")
        self.assertEqual(item["primary_action"]["tool"], "review_memory")
        self.assertIn("review-memory", item["primary_action"]["command"])
        self.assertEqual(inbox["next_actions"][0]["kind"], "review")
        self.assertIn("actions", item)
        forget_action = next(action for action in item["actions"] if action["kind"] == "forget")
        self.assertEqual(forget_action["tool"], "forget_memory")
        self.assertTrue(forget_action["arguments"]["confirm"])

    def test_memory_audit_report_builds_shared_risk_factors(self):
        profile = {"memory_count": 2}
        inbox = {"review_count": 1}
        captures = {"count": 2, "warning_count": 1, "read_warning_count": 1, "items": []}
        actions = [{"label": "Review memory inbox", "recommended": True}]

        audit = memory_audit_report(profile, inbox, captures, actions, project="Link Product")

        self.assertEqual(audit["status"], "needs_attention")
        self.assertEqual(audit["project"], "link-product")
        self.assertEqual(
            [factor["code"] for factor in audit["risk_factors"]],
            [
                "memory_review_backlog",
                "raw_capture_backlog",
                "capture_secret_warnings",
                "capture_read_warnings",
            ],
        )
        self.assertEqual(audit["next_actions"], actions)

    def test_memory_audit_next_actions_formats_cli_mcp_and_web_modes(self):
        inbox = {"review_count": 1}
        captures = {"count": 1, "read_warning_count": 0}
        risk_factors = [{"code": "memory_review_backlog"}]

        cli_actions = memory_audit_next_actions(
            mode="cli",
            inbox=inbox,
            captures=captures,
            risk_factors=risk_factors,
            project="Link Product",
            root="/tmp/link",
        )
        mcp_actions = memory_audit_next_actions(
            mode="mcp",
            inbox=inbox,
            captures=captures,
            project="Link Product",
        )
        web_actions = memory_audit_next_actions(
            mode="web",
            inbox=inbox,
            captures=captures,
            risk_factors=[],
            project="Link Product",
        )

        self.assertEqual(cli_actions[0]["command"], 'python3 link.py memory-inbox "/tmp/link" --project "link-product"')
        self.assertTrue(cli_actions[1]["recommended"])
        self.assertFalse(cli_actions[2]["recommended"])
        self.assertEqual(mcp_actions[0]["tool"], "memory_inbox")
        self.assertIn('project="link-product"', mcp_actions[0]["command"])
        self.assertEqual(mcp_actions[1]["tool"], "capture_inbox")
        self.assertEqual(web_actions[0]["href"], "/inbox?project=link-product")
        self.assertEqual(web_actions[1]["href"], "/captures?project=link-product")
        self.assertTrue(web_actions[2]["recommended"])

    def test_memory_audit_next_actions_rejects_unknown_mode(self):
        with self.assertRaises(ValueError):
            memory_audit_next_actions(mode="desktop", inbox={}, captures={})

    def test_add_capture_review_to_brief_adds_capture_guidance(self):
        payload = {"agent_guidance": ["Use memory first."]}
        captures = {"count": 1, "warning_count": 1, "read_warning_count": 1, "items": []}

        brief = add_capture_review_to_brief(payload, captures)

        self.assertEqual(brief["captures"], captures)
        self.assertEqual(payload["agent_guidance"], ["Use memory first."])
        self.assertIn("Review 1 saved raw capture", brief["agent_guidance"][1])
        self.assertIn("Redact raw captures", brief["agent_guidance"][2])
        self.assertIn("Fix unreadable raw captures", brief["agent_guidance"][3])

    def test_memory_inbox_filters_project_scoped_memories(self):
        base = {
            "path": "wiki/memories/example.md",
            "memory_type": "project",
            "scope": "project",
            "status": "active",
            "date_captured": "2026-05-05T00:00:00Z",
            "source": "unit test",
            "review_status": "pending",
            "tags": ["memory"],
            "tldr": "Project memory.",
            "snippet": "Project memory.",
        }
        records = [
            {**base, "name": "alpha-note", "title": "Alpha note", "project": "alpha"},
            {**base, "name": "beta-note", "title": "Beta note", "project": "beta"},
            {
                **base,
                "name": "global-note",
                "title": "Global note",
                "scope": "global",
                "project": "",
            },
        ]

        inbox = memory_inbox(records, project="alpha")

        self.assertEqual(inbox["project"], "alpha")
        self.assertEqual([item["name"] for item in inbox["items"]], ["alpha-note", "global-note"])

    def test_memory_inbox_prioritizes_metadata_repairs(self):
        records = [
            {
                "name": "missing-source",
                "path": "wiki/memories/missing-source.md",
                "title": "Missing source",
                "memory_type": "preference",
                "scope": "user",
                "status": "active",
                "date_captured": "2026-05-05T00:00:00Z",
                "source": "",
                "review_status": "reviewed",
                "tags": ["memory"],
                "tldr": "User prefers metadata.",
                "snippet": "User prefers metadata.",
            }
        ]

        inbox = memory_inbox(records)

        self.assertEqual(inbox["items"][0]["primary_action"]["kind"], "edit_metadata")
        self.assertIn("wiki/memories/missing-source.md", inbox["items"][0]["primary_action"]["command"])

    def test_recall_and_profile_filter_project_memories(self):
        records = [
            {
                "name": "global-style",
                "path": "wiki/memories/global-style.md",
                "title": "Global style",
                "memory_type": "preference",
                "scope": "user",
                "project": "",
                "status": "active",
                "tldr": "User prefers concise status updates.",
                "snippet": "User prefers concise status updates.",
                "body": "User prefers concise status updates.",
            },
            {
                "name": "link-branching",
                "path": "wiki/memories/link-branching.md",
                "title": "Link branching",
                "memory_type": "preference",
                "scope": "project",
                "project": "link",
                "status": "active",
                "tldr": "User prefers release branches for Link.",
                "snippet": "User prefers release branches for Link.",
                "body": "User prefers release branches for Link.",
            },
            {
                "name": "other-branching",
                "path": "wiki/memories/other-branching.md",
                "title": "Other branching",
                "memory_type": "preference",
                "scope": "project",
                "project": "other",
                "status": "active",
                "tldr": "User prefers develop branches for Other.",
                "snippet": "User prefers develop branches for Other.",
                "body": "User prefers develop branches for Other.",
            },
        ]

        recalled = recall_memories(records, "branches", project="link")
        profile = memory_profile(records, project="link")

        self.assertEqual([record["name"] for record in recalled], ["link-branching"])
        self.assertEqual(profile["project"], "link")
        self.assertEqual(profile["memory_count"], 2)
        self.assertEqual(profile["by_scope"]["user"], 1)
        self.assertEqual(profile["by_scope"]["project"], 1)
        self.assertEqual(profile["by_project"]["link"], 1)

    def test_recall_ranking_prefers_reviewed_project_context(self):
        records = [
            {
                "name": "global-api-imports",
                "path": "wiki/memories/global-api-imports.md",
                "title": "API imports",
                "memory_type": "project",
                "scope": "user",
                "project": "",
                "status": "active",
                "date_captured": "2026-05-03T00:00:00Z",
                "review_status": "reviewed",
                "tldr": "Use API imports.",
                "snippet": "Use API imports.",
                "body": "Use API imports.",
            },
            {
                "name": "alpha-api-imports-pending",
                "path": "wiki/memories/alpha-api-imports-pending.md",
                "title": "API imports",
                "memory_type": "project",
                "scope": "project",
                "project": "alpha",
                "status": "active",
                "date_captured": "2026-05-02T00:00:00Z",
                "review_status": "pending",
                "tldr": "Use API imports.",
                "snippet": "Use API imports.",
                "body": "Use API imports.",
            },
            {
                "name": "alpha-api-imports-reviewed",
                "path": "wiki/memories/alpha-api-imports-reviewed.md",
                "title": "API imports",
                "memory_type": "project",
                "scope": "project",
                "project": "alpha",
                "status": "active",
                "date_captured": "2026-05-01T00:00:00Z",
                "review_status": "reviewed",
                "tldr": "Use API imports.",
                "snippet": "Use API imports.",
                "body": "Use API imports.",
            },
        ]

        recalled = recall_memories(records, "API imports", project="alpha")
        brief = memory_brief(records, query="API imports", project="alpha")

        self.assertEqual(
            [record["name"] for record in recalled],
            [
                "alpha-api-imports-reviewed",
                "alpha-api-imports-pending",
                "global-api-imports",
            ],
        )
        self.assertGreater(recalled[0]["rank_score"], recalled[0]["score"])
        self.assertEqual(brief["relevant_memories"][0]["name"], "alpha-api-imports-reviewed")

    def test_proposals_are_duplicate_aware_and_write_free(self):
        records = [
            {
                "name": "prefer-release-branches",
                "path": "wiki/memories/prefer-release-branches.md",
                "title": "Prefer release branches",
                "memory_type": "preference",
                "scope": "project",
                "status": "active",
                "tldr": "User prefers release branches for Link work.",
                "snippet": "User prefers release branches for Link work.",
                "body": "User prefers release branches for Link work.",
            }
        ]

        payload = propose_memories_from_text(
            "\n".join([
                "- I prefer release branches for Link work.",
                "- We decided to keep Memory Mode local and source-backed.",
                "- Maybe we could add cloud sync later.",
            ]),
            records,
            source="unit test",
        )

        self.assertTrue(payload["proposed"])
        self.assertFalse(payload["writes_memory"])
        self.assertEqual(payload["count"], 2)
        self.assertGreaterEqual(payload["skipped_count"], 1)
        self.assertEqual(payload["proposals"][0]["suggested_action"], "update-memory")
        self.assertEqual(payload["proposals"][0]["primary_action"]["kind"], "update")
        self.assertEqual(payload["proposals"][0]["primary_action"]["tool"], "update_memory")
        self.assertIn("update-memory", payload["proposals"][0]["primary_action"]["command"])
        duplicate = payload["proposals"][0]["duplicate_candidates"][0]
        self.assertEqual(duplicate["name"], "prefer-release-branches")
        self.assertNotIn("body", duplicate)
        self.assertEqual(payload["proposals"][1]["memory_type"], "decision")
        self.assertEqual(payload["proposals"][1]["primary_action"]["kind"], "remember")
        self.assertEqual(payload["proposals"][1]["primary_action"]["tool"], "remember_memory")

    def test_proposals_carry_neighboring_sentences_as_context(self):
        payload = propose_memories_from_text(
            "we spent an hour debugging the deploy pipeline. "
            "from now on I only deploy to staging through the release script. "
            "also check whether the bucket migration ticket is still open.",
            [],
            source="unit test",
        )
        proposal = payload["proposals"][0]

        self.assertIn("release script", proposal["memory"])
        self.assertIn("debugging the deploy pipeline", proposal["context"])
        self.assertIn("bucket migration ticket", proposal["context"])
        self.assertNotIn("release script", proposal["context"])
        self.assertEqual(proposal["primary_action"]["arguments"]["context"], proposal["context"])
        self.assertNotIn("--context", proposal["primary_action"]["command"])

    def test_standing_rule_phrasings_propose_preferences(self):
        payload = propose_memories_from_text(
            "hey, before we start — from now on I only push to the develop "
            "branch. never push to main directly, releases go through PRs. "
            "great. now help me fix the failing test in utils.py",
            [],
            source="unit test",
        )
        memories = [p["memory"] for p in payload["proposals"]]

        self.assertEqual(len(memories), 2)
        self.assertTrue(any("develop branch" in m for m in memories))
        self.assertTrue(any("push to main" in m.lower() for m in memories))
        for proposal in payload["proposals"]:
            self.assertEqual(proposal["memory_type"], "preference")

    def test_conversational_preambles_are_trimmed_from_memory_text(self):
        payload = propose_memories_from_text(
            "hey, before we start — from now on I only push to the develop branch.",
            [],
            source="unit test",
        )
        self.assertEqual(
            [p["memory"] for p in payload["proposals"]],
            ["I only push to the develop branch."],
        )

        payload = propose_memories_from_text("ok so I prefer tabs over spaces.", [], source="unit test")
        self.assertEqual([p["memory"] for p in payload["proposals"]], ["User prefers tabs over spaces."])

    def test_preamble_trim_keeps_full_text_when_tail_does_not_classify(self):
        payload = propose_memories_from_text("never push to main — thanks!", [], source="unit test")
        self.assertEqual([p["memory"] for p in payload["proposals"]], ["Never push to main — thanks!"])

    def test_narrative_only_is_not_a_preference(self):
        payload = propose_memories_from_text(
            "I only found one bug in the parser.",
            [],
            source="unit test",
        )
        self.assertEqual(payload["proposals"], [])

    def test_project_duplicate_proposal_command_preserves_project(self):
        records = [
            {
                "name": "prefer-release-branches",
                "path": "wiki/memories/prefer-release-branches.md",
                "title": "Prefer release branches",
                "memory_type": "project",
                "scope": "project",
                "project": "link",
                "status": "active",
                "tldr": "Project uses release branches for Link work.",
                "snippet": "Project uses release branches for Link work.",
                "body": "Project uses release branches for Link work.",
            }
        ]

        payload = propose_memories_from_text(
            "This project uses release branches for Link work.",
            records,
            source="unit test",
            project="Link",
        )
        action = payload["proposals"][0]["primary_action"]

        self.assertEqual(payload["project"], "link")
        self.assertEqual(action["arguments"]["project"], "link")
        self.assertIn("--project link", action["command"])

    def test_memory_proposal_command_uses_explicit_target(self):
        payload = propose_memories_from_text(
            "I prefer local agent memory for release work.",
            [],
            source="unit test",
            command_target="/tmp/link demo",
        )
        action = payload["proposals"][0]["primary_action"]

        self.assertEqual(action["kind"], "remember")
        self.assertIn("link demo", action["command"])
        self.assertNotIn(" remember . ", action["command"])

    def test_memory_conflict_candidates_catch_branch_policy_changes(self):
        records = [
            {
                "name": "prefer-release-branches",
                "path": "wiki/memories/prefer-release-branches.md",
                "title": "Prefer release branches",
                "memory_type": "preference",
                "scope": "project",
                "status": "active",
                "tldr": "User prefers release branches for Link work.",
                "snippet": "User prefers release branches for Link work.",
                "body": "User prefers release branches for Link work.",
            }
        ]

        conflicts = memory_conflict_candidates(
            records,
            "User prefers develop branches for Link work.",
            "Prefer develop branches",
            "preference",
            "project",
        )

        self.assertEqual(conflicts[0]["name"], "prefer-release-branches")
        self.assertIn("different_branch_policy", conflicts[0]["conflict_reasons"])
        self.assertNotIn("body", conflicts[0])

    def test_memory_conflict_candidates_avoid_release_word_false_positive(self):
        records = [
            {
                "name": "prefer-develop-branches",
                "path": "wiki/memories/prefer-develop-branches.md",
                "title": "Prefer develop branches",
                "memory_type": "preference",
                "scope": "project",
                "status": "active",
                "tldr": "User prefers develop branches for Link work.",
                "snippet": "User prefers develop branches for Link work.",
                "body": "User prefers develop branches for Link work.",
            }
        ]

        conflicts = memory_conflict_candidates(
            records,
            "User wants release notes to include screenshots.",
            "Prefer release notes screenshots",
            "preference",
            "project",
        )

        self.assertEqual(conflicts, [])

    def test_memory_conflict_candidates_catch_negation(self):
        records = [
            {
                "name": "want-screenshots",
                "path": "wiki/memories/want-screenshots.md",
                "title": "Want screenshots",
                "memory_type": "preference",
                "scope": "user",
                "status": "active",
                "tldr": "User wants screenshots in release notes.",
                "snippet": "User wants screenshots in release notes.",
                "body": "User wants screenshots in release notes.",
            }
        ]

        conflicts = memory_conflict_candidates(
            records,
            "User does not want screenshots in release notes.",
            "Avoid screenshots",
            "preference",
            "user",
        )

        self.assertEqual(conflicts[0]["name"], "want-screenshots")
        self.assertIn("opposite_negation", conflicts[0]["conflict_reasons"])

    def test_memory_resolution_logs_and_recall_state(self):
        root = Path(tempfile.mkdtemp(prefix="link-memory-resolution-"))
        wiki = root / "wiki"
        memories = wiki / "memories"
        memories.mkdir(parents=True)
        (memories / "prefer-focused-commits.md").write_text(
            "---\n"
            "type: memory\n"
            "title: \"Prefer focused commits\"\n"
            "memory_type: preference\n"
            "scope: project\n"
            "status: active\n"
            "date_captured: \"2026-05-05T00:00:00Z\"\n"
            "source: \"unit test\"\n"
            "review_status: reviewed\n"
            "tags: [memory, git]\n"
            "---\n\n"
            "# Prefer focused commits\n\n"
            "> **TLDR:** User prefers focused commits on develop.\n\n"
            "## Memory\n\nUser prefers focused commits on develop.\n",
            encoding="utf-8",
        )
        (memories / "duplicate-a.md").write_text(
            "---\n"
            "title: \"Duplicate title\"\n"
            "memory_type: note\n"
            "scope: project\n"
            "status: active\n"
            "date_captured: \"2026-05-05T00:00:00Z\"\n"
            "source: \"unit test\"\n"
            "review_status: reviewed\n"
            "---\n\n"
            "# Duplicate title\n",
            encoding="utf-8",
        )
        (memories / "duplicate-b.md").write_text(
            "---\n"
            "title: \"Duplicate title\"\n"
            "memory_type: note\n"
            "scope: project\n"
            "status: active\n"
            "date_captured: \"2026-05-05T00:00:00Z\"\n"
            "source: \"unit test\"\n"
            "review_status: reviewed\n"
            "---\n\n"
            "# Duplicate title\n",
            encoding="utf-8",
        )
        (wiki / "log.md").write_text(
            "# Link Wiki Log\n\n"
            "## unrelated\n\n- No match\n"
            "---\n"
            "## remember | Prefer focused commits\n\n"
            "- Added [[prefer-focused-commits]]\n"
            "---\n"
            "## update | wiki/memories/prefer-focused-commits.md\n\n"
            "- Updated memory text\n"
            "---\n",
            encoding="utf-8",
        )

        path, record, error = resolve_memory_page(wiki, "Prefer focused commits")
        self.assertIsNone(error)
        self.assertEqual(path, (memories / "prefer-focused-commits.md").resolve())
        self.assertEqual(record["name"], "prefer-focused-commits")
        self.assertIn("body", record)

        path, record, error = resolve_memory_page(wiki, "wiki/memories/prefer-focused-commits.md")
        self.assertIsNone(error)
        self.assertEqual(path, (memories / "prefer-focused-commits.md").resolve())
        self.assertEqual(record["title"], "Prefer focused commits")

        with patch("link_core.memory.memory_records", return_value=[]) as mocked_records:
            path, record, error = resolve_memory_page(wiki, "wiki/memories/prefer-focused-commits.md")
        self.assertIsNone(error)
        self.assertEqual(path, (memories / "prefer-focused-commits.md").resolve())
        self.assertEqual(record["title"], "Prefer focused commits")
        self.assertEqual(mocked_records.call_count, 0)

        path, record, error = resolve_memory_page(wiki, "../log.md")
        self.assertIsNone(path)
        self.assertIsNone(record)
        self.assertEqual(error, "memory not found: ../log.md")

        path, record, error = resolve_memory_page(wiki, "Duplicate title")
        self.assertIsNone(path)
        self.assertIsNone(record)
        self.assertIn("ambiguous", error)

        entries = memory_log_entries(wiki, {"name": "prefer-focused-commits", "title": "Prefer focused commits"}, limit=1)
        self.assertEqual(len(entries), 1)
        self.assertIn("wiki/memories/prefer-focused-commits.md", entries[0])

        ready = recall_state(record={"status": "active"}, issues=[])
        needs_review = recall_state(record={"status": "active"}, issues=[{"severity": "medium"}])
        unsafe = recall_state(record={"status": "active"}, issues=[{"severity": "high"}])
        disabled = recall_state(record={"status": "archived"}, issues=[])
        self.assertEqual(ready["state"], "ready")
        self.assertEqual(needs_review["state"], "needs_review")
        self.assertEqual(unsafe["state"], "unsafe")
        self.assertEqual(disabled["state"], "disabled")

    def test_memory_explanation_reports_audit_payload_and_graph(self):
        root = Path(tempfile.mkdtemp(prefix="link-memory-explain-"))
        wiki = root / "wiki"
        memories = wiki / "memories"
        memories.mkdir(parents=True)
        (memories / "prefer-focused-commits.md").write_text(
            "---\n"
            "type: memory\n"
            "title: \"Prefer focused commits\"\n"
            "memory_type: preference\n"
            "scope: project\n"
            "status: active\n"
            "date_captured: \"2026-05-05T00:00:00Z\"\n"
            "source: \"unit test\"\n"
            "review_status: reviewed\n"
            "tags: [memory, git]\n"
            "---\n\n"
            "# Prefer focused commits\n\n"
            "> **TLDR:** User prefers focused commits on develop.\n\n"
            "## Memory\n\n"
            "User prefers focused commits on develop and links [[release-workflow]].\n",
            encoding="utf-8",
        )
        (wiki / "_backlinks.json").write_text(
            '{"backlinks": {"prefer-focused-commits": ["agent-memory"]}, "forward": {"prefer-focused-commits": ["release-workflow"]}}',
            encoding="utf-8",
        )
        (wiki / "log.md").write_text(
            "# Link Wiki Log\n\n"
            "## remember | Prefer focused commits\n\n"
            "- Added [[prefer-focused-commits]]\n"
            "---\n",
            encoding="utf-8",
        )

        explanation = memory_explanation(
            wiki,
            "prefer-focused-commits",
            records=memory_records(wiki, include_body=False),
        )

        self.assertTrue(explanation["found"])
        self.assertEqual(explanation["memory"]["name"], "prefer-focused-commits")
        self.assertNotIn("body", explanation["memory"])
        self.assertEqual(explanation["recall"]["state"], "ready")
        self.assertEqual(explanation["graph"]["inbound"], ["agent-memory"])
        self.assertEqual(explanation["graph"]["forward"], ["release-workflow"])
        self.assertEqual(explanation["graph"]["wikilinks"], ["release-workflow"])
        self.assertEqual(explanation["review"]["primary_action"]["kind"], "explain")
        self.assertIn("User prefers focused commits", explanation["body"])
        self.assertEqual(len(explanation["log_entries"]), 1)
        self.assertEqual(extract_wikilinks("[[one]] [[one]] [[two|Two]]"), ["one", "two"])

    def test_memory_lifecycle_mutations_update_files_and_callbacks(self):
        root = Path(tempfile.mkdtemp(prefix="link-memory-lifecycle-"))
        wiki = root / "wiki"
        memories = wiki / "memories"
        memories.mkdir(parents=True)
        memory_path = memories / "prefer-focused-commits.md"
        memory_path.write_text(
            "---\n"
            "type: memory\n"
            "title: \"Prefer focused commits\"\n"
            "memory_type: preference\n"
            "scope: project\n"
            "status: active\n"
            "date_captured: \"2026-05-05T00:00:00Z\"\n"
            "source: \"unit test\"\n"
            "review_status: pending\n"
            "tags: [memory, git]\n"
            "---\n\n"
            "# Prefer focused commits\n\n"
            "> **TLDR:** User prefers focused commits on develop.\n\n"
            "## Memory\n\nUser prefers focused commits on develop.\n",
            encoding="utf-8",
        )
        logged: list[tuple[str, str, str, list[str]]] = []
        rebuilds = []

        def log_writer(timestamp: str, operation: str, description: str, lines: list[str]) -> None:
            logged.append((timestamp, operation, description, lines))

        reviewed = mark_memory_reviewed(
            wiki,
            "prefer-focused-commits",
            note="confirmed",
            timestamp="2026-05-05T01:00:00Z",
            records=memory_records(wiki),
            log_writer=log_writer,
        )
        reviewed_text = memory_path.read_text(encoding="utf-8")

        self.assertTrue(reviewed["updated"])
        self.assertEqual(reviewed["review_status"], "reviewed")
        self.assertEqual(reviewed["remaining_issue_count"], 0)
        self.assertIn("review_status: reviewed", reviewed_text)
        self.assertIn('review_note: "confirmed"', reviewed_text)
        self.assertEqual(logged[-1][1], "review-memory")

        updated = update_memory_page(
            wiki,
            "Prefer focused commits",
            "Also prefer one logical change per commit.",
            source="unit test",
            timestamp="2026-05-05T02:00:00Z",
            records=memory_records(wiki),
            log_writer=log_writer,
            rebuild_backlinks=lambda: rebuilds.append(True) or True,
        )
        updated_text = memory_path.read_text(encoding="utf-8")

        self.assertTrue(updated["updated"])
        self.assertEqual(updated["previous_review_status"], "reviewed")
        self.assertEqual(updated["review_status"], "pending")
        self.assertEqual(updated["update_count"], 1)
        self.assertTrue(updated["backlinks_rebuilt"])
        self.assertEqual(rebuilds, [True])
        self.assertIn("updated_at:", updated_text)
        self.assertIn("update_count: 1", updated_text)
        self.assertIn('last_update_source: "unit test"', updated_text)
        self.assertNotIn("reviewed_at:", updated_text)
        self.assertIn("Also prefer one logical change per commit.", updated_text)
        self.assertEqual(logged[-1][1], "update-memory")

        archived = set_memory_status(
            wiki,
            "prefer-focused-commits",
            "archived",
            reason="stale",
            timestamp="2026-05-05T03:00:00Z",
            records=memory_records(wiki),
            log_writer=log_writer,
        )
        archived_text = memory_path.read_text(encoding="utf-8")

        self.assertTrue(archived["updated"])
        self.assertEqual(archived["status"], "archived")
        self.assertIn("status: archived", archived_text)
        self.assertIn("archived_at:", archived_text)
        self.assertIn('archive_reason: "stale"', archived_text)
        self.assertEqual(logged[-1][1], "archive-memory")

        with self.assertRaisesRegex(ValueError, "restore it first"):
            update_memory_page(
                wiki,
                "prefer-focused-commits",
                "Should not write while archived.",
                source="unit test",
                timestamp="2026-05-05T04:00:00Z",
                records=memory_records(wiki),
            )

        restored = set_memory_status(
            wiki,
            "prefer-focused-commits",
            "active",
            reason=None,
            timestamp="2026-05-05T05:00:00Z",
            records=memory_records(wiki),
            log_writer=log_writer,
        )
        restored_text = memory_path.read_text(encoding="utf-8")

        self.assertTrue(restored["updated"])
        self.assertEqual(restored["status"], "active")
        self.assertIn("status: active", restored_text)
        self.assertIn("restored_at:", restored_text)
        self.assertNotIn("archived_at:", restored_text)
        self.assertNotIn("archive_reason:", restored_text)
        self.assertEqual(logged[-1][1], "restore-memory")

        visibility = set_memory_visibility(
            wiki,
            "prefer-focused-commits",
            "team",
            timestamp="2026-05-05T05:30:00Z",
            records=memory_records(wiki),
            log_writer=log_writer,
        )
        visibility_text = memory_path.read_text(encoding="utf-8")

        self.assertTrue(visibility["updated"])
        self.assertEqual(visibility["previous_visibility"], "project")
        self.assertEqual(visibility["visibility"], "team")
        self.assertIn("visibility: team", visibility_text)
        self.assertEqual(logged[-1][1], "set-memory-visibility")

        unchanged_visibility = set_memory_visibility(
            wiki,
            "prefer-focused-commits",
            "team",
            timestamp="2026-05-05T05:35:00Z",
            records=memory_records(wiki),
            log_writer=log_writer,
        )

        self.assertFalse(unchanged_visibility["updated"])
        self.assertEqual(unchanged_visibility["visibility"], "team")

        (wiki / "index.md").write_text("### memories\n- [[prefer-focused-commits]] - old entry\n", encoding="utf-8")
        denied = forget_memory_page(
            wiki,
            "prefer-focused-commits",
            records=memory_records(wiki),
            log_writer=log_writer,
            timestamp="2026-05-05T06:00:00Z",
            rebuild_backlinks=lambda: rebuilds.append(True) or True,
        )
        forgotten = forget_memory_page(
            wiki,
            "prefer-focused-commits",
            confirm=True,
            records=memory_records(wiki),
            log_writer=log_writer,
            timestamp="2026-05-05T06:00:00Z",
            rebuild_backlinks=lambda: rebuilds.append(True) or True,
        )

        self.assertFalse(denied["forgotten"])
        self.assertTrue(denied["confirmation_required"])
        self.assertTrue(forgotten["forgotten"])
        self.assertFalse(memory_path.exists())
        self.assertTrue(forgotten["index_updated"])
        self.assertNotIn("[[prefer-focused-commits]]", (wiki / "index.md").read_text(encoding="utf-8"))
        self.assertEqual(logged[-1][1], "forget-memory")
        self.assertNotIn("User prefers focused commits", "\n".join(logged[-1][3]))
        self.assertEqual(pending_operations(wiki), [])

    def test_write_memory_page_refuses_secret_looking_text(self):
        root = Path(tempfile.mkdtemp(prefix="link-memory-secret-"))
        wiki = root / "wiki"
        wiki.mkdir(parents=True)

        refused = write_memory_page(
            wiki, "Zk9#mango42", title=None, memory_type="note", scope="user",
            tags=None, source="unit test", timestamp="2026-07-12T06:00:00Z",
            records=[], log_writer=lambda *a: None, rebuild_backlinks=lambda: True,
        )
        allowed = write_memory_page(
            wiki, "Zk9#mango42", title=None, memory_type="note", scope="user",
            tags=None, source="unit test", timestamp="2026-07-12T06:00:00Z",
            allow_secret=True,
            records=[], log_writer=lambda *a: None, rebuild_backlinks=lambda: True,
        )

        self.assertFalse(refused["created"])
        self.assertTrue(refused["secret"])
        self.assertIn("password manager", str(refused["message"]))
        self.assertTrue(allowed["created"])

    def test_forget_memory_redacts_log_references(self):
        from link_core.log import append_log, verify_log_integrity

        root = Path(tempfile.mkdtemp(prefix="link-memory-forget-"))
        wiki = root / "wiki"
        (wiki / "memories").mkdir(parents=True)
        (wiki / "index.md").write_text("# Index\n", encoding="utf-8")

        def log_writer(timestamp, operation, description, lines):
            append_log(wiki, timestamp, operation, description, lines)

        created = write_memory_page(
            wiki, "TempSecret@42 for the beta box", title=None, memory_type="note",
            scope="user", tags=None, source="unit test",
            timestamp="2026-07-12T06:00:00Z", allow_secret=True,
            records=[], log_writer=log_writer, rebuild_backlinks=lambda: True,
        )
        self.assertTrue(created["created"])
        self.assertIn("TempSecret@42", (wiki / "log.md").read_text(encoding="utf-8"))

        result = forget_memory_page(
            wiki, str(created["name"]), confirm=True, records=None,
            log_writer=log_writer, timestamp="2026-07-12T07:00:00Z",
            rebuild_backlinks=lambda: True,
        )
        log_text = (wiki / "log.md").read_text(encoding="utf-8")

        self.assertTrue(result["forgotten"])
        self.assertGreater(result["log_redaction"]["redacted_entries"], 0)
        self.assertNotIn("TempSecret@42", log_text)
        self.assertIn("redact-log", log_text)
        integrity = verify_log_integrity(wiki)
        self.assertTrue(integrity["passed"], integrity)

    def test_write_memory_page_stores_bounded_context_in_frontmatter(self):
        root = Path(tempfile.mkdtemp(prefix="link-memory-ctx-"))
        wiki = root / "wiki"
        wiki.mkdir(parents=True)

        created = write_memory_page(
            wiki,
            "User only deploys to staging through the release script.",
            title="Deploy through release script",
            memory_type="preference",
            scope="user",
            tags=None,
            source="unit test",
            timestamp="2026-07-12T06:00:00Z",
            context="we debugged the pipeline for an hour " * 30,  # > 600 chars
            records=[],
            log_writer=lambda *a: None,
            rebuild_backlinks=lambda: True,
        )
        page = (wiki / "memories" / f"{created['name']}.md").read_text(encoding="utf-8")
        context_line = next(line for line in page.splitlines() if line.startswith("context:"))

        self.assertTrue(created["created"])
        self.assertIn("we debugged the pipeline", context_line)
        self.assertLessEqual(len(context_line), 620)
        # context never appears in the visible page body — it is not a claim
        body = page.split("---", 2)[2]
        self.assertNotIn("we debugged the pipeline", body)

    def test_write_memory_page_creates_index_log_and_blocks_duplicates(self):
        root = Path(tempfile.mkdtemp(prefix="link-memory-write-"))
        wiki = root / "wiki"
        wiki.mkdir(parents=True)
        logged: list[tuple[str, str, str, list[str]]] = []
        rebuilds = []

        def log_writer(timestamp: str, operation: str, description: str, lines: list[str]) -> None:
            logged.append((timestamp, operation, description, lines))

        created = write_memory_page(
            wiki,
            "User prefers release branches for Link work.",
            title="Prefer release branches",
            memory_type="preference",
            scope="project",
            tags="git, release",
            source="unit test",
            timestamp="2026-05-05T06:00:00Z",
            review_after="2026-08-01",
            expires_at="2026-12-01",
            records=[],
            log_writer=log_writer,
            rebuild_backlinks=lambda: rebuilds.append(True) or True,
        )
        memory_path = wiki / "memories/prefer-release-branches.md"
        memory_text = memory_path.read_text(encoding="utf-8")
        index_text = (wiki / "index.md").read_text(encoding="utf-8")

        self.assertTrue(created["created"])
        self.assertEqual(created["name"], "prefer-release-branches")
        self.assertTrue(created["backlinks_rebuilt"])
        self.assertEqual(rebuilds, [True])
        self.assertIn('title: "Prefer release branches"', memory_text)
        self.assertIn("memory_type: preference", memory_text)
        self.assertIn("visibility: project", memory_text)
        self.assertIn('review_after: "2026-08-01"', memory_text)
        self.assertIn('expires_at: "2026-12-01"', memory_text)
        self.assertIn("tags: [memory, preference, git, release]", memory_text)
        self.assertEqual(created["review_after"], "2026-08-01")
        self.assertEqual(created["expires_at"], "2026-12-01")
        self.assertEqual(created["visibility"], "project")
        self.assertEqual(memory_records(wiki)[0]["visibility"], "project")
        self.assertIn("## Source\n\nunit test", memory_text)
        self.assertIn("[[prefer-release-branches]]", index_text)
        self.assertEqual(logged[-1][1], "remember")
        self.assertIn("Created: memories/prefer-release-branches.md", logged[-1][3])
        self.assertEqual(pending_operations(wiki), [])

        duplicate = write_memory_page(
            wiki,
            "User prefers release branches for Link work.",
            title="Prefer release branches",
            memory_type="preference",
            scope="project",
            tags="git, release",
            source="unit test",
            timestamp="2026-05-05T07:00:00Z",
            records=memory_records(wiki),
        )
        self.assertFalse(duplicate["created"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["visibility"], "project")
        self.assertEqual(duplicate["candidates"][0]["name"], "prefer-release-branches")

        conflict = write_memory_page(
            wiki,
            "User prefers develop branches for Link work.",
            title="Prefer develop branches",
            memory_type="preference",
            scope="project",
            tags="git, develop",
            source="unit test",
            timestamp="2026-05-05T07:30:00Z",
            records=memory_records(wiki),
        )
        self.assertFalse(conflict["created"])
        self.assertTrue(conflict["conflict"])
        self.assertEqual(conflict["conflict_candidates"][0]["name"], "prefer-release-branches")

        conflict_override = write_memory_page(
            wiki,
            "User prefers develop branches for Link work.",
            title="Prefer develop branches",
            memory_type="preference",
            scope="project",
            tags="git, develop",
            source="unit test",
            timestamp="2026-05-05T07:45:00Z",
            records=memory_records(wiki),
            allow_conflict=True,
        )
        self.assertTrue(conflict_override["created"])
        self.assertTrue(conflict_override["conflict_override"])

        duplicate_override = write_memory_page(
            wiki,
            "User prefers release branches for Link work.",
            title="Prefer release branches",
            memory_type="preference",
            scope="project",
            tags="git, release",
            source="unit test",
            timestamp="2026-05-05T08:00:00Z",
            records=memory_records(wiki),
            allow_duplicate=True,
            allow_conflict=True,
        )
        self.assertTrue(duplicate_override["created"])
        self.assertTrue(duplicate_override["duplicate_override"])
        self.assertEqual(duplicate_override["name"], "prefer-release-branches-2")

    def test_write_memory_page_allows_explicit_team_visibility(self):
        root = Path(tempfile.mkdtemp(prefix="link-memory-visibility-"))
        wiki = root / "wiki"
        wiki.mkdir(parents=True)

        created = write_memory_page(
            wiki,
            "Team should share release checklist decisions.",
            title="Team release checklist",
            memory_type="decision",
            scope="project",
            visibility="team",
            tags="release",
            source="unit test",
            timestamp="2026-05-05T06:00:00Z",
            records=[],
        )

        self.assertTrue(created["created"])
        self.assertEqual(created["visibility"], "team")
        self.assertIn("visibility: team", (wiki / "memories/team-release-checklist.md").read_text(encoding="utf-8"))
        self.assertEqual(memory_profile(memory_records(wiki))["by_visibility"], {"team": 1})

        with self.assertRaises(ValueError):
            write_memory_page(
                wiki,
                "Bad visibility.",
                title="Bad",
                memory_type="note",
                scope="user",
                visibility="public",
                tags="",
                source="unit test",
                timestamp="2026-05-05T06:01:00Z",
                records=[],
            )


if __name__ == "__main__":
    unittest.main()


class SlugifyBoundsTests(unittest.TestCase):
    def test_slugify_caps_length_for_filesystem_limits(self):
        slug = slugify("word " * 200)
        self.assertLessEqual(len(slug), 80)
        self.assertFalse(slug.endswith("-"))
        # short slugs unchanged
        self.assertEqual(slugify("My Cool Title"), "my-cool-title")


class ProposalDurabilityRankingTests(unittest.TestCase):
    def test_concrete_rule_outranks_meta_preamble(self):
        self.assertGreater(
            memory_durability_rank("From now on I only deploy on Fridays"),
            memory_durability_rank("I want to set some conventions for how we work going forward"),
        )

    def test_one_click_accept_lands_on_substance_not_preamble(self):
        text = (
            "I want to set some conventions for how we work on the payments service going forward. "
            "From now on I only deploy the payments service on Fridays, never mid-week. "
            "I prefer squash merges for that repo."
        )
        proposals = propose_memories_from_text(text, [])["proposals"]
        # The default accept (--index 1 / one-click) must not be the preamble.
        self.assertNotIn("set some conventions", proposals[0]["memory"])
        # The vague preamble ranks last, not first.
        self.assertIn("set some conventions", proposals[-1]["memory"])

    def test_ranking_is_stable_for_equal_substance(self):
        # Two concrete rules keep transcript order (both rank equally).
        text = "I only merge with squash commits. I always run the linter before pushing."
        proposals = propose_memories_from_text(text, [])["proposals"]
        self.assertIn("squash", proposals[0]["memory"])


class MiningQualityTests(unittest.TestCase):
    """2.1 extraction quality: questions, hearsay, ephemeral scope, ranking."""

    def test_questions_never_classify_even_with_absolutes(self):
        from mcp_package.link_core.memory import classify_memory_segment
        for question in (
            "number of walkers is always fixed?",
            "Should we always deploy on Fridays?",
            "Why does the linter never flag this file?",
        ):
            self.assertIsNone(classify_memory_segment(question), question)

    def test_questions_sink_in_durability_rank(self):
        from mcp_package.link_core.memory import memory_durability_rank
        self.assertLess(
            memory_durability_rank("number of walkers is always fixed?"),
            memory_durability_rank("User wants to set some conventions going forward."),
        )

    def test_bare_imperatives_outrank_meta_preambles(self):
        from mcp_package.link_core.memory import memory_durability_rank
        imperative = memory_durability_rank("Plot the loss curve every 500 steps.")
        preamble = memory_durability_rank("User wants to set some conventions for this repo.")
        concrete = memory_durability_rank("I always plot the loss curve every 500 steps.")
        self.assertGreater(imperative, preamble)
        self.assertGreater(concrete, imperative)

    def test_pasted_hearsay_absolutes_do_not_classify(self):
        from mcp_package.link_core.memory import classify_memory_segment
        for hearsay in (
            "People on Reddit emphasize that they heavily screen for candidates who do not outsource their thinking.",
            "Reviewers never accept generic cover letters according to that thread.",
            "The blog post says teams always squash their commits before merging.",
        ):
            self.assertIsNone(classify_memory_segment(hearsay), hearsay)

    def test_user_voice_and_imperative_absolutes_still_classify(self):
        from mcp_package.link_core.memory import classify_memory_segment
        for direct in (
            "I never commit directly to main.",
            "never push to main directly, releases go through PRs.",
            "Please always ask before deleting files.",
            "The user does not prefer short release notes anymore; write detailed notes.",
        ):
            self.assertIsNotNone(classify_memory_segment(direct), direct)

    def test_time_scoped_observations_do_not_classify(self):
        from mcp_package.link_core.memory import classify_memory_segment
        self.assertIsNone(classify_memory_segment(
            "We concluded the vendor change does not affect us this quarter."
        ))

    def test_proposal_fingerprint_ignores_case_and_punctuation(self):
        from mcp_package.link_core.memory import proposal_fingerprint
        self.assertEqual(
            proposal_fingerprint("User always plots the loss curve!"),
            proposal_fingerprint("  user ALWAYS plots — the loss curve.  "),
        )

    def test_exclude_fingerprints_skips_matching_proposals(self):
        from mcp_package.link_core.memory import (
            proposal_fingerprint,
            propose_memories_from_text,
        )
        text = "I always plot the loss curve every 500 steps."
        mined = propose_memories_from_text(text, [])["proposals"][0]["memory"]
        excluded = propose_memories_from_text(
            text, [], exclude_fingerprints={proposal_fingerprint(str(mined))}
        )
        self.assertEqual(excluded["count"], 0)
        self.assertEqual(excluded["skipped_count"], 1)

    def test_decision_cue_outranks_bare_absolute_typing(self):
        from mcp_package.link_core.memory import classify_memory_segment
        revision = classify_memory_segment(
            "We decided the backend API does not listen on port 8080 anymore; local development now binds port 9000."
        )
        self.assertIsNotNone(revision)
        self.assertEqual(revision["memory_type"], "decision")

    def test_polarity_flip_is_not_an_echo(self):
        from mcp_package.link_core.memory import is_existing_memory_echo
        records = [{
            "name": "ruff", "status": "active", "memory_type": "decision",
            "title": "Python linting uses Ruff",
            "tldr": "Project decided Python linting uses Ruff through the shared config file; CI runs it on every push.",
            "body": "",
        }]
        update = "We decided Python linting does not use Ruff anymore; linting now runs through Biome with the shared config."
        restatement = "Per your saved preference, Python linting uses Ruff through the shared config file; CI runs it on every push."
        self.assertFalse(is_existing_memory_echo(records, update))
        self.assertTrue(is_existing_memory_echo(records, restatement))

    def test_boilerplate_overlap_does_not_create_conflicts(self):
        from mcp_package.link_core.memory import memory_conflict_candidates
        records = [{
            "name": "squash", "status": "active", "memory_type": "decision", "scope": "project",
            "title": "Pull requests are squash-merged",
            "tldr": "Project decided pull requests are squash-merged; main history stays linear.",
            "body": "",
        }]
        candidates = memory_conflict_candidates(
            records,
            "Project decided: The backend API listens on port 8080 in local development; the frontend proxies /api there.",
            "API port", "decision", "project",
        )
        self.assertEqual(candidates, [])


class RevisionDetectionTests(unittest.TestCase):
    """2.1 detector recall: revisions must reach conflict detection."""

    def test_update_with_new_content_is_not_an_echo_despite_high_containment(self):
        from mcp_package.link_core.memory import is_existing_memory_echo
        records = [{
            "name": "deploy", "status": "active", "memory_type": "decision",
            "title": "Deploy from main",
            "tldr": "Project decided deploys ship from the main branch only, never from feature branches, after CI passes.",
            "body": "",
        }]
        update = ("We decided releases never deploy from the main branch now; "
                  "production ships only from release branches after sign-off.")
        framed_echo = ("Per your saved preference, deploys ship from the main branch only, "
                       "never from feature branches, after CI passes. I will keep following that.")
        self.assertFalse(is_existing_memory_echo(records, update))
        self.assertTrue(is_existing_memory_echo(records, framed_echo))

    def test_revision_rule_catches_detailed_heads_at_partial_coverage(self):
        from mcp_package.link_core.memory import memory_conflict_candidates
        records = [{
            "name": "weekly", "status": "active", "memory_type": "decision", "scope": "project",
            "title": "Weekly release trains",
            "tldr": "Project decided releases ship weekly on Thursdays; anything merged after Wednesday noon waits for the next train.",
            "body": "",
        }]
        candidates = memory_conflict_candidates(
            records,
            "Project decided releases never ship weekly on Thursdays now; a release train leaves every day after CI passes.",
            "Daily release trains", "decision", "project",
        )
        self.assertTrue(candidates)
        self.assertIn("revises_existing_claim", candidates[0]["conflict_reasons"])

    def test_preference_decision_cross_pair_skips_scope_gate(self):
        from mcp_package.link_core.memory import memory_conflict_candidates
        records = [{
            "name": "dark", "status": "active", "memory_type": "decision", "scope": "project",
            "title": "Dark theme for demos",
            "tldr": "Project decided every demo screenshot uses dark theme mode in the capture tool.",
            "body": "",
        }]
        candidates = memory_conflict_candidates(
            records,
            "User does not use dark theme for demos anymore; capture screenshots in light mode.",
            "Light theme for demos", "preference", "user",
        )
        self.assertTrue(candidates)


class TrustLifecycleTests(unittest.TestCase):
    """Memory ages honestly: typed windows, re-arm on review, no silent hiding."""

    def _wiki(self):
        import tempfile
        from pathlib import Path
        temp = Path(tempfile.mkdtemp(prefix="link-lifecycle-"))
        (temp / "memories").mkdir(parents=True)
        (temp / "index.md").write_text("# Index\n", encoding="utf-8")
        (temp / "log.md").write_text("# Log\n", encoding="utf-8")
        return temp

    def test_write_stamps_typed_review_window(self):
        from mcp_package.link_core.memory import memory_records, write_memory_page
        wiki = self._wiki()
        write_memory_page(wiki, "I prefer tabs over spaces.", title="Tabs",
                          memory_type="preference", scope="user", tags=None,
                          source="unit", timestamp="2026-08-02T00:00:00Z")
        write_memory_page(wiki, "This project uses uv for env management.", title="Uv",
                          memory_type="project", scope="project", project="demo",
                          tags=None, source="unit", timestamp="2026-08-02T00:00:00Z")
        by_title = {str(r["title"]): r for r in memory_records(wiki)}
        self.assertEqual(by_title["Tabs"]["review_after"], "2027-02-02")     # 6 months
        self.assertEqual(by_title["Uv"]["review_after"], "2026-11-02")       # 3 months

    def test_explicit_review_after_wins(self):
        from mcp_package.link_core.memory import memory_records, write_memory_page
        wiki = self._wiki()
        result = write_memory_page(wiki, "Releases deploy from the release branch.", title="Pin",
                                   memory_type="decision", scope="project", project="demo",
                                   tags=None, source="unit", timestamp="2026-08-02T00:00:00Z",
                                   review_after="2026-09-15")
        self.assertTrue(result.get("created"), result)
        record = memory_records(wiki)[0]
        self.assertEqual(record["review_after"], "2026-09-15")

    def test_review_rearms_due_window_but_keeps_future_custom_date(self):
        from mcp_package.link_core.memory import (
            mark_memory_reviewed, memory_records, write_memory_page,
        )
        wiki = self._wiki()
        write_memory_page(wiki, "I prefer rebase over merge.", title="Rebase",
                          memory_type="preference", scope="user", tags=None,
                          source="unit", timestamp="2026-01-01T00:00:00Z",
                          review_after="2026-06-01")
        mark_memory_reviewed(wiki, "Rebase", None, "2026-08-02T00:00:00Z")
        record = memory_records(wiki)[0]
        self.assertEqual(record["review_after"], "2027-02-02")  # re-armed 6 months

        write_memory_page(wiki, "Keep the beta flag until Q4.", title="Beta",
                          memory_type="note", scope="user", tags=None,
                          source="unit", timestamp="2026-08-01T00:00:00Z",
                          review_after="2026-12-01")
        mark_memory_reviewed(wiki, "Beta", None, "2026-08-02T00:00:00Z")
        beta = next(r for r in memory_records(wiki) if r["title"] == "Beta")
        self.assertEqual(beta["review_after"], "2026-12-01")  # custom future date kept

    def test_memories_without_review_after_age_implicitly(self):
        from mcp_package.link_core.memory import memory_review_issues
        record = {
            "status": "active", "review_status": "reviewed", "memory_type": "preference",
            "scope": "user", "visibility": "private", "review_after": "", "expires_at": "",
            "reviewed_at": "2026-01-05T00:00:00Z", "date_captured": "2025-12-01T00:00:00Z",
            "title": "t", "tldr": "x", "source": "unit",
        }
        codes = [i["code"] for i in memory_review_issues(record, today="2026-08-02")]
        self.assertIn("review_due", codes)
        fresh = dict(record, reviewed_at="2026-06-01T00:00:00Z")
        codes = [i["code"] for i in memory_review_issues(fresh, today="2026-08-02")]
        self.assertNotIn("review_due", codes)

    def test_month_arithmetic_clamps_short_months(self):
        from datetime import date
        from mcp_package.link_core.memory import _add_months
        self.assertEqual(_add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(_add_months(2028 and date(2028, 1, 31), 1), date(2028, 2, 29))
        self.assertEqual(_add_months(date(2026, 12, 15), 1), date(2027, 1, 15))


class FrictionRoundTests(unittest.TestCase):
    """Cold-walk fixes: lead-in trim, trust markers, type inference cues."""

    def test_durability_lead_ins_trimmed_from_stored_claim(self):
        from mcp_package.link_core.memory import normalize_proposed_memory
        self.assertEqual(
            normalize_proposed_memory("from now on I only push to develop", "preference"),
            "I only push to develop.",
        )
        self.assertEqual(
            normalize_proposed_memory("Going forward, we always tag releases.", "preference"),
            "We always tag releases.",
        )

    def test_trust_marker_flags_pending_and_due(self):
        from mcp_package.link_core.cli_memory import _trust_marker
        self.assertEqual(_trust_marker({"review_status": "pending"}), " · pending review")
        self.assertEqual(
            _trust_marker({"review_status": "reviewed", "review_after": "2020-01-01"}),
            " · review due",
        )
        self.assertEqual(
            _trust_marker({"review_status": "reviewed", "review_after": "2999-01-01"}), "",
        )

    def test_remember_type_cues_classify_for_inference(self):
        from mcp_package.link_core.memory import classify_memory_segment
        self.assertEqual(classify_memory_segment("I prefer dark mode in every editor.")["memory_type"], "preference")
        self.assertEqual(classify_memory_segment("We decided sprints are two weeks.")["memory_type"], "decision")
        self.assertIsNone(classify_memory_segment("The meeting moved to Thursday afternoon room 4."))


class SemanticRevisionTests(unittest.TestCase):
    """Lexically disjoint revisions caught by meaning when the tier exists."""

    RECORDS = [{
        "name": "sqlite", "status": "active", "memory_type": "decision", "scope": "project",
        "title": "Embedded storage engine",
        "tldr": "Local data lives in SQLite with FTS enabled; queries use the embedded engine and no external database service runs.",
        "body": "",
    }, {
        "name": "squash", "status": "active", "memory_type": "decision", "scope": "project",
        "title": "Squash-merge pull requests",
        "tldr": "Pull requests are squash-merged; main history stays linear.",
        "body": "",
    }]
    REVISION = ("Project decided local data does not live in SQLite anymore; "
                "we settled on DuckDB files.")

    @staticmethod
    def _stub_embedder(texts):
        # Deterministic stand-in: storage-topic texts share an axis,
        # merge-topic texts another — mirrors what the real model showed
        # (true revisions 0.60-0.82, unrelated pairs <= 0.18).
        def vec(text):
            lower = text.lower()
            storage = 1.0 if ("sqlite" in lower or "duckdb" in lower) else 0.0
            merging = 1.0 if ("squash" in lower or "merge" in lower) else 0.0
            return [storage, merging, 0.1]
        return [vec(text) for text in texts]

    def _reasons(self, candidates, name):
        for candidate in candidates:
            if str(candidate.get("name")) == name:
                return list(candidate.get("conflict_reasons") or [])
        return []

    def test_semantic_tier_catches_disjoint_revision(self):
        from mcp_package.link_core.memory import memory_conflict_candidates
        candidates = memory_conflict_candidates(
            self.RECORDS, self.REVISION, "DuckDB decision",
            "decision", "project", embedder=self._stub_embedder,
        )
        self.assertIn("semantic_revision", self._reasons(candidates, "sqlite"))
        self.assertEqual(self._reasons(candidates, "squash"), [])

    def test_without_embedder_detection_stays_lexical(self):
        from mcp_package.link_core.memory import memory_conflict_candidates
        candidates = memory_conflict_candidates(
            self.RECORDS, self.REVISION, "DuckDB decision",
            "decision", "project", embedder=lambda texts: [],
        )
        for candidate in candidates:
            self.assertNotIn("semantic_revision", candidate.get("conflict_reasons") or [])

    def test_semantic_pass_needs_revision_cue(self):
        from mcp_package.link_core.memory import memory_conflict_candidates
        plain = "The project stores analytics in DuckDB files."
        candidates = memory_conflict_candidates(
            self.RECORDS, plain, "DuckDB analytics",
            "decision", "project", embedder=self._stub_embedder,
        )
        for candidate in candidates:
            self.assertNotIn("semantic_revision", candidate.get("conflict_reasons") or [])


class MergeCandidateTests(unittest.TestCase):
    """Consolidation v2: accepted memories that likely say the same thing."""

    @staticmethod
    def _record(name, tldr, memory_type="preference", scope="user",
                review_status="pending", date="2026-08-01T00:00:00Z", **extra):
        return {"name": name, "title": tldr[:50], "tldr": tldr, "snippet": tldr,
                "body": "", "status": "active", "memory_type": memory_type,
                "scope": scope, "review_status": review_status,
                "date_captured": date, **extra}

    def test_token_overlap_pair_detected_with_survivor_preference(self):
        from mcp_package.link_core.memory import memory_merge_candidates
        records = [
            self._record("a", "I prefer short PR descriptions with a test plan section.",
                         review_status="reviewed"),
            self._record("b", "Short PR descriptions and always a test plan section included.",
                         date="2026-08-02T00:00:00Z"),
            self._record("c", "We deploy the payments service only on Fridays."),
        ]
        candidates = memory_merge_candidates(records)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["survivor"], "a")   # reviewed beats newer
        self.assertEqual(candidates[0]["absorbed"], "b")
        self.assertEqual(candidates[0]["reason"], "token_overlap")

    def test_polarity_flip_is_never_a_merge(self):
        from mcp_package.link_core.memory import memory_merge_candidates
        records = [
            self._record("a", "I always include a test plan section in PR descriptions."),
            self._record("b", "I never include a test plan section in PR descriptions."),
        ]
        self.assertEqual(memory_merge_candidates(records), [])

    def test_lineage_and_type_gates(self):
        from mcp_package.link_core.memory import memory_merge_candidates
        linked = [
            self._record("a", "Short PR descriptions with a test plan section.",
                         superseded_by="b"),
            self._record("b", "Short PR descriptions with a test plan section please.",
                         supersedes="a"),
        ]
        self.assertEqual(memory_merge_candidates(linked), [])
        cross_type = [
            self._record("a", "Short PR descriptions with a test plan section."),
            self._record("b", "Short PR descriptions with a test plan section please.",
                         memory_type="note"),
        ]
        self.assertEqual(memory_merge_candidates(cross_type), [])

    def test_semantic_pair_via_stub_embedder(self):
        from mcp_package.link_core.memory import memory_merge_candidates
        records = [
            self._record("a", "Keep pull request summaries brief and attach testing steps."),
            self._record("b", "PR descriptions stay short with a validation checklist."),
        ]
        def stub(texts):
            return [[1.0, 0.0] for _ in texts]  # everything identical in meaning
        candidates = memory_merge_candidates(records, embedder=stub)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["reason"], "semantic")

    def test_no_embedder_means_lexical_only(self):
        from mcp_package.link_core.memory import memory_merge_candidates
        records = [
            self._record("a", "Keep pull request summaries brief and attach testing steps."),
            self._record("b", "PR descriptions stay short with a validation checklist."),
        ]
        candidates = memory_merge_candidates(records, embedder=lambda texts: [])
        self.assertEqual(candidates, [])


class TemporalExpressionTests(unittest.TestCase):
    """Plain-language time phrases resolve to exact as-of dates."""

    TODAY = "2026-08-03"

    def _parse(self, query):
        from mcp_package.link_core.memory import parse_time_expression
        return parse_time_expression(query, today=self.TODAY)

    def test_relative_windows_resolve(self):
        cases = {
            "what did we decide last quarter": "2026-05-05",
            "the plan 2 months ago": "2026-06-04",
            "releases this year": "2026-01-01",
            "stack in 2025": "2025-12-31",
            "database choice in March": "2026-03-31",
            "api port as of 2026-01-15": "2026-01-15",
        }
        for query, expected in cases.items():
            parsed = self._parse(query)
            self.assertIsNotNone(parsed, query)
            self.assertEqual(parsed["as_of"], expected, query)

    def test_residual_query_drops_the_date_words(self):
        parsed = self._parse("where does local data live in March")
        self.assertEqual(parsed["residual_query"], "where does local data live")

    def test_vague_phrases_anchor_honestly(self):
        for phrase in ("what did I prefer back then", "the setup at the time"):
            parsed = self._parse(phrase)
            self.assertEqual(parsed["as_of"], "2026-05-05")

    def test_event_anchors_are_reported_not_guessed(self):
        parsed = self._parse("decisions before the migration")
        self.assertIsNotNone(parsed)
        self.assertIsNone(parsed["as_of"])
        self.assertIn("before the migration", str(parsed["unresolved_event"]))
        # The topic words stay in the query so ranking can use them.
        self.assertIn("migration", str(parsed["residual_query"]))

    def test_queries_without_time_are_untouched(self):
        self.assertIsNone(self._parse("where does local data live"))
        self.assertIsNone(self._parse("what is the deploy process"))

    def test_point_in_time_reconstruction_picks_the_old_era(self):
        from mcp_package.link_core.memory import memory_active_at
        old = {"name": "sqlite", "status": "archived",
               "date_captured": "2026-01-10T00:00:00Z",
               "archived_at": "2026-06-01T00:00:00Z"}
        new = {"name": "duckdb", "status": "active",
               "date_captured": "2026-06-01T00:00:00Z"}
        self.assertTrue(memory_active_at(old, "2026-03-31"))
        self.assertFalse(memory_active_at(new, "2026-03-31"))
        self.assertFalse(memory_active_at(old, self.TODAY))
        self.assertTrue(memory_active_at(new, self.TODAY))
