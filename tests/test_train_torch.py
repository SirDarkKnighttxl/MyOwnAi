"""WP-13 torch checks: skipped unless torch, transformers, peft and safetensors are installed
(train\\.venv). The daemon test environment does not have them."""
import importlib.util
import pathlib
import tempfile
import unittest

HAVE = all(importlib.util.find_spec(m) for m in ("torch", "transformers", "peft", "safetensors"))


@unittest.skipUnless(HAVE, "training deps (torch, transformers, peft) not installed")
class AbliterationLoraTests(unittest.TestCase):
    def test_rank1_factors_reproduce_projection(self):
        import torch
        from train import abliterate
        torch.manual_seed(0)
        r = abliterate.unit(torch.randn(16))
        W = torch.randn(16, 40)
        A, B = abliterate.linear_factors(W, r)
        self.assertEqual((tuple(A.shape), tuple(B.shape)), ((1, 40), (16, 1)))
        P = torch.eye(16) - torch.outer(r, r)
        self.assertTrue(torch.allclose(W + B @ A, P @ W, atol=1e-5))
        E = torch.randn(100, 16)
        EA, EB = abliterate.embedding_factors(E, r)
        self.assertTrue(torch.allclose(E + (EB @ EA).T, E @ P, atol=1e-5))

    def test_adapter_merges_to_orthogonalized_weights(self):
        import torch
        from peft import PeftModel
        from transformers import Qwen3Config, Qwen3ForCausalLM
        from train import abliterate
        torch.manual_seed(0)
        config = Qwen3Config(vocab_size=128, hidden_size=32, intermediate_size=64, num_hidden_layers=3,
                             num_attention_heads=4, num_key_value_heads=2, head_dim=8,
                             tie_word_embeddings=False)
        with tempfile.TemporaryDirectory() as raw:
            base, out = pathlib.Path(raw) / "base", pathlib.Path(raw) / "adapter"
            Qwen3ForCausalLM(config).save_pretrained(base)
            r = abliterate.unit(torch.randn(32))
            info = abliterate.build_adapter(base, r, out, layers=[0, 2], embed=True)
            self.assertEqual(info["tensors"], 2 * 2 * 2 + 2)
            model = Qwen3ForCausalLM.from_pretrained(base, dtype=torch.float32)
            orig = {k: v.clone() for k, v in model.state_dict().items()}
            merged = PeftModel.from_pretrained(model, str(out)).merge_and_unload().state_dict()
        P = torch.eye(32) - torch.outer(r, r)
        for i in (0, 2):
            for t in ("self_attn.o_proj", "mlp.down_proj"):
                k = f"model.layers.{i}.{t}.weight"
                self.assertTrue(torch.allclose(merged[k], P @ orig[k], atol=1e-5), k)
        for k in ("model.layers.1.self_attn.o_proj.weight", "model.layers.0.self_attn.q_proj.weight",
                  "lm_head.weight"):
            self.assertTrue(torch.equal(merged[k], orig[k]), k)
        k = "model.embed_tokens.weight"
        self.assertTrue(torch.allclose(merged[k], orig[k] @ P, atol=1e-5))


if __name__ == "__main__":
    unittest.main()
