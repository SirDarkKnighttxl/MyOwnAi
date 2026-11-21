import pathlib
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from noxd import tools
from noxd.policy import Policy


class RunPythonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.work = pathlib.Path(self.temporary.name)
        self.work_patch = patch.object(tools, "WORK", self.work)
        self.work_patch.start()
        self.policy = Policy({
            "policy": {
                "mode": "auto",
                "scope_roots": [str(self.work)],
                "allowed_bins": [pathlib.Path(sys.executable).stem],
            }
        })

    def tearDown(self):
        self.work_patch.stop()
        self.temporary.cleanup()

    def test_captures_streams_and_exit_code_from_temp_file(self):
        result = tools.dispatch(
            self.policy,
            "run_python",
            {
                "code": (
                    "import sys\n"
                    "print('standard output')\n"
                    "print('standard error', file=sys.stderr)\n"
                    "raise SystemExit(7)\n"
                ),
                "timeout": 5,
            },
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], 7)
        self.assertEqual(result["stdout"], "standard output\n")
        self.assertEqual(result["stderr"], "standard error\n")
        self.assertFalse(result["timed_out"])
        self.assertEqual(list(self.work.glob("nox-python-*.py")), [])

    def test_busy_loop_is_killed_by_parent_timeout(self):
        started = time.monotonic()

        result = tools.dispatch(
            self.policy,
            "run_python",
            {"code": "while True:\n    pass\n", "timeout": 0.2},
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["timed_out"])
        self.assertIn("process tree killed", result["error"])
        self.assertLess(time.monotonic() - started, 5)

    def test_code_body_is_not_shell_interpolated(self):
        marker = self.work / "shell-marker.txt"
        source = "print('literal: && echo shell-marker.txt > shell-marker.txt')"

        result = tools.dispatch(
            self.policy,
            "run_python",
            {"code": source, "timeout": 5},
        )

        self.assertTrue(result["ok"])
        self.assertIn("literal: && echo", result["stdout"])
        self.assertFalse(marker.exists())

    def test_python_binary_is_policy_gated(self):
        blocked = Policy({
            "policy": {
                "mode": "auto",
                "scope_roots": [str(self.work)],
                "allowed_bins": ["git"],
            }
        })

        result = tools.dispatch(
            blocked,
            "run_python",
            {"code": "print('blocked')"},
        )

        self.assertFalse(result["ok"])
        self.assertIn("binary not in allowlist", result["error"])
        self.assertEqual(list(self.work.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
