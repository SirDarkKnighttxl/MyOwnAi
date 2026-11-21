import types
import unittest
from unittest.mock import patch

from noxd import tools
from noxd.policy import Policy


class AirgapTests(unittest.TestCase):
    def test_policy_reads_airgap_flag(self):
        policy = Policy({"policy": {}, "ui": {"airgap": True}})
        self.assertTrue(policy.airgap)

    def test_airgap_blocks_network_tools(self):
        policy = types.SimpleNamespace(airgap=True)
        for name in ("search", "fetch"):
            result = tools.dispatch(policy, name, {"query": "test", "url": "example.com"})
            self.assertFalse(result["ok"])
            self.assertIn("airgap mode", result["error"])

    def test_airgap_leaves_local_tools_available(self):
        policy = types.SimpleNamespace(airgap=True)
        handler = lambda _policy, _args: {"ok": True, "value": "local"}
        with patch.dict(tools.HANDLERS, {"read_file": handler}):
            result = tools.dispatch(policy, "read_file", {"path": "anything"})
        self.assertEqual(result, {"ok": True, "value": "local"})

    def test_network_tools_resume_when_airgap_is_off(self):
        policy = types.SimpleNamespace(airgap=False)
        handler = lambda _policy, _args: {"ok": True, "value": "network"}
        with patch.dict(tools.HANDLERS, {"search": handler}):
            result = tools.dispatch(policy, "search", {"query": "test"})
        self.assertEqual(result, {"ok": True, "value": "network"})


if __name__ == "__main__":
    unittest.main()
