import json
import os
import re
import shutil
import subprocess
import unittest

from aicomply.frameworks import control_index, load_frameworks
from tests.helpers import FRAMEWORKS, ROOT

GUARD = os.path.join(ROOT, "hooks", "compliance-guard.js")


class HookTest(unittest.TestCase):
    def test_every_advisory_cites_a_real_control(self):
        with open(GUARD, encoding="utf-8") as f:
            src = f.read()
        ids = set(re.findall(r"ctrl\('([^']+)'\)", src)) | set(re.findall(r"^\s+'([^']+)':", src, re.M))
        known = control_index(load_frameworks(FRAMEWORKS))
        self.assertTrue(ids)
        self.assertEqual(sorted(i for i in ids if i not in known), [])

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_guard_blocks_a_secret_written_to_the_repo(self):
        token = "ghp" + "_" + "a" * 36  # built at runtime so no token-shaped literal sits in the repo
        payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "/repo/.github/ci.yml", "content": f"token: {token}"}})
        proc = subprocess.run(["node", GUARD], input=payload, capture_output=True, text=True)
        self.assertIn("A.8.24-SECRETS", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
