"""Every test run gets a home folder of its own.

Installing one agent's hooks can also write another agent's file at its
default place in the home folder (Kiro's agent profile, Gemini CLI's
settings). A test that passed a temporary path for the first file still
wrote a fixture command into the developer's real ~/.kiro/agents/link.json.
Set here, before any test module is imported, so no test can reach the
real home by forgetting to move it.
"""
import atexit
import os
import shutil
import tempfile

TEST_HOME = tempfile.mkdtemp(prefix="link-test-home-")
os.environ["HOME"] = TEST_HOME
os.environ["USERPROFILE"] = TEST_HOME
for _name in ("CODEX_HOME", "COPILOT_HOME", "LINK_WORKSPACE"):
    os.environ.pop(_name, None)
atexit.register(shutil.rmtree, TEST_HOME, True)
