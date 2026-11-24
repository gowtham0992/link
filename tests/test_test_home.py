"""The suite runs in a home folder of its own (tests/conftest.py)."""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_package"))

from link_core.agent_hooks import build_agent_hooks_payload  # noqa: E402


@unittest.skipIf(os.name == "nt", "the account's home comes from pwd on POSIX")
class TestHomeTests(unittest.TestCase):
    def test_no_test_sees_the_real_home(self):
        import pwd  # noqa: PLC0415

        self.assertNotEqual(Path.home().resolve(), Path(pwd.getpwuid(os.getuid()).pw_dir).resolve())

    def test_an_agents_second_hook_file_lands_in_the_test_home(self):
        # Kiro's install also writes its agent profile at the default place,
        # whatever path the first file was given.
        settings = Path.home() / "elsewhere" / "link.json"
        payload = build_agent_hooks_payload(target=Path("/home/x/link"), agent="kiro",
                                            runtime_script=Path("/opt/link/link.py"), python_cmd="python3",
                                            settings_path=str(settings), write=True)
        profile = Path(str(payload["companions"][0]["settings_path"]))  # type: ignore[index]
        self.assertTrue(profile.is_relative_to(Path.home()), profile)
        self.assertTrue(profile.exists())


if __name__ == "__main__":
    unittest.main()
