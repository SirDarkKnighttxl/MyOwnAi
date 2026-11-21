import pathlib
import subprocess
import tempfile
import unittest

from noxd import tools
from noxd.policy import Policy


class GitToolTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.run_git("init", "--quiet")
        self.run_git("config", "user.name", "NOX Test")
        self.run_git("config", "user.email", "nox@example.invalid")
        (self.repo / "tracked.txt").write_text("initial\n", encoding="utf-8")
        self.run_git("add", "tracked.txt")
        self.run_git("commit", "--quiet", "-m", "initial commit")
        self.policy = Policy({
            "policy": {
                "mode": "auto",
                "scope_roots": [str(self.root)],
                "allowed_bins": ["git"],
            }
        })

    def tearDown(self):
        self.temporary.cleanup()

    def run_git(self, *args):
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_status_diff_and_log_return_real_output(self):
        (self.repo / "tracked.txt").write_text("changed\n", encoding="utf-8")

        status = tools.dispatch(
            self.policy, "git_status", {"cwd": str(self.repo)}
        )
        diff = tools.dispatch(
            self.policy, "git_diff", {"cwd": str(self.repo)}
        )
        log = tools.dispatch(
            self.policy, "git_log", {"cwd": str(self.repo), "limit": 1}
        )

        self.assertTrue(status["ok"])
        self.assertIn("tracked.txt", status["status"])
        self.assertIn("-initial", diff["diff"])
        self.assertIn("+changed", diff["diff"])
        self.assertIn("initial commit", log["log"])

    def test_commit_requires_message_and_commits_staged_changes(self):
        (self.repo / "tracked.txt").write_text("committed\n", encoding="utf-8")
        self.run_git("add", "tracked.txt")

        missing = tools.dispatch(
            self.policy, "git_commit", {"cwd": str(self.repo)}
        )
        committed = tools.dispatch(
            self.policy,
            "git_commit",
            {"cwd": str(self.repo), "message": "update tracked file"},
        )
        log = tools.dispatch(
            self.policy, "git_log", {"cwd": str(self.repo), "limit": 1}
        )

        self.assertFalse(missing["ok"])
        self.assertIn("message is required", missing["error"])
        self.assertTrue(committed["ok"])
        self.assertIn("update tracked file", log["log"])

    def test_repository_root_must_remain_in_policy_scope(self):
        child = self.repo / "child"
        child.mkdir()
        restricted = Policy({
            "policy": {
                "mode": "auto",
                "scope_roots": [str(child)],
                "allowed_bins": ["git"],
            }
        })

        result = tools.dispatch(
            restricted, "git_status", {"cwd": str(child)}
        )

        self.assertFalse(result["ok"])
        self.assertIn("outside scope", result["error"])

    def test_git_binary_passes_through_command_policy(self):
        blocked = Policy({
            "policy": {
                "mode": "auto",
                "scope_roots": [str(self.root)],
                "allowed_bins": ["python"],
            }
        })

        result = tools.dispatch(
            blocked, "git_status", {"cwd": str(self.repo)}
        )

        self.assertFalse(result["ok"])
        self.assertIn("binary not in allowlist: git", result["error"])


if __name__ == "__main__":
    unittest.main()
