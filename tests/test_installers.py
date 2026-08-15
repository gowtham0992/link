import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLERS = [
    ROOT / "integrations/antigravity/install.sh",
    ROOT / "integrations/claude-code/install.sh",
    ROOT / "integrations/codex/install.sh",
    ROOT / "integrations/copilot/install.sh",
    ROOT / "integrations/cursor/install.sh",
    ROOT / "integrations/kiro/install.sh",
    ROOT / "integrations/vscode/install.sh",
]
POWERSHELL_INSTALLERS = [
    ROOT / "integrations/antigravity/install.ps1",
    ROOT / "integrations/claude-code/install.ps1",
    ROOT / "integrations/codex/install.ps1",
    ROOT / "integrations/copilot/install.ps1",
    ROOT / "integrations/cursor/install.ps1",
    ROOT / "integrations/kiro/install.ps1",
    ROOT / "integrations/vscode/install.ps1",
]


class InstallerTests(unittest.TestCase):
    def test_scaffold_does_not_use_break_system_packages(self):
        scaffold = (ROOT / "integrations/_shared/scaffold.sh").read_text(encoding="utf-8")

        self.assertNotIn("--break-system-packages", scaffold)
        self.assertIn(".link-mcp-venv", scaffold)
        self.assertIn(".link-mcp-python", scaffold)
        self.assertIn("LINK_MCP_INSTALLED=false", scaffold)
        self.assertIn('[ "$LINK_MCP_INSTALLED" = true ]', scaffold)

    def test_scaffold_installs_short_global_link_command(self):
        scaffold = (ROOT / "integrations/_shared/scaffold.sh").read_text(encoding="utf-8")

        self.assertIn('LINK_CLI_BIN="$LINK_CLI_DIR/lnk"', scaffold)
        self.assertIn('LEGACY_LINK_CLI_BIN="$LINK_CLI_DIR/link"', scaffold)
        self.assertIn("Removed old Link wrapper", scaffold)
        self.assertIn("Link command wrapper", scaffold)
        self.assertIn("not overwriting", scaffold)
        self.assertIn("lnk health", scaffold)
        self.assertIn("LINK_CLI_COMMAND=lnk exec python3", scaffold)
        self.assertIn('if [ "$MODE" = "--project" ]', scaffold)
        self.assertIn('python3 "$TARGET_DIR/link.py" doctor --fix "$TARGET_DIR"', scaffold)
        self.assertNotIn('cp "$LINK_ROOT/wiki/index.md"', scaffold)

    def test_scaffold_project_mode_uses_absolute_target(self):
        scaffold = (ROOT / "integrations/_shared/scaffold.sh").read_text(encoding="utf-8")

        self.assertIn('TARGET_DIR="$(pwd)"', scaffold)
        self.assertNotIn('TARGET_DIR="."', scaffold)

    def test_powershell_scaffold_uses_venv_and_short_link_command(self):
        scaffold = (ROOT / "integrations/_shared/scaffold.ps1").read_text(encoding="utf-8")

        self.assertNotIn("--break-system-packages", scaffold)
        self.assertIn(".link-mcp-venv", scaffold)
        self.assertIn(".link-mcp-python", scaffold)
        self.assertIn("lnk.cmd", scaffold)
        self.assertIn("link.cmd", scaffold)
        self.assertIn("Removed old Link wrapper", scaffold)
        self.assertIn("Link command wrapper", scaffold)
        self.assertIn("set LINK_CLI_COMMAND=lnk", scaffold)
        self.assertIn('$env:LINK_CLI_COMMAND = "lnk"', scaffold)
        self.assertIn("Get-Command py", scaffold)
        self.assertIn("-m venv", scaffold)
        self.assertIn("doctor --fix $TargetDir", scaffold)
        self.assertNotIn('Copy-LinkFile (Join-Path $LinkRoot "wiki\\index.md")', scaffold)

    def test_installers_read_resolved_mcp_python_marker(self):
        for installer in INSTALLERS:
            with self.subTest(installer=installer.name):
                text = installer.read_text(encoding="utf-8")
                self.assertIn("MCP_PYTHON", text)
                self.assertIn(".link-mcp-python", text)

        for installer in POWERSHELL_INSTALLERS:
            with self.subTest(installer=installer.name):
                text = installer.read_text(encoding="utf-8")
                self.assertIn("Link-ReadMcpPython", text)
                self.assertIn("scaffold.ps1", text)

    def test_installers_print_mode_specific_next_steps(self):
        instructions = (ROOT / "integrations/_shared/instructions.sh").read_text(encoding="utf-8")

        self.assertIn("link_print_next_steps()", instructions)
        self.assertIn('if [ "$mode" = "--project" ]; then', instructions)
        self.assertIn("View wiki: python3 link.py serve", instructions)
        self.assertIn("View wiki: lnk serve", instructions)
        self.assertIn("Print starter prompts: python3 link.py next", instructions)
        self.assertIn("Print starter prompts: lnk next", instructions)
        self.assertIn("Try in your agent:", instructions)
        self.assertIn("is Link ready?", instructions)
        self.assertIn("start with Link before we continue", instructions)
        self.assertIn("ingest raw/<file> into Link", instructions)
        self.assertIn("what does Link know about me?", instructions)
        self.assertIn("what does Link remember about this project?", instructions)

        for installer in INSTALLERS:
            with self.subTest(installer=installer.name):
                text = installer.read_text(encoding="utf-8")
                self.assertIn('. "$SCRIPT_DIR/../_shared/instructions.sh"', text)
                self.assertIn('link_print_next_steps "$MODE"', text)

        instructions_ps1 = (ROOT / "integrations/_shared/instructions.ps1").read_text(encoding="utf-8")
        self.assertIn("function Link-PrintNextSteps", instructions_ps1)
        self.assertIn("py link.py next", instructions_ps1)
        self.assertIn("Try in your agent:", instructions_ps1)
        self.assertIn("is Link ready?", instructions_ps1)

        for installer in POWERSHELL_INSTALLERS:
            with self.subTest(installer=installer.name):
                text = installer.read_text(encoding="utf-8")
                self.assertIn("instructions.ps1", text)
                self.assertIn("Link-PrintNextSteps", text)

    def test_windows_installers_are_documented(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        integrations = (ROOT / "integrations/README.md").read_text(encoding="utf-8")
        getting_started = (ROOT / "docs/getting-started.html").read_text(encoding="utf-8")
        mcp = (ROOT / "docs/mcp.html").read_text(encoding="utf-8")

        for name in ["codex", "kiro", "claude-code", "cursor", "copilot", "vscode", "antigravity"]:
            self.assertIn(f".\\integrations\\{name}\\install.ps1", readme)
            self.assertIn(f".\\integrations\\{name}\\install.ps1", integrations)
            self.assertIn(f".\\integrations\\{name}\\install.ps1", getting_started)
            self.assertIn(f".\\integrations\\{name}\\install.ps1", mcp)

    def test_integration_maintainer_checklist_is_documented(self):
        integrations = (ROOT / "integrations/README.md").read_text(encoding="utf-8")
        contributing = (ROOT / "docs/contributing.html").read_text(encoding="utf-8")

        for expected in [
            "Maintainer checklist",
            "Preserve existing user instructions",
            "CLI and MCP independent from the web viewer",
            "PowerShell",
            "tests/test_installers.py",
        ]:
            self.assertIn(expected, integrations)

        self.assertIn("integrations/README.md", contributing)
        self.assertIn("CLI/MCP independent from the web viewer", contributing)

    def test_ci_checks_powershell_installer_syntax(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertIn("Check PowerShell syntax", workflow)
        self.assertIn("[scriptblock]::Create", workflow)
        self.assertIn("*.ps1", workflow)

    def test_codex_and_kiro_update_existing_mcp_registration(self):
        codex = (ROOT / "integrations/codex/install.sh").read_text(encoding="utf-8")
        kiro = (ROOT / "integrations/kiro/install.sh").read_text(encoding="utf-8")

        self.assertIn("pattern.sub(block, text)", codex)
        self.assertNotIn("! grep -q '\\[mcp_servers.link\\]'", codex)
        self.assertNotIn("Link MCP already registered", kiro)

    def test_codex_mcp_registration_pattern_compiles_and_replaces_block(self):
        codex = (ROOT / "integrations/codex/install.sh").read_text(encoding="utf-8")
        match = re.search(r"pattern = re\.compile\((r\"[^\"]+\")\)", codex)
        self.assertIsNotNone(match)

        pattern = re.compile(ast.literal_eval(match.group(1)))
        existing_config = (
            '[mcp_servers.link]\n'
            'command = "python3"\n'
            'args = ["-m", "link_mcp", "--wiki", "/old/wiki"]\n'
            '\n'
            '[profiles.default]\n'
            'model = "gpt-5"\n'
        )
        replacement = (
            '[mcp_servers.link]\n'
            'command = "/Users/g/.link-mcp-venv/bin/python"\n'
            'args = ["-m", "link_mcp", "--wiki", "/Users/g/link/wiki"]\n'
        )

        updated = pattern.sub(replacement, existing_config)

        self.assertIn('command = "/Users/g/.link-mcp-venv/bin/python"', updated)
        self.assertNotIn("/old/wiki", updated)
        self.assertIn("[profiles.default]", updated)


if __name__ == "__main__":
    unittest.main()


class PipCliPackagingTests(unittest.TestCase):
    """pip install link-mcp must yield the full lnk CLI, not just the server."""

    def test_wheel_declares_the_lnk_console_script(self):
        pyproject = (ROOT / "mcp_package" / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('lnk = "link_cli:main"', pyproject)
        # Staged locally by hatch_build.py: a "../" reference here fails
        # when the wheel is built from an extracted sdist.
        for shipped in ('"link_cli.py" = "link_cli.py"', '"serve.py" = "serve.py"',
                        '"LINK.md" = "LINK.md"'):
            self.assertIn(shipped, pyproject)

    def test_runtime_copy_falls_back_to_link_cli(self):
        import tempfile
        from pathlib import Path as P
        from mcp_package.link_core.demo import copy_runtime_files
        with tempfile.TemporaryDirectory() as temp:
            source = P(temp) / "site-packages"
            source.mkdir()
            (source / "link_cli.py").write_text("# cli\n", encoding="utf-8")
            (source / "LINK.md").write_text("# schema\n", encoding="utf-8")
            target = P(temp) / "ws"
            copy_runtime_files(source, target)
            self.assertTrue((target / "link.py").exists(),
                            "wheel installs must plant link.py from link_cli.py")


class LinkBarBundlingTests(unittest.TestCase):
    """Issue #58: the shipped app crashed at launch everywhere but the build
    host, because SPM's Bundle.module accessor fatalErrors when it cannot
    find its resource bundle - and it only looks at the app root and the
    build machine's absolute path."""

    def test_no_source_touches_bundle_module(self):
        for swift in (ROOT / "apps/LinkBar/Sources/LinkBar").glob("*.swift"):
            for number, line in enumerate(swift.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("//", 1)[0]  # the explanation may name it
                self.assertNotIn(
                    "Bundle.module", code,
                    f"{swift.name}:{number} touches Bundle.module, which "
                    "fatalErrors in a packaged app (issue #58)",
                )

    def test_packaged_launch_harness_exists_and_runs_in_ci(self):
        """The static checks above cannot prove the packaged app launches.

        Only running the artifact with the build environment hidden can,
        so that harness must exist and must be wired into the macOS job -
        the class of bug in #58 is invisible everywhere else.
        """
        smoke = ROOT / "scripts" / "smoke_linkbar_packaged.py"
        self.assertTrue(smoke.is_file(), "packaged-launch smoke harness is missing")
        body = smoke.read_text(encoding="utf-8")
        self.assertIn("_LinkBar.bundle", body, "the harness must hide build resource bundles")
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("scripts/smoke_linkbar_packaged.py", workflow,
                      "the harness must run in CI, not just exist")

    def test_resource_copy_failure_fails_the_build(self):
        script = (ROOT / "apps/LinkBar/Scripts/bundle.sh").read_text(encoding="utf-8")
        line = next(
            entry for entry in script.splitlines()
            if "LinkBar_LinkBar.bundle" in entry and entry.strip().startswith("cp -R")
        )
        self.assertNotIn("|| true", line, "a failed resource copy must fail the build")


class SdistSelfContainedTests(unittest.TestCase):
    """`python -m build` builds the wheel from the extracted sdist, where no
    parent directory exists. Referencing ../link.py there broke CI, so the
    staging hook must keep the sdist self-contained."""

    def test_build_hook_stages_runtime_files_locally(self):
        pyproject = (ROOT / "mcp_package" / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("[tool.hatch.build.hooks.custom]", pyproject)
        self.assertIn('path = "hatch_build.py"', pyproject)
        force_include = pyproject.split("[tool.hatch.build.targets.wheel.force-include]", 1)[1]
        force_include = force_include.split("[", 1)[0]
        self.assertNotIn(
            "../", force_include,
            "force-include must not reach outside the package: it fails when "
            "the wheel is built from an extracted sdist",
        )

    def test_hook_refuses_to_build_without_the_runtime_files(self):
        import shutil
        import sys as _sys
        import tempfile
        from pathlib import Path as P
        _sys.path.insert(0, str(ROOT / "mcp_package"))
        from hatch_build import STAGED_RUNTIME_FILES, StageRuntimeFilesHook
        with tempfile.TemporaryDirectory() as temp:
            package = P(temp) / "pkg"        # no parent runtime files, none staged
            package.mkdir(parents=True)
            hook = StageRuntimeFilesHook.__new__(StageRuntimeFilesHook)
            hook.__dict__["root"] = str(package)
            with self.assertRaises(FileNotFoundError):
                hook.initialize("standard", {})
            # With the files staged (the sdist case) it proceeds.
            for staged in STAGED_RUNTIME_FILES.values():
                (package / staged).write_text("x", encoding="utf-8")
            hook.initialize("standard", {})
            shutil.rmtree(package, ignore_errors=True)
