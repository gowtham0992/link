import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_tool_contract", ROOT / "scripts/check_tool_contract.py")
contract = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(contract)


class ToolContractTests(unittest.TestCase):
    def test_cli_contract_matches_expected_commands(self):
        self.assertEqual(contract.cli_commands(), contract.EXPECTED_CLI_COMMANDS)

    def test_mcp_contract_matches_expected_tools(self):
        self.assertEqual(contract.mcp_tools(), contract.EXPECTED_MCP_TOOLS)

    def test_repo_tool_contract_passes(self):
        self.assertEqual(contract.check_tool_contract(), [])

    def test_contract_reports_missing_mcp_docs(self):
        tmp = Path(tempfile.mkdtemp(prefix="link-tool-contract-"))
        try:
            (tmp / "mcp_package/link_mcp").mkdir(parents=True)
            (tmp / "mcp_package/link_core").mkdir(parents=True)
            (tmp / "mcp_package").mkdir(exist_ok=True)
            shutil.copy2(ROOT / "link.py", tmp / "link.py")
            shutil.copy2(ROOT / "mcp_package/link_core/cli_parser.py", tmp / "mcp_package/link_core/cli_parser.py")
            shutil.copy2(ROOT / "mcp_package/link_mcp/server.py", tmp / "mcp_package/link_mcp/server.py")

            (tmp / "docs").mkdir()
            cli_reference = "\n".join(f"`lnk {command}`" for command in sorted(contract.DOCS_CLI_COMMANDS))
            mcp_reference = "\n".join(
                tool for tool in sorted(contract.EXPECTED_MCP_TOOLS) if tool != "query_link"
            )
            (tmp / "docs/cli.html").write_text(cli_reference, encoding="utf-8")
            (tmp / "docs/mcp.html").write_text(mcp_reference, encoding="utf-8")
            (tmp / "mcp_package/README.md").write_text(mcp_reference, encoding="utf-8")

            findings = contract.check_tool_contract(tmp)
        finally:
            shutil.rmtree(tmp)

        self.assertTrue(any("query_link" in finding for finding in findings))


if __name__ == "__main__":
    unittest.main()
