import asyncio
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from noxd import agent, approvals
from noxd.policy import Policy


SAMPLING = {
    "temp": 0.7,
    "top_p": 0.9,
    "top_k": 40,
    "min_p": 0.05,
    "repeat_penalty": 1.05,
    "max_tokens": 128,
}


class FakeResponse:
    def __init__(self, message):
        self.message = message

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": self.message}]}


class SequenceClient:
    def __init__(self, messages):
        self.messages = iter(messages)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, _url, json):
        return FakeResponse(next(self.messages))


class ApprovalPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.work = pathlib.Path(self.temporary.name) / "work"
        self.outside = pathlib.Path(self.temporary.name) / "outside"
        self.work.mkdir()
        self.outside.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def make_policy(self, mode):
        return Policy({
            "policy": {
                "mode": mode,
                "scope_roots": [str(self.work)],
                "allowed_bins": [],
            }
        })

    def test_ask_requires_each_command_until_binary_has_session_grant(self):
        policy = self.make_policy("ask")
        command = "python -V"

        self.assertTrue(policy.needs_command_approval(command, str(self.work)))
        policy.grant_command(command, str(self.work), for_session=False)
        self.assertTrue(policy.check_command(command, str(self.work)))
        self.assertTrue(policy.needs_command_approval(command, str(self.work)))

        policy.grant_command(command, str(self.work), for_session=True)
        self.assertFalse(
            policy.needs_command_approval("python other.py", str(self.outside))
        )
        self.assertTrue(policy.check_command("python other.py", str(self.outside)))
        self.assertTrue(
            policy.needs_command_approval("git status", str(self.work))
        )

    def test_auto_only_prompts_outside_scope(self):
        policy = self.make_policy("auto")

        self.assertFalse(
            policy.needs_command_approval("cmd /c echo inside", str(self.work))
        )
        self.assertTrue(
            policy.check_command("cmd /c echo inside", str(self.work))
        )
        self.assertTrue(
            policy.needs_command_approval("cmd /c echo outside", str(self.outside))
        )
        self.assertFalse(
            policy.check_command("cmd /c echo outside", str(self.outside))
        )

        command = "cmd /c echo outside"
        policy.grant_command(command, str(self.outside), for_session=False)
        self.assertTrue(policy.check_command(command, str(self.outside)))
        self.assertFalse(policy.check_command(command, str(self.outside)))

    def test_only_session_grants_survive_policy_refresh(self):
        original = self.make_policy("ask")
        original.grant_command("python -V", str(self.work), for_session=True)
        refreshed = self.make_policy("ask")
        restarted = self.make_policy("ask")

        refreshed.inherit_session_grants(original)

        self.assertFalse(
            refreshed.needs_command_approval("python -c pass", str(self.work))
        )
        self.assertTrue(
            restarted.needs_command_approval("python -c pass", str(self.work))
        )


class ApprovalAgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        approvals.broker.reset()

    async def asyncTearDown(self):
        approvals.broker.reset()

    async def test_agent_waits_for_modal_decision_and_records_session_grant(self):
        tool_message = {
            "content": "",
            "tool_calls": [{
                "id": "call-1",
                "function": {
                    "name": "shell",
                    "arguments": '{"command":"python -V","cwd":"."}',
                },
            }],
        }
        client = SequenceClient([tool_message, {"content": "done"}])
        policy = Policy({
            "policy": {
                "mode": "ask",
                "scope_roots": [str(agent.tools.WORK)],
                "allowed_bins": [],
            }
        })

        with (
            patch.object(agent.httpx, "AsyncClient", return_value=client),
            patch.object(
                agent.tools,
                "dispatch",
                return_value={"ok": True, "code": 0, "stdout": "Python"},
            ) as dispatch,
        ):
            task = asyncio.create_task(
                agent.run(
                    policy,
                    "http://engine",
                    [{"role": "user", "content": "version"}],
                    SAMPLING,
                    lambda _event: None,
                    think=False,
                )
            )
            for _ in range(50):
                pending = approvals.broker.list()
                if pending:
                    break
                await asyncio.sleep(0.01)
            else:
                self.fail("agent did not request approval")

            request = pending[0]
            self.assertEqual(request["command"], "python -V")
            self.assertEqual(request["binary"], "python")
            approvals.broker.resolve(request["id"], "allow-session")
            result = await task

        self.assertEqual(result, "done")
        dispatch.assert_called_once()
        self.assertFalse(
            policy.needs_command_approval(
                "python another.py", str(agent.tools.WORK)
            )
        )


if __name__ == "__main__":
    unittest.main()
