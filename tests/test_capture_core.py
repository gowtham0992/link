import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp_package.link_core.capture import (
    capture_accept_memory_args,
    capture_accept_payload,
    capture_decision_trail,
    capture_filename,
    capture_inbox,
    capture_notes_from_markdown,
    capture_proposal_selection,
    capture_proposal_source,
    capture_records,
    capture_review_summary,
    capture_title,
    delete_capture_file,
    mcp_capture_commands,
    redact_capture_file,
    render_accept_capture_text,
    render_capture_inbox_text,
    render_capture_session_text,
    render_delete_capture_text,
    render_redact_capture_text,
    render_session_end_text,
    resolve_capture_file,
    write_session_capture,
)


class CaptureCoreTests(unittest.TestCase):
    def test_capture_title_uses_explicit_title_first(self):
        self.assertEqual(
            capture_title("ignored", "inline", "  Sprint   planning notes  "),
            "Sprint planning notes",
        )

    def test_capture_title_supports_cli_path_sources(self):
        self.assertEqual(
            capture_title("", "raw/first-memory.md", path_source=True),
            "Memory capture: First Memory",
        )

    def test_capture_title_supports_mcp_source_labels(self):
        self.assertEqual(
            capture_title("", "daily standup", default_source="mcp"),
            "Memory capture: daily standup",
        )

    def test_capture_title_falls_back_to_first_note_line(self):
        self.assertEqual(
            capture_title("\n\nRemember that Link is local agent memory.\nMore detail."),
            "Memory capture: Remember that Link is local agent memory",
        )

    def test_capture_filename_is_unique_and_slugged(self):
        root = Path(tempfile.mkdtemp(prefix="link-capture-filename-"))
        first = capture_filename("2026-05-06T01:02:03Z", "Memory capture: First Memory", root)
        first.write_text("# first\n", encoding="utf-8")
        second = capture_filename("2026-05-06T01:02:03Z", "Memory capture: First Memory", root)

        self.assertEqual(first.name, "20260506T010203Z-first-memory.md")
        self.assertEqual(second.name, "20260506T010203Z-first-memory-2.md")

    def test_write_session_capture_persists_proposal_only_markdown(self):
        root = Path(tempfile.mkdtemp(prefix="link-capture-write-"))

        payload = write_session_capture(
            root,
            text="Remember that Link uses local markdown memory.",
            source="raw/first-memory.md",
            title=None,
            project="Link Product",
            timestamp="2026-05-06T01:02:03Z",
            path_source=True,
        )

        capture_path = root / str(payload["path"])
        text = capture_path.read_text(encoding="utf-8")
        self.assertEqual(payload["path"], "raw/memory-captures/20260506T010203Z-first-memory.md")
        self.assertEqual(payload["title"], "Memory capture: First Memory")
        self.assertEqual(payload["project"], "link-product")
        self.assertEqual(payload["secret_warnings"], [])
        self.assertIn('project: "link-product"', text)
        self.assertIn("## Source Input\n\nraw/first-memory.md", text)
        self.assertIn("## Notes\n\nRemember that Link uses local markdown memory.", text)

    def test_write_session_capture_rejects_empty_notes(self):
        root = Path(tempfile.mkdtemp(prefix="link-capture-write-"))

        with self.assertRaises(ValueError):
            write_session_capture(root, text="   ", source="inline")

    def test_resolve_capture_file_accepts_supported_root_relative_forms(self):
        root = Path(tempfile.mkdtemp(prefix="link-capture-core-"))
        capture_dir = root / "raw" / "memory-captures"
        capture_dir.mkdir(parents=True)
        capture = capture_dir / "session.md"
        capture.write_text("# Session\n", encoding="utf-8")

        self.assertEqual(resolve_capture_file(root, "raw/memory-captures/session.md"), capture.resolve())
        self.assertEqual(resolve_capture_file(root, "session.md"), capture.resolve())
        self.assertEqual(resolve_capture_file(root, "session"), capture.resolve())

    def test_resolve_capture_file_rejects_paths_outside_root(self):
        root = Path(tempfile.mkdtemp(prefix="link-capture-core-"))
        outside = Path(tempfile.mkdtemp(prefix="link-capture-outside-")) / "session.md"
        outside.write_text("# Outside\n", encoding="utf-8")
        capture_dir = root / "raw" / "memory-captures"
        capture_dir.mkdir(parents=True)
        symlink = capture_dir / "outside.md"
        try:
            symlink.symlink_to(outside)
        except OSError:
            symlink = None

        self.assertIsNone(resolve_capture_file(root, str(outside)))
        self.assertIsNone(resolve_capture_file(root, "../session.md"))
        if symlink is not None:
            self.assertIsNone(resolve_capture_file(root, "outside.md"))

    def test_capture_notes_from_markdown_extracts_notes_section(self):
        meta, notes = capture_notes_from_markdown(
            "---\ntitle: Session\nproject: link\n---\n\n"
            "# Session\n\n"
            "Intro should not be used.\n\n"
            "## Notes\n\n"
            "Important memory candidate.\n\n"
            "## Proposals\n\n"
            "- Ignore generated proposals.\n"
        )

        self.assertEqual(meta["title"], "Session")
        self.assertEqual(meta["project"], "link")
        self.assertEqual(notes, "Important memory candidate.")

    def test_capture_proposal_selection_reads_capture_and_selects_index(self):
        root = Path(tempfile.mkdtemp(prefix="link-capture-selection-"))
        capture_dir = root / "raw" / "memory-captures"
        capture_dir.mkdir(parents=True)
        (capture_dir / "session.md").write_text(
            "---\n"
            "title: Session\n"
            "project: Alpha Project\n"
            "---\n\n"
            "## Notes\n\n"
            "Remember the selected proposal.\n",
            encoding="utf-8",
        )

        def propose(notes: str, source: str, limit: int, project: str, curated: bool = False) -> dict[str, object]:
            return {
                "count": 2,
                "proposals": [
                    {"title": "First", "memory": notes, "scope": "user", "project": project},
                    {"title": "Second", "memory": source, "scope": "project", "project": project},
                ],
                "limit": limit,
            }

        selection = capture_proposal_selection(
            root,
            "session",
            index=2,
            default_project="default",
            propose_memories=propose,
        )

        self.assertEqual(selection["capture"], "raw/memory-captures/session.md")
        self.assertEqual(selection["project"], "alpha-project")
        self.assertEqual(selection["proposal_index"], 2)
        self.assertEqual(selection["proposal"]["title"], "Second")
        self.assertEqual(selection["proposals"]["limit"], 10)

    def test_capture_accept_memory_args_and_payload(self):
        selection = {
            "capture": "raw/memory-captures/session.md",
            "proposal_index": 2,
            "project": "link",
            "proposal": {
                "title": "Prefer release branches",
                "memory": "The user prefers release branches.",
                "memory_type": "preference",
                "scope": "project",
                "visibility": "team",
                "project": "link",
            },
        }

        args = capture_accept_memory_args(selection, title="Release branch preference", tags="workflow")
        payload = capture_accept_payload(selection, {
            "created": True,
            "path": "wiki/memories/release-branch-preference.md",
            "project": "link",
        })

        self.assertEqual(args["text"], "The user prefers release branches.")
        self.assertEqual(args["title"], "Release branch preference")
        self.assertEqual(args["memory_type"], "preference")
        self.assertEqual(args["scope"], "project")
        self.assertEqual(args["visibility"], "team")
        self.assertEqual(args["tags"], "workflow")
        self.assertEqual(args["source"], "raw/memory-captures/session.md")
        self.assertEqual(args["project"], "link")
        self.assertTrue(payload["accepted"])
        self.assertEqual(payload["proposal_index"], 2)
        self.assertEqual(payload["result"]["path"], "wiki/memories/release-branch-preference.md")

    def test_capture_accept_memory_args_omits_project_for_user_scope(self):
        selection = {
            "capture": "raw/memory-captures/session.md",
            "project": "link",
            "proposal": {
                "title": "Prefer local memory",
                "memory": "The user prefers local memory.",
                "memory_type": "preference",
                "scope": "user",
            },
        }

        args = capture_accept_memory_args(selection)

        self.assertEqual(args["scope"], "user")
        self.assertEqual(args["project"], "")

    def test_capture_proposal_selection_validates_index_and_notes(self):
        root = Path(tempfile.mkdtemp(prefix="link-capture-selection-"))
        capture_dir = root / "raw" / "memory-captures"
        capture_dir.mkdir(parents=True)
        (capture_dir / "empty.md").write_text("", encoding="utf-8")

        def propose(_notes: str, _source: str, _limit: int, _project: str, _curated: bool = False) -> dict[str, object]:
            return {"proposals": []}

        with self.assertRaisesRegex(ValueError, "proposal index must be 1 or greater"):
            capture_proposal_selection(root, "empty", index=0, propose_memories=propose)
        with self.assertRaisesRegex(ValueError, "capture has no notes"):
            capture_proposal_selection(root, "empty", index=1, propose_memories=propose)
        with self.assertRaisesRegex(ValueError, "capture not found"):
            capture_proposal_selection(root, "missing", index=1, propose_memories=propose)

    def test_redact_capture_file_redacts_and_reports_labels(self):
        root = Path(tempfile.mkdtemp(prefix="link-capture-redact-"))
        capture_dir = root / "raw" / "memory-captures"
        capture_dir.mkdir(parents=True)
        fake_key = "sk-" + "a" * 48
        capture = capture_dir / "session.md"
        capture.write_text(f"## Notes\n\nSecret: {fake_key}\n", encoding="utf-8")

        payload = redact_capture_file(root, "session", replacement="[gone]")

        self.assertTrue(payload["redacted"])
        self.assertEqual(payload["path"], "raw/memory-captures/session.md")
        self.assertEqual(payload["labels"], ["OpenAI API key"])
        self.assertEqual(payload["replacement_count"], 1)
        self.assertNotIn(fake_key, capture.read_text(encoding="utf-8"))
        self.assertIn("[gone]", capture.read_text(encoding="utf-8"))

    def test_redact_capture_file_reports_noop_without_rewriting(self):
        root = Path(tempfile.mkdtemp(prefix="link-capture-redact-"))
        capture_dir = root / "raw" / "memory-captures"
        capture_dir.mkdir(parents=True)
        capture = capture_dir / "session.md"
        capture.write_text("## Notes\n\nNo secrets here.\n", encoding="utf-8")

        payload = redact_capture_file(root, "session")

        self.assertFalse(payload["redacted"])
        self.assertEqual(payload["labels"], [])
        self.assertEqual(payload["replacement_count"], 0)
        self.assertEqual(capture.read_text(encoding="utf-8"), "## Notes\n\nNo secrets here.\n")

    def test_delete_capture_file_requires_confirmation(self):
        root = Path(tempfile.mkdtemp(prefix="link-capture-delete-"))
        capture_dir = root / "raw" / "memory-captures"
        capture_dir.mkdir(parents=True)
        capture = capture_dir / "session.md"
        capture.write_text("## Notes\n\nDelete me.\n", encoding="utf-8")

        payload = delete_capture_file(root, "session", confirm=False)

        self.assertFalse(payload["deleted"])
        self.assertTrue(payload["confirmation_required"])
        self.assertTrue(capture.exists())

        payload = delete_capture_file(root, "session", confirm=True)

        self.assertTrue(payload["deleted"])
        self.assertFalse(payload["confirmation_required"])
        self.assertFalse(capture.exists())

    def test_capture_mutation_helpers_reject_missing_capture(self):
        root = Path(tempfile.mkdtemp(prefix="link-capture-missing-"))

        with self.assertRaisesRegex(ValueError, "capture not found"):
            redact_capture_file(root, "missing")
        with self.assertRaisesRegex(ValueError, "capture not found"):
            delete_capture_file(root, "missing", confirm=True)

    def test_capture_records_redact_snippets_and_filter_project(self):
        root = Path(tempfile.mkdtemp(prefix="link-capture-core-"))
        capture_dir = root / "raw" / "memory-captures"
        capture_dir.mkdir(parents=True)
        fake_key = "sk-" + "a" * 48
        (capture_dir / "alpha.md").write_text(
            "---\n"
            "title: Alpha\n"
            "project: alpha\n"
            "date_captured: 2026-05-05T00:00:00Z\n"
            "---\n\n"
            "# Alpha\n\n"
            "## Notes\n\n"
            f"Remember alpha. Secret {fake_key}\n",
            encoding="utf-8",
        )
        (capture_dir / "beta.md").write_text(
            "---\n"
            "title: Beta\n"
            "project: beta\n"
            "date_captured: 2026-05-04T00:00:00Z\n"
            "---\n\n"
            "# Beta\n\n"
            "## Notes\n\n"
            "Remember beta.\n",
            encoding="utf-8",
        )

        records = capture_records(root, project="alpha", commands_for=mcp_capture_commands)
        inbox = capture_inbox(root, project="alpha", commands_for=mcp_capture_commands)

        self.assertEqual([record["title"] for record in records], ["Alpha"])
        self.assertEqual(records[0]["secret_warnings"], ["OpenAI API key"])
        self.assertIn("[redacted-secret]", records[0]["snippet"])
        self.assertNotIn(fake_key, records[0]["snippet"])
        self.assertIn("accept_capture", records[0]["commands"]["accept"])
        self.assertEqual(inbox["count"], 1)
        self.assertEqual(inbox["warning_count"], 1)
        self.assertEqual(inbox["project"], "alpha")

    def test_capture_inbox_reports_unreadable_captures(self):
        root = Path(tempfile.mkdtemp(prefix="link-capture-core-"))
        capture_dir = root / "raw" / "memory-captures"
        capture_dir.mkdir(parents=True)
        (capture_dir / "good.md").write_text(
            "---\n"
            "title: Good\n"
            "date_captured: 2026-05-05T00:00:00Z\n"
            "---\n\n"
            "## Notes\n\n"
            "Remember the readable capture.\n",
            encoding="utf-8",
        )
        (capture_dir / "locked.md").write_text(
            "---\n"
            "title: Locked\n"
            "---\n\n"
            "## Notes\n\n"
            "This should report a read warning.\n",
            encoding="utf-8",
        )

        original_read_text = Path.read_text

        def flaky_read_text(path: Path, *args, **kwargs):
            if path.name == "locked.md":
                raise OSError("permission denied")
            return original_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", flaky_read_text):
            inbox = capture_inbox(root)
            summary = capture_review_summary(root)

        self.assertEqual(inbox["count"], 1)
        self.assertEqual(inbox["read_warning_count"], 1)
        self.assertEqual(
            inbox["read_warnings"],
            [{"capture": "raw/memory-captures/locked.md", "error": "permission denied"}],
        )
        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["read_warning_count"], 1)

    def test_render_capture_inbox_text_lists_actions_and_warnings(self):
        payload = {
            "project": "alpha",
            "warning_count": 1,
            "read_warning_count": 1,
            "read_warnings": [{"capture": "raw/memory-captures/locked.md", "error": "permission denied"}],
            "captures": [
                {
                    "title": "Alpha capture",
                    "path": "raw/memory-captures/alpha.md",
                    "project": "alpha",
                    "secret_warnings": ["OpenAI API key"],
                    "commands": {
                        "accept": "python3 link.py accept-capture alpha . --index 1",
                        "redact": "python3 link.py redact-capture alpha .",
                        "delete": "python3 link.py delete-capture alpha . --confirm",
                    },
                }
            ],
        }

        text = render_capture_inbox_text(payload)

        self.assertIn("Raw capture inbox", text)
        self.assertIn("Project: alpha", text)
        self.assertIn("1 readable capture · 1 with secret-looking warnings · 1 read warnings", text)
        self.assertIn("raw/memory-captures/locked.md: permission denied", text)
        self.assertIn("1. Alpha capture", text)
        self.assertIn("Secret-looking values: OpenAI API key", text)
        self.assertIn("Accept: python3 link.py accept-capture", text)
        self.assertIn("Redact: python3 link.py redact-capture", text)

    def test_render_accept_capture_text_reports_success_and_rejection(self):
        code, text = render_accept_capture_text({
            "accepted": True,
            "capture": "raw/memory-captures/alpha.md",
            "proposal_index": 1,
            "result": {
                "path": "wiki/memories/prefer-local-memory.md",
                "name": "prefer-local-memory",
                "project": "link",
            },
        })

        self.assertEqual(code, 0)
        self.assertIn("Capture proposal accepted", text)
        self.assertIn("Memory: wiki/memories/prefer-local-memory.md", text)
        self.assertIn("lnk review-memory prefer-local-memory", text)

        code, text = render_accept_capture_text({
            "accepted": False,
            "result": {
                "duplicate_candidates": [{
                    "title": "Prefer local memory",
                    "path": "wiki/memories/prefer-local-memory.md",
                }]
            },
        })

        self.assertEqual(code, 1)
        self.assertIn("Duplicate candidate: Prefer local memory", text)

    def test_render_redact_and_delete_capture_text(self):
        text = render_redact_capture_text({
            "redacted": True,
            "path": "raw/memory-captures/alpha.md",
            "labels": ["OpenAI API key"],
            "replacement_count": 2,
        })

        self.assertIn("Capture redacted", text)
        self.assertIn("Labels: OpenAI API key", text)
        self.assertIn("Replacement count: 2", text)

        text = render_redact_capture_text({
            "redacted": False,
            "path": "raw/memory-captures/alpha.md",
        })
        self.assertIn("No secret-looking values found.", text)

        code, text = render_delete_capture_text({
            "deleted": False,
            "path": "raw/memory-captures/alpha.md",
            "confirmation_required": True,
        })
        self.assertEqual(code, 1)
        self.assertIn("--confirm", text)

        code, text = render_delete_capture_text({
            "deleted": True,
            "path": "raw/memory-captures/alpha.md",
            "confirmation_required": False,
        })
        self.assertEqual(code, 0)
        self.assertIn("Capture deleted", text)

    def test_render_capture_session_text_lists_proposals(self):
        text = render_capture_session_text({
            "path": "raw/memory-captures/session.md",
            "project": "link",
            "secret_warnings": ["OpenAI API key"],
            "proposals": {
                "count": 1,
                "proposals": [{
                    "title": "Prefer release branches",
                    "confidence": "high",
                    "memory_type": "preference",
                    "scope": "project",
                    "project": "link",
                    "suggested_action": "remember",
                    "memory": "The user prefers release branches.",
                }],
            },
        })

        self.assertIn("Session captured", text)
        self.assertIn("Path: raw/memory-captures/session.md", text)
        self.assertIn("Project: link", text)
        self.assertIn("Secret-looking content: OpenAI API key", text)
        self.assertIn("1. Prefer release branches [high]", text)
        self.assertIn("Ask the user which proposals to remember", text)

        text = render_capture_session_text({
            "path": "raw/memory-captures/session.md",
            "proposals": {"count": 0, "proposals": []},
        })
        self.assertIn("No durable memory candidates found.", text)

    def test_render_session_end_text_lists_review_gated_proposals(self):
        text = render_session_end_text({
            "path": "raw/memory-captures/session-end.md",
            "project": "link",
            "secret_warnings": ["GitHub token"],
            "proposals": {
                "count": 1,
                "proposals": [{
                    "title": "Prefer review gated memory",
                    "confidence": "high",
                    "memory_type": "preference",
                    "scope": "project",
                    "project": "link",
                    "suggested_action": "remember",
                    "memory": "The user prefers review-gated memory.",
                }],
            },
        })

        self.assertIn("Link session end", text)
        self.assertIn("proposal-only session notes", text)
        self.assertIn("Path: raw/memory-captures/session-end.md", text)
        self.assertIn("Secret-looking content: GitHub token", text)
        self.assertIn("1. Prefer review gated memory [high]", text)
        self.assertIn("Do not save durable memory without approval.", text)


if __name__ == "__main__":
    unittest.main()


class CaptureInboxProposalPreviewTests(unittest.TestCase):
    def test_inbox_items_carry_proposal_previews(self):
        import tempfile
        from pathlib import Path
        from mcp_package.link_core.capture import capture_inbox

        root = Path(tempfile.mkdtemp(prefix="link-capture-preview-"))
        captures_dir = root / "raw" / "memory-captures"
        captures_dir.mkdir(parents=True)
        (captures_dir / "20260712T120000Z-agent-session-notes.md").write_text(
            "---\n"
            'title: "Agent session notes"\n'
            'date_captured: "2026-07-12T12:00:00Z"\n'
            "---\n\n"
            "## Notes\n\n"
            "User: from now on I only deploy to staging through the release script.\n"
            "User: also we decided to keep the memory layer deterministic.\n",
            encoding="utf-8",
        )

        payload = capture_inbox(root)
        records = payload["captures"]

        self.assertEqual(len(records), 1)
        item = records[0]
        self.assertGreaterEqual(item["proposal_count"], 1)
        first = item["proposals"][0]
        self.assertIn("release script", first["memory"])
        self.assertEqual(first["memory_type"], "preference")


class CaptureProvenanceTests(unittest.TestCase):
    def test_capture_records_proposal_source_and_trail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = write_session_capture(
                root,
                text="User: hi\n\nAssistant: here is a long helpful explanation.",
                source="session-end",
                proposal_text="User: from now on I only push to develop.",
                decision_trail=["Read the session: kept 4 messages.", "Stored 1 proposal."],
            )
            text = (root / record["path"]).read_text(encoding="utf-8")

        source = capture_proposal_source(text)
        self.assertIn("only push to develop", source)
        self.assertNotIn("helpful explanation", source)
        self.assertEqual(len(capture_decision_trail(text)), 2)

    def test_accept_mines_user_turns_not_assistant_prose(self):
        from mcp_package.link_core.memory import propose_memories_from_text

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = write_session_capture(
                root,
                text=(
                    "User: help me name branches.\n\n"
                    "Assistant: I always recommend feat/short-topic naming for clarity."
                ),
                source="session-end",
                proposal_text="User: from now on I only push to develop.",
            )

            def builder(notes, source, limit, project, curated=False):
                return propose_memories_from_text(notes, [], source=source, limit=limit)

            selection = capture_proposal_selection(
                root, record["path"], index=1, propose_memories=builder,
            )
            memory = str(selection["proposal"]["memory"])

        self.assertIn("only push to develop", memory)
        self.assertNotIn("feat/short-topic", memory)


class CaptureFilenameConcurrencyTests(unittest.TestCase):
    def test_capture_filename_never_collides_under_concurrency(self):
        import concurrent.futures

        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp)
            # Same timestamp AND title — the collision case real hooks hit
            # when several sessions end in the same second.
            def claim(_):
                return capture_filename("2026-07-12T18:00:00Z", "Agent session notes", raw)

            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
                paths = list(ex.map(claim, range(32)))

            # Every reservation is a distinct, actually-created file (checked
            # inside the tempdir, before it is cleaned up).
            self.assertEqual(len(paths), 32)
            self.assertEqual(len({p.name for p in paths}), 32)
            for p in paths:
                self.assertTrue(p.exists())


class CaptureDedupTests(unittest.TestCase):
    """2.1 inbox-zero behaviors: ledger, per-conversation refresh, dedup."""

    RULE = "I always plot the loss curve every 500 steps."
    OTHER = "I only merge to main with squash commits after CI passes."

    def _mined_memories(self, text):
        from mcp_package.link_core.memory import propose_memories_from_text
        return [str(p["memory"]) for p in propose_memories_from_text(text, [])["proposals"]]

    def test_dismissed_ledger_roundtrip_and_cap(self):
        from mcp_package.link_core.capture import (
            load_dismissed_fingerprints,
            record_dismissed_proposals,
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            added = record_dismissed_proposals(root, [self.RULE, self.RULE, ""])
            self.assertEqual(added, 1)
            entries = load_dismissed_fingerprints(root)
            self.assertEqual(len(entries), 1)
            memory = next(iter(entries.values()))["memory"]
            self.assertIn("loss curve", memory)

    def test_delete_capture_records_dismissals(self):
        from mcp_package.link_core.capture import load_dismissed_fingerprints
        from mcp_package.link_core.memory import proposal_fingerprint
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = write_session_capture(root, text=self.RULE, source="inline")
            result = delete_capture_file(root, str(payload["path"]), confirm=True)
            self.assertTrue(result["deleted"])
            self.assertGreaterEqual(int(result["dismissed_count"]), 1)
            mined = self._mined_memories(self.RULE)
            fingerprints = set(load_dismissed_fingerprints(root))
            self.assertIn(proposal_fingerprint(mined[0]), fingerprints)

    def test_dedup_cleanup_delete_skips_ledger(self):
        from mcp_package.link_core.capture import load_dismissed_fingerprints
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = write_session_capture(root, text=self.RULE, source="inline")
            delete_capture_file(root, str(payload["path"]), confirm=True, record_dismissals=False)
            self.assertEqual(load_dismissed_fingerprints(root), {})

    def test_write_session_capture_refreshes_conversation_in_place(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = write_session_capture(
                root, text=self.RULE, source="session-end",
                conversation_id="conv-abc", timestamp="2026-07-01T00:00:00Z",
            )
            second = write_session_capture(
                root, text=self.RULE + " " + self.OTHER, source="session-end",
                conversation_id="conv-abc", timestamp="2026-07-02T00:00:00Z",
            )
            self.assertEqual(first["path"], second["path"])
            self.assertTrue(second["refreshed"])
            files = list((root / "raw" / "memory-captures").glob("*.md"))
            self.assertEqual(len(files), 1)
            text = files[0].read_text(encoding="utf-8")
            self.assertIn('conversation: "conv-abc"', text)
            self.assertIn("squash commits", text)

    def test_different_conversations_keep_separate_captures(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_session_capture(root, text=self.RULE, source="session-end",
                                  conversation_id="conv-a", timestamp="2026-07-01T00:00:00Z")
            second = write_session_capture(root, text=self.OTHER, source="session-end",
                                           conversation_id="conv-b", timestamp="2026-07-02T00:00:00Z")
            self.assertFalse(second["refreshed"])
            files = list((root / "raw" / "memory-captures").glob("*.md"))
            self.assertEqual(len(files), 2)

    def test_pending_proposal_fingerprints_excludes_own_conversation(self):
        from mcp_package.link_core.capture import pending_proposal_fingerprints
        from mcp_package.link_core.memory import proposal_fingerprint
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_session_capture(root, text=self.RULE, source="session-end",
                                  conversation_id="conv-a", timestamp="2026-07-01T00:00:00Z")
            write_session_capture(root, text=self.OTHER, source="session-end",
                                  conversation_id="conv-b", timestamp="2026-07-02T00:00:00Z")
            pending = pending_proposal_fingerprints(root, exclude_conversation="conv-a")
            mined_other = proposal_fingerprint(self._mined_memories(self.OTHER)[0])
            mined_rule = proposal_fingerprint(self._mined_memories(self.RULE)[0])
            self.assertIn(mined_other, pending)
            self.assertNotIn(mined_rule, pending)

    def test_dedup_pending_captures_keeps_newest_and_removes_covered(self):
        from mcp_package.link_core.capture import dedup_pending_captures
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Two captures proposing the same rule (older is redundant), one
            # proposal-free capture, one unique capture.
            write_session_capture(root, text=self.RULE, source="session-end",
                                  timestamp="2026-07-01T00:00:00Z", title="Old duplicate")
            write_session_capture(root, text=self.RULE, source="session-end",
                                  timestamp="2026-07-03T00:00:00Z", title="New duplicate")
            write_session_capture(root, text="Nothing durable happened in this session at all.",
                                  source="session-end", timestamp="2026-07-02T00:00:00Z",
                                  title="No proposals")
            write_session_capture(root, text=self.OTHER, source="session-end",
                                  timestamp="2026-07-04T00:00:00Z", title="Unique")

            dry = dedup_pending_captures(root)
            self.assertFalse(dry["applied"])
            removable = {item["path"]: item["reason"] for item in dry["removable"]}
            self.assertEqual(len(removable), 2)
            self.assertIn("all_duplicates", removable.values())
            self.assertIn("no_proposals", removable.values())
            kept_paths = {item["path"] for item in dry["kept"]}
            self.assertTrue(any("new-duplicate" in path for path in kept_paths))
            self.assertTrue(all("old-duplicate" not in path for path in kept_paths))

            applied = dedup_pending_captures(root, apply=True)
            self.assertEqual(len(applied["removed"]), 2)
            remaining = list((root / "raw" / "memory-captures").glob("*.md"))
            self.assertEqual(len(remaining), 2)

    def test_dedup_respects_accepted_and_dismissed_fingerprints(self):
        from mcp_package.link_core.capture import (
            dedup_pending_captures,
            record_dismissed_proposals,
        )
        from mcp_package.link_core.memory import proposal_fingerprint
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_session_capture(root, text=self.RULE, source="session-end",
                                  timestamp="2026-07-01T00:00:00Z", title="Covered by accept")
            write_session_capture(root, text=self.OTHER, source="session-end",
                                  timestamp="2026-07-02T00:00:00Z", title="Covered by dismissal")
            accepted = {proposal_fingerprint(self._mined_memories(self.RULE)[0])}
            record_dismissed_proposals(root, [self._mined_memories(self.OTHER)[0]])
            report = dedup_pending_captures(root, accepted_fingerprints=accepted)
            self.assertEqual(report["removable_count"], 2)
            self.assertEqual(report["kept_count"], 0)

    def test_capture_records_hides_dismissed_proposals(self):
        from mcp_package.link_core.capture import record_dismissed_proposals
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_session_capture(
                root, text=self.RULE + " " + self.OTHER, source="session-end",
                timestamp="2026-07-01T00:00:00Z",
            )
            before = capture_records(root)[0]
            self.assertEqual(before["proposal_count"], 2)
            record_dismissed_proposals(root, [self._mined_memories(self.RULE)[0]])
            after = capture_records(root)[0]
            self.assertEqual(after["proposal_count"], 1)
            memories = " ".join(str(p["memory"]) for p in after["proposals"])
            self.assertNotIn("loss curve", memories)


class CapturePreviewLimitTests(unittest.TestCase):
    """The inbox preview must be able to show everything accept can reach."""

    def test_proposal_limit_uncaps_previews_and_import_previews_curated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "wiki").mkdir()
            lines = "\n".join(
                f"Always run check number {index} before shipping." for index in range(8)
            )
            write_session_capture(
                root, text=lines, source="import:test", title="Imported rules",
                source_type="import",
            )
            capped = capture_records(root)
            self.assertEqual(len(capped[0]["proposals"]), 3)
            full = capture_records(root, proposal_limit=50)
            # Curated preview: all 8 deliberate lines visible, not just the
            # chat-shaped subset.
            self.assertEqual(len(full[0]["proposals"]), 8)
