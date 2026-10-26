import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "prepare_release", ROOT / "scripts/prepare_release.py"
)
prepare_release = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = prepare_release
SPEC.loader.exec_module(prepare_release)


def make_release_root() -> Path:
    root = Path(tempfile.mkdtemp(prefix="link-release-test-"))
    (root / "mcp_package/link_mcp").mkdir(parents=True)
    (root / "mcp_package/link_core").mkdir(parents=True)
    (root / "mcp_package/pyproject.toml").write_text(
        '[project]\nname = "link-mcp"\nversion = "1.0.5"\n',
        encoding="utf-8",
    )
    (root / "mcp_package/link_mcp/__init__.py").write_text(
        '__version__ = "1.0.5"\n',
        encoding="utf-8",
    )
    (root / "mcp_package/link_core/version.py").write_text(
        'LINK_VERSION = "1.0.5"\n',
        encoding="utf-8",
    )
    (root / "mcp_package/server.json").write_text(
        json.dumps(
            {
                "version": "1.0.5",
                "packages": [
                    {
                        "identifier": "link-mcp",
                        "version": "1.0.5",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(
        (
            "# Changelog\n\n"
            "## [Unreleased]\n\n"
            "### Added\n\n"
            "- Added release automation.\n\n"
            "## [1.0.5] - 2026-05-02\n\n"
            "### Added\n\n"
            "- Added previous release.\n"
        ),
        encoding="utf-8",
    )
    return root


class PrepareReleaseTests(unittest.TestCase):
    def test_prepare_release_updates_versions_and_changelog(self):
        root = make_release_root()

        changed = prepare_release.prepare_release(root, "v1.0.6", "2026-05-04")

        self.assertEqual(
            {path.relative_to(root).as_posix() for path in changed},
            {
                "mcp_package/pyproject.toml",
                "mcp_package/link_mcp/__init__.py",
                "mcp_package/link_core/version.py",
                "mcp_package/server.json",
                "CHANGELOG.md",
            },
        )
        self.assertIn('version = "1.0.6"', (root / "mcp_package/pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn('__version__ = "1.0.6"', (root / "mcp_package/link_mcp/__init__.py").read_text(encoding="utf-8"))
        self.assertIn('LINK_VERSION = "1.0.6"', (root / "mcp_package/link_core/version.py").read_text(encoding="utf-8"))

        server = json.loads((root / "mcp_package/server.json").read_text(encoding="utf-8"))
        self.assertEqual(server["version"], "1.0.6")
        self.assertEqual(server["packages"][0]["version"], "1.0.6")

        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [Unreleased]\n\n## [1.0.6] - 2026-05-04", changelog)
        self.assertIn("- Added release automation.", changelog)

    def test_prepare_release_dry_run_does_not_write(self):
        root = make_release_root()
        before = (root / "mcp_package/pyproject.toml").read_text(encoding="utf-8")

        changed = prepare_release.prepare_release(root, "1.0.6", "2026-05-04", dry_run=True)

        self.assertEqual(len(changed), 5)
        self.assertEqual((root / "mcp_package/pyproject.toml").read_text(encoding="utf-8"), before)

    def test_prepare_release_rejects_non_incrementing_version(self):
        root = make_release_root()

        with self.assertRaisesRegex(ValueError, "must be greater"):
            prepare_release.prepare_release(root, "1.0.5", "2026-05-04")

    def test_prepare_release_rejects_empty_unreleased_notes(self):
        root = make_release_root()
        (root / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [Unreleased]\n\n## [1.0.5] - 2026-05-02\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "no bullet notes"):
            prepare_release.prepare_release(root, "1.0.6", "2026-05-04")

    def test_prepare_release_rejects_bad_date(self):
        root = make_release_root()

        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            prepare_release.prepare_release(root, "1.0.6", "05/04/2026")

    def test_release_commands_use_version_tag(self):
        commands = prepare_release.release_commands("v1.0.6")

        self.assertIn('git tag -a v1.0.6 -m "v1.0.6"', commands)
        self.assertTrue(any("glob('*.egg-info')" in command for command in commands))
        self.assertTrue(any("twine upload dist/link_mcp-1.0.6*" in command and ".link-release-venv" in command
                            for command in commands))
        # Protected main: the bump goes through a PR before the tag.
        self.assertLess(next(i for i, c in enumerate(commands) if "gh pr create" in c),
                        next(i for i, c in enumerate(commands) if c.startswith("git tag")))
        self.assertIn("mcp-publisher validate", commands)
        self.assertIn("mcp-publisher publish", commands)
        # The release commit stages what the script changed, never a stray
        # untracked file sitting in the checkout.
        commit = next(c for c in commands if "git commit" in c)
        self.assertIn("git add -u", commit)
        self.assertNotIn("git add -A", commit)
        self.assertNotIn("git add .", commit)



class ReleaseGuardTests(unittest.TestCase):
    def _root_with_homepage(self) -> Path:
        root = make_release_root()
        (root / "docs").mkdir(exist_ok=True)
        (root / "docs" / "index.html").write_text(
            'New \\u00b7 Link 1.0.5 is out \\u2014 old words <span>x</span> tag/v1.0.5\\"', encoding="utf-8")
        return root

    def test_missing_banner_words_are_an_error(self):
        root = self._root_with_homepage()
        with self.assertRaisesRegex(ValueError, "--banner"):
            prepare_release.prepare_release(root, "1.0.6", "2026-09-26")
        changed = prepare_release.prepare_release(root, "1.0.6", "2026-09-26", keep_banner=True, dry_run=True)
        self.assertTrue(changed)

    def test_linkbar_version_is_bumped_in_both_files(self):
        root = make_release_root()
        swift = root / prepare_release.LINKBAR_SWIFT
        bundle = root / prepare_release.LINKBAR_BUNDLE
        swift.parent.mkdir(parents=True)
        bundle.parent.mkdir(parents=True)
        swift.write_text('    static let version = "1.4.0"\n', encoding="utf-8")
        bundle.write_text("<key>CFBundleShortVersionString</key><string>1.4.0</string>\n"
                          "<key>CFBundleVersion</key><string>1.4.0</string>\n", encoding="utf-8")
        prepare_release.prepare_release(root, "1.0.6", "2026-09-26", linkbar_version="1.5.0")
        self.assertIn('"1.5.0"', swift.read_text(encoding="utf-8"))
        self.assertEqual(bundle.read_text(encoding="utf-8").count("1.5.0"), 2)

    def test_tap_commands_cover_formula_and_cask(self):
        lines = prepare_release.tap_commands("4.0.0", "1.5.0")
        joined = "\n".join(lines)
        self.assertIn("refs/tags/v4.0.0.tar.gz", joined)
        self.assertIn("LinkBar-1.5.0.zip", joined)
        self.assertIn("three lines", joined)


if __name__ == "__main__":
    unittest.main()
