import unittest

from mcp_package.link_core.cli_memory import (
    render_brief_text,
    render_forget_memory_text,
    render_explain_memory_text,
    render_memory_audit_text,
    render_memory_inbox_text,
    render_memory_status_text,
    render_profile_text,
    render_propose_memories_text,
    render_recall_text,
    render_review_memory_text,
    render_remember_text,
    render_update_memory_text,
)


class CliMemoryCoreTests(unittest.TestCase):
    def test_render_remember_created(self):
        code, text = render_remember_text({
            "created": True,
            "title": "Prefer release branches",
            "path": "wiki/memories/prefer-release-branches.md",
            "memory_type": "preference",
            "scope": "project",
            "project": "link",
            "review_after": "2026-08-01",
            "expires_at": "2026-12-01",
        })

        self.assertEqual(code, 0)
        self.assertIn("Memory saved", text)
        self.assertIn("Project: link", text)
        self.assertIn("Review after: 2026-08-01", text)
        self.assertIn("Expires at: 2026-12-01", text)
        self.assertIn("python3 link.py recall", text)
        self.assertIn("Prefer release branches", text)

    def test_render_remember_duplicate(self):
        code, text = render_remember_text({
            "created": False,
            "duplicate": True,
            "title": "Prefer release branches",
            "memory_type": "preference",
            "scope": "project",
            "candidates": [{
                "name": "prefer-release-branches",
                "title": "Prefer release branches",
                "path": "wiki/memories/prefer-release-branches.md",
            }],
        })

        self.assertEqual(code, 0)
        self.assertIn("Similar memory already exists", text)
        self.assertIn("Existing candidates:", text)
        self.assertIn("python3 link.py explain-memory prefer-release-branches", text)

    def test_render_remember_conflict(self):
        code, text = render_remember_text({
            "created": False,
            "conflict": True,
            "title": "Prefer develop branches",
            "memory_type": "preference",
            "scope": "project",
            "conflict_candidates": [{
                "name": "prefer-release-branches",
                "title": "Prefer release branches",
                "path": "wiki/memories/prefer-release-branches.md",
                "conflict_reasons": ["different_branch_policy"],
            }],
        })

        self.assertEqual(code, 0)
        self.assertIn("Possible conflicting memory found", text)
        self.assertIn("Reasons: different_branch_policy", text)

    def test_render_update_memory(self):
        code, text = render_update_memory_text({
            "updated": True,
            "name": "prefer-release-branches",
            "title": "Prefer release branches",
            "path": "wiki/memories/prefer-release-branches.md",
            "update_count": 2,
            "previous_review_status": "reviewed",
            "review_status": "pending",
        })

        self.assertEqual(code, 0)
        self.assertIn("Memory updated", text)
        self.assertIn("Review: reviewed -> pending", text)
        self.assertIn("python3 link.py review-memory prefer-release-branches", text)

    def test_render_propose_memories_text(self):
        code, text = render_propose_memories_text({
            "source": "raw/session.md",
            "project": "link",
            "count": 1,
            "proposals": [{
                "title": "Prefer release branches",
                "confidence": "high",
                "memory_type": "preference",
                "scope": "project",
                "project": "link",
                "suggested_action": "update-memory",
                "memory": "The user prefers release branches.",
                "primary_action": {"command": "python3 link.py update-memory prefer-release-branches"},
                "duplicate_candidates": [{
                    "title": "Prefer release branches",
                    "path": "wiki/memories/prefer-release-branches.md",
                }],
            }],
        })

        self.assertEqual(code, 0)
        self.assertIn("Memory proposals", text)
        self.assertIn("Source: raw/session.md", text)
        self.assertIn("Project: link", text)
        self.assertIn("1. Prefer release branches [high]", text)
        self.assertIn("Command: python3 link.py update-memory", text)
        self.assertIn("Duplicate candidate: Prefer release branches", text)
        self.assertIn("Use remember for new memories", text)

    def test_render_propose_memories_text_empty(self):
        code, text = render_propose_memories_text({
            "source": "inline",
            "count": 0,
            "proposals": [],
        })

        self.assertEqual(code, 0)
        self.assertIn("No durable memory candidates found.", text)

    def test_render_recall_empty(self):
        code, text = render_recall_text(query="release branches", results=[], project="link")

        self.assertEqual(code, 0)
        self.assertIn("Link memory recall: release branches", text)
        self.assertIn("Project: link", text)
        self.assertIn("No matching memories found.", text)

    def test_render_recall_results(self):
        code, text = render_recall_text(
            query="release branches",
            include_archived=True,
            results=[{
                "title": "Prefer release branches",
                "memory_type": "preference",
                "scope": "project",
                "path": "wiki/memories/prefer-release-branches.md",
                "recall": {"state": "ready"},
                "tldr": "Use release branches for public changes.",
            }],
        )

        self.assertEqual(code, 0)
        self.assertIn("Including archived/stale memories", text)
        self.assertIn("1 memory", text)
        self.assertIn("Recall: ready", text)
        self.assertIn("Use release branches for public changes.", text)

    def test_render_memory_status_archive(self):
        code, text = render_memory_status_text({
            "updated": True,
            "name": "prefer-local-memory",
            "title": "Prefer local memory",
            "path": "wiki/memories/prefer-local-memory.md",
            "previous_status": "active",
            "status": "archived",
        }, action="archive")

        self.assertEqual(code, 0)
        self.assertIn("Memory archived", text)
        self.assertIn("Restore: python3 link.py restore-memory prefer-local-memory", text)

    def test_render_memory_status_restore(self):
        code, text = render_memory_status_text({
            "updated": False,
            "name": "prefer-local-memory",
            "title": "Prefer local memory",
            "path": "wiki/memories/prefer-local-memory.md",
            "previous_status": "active",
            "status": "active",
        }, action="restore")

        self.assertEqual(code, 0)
        self.assertIn("Memory already active", text)
        self.assertNotIn("Restore:", text)

    def test_render_forget_memory_requires_confirmation(self):
        code, text = render_forget_memory_text({
            "found": True,
            "confirmation_required": True,
            "name": "prefer-local-memory",
        }, identifier="prefer-local-memory")

        self.assertEqual(code, 1)
        self.assertIn("Confirmation required.", text)
        self.assertIn('--confirm', text)

    def test_render_forget_memory_done(self):
        code, text = render_forget_memory_text({
            "found": True,
            "forgotten": True,
            "title": "Prefer local memory",
            "path": "wiki/memories/prefer-local-memory.md",
            "backlinks_rebuilt": True,
        }, identifier="prefer-local-memory")

        self.assertEqual(code, 0)
        self.assertIn("Memory forgotten", text)
        self.assertIn("Backlinks rebuilt: yes", text)

    def test_render_review_memory_with_remaining_issues(self):
        code, text = render_review_memory_text({
            "updated": True,
            "title": "Prefer local memory",
            "path": "wiki/memories/prefer-local-memory.md",
            "previous_review_status": "pending",
            "review_status": "reviewed",
            "remaining_issue_count": 1,
            "remaining_issues": [{
                "severity": "medium",
                "code": "missing_source",
                "message": "Memory should cite a source.",
            }],
        })

        self.assertEqual(code, 0)
        self.assertIn("Memory reviewed", text)
        self.assertIn("1 issue still need attention:", text)
        self.assertIn("[medium] missing_source: Memory should cite a source.", text)

    def test_render_memory_inbox(self):
        code, text = render_memory_inbox_text({
            "project": "link",
            "review_count": 1,
            "counts_by_severity": {"medium": 1},
            "items": [{
                "title": "Prefer local memory",
                "memory_type": "preference",
                "scope": "user",
                "status": "active",
                "path": "wiki/memories/prefer-local-memory.md",
                "issues": [{
                    "severity": "medium",
                    "code": "pending_review",
                    "message": "Memory needs review.",
                }],
                "primary_action": {
                    "kind": "review",
                    "label": "Review",
                    "description": "Mark memory reviewed",
                    "command": "link review-memory prefer-local-memory",
                },
                "actions": [
                    {"kind": "review", "label": "Review"},
                    {"kind": "archive", "label": "Archive"},
                ],
            }],
        }, target="/tmp/link", include_archived=True)

        self.assertEqual(code, 0)
        self.assertIn("Link memory inbox: /tmp/link", text)
        self.assertIn("Project: link", text)
        self.assertIn("Severity: medium: 1", text)
        self.assertIn("Next: Review - Mark memory reviewed", text)
        self.assertIn("Other actions: Archive", text)

    def test_render_memory_inbox_clear(self):
        code, text = render_memory_inbox_text({
            "review_count": 0,
            "counts_by_severity": {},
            "items": [],
        }, target="/tmp/link")

        self.assertEqual(code, 0)
        self.assertIn("0 memories need review", text)
        self.assertIn("Inbox is clear.", text)

    def test_render_explain_memory(self):
        code, text = render_explain_memory_text({
            "memory": {
                "title": "Prefer local memory",
                "path": "wiki/memories/prefer-local-memory.md",
                "memory_type": "preference",
                "scope": "user",
                "tldr": "User prefers local memory.",
            },
            "recall": {
                "state": "needs_review",
                "default_enabled": True,
                "reason": "Pending review",
            },
            "review": {
                "status": "pending",
                "issue_count": 1,
                "issues": [{
                    "severity": "medium",
                    "code": "pending_review",
                    "message": "Memory needs review.",
                    "suggested_action": "review-memory",
                }],
            },
            "provenance": {
                "source": "manual",
                "date_captured": "2026-05-16T00:00:00Z",
            },
            "lifecycle": {"status": "active"},
            "graph": {"forward": ["agent-memory"], "inbound": []},
            "log_entries": ["## remember | Prefer local memory\n\nCreated."],
        })

        self.assertEqual(code, 0)
        self.assertIn("Link memory explanation: Prefer local memory", text)
        self.assertIn("Recall: needs_review (enabled by default)", text)
        self.assertIn("Summary: User prefers local memory.", text)
        self.assertIn("Action: review-memory", text)
        self.assertIn("Forward links: agent-memory", text)
        self.assertIn("remember | Prefer local memory", text)

    def test_render_brief_text(self):
        payload = {
            "profile": {
                "active_count": 2,
                "by_type": {"preference": 1},
                "by_scope": {"user": 1},
            },
            "relevant_count": 1,
            "relevant_memories": [{
                "title": "Prefer local memory",
                "memory_type": "preference",
                "scope": "user",
                "path": "wiki/memories/prefer-local-memory.md",
                "tldr": "Local memory preferred.",
            }],
            "review": {
                "count": 1,
                "items": [{
                    "title": "Prefer local memory",
                    "memory_type": "preference",
                    "scope": "user",
                    "issues": [{
                        "severity": "medium",
                        "code": "pending_review",
                        "message": "Needs review.",
                    }],
                }],
            },
            "captures": {
                "count": 1,
                "warning_count": 1,
                "next_action": "review captures",
                "items": [{
                    "title": "Session",
                    "path": "raw/memory-captures/session.md",
                    "secret_warnings": ["api_key"],
                }],
            },
            "agent_guidance": ["Use query_link for task context."],
        }

        code, text = render_brief_text(payload, query="local memory", project="link")

        self.assertEqual(code, 0)
        self.assertIn("Link memory brief: local memory", text)
        self.assertIn("Project: link", text)
        self.assertIn("Relevant memories", text)
        self.assertIn("Review queue", text)
        self.assertIn("Raw captures", text)
        self.assertIn("Agent guidance", text)

    def test_render_profile_text_empty(self):
        code, text = render_profile_text({
            "memory_count": 0,
            "active_count": 0,
            "review_count": 0,
            "by_type": {},
            "by_scope": {},
            "by_project": {},
            "by_status": {},
            "top_tags": [],
            "recent": [],
            "preferences": [],
            "decisions": [],
            "projects": [],
            "archived": [],
        }, target="/tmp/link")

        self.assertEqual(code, 0)
        self.assertIn("No memories found.", text)
        self.assertIn("python3 link.py remember", text)
        self.assertIn("/tmp/link", text)

    def test_render_profile_text_with_sections(self):
        record = {
            "title": "Prefer local memory",
            "memory_type": "preference",
            "scope": "user",
            "path": "wiki/memories/prefer-local-memory.md",
            "tldr": "Local memory preferred.",
        }

        code, text = render_profile_text({
            "memory_count": 1,
            "active_count": 1,
            "review_count": 1,
            "by_type": {"preference": 1},
            "by_scope": {"user": 1},
            "by_project": {"link": 1},
            "by_status": {"active": 1},
            "top_tags": [{"tag": "memory", "count": 1}],
            "recent": [record],
            "preferences": [record],
            "decisions": [],
            "projects": [],
            "archived": [],
        }, target="/tmp/link", project="link")

        self.assertEqual(code, 0)
        self.assertIn("Link memory profile: /tmp/link", text)
        self.assertIn("Projects: link: 1", text)
        self.assertIn("Tags: memory (1)", text)
        self.assertIn("Recent memories", text)
        self.assertIn("Decisions\n- none", text)

    def test_render_memory_audit_text(self):
        code, text = render_memory_audit_text({
            "project": "link",
            "status": "needs_attention",
            "profile": {
                "memory_count": 2,
                "active_count": 1,
                "review_count": 1,
            },
            "captures": {
                "count": 1,
                "warning_count": 1,
                "read_warning_count": 0,
            },
            "risk_factors": [{
                "code": "pending_review",
                "message": "A memory needs review.",
            }],
            "next_actions": [{
                "label": "Review memory inbox",
                "recommended": True,
                "command": "link memory-inbox",
            }],
        }, target="/tmp/link")

        self.assertEqual(code, 0)
        self.assertIn("Link memory audit: /tmp/link", text)
        self.assertIn("Status: needs_attention", text)
        self.assertIn("pending_review: A memory needs review.", text)
        self.assertIn("Review memory inbox (recommended)", text)


if __name__ == "__main__":
    unittest.main()
