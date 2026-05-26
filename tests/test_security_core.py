import unittest
import tempfile
from pathlib import Path

from mcp_package.link_core.security import (
    clean_text_input,
    find_sensitive_filenames,
    find_sensitive_values,
    iter_scannable_files,
    redact_secret_values,
    secret_file_warnings,
    secret_value_warnings,
)


class SecurityCoreTests(unittest.TestCase):
    def test_clean_text_input_strips_bounds_and_handles_none(self):
        self.assertEqual(clean_text_input(None), "")
        self.assertEqual(clean_text_input("  hello  "), "hello")
        self.assertEqual(clean_text_input("  hello world  ", max_len=5), "hello")
        self.assertEqual(clean_text_input(123, max_len=2), "12")

    def test_secret_warnings_and_redaction(self):
        fake_key = "sk-" + "a" * 48

        warnings = secret_value_warnings(f"token {fake_key}")
        redacted, labels, count = redact_secret_values(f"token {fake_key}")

        self.assertEqual(warnings, ["OpenAI API key"])
        self.assertEqual(labels, ["OpenAI API key"])
        self.assertEqual(count, 1)
        self.assertNotIn(fake_key, redacted)
        self.assertIn("[redacted-secret]", redacted)

    def test_secret_warnings_cover_common_provider_tokens(self):
        text = "\n".join(
            [
                "hf_" + "A" * 24,
                "npm_" + "b" * 24,
                "vercel_" + "C" * 24,
                "AccountKey=" + "D" * 48,
                "DD_API_KEY=" + "a" * 32,
                "https://" + ("b" * 32) + "@sentry.example.com/42",
                "eyJ" + ("a" * 16) + "." + ("b" * 16) + "." + ("c" * 16),
                '{"auths":{"registry.example.com":{"auth":"' + ("d" * 24) + '"}}}',
            ]
        )

        warnings = secret_value_warnings(text)

        self.assertEqual(
            warnings,
            [
                "Hugging Face token",
                "npm token",
                "Vercel token",
                "Azure storage account key",
                "Datadog API key",
                "Sentry DSN",
                "JWT token",
                "Docker registry auth",
            ],
        )

    def test_anthropic_key_is_not_double_reported_as_openai(self):
        fake_key = "sk-ant-" + "a" * 48

        warnings = secret_value_warnings(f"token {fake_key}")

        self.assertEqual(warnings, ["Anthropic API key"])

    def test_secret_file_warnings_streams_across_chunks(self):
        tmp = Path(tempfile.mkdtemp(prefix="link-security-core-"))
        fake_key = "sk-" + "a" * 48
        path = tmp / "large-ish-source.md"
        path.write_text("safe text\n" + ("x" * 40) + " " + fake_key + "\n", encoding="utf-8")

        warnings = secret_file_warnings(path, chunk_size=16, tail_size=80)

        self.assertEqual(warnings, ["OpenAI API key"])

    def test_secret_file_warnings_handles_missing_file(self):
        tmp = Path(tempfile.mkdtemp(prefix="link-security-core-"))

        warnings = secret_file_warnings(tmp / "missing.md")

        self.assertEqual(warnings, [])

    def test_sensitive_filename_scan_skips_configured_dirs(self):
        root = Path(tempfile.mkdtemp(prefix="link-sensitive-name-"))
        (root / "raw").mkdir()
        (root / "raw" / ".env").write_text("secret\n", encoding="utf-8")
        (root / ".git").mkdir()
        (root / ".git" / ".env").write_text("ignored\n", encoding="utf-8")

        matches = find_sensitive_filenames(
            root,
            skip_dirs={".git"},
            patterns=(".env", "*.key"),
        )

        self.assertEqual(matches, ["raw/.env"])

    def test_iter_scannable_files_skips_binary_suffixes(self):
        root = Path(tempfile.mkdtemp(prefix="link-scannable-"))
        (root / "note.md").write_text("text\n", encoding="utf-8")
        (root / "image.png").write_bytes(b"png")
        (root / "node_modules").mkdir()
        (root / "node_modules" / "note.md").write_text("ignored\n", encoding="utf-8")

        files = iter_scannable_files(root, skip_dirs={"node_modules"}, skip_suffixes={".png"})

        self.assertEqual([path.name for path in files], ["note.md"])

    def test_find_sensitive_values_reports_matches(self):
        root = Path(tempfile.mkdtemp(prefix="link-sensitive-values-"))
        fake_key = "sk-" + ("A" * 24)
        (root / "note.md").write_text(f"token {fake_key}\n", encoding="utf-8")

        matches, read_errors = find_sensitive_values(root, skip_dirs=set(), skip_suffixes=set())

        self.assertEqual(matches, ["note.md (OpenAI API key)"])
        self.assertEqual(read_errors, [])


if __name__ == "__main__":
    unittest.main()
