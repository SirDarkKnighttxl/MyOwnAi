import pathlib
import tempfile
import unittest

from noxd import models


class ModelDiscoveryTests(unittest.TestCase):
    def test_discovers_roles_across_configured_directories(self):
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            fast = root / "fast"
            portable = root / "portable"
            fast.mkdir()
            portable.mkdir()
            stock = fast / "Qwen3-8B-Q4_K_M.gguf"
            ablit = fast / "Huihui-Qwen3-8B-abliterated-v2.Q4_K_M.gguf"
            embed = portable / "nomic-embed-text.gguf"
            for path in (stock, ablit, embed):
                path.write_bytes(b"gguf")
            config = {
                "model": {
                    "paths": [str(ablit), str(stock), str(portable / "fallback.gguf")]
                }
            }

            found = models.discover(config, str(stock))

        by_name = {item["name"]: item for item in found}
        self.assertEqual(by_name[stock.name]["role"], "stock")
        self.assertTrue(by_name[stock.name]["active"])
        self.assertEqual(by_name[ablit.name]["role"], "ablit")
        self.assertEqual(by_name[embed.name]["kind"], "embedding")
        self.assertFalse(by_name[embed.name]["loadable"])

    def test_selection_is_limited_to_discovered_files(self):
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            model = root / "custom.gguf"
            model.write_bytes(b"gguf")
            config = {"model": {"paths": [str(root / "fallback.gguf")]}}

            selected = models.select(config, str(model))
            missing = models.select(config, str(root.parent / "outside.gguf"))

        self.assertEqual(selected["role"], "trained")
        self.assertIsNone(missing)


if __name__ == "__main__":
    unittest.main()
