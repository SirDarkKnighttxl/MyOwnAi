import pathlib
import tempfile
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


class EditorToolTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary.name)
        self.policy = Policy({"policy": {"mode": "yolo"}})

    def tearDown(self):
        self.temporary.cleanup()

    def test_edit_file_replaces_one_exact_block(self):
        path = self.root / "sample.txt"
        path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

        result = tools.dispatch(
            self.policy,
            "edit_file",
            {
                "path": str(path),
                "old_text": "alpha\nbeta",
                "new_text": "ALPHA\nBETA",
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual(path.read_text(encoding="utf-8"), "ALPHA\nBETA\ngamma\n")

    def test_edit_file_rejects_ambiguous_text(self):
        path = self.root / "sample.txt"
        original = "repeat\nmiddle\nrepeat\n"
        path.write_text(original, encoding="utf-8")

        result = tools.dispatch(
            self.policy,
            "edit_file",
            {"path": str(path), "old_text": "repeat", "new_text": "changed"},
        )

        self.assertFalse(result["ok"])
        self.assertIn("ambiguous", result["error"])
        self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_apply_patch_applies_multiple_hunks(self):
        path = self.root / "sample.txt"
        path.write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")
        diff = """--- a/sample.txt
+++ b/sample.txt
@@ -1,3 +1,3 @@
 one
-two
+TWO
 three
@@ -4,2 +4,3 @@
 four
+four-and-a-half
 five
"""

        result = tools.dispatch(
            self.policy,
            "apply_patch",
            {"path": str(path), "patch": diff},
        )

        self.assertEqual(result["hunks"], 2)
        self.assertEqual(
            path.read_text(encoding="utf-8"),
            "one\nTWO\nthree\nfour\nfour-and-a-half\nfive\n",
        )

    def test_apply_patch_rejects_stale_context_without_partial_write(self):
        path = self.root / "sample.txt"
        original = "one\ntwo\nthree\nfour\nfive\n"
        path.write_text(original, encoding="utf-8")
        diff = """@@ -1,2 +1,2 @@
 one
-two
+TWO
@@ -4,2 +4,2 @@
-stale
+FOUR
 five
"""

        result = tools.dispatch(
            self.policy,
            "apply_patch",
            {"path": str(path), "patch": diff},
        )

        self.assertFalse(result["ok"])
        self.assertIn("stale patch", result["error"])
        self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_editor_tools_preserve_crlf(self):
        path = self.root / "windows.txt"
        path.write_bytes(b"one\r\ntwo\r\nthree\r\n")

        edited = tools.dispatch(
            self.policy,
            "edit_file",
            {"path": str(path), "old_text": "one\ntwo", "new_text": "ONE\nTWO"},
        )
        patched = tools.dispatch(
            self.policy,
            "apply_patch",
            {
                "path": str(path),
                "patch": "@@ -2,2 +2,2 @@\n TWO\n-three\n+THREE\n",
            },
        )

        self.assertTrue(edited["ok"])
        self.assertTrue(patched["ok"])
        self.assertEqual(path.read_bytes(), b"ONE\r\nTWO\r\nTHREE\r\n")


if __name__ == "__main__":
    unittest.main()
