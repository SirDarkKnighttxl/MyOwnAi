"""Refusal-direction abliteration exported as a LoRA -> train/adapters/nox-ablit.

    python train\\abliterate.py --base models\\hf\\Qwen3-8B ^
        --harmful train\\prompts\\harmful.txt --harmless train\\prompts\\harmless.txt

Method (Arditi et al. 2024, "Refusal in LLMs is mediated by a single direction"):
 1. Run both prompt sets (user-supplied, one prompt per line or JSONL "prompt";
    train/prompts/ is gitignored, and NOX ships no prompt content) through the
    chat template and take the residual stream at --layer, last token.
 2. r = mean(harmful) - mean(harmless), normalized to unit length.
 3. Remove r from everything that writes into the residual stream, in every
    layer: W' = (I - r r^T) W for self_attn.o_proj and mlp.down_proj, and
    E' = E - (E r) r^T for embed_tokens (skip with --no-embed).
 4. Each delta is exactly rank 1 (-r (r^T W)), so it is stored *exactly* as a
    LoRA with r=1, alpha=1: lora_B = -r, lora_A = r^T W
    (embedding: lora_embedding_A = (E r)^T, lora_embedding_B = -r).

Reproducible: --seed fixes prompt sampling (--n) and torch RNG; the forward
passes are deterministic. Outputs: adapter_config.json +
adapter_model.safetensors (PEFT format), refusal_direction.safetensors, and
nox_ablit.json (layer, counts, prompt-file SHA-256s, seed, base path).

What fits on a 16 GB GPU (estimated, not measured):
 - Step 1 with --load-4bit (default when CUDA is available): ~6.5 GB of
   weights (embeddings/lm_head stay bf16) plus small activations. Fits. The
   direction comes from the 4-bit model, an approximation of the bf16 one;
   it is usually close enough, but re-run with --no-4bit to compare if
   the eval looks off.
 - --no-4bit: 8B in bf16 is ~16.4 GB of weights and does NOT fit; accelerate
   offloads the overflow to CPU RAM, then to work/offload on disk. Works,
   slowly. It needs roughly 20+ GB of free system RAM, or it pages to disk.
 - Steps 3-4 never load the model: the needed tensors are read one at a time
   from the base safetensors on the CPU (peak ~1 GB RAM). Any machine can do it.
 - Merging the LoRA into a full model for GGUF export (train/export_gguf.py)
   is a CPU bf16 job: ~16-17 GB RAM, more is better.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import random
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "train" / "adapters" / "nox-ablit"
OFFLOAD = ROOT / "work" / "offload"
LINEAR_TARGETS = ("self_attn.o_proj", "mlp.down_proj")
EMBED = "model.embed_tokens"


def read_prompts(path: pathlib.Path) -> list[str]:
    prompts = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if path.suffix.lower() == ".jsonl":
            value = json.loads(line).get("prompt")
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{path.name}: every JSONL row needs a non-empty 'prompt'")
            line = value.strip()
        prompts.append(line)
    if not prompts:
        raise ValueError(f"{path}: no prompts")
    return prompts


def sample(prompts: list[str], n: int | None, seed: int) -> list[str]:
    if not n or n >= len(prompts):
        return list(prompts)
    return random.Random(seed).sample(prompts, n)


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_layers(spec: str, n_layers: int) -> list[int]:
    if spec == "all":
        return list(range(n_layers))
    start, _, stop = spec.partition(":")
    layers = list(range(int(start or 0), int(stop or n_layers)))
    if not layers or layers[0] < 0 or layers[-1] >= n_layers:
        raise ValueError(f"--apply-layers {spec!r} is outside 0..{n_layers - 1}")
    return layers


def target_regex(layers: list[int], embed: bool) -> str:
    layer_alt = "|".join(map(str, layers))
    target_alt = "|".join(re.escape(t) for t in LINEAR_TARGETS)
    parts = [rf"model\.layers\.({layer_alt})\.({target_alt})"]
    if embed:
        parts.append(r"model\.embed_tokens")
    return "|".join(parts)


# --- math (torch) ---------------------------------------------------------

def unit(vector):
    import torch
    v = vector.to(torch.float32)
    norm = v.norm()
    if not torch.isfinite(norm) or norm == 0:
        raise ValueError("refusal direction is zero/NaN; check the prompt sets and --layer")
    return v / norm


def refusal_direction(harmful_mean, harmless_mean):
    return unit(harmful_mean - harmless_mean)


def linear_factors(weight, r, scale: float = 1.0):
    """W [d_model, d_in] writing to the residual: delta = -r (r^T W) = B @ A."""
    W = weight.to(r.dtype)
    A = (r @ W).unsqueeze(0)          # [1, d_in]
    B = (-scale * r).unsqueeze(1)     # [d_model, 1]
    return A.contiguous(), B.contiguous()


def embedding_factors(weight, r, scale: float = 1.0):
    """E [vocab, d_model]: delta = -(E r) r^T = (lora_B @ lora_A)^T in PEFT's layout."""
    E = weight.to(r.dtype)
    A = (E @ r).unsqueeze(0)          # lora_embedding_A [1, vocab]
    B = (-scale * r).unsqueeze(1)     # lora_embedding_B [d_model, 1]
    return A.contiguous(), B.contiguous()


# --- step 1: activations --------------------------------------------------

def chat_texts(tokenizer, prompts: list[str]) -> list[str]:
    texts = []
    for prompt in prompts:
        messages = [{"role": "user", "content": prompt}]
        try:
            text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                                 enable_thinking=False)
        except TypeError:
            text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        texts.append(text)
    return texts


def mean_activation(model, tokenizer, prompts: list[str], layer: int, batch_size: int):
    """Mean residual stream after block `layer` (hidden_states[layer]) at the last token."""
    import torch
    tokenizer.padding_side = "left"   # last position is the real last token
    total, count = None, 0
    device = next(model.parameters()).device
    with torch.inference_mode():
        for i in range(0, len(prompts), batch_size):
            enc = tokenizer(chat_texts(tokenizer, prompts[i:i + batch_size]), return_tensors="pt",
                            padding=True, add_special_tokens=False).to(device)
            out = model(**enc, output_hidden_states=True, use_cache=False)
            h = out.hidden_states[layer][:, -1, :].to(torch.float32).cpu()
            total = h.sum(0) if total is None else total + h.sum(0)
            count += h.shape[0]
    return total / count


def load_for_activations(base: pathlib.Path, four_bit: bool):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(base)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    kwargs = {"low_cpu_mem_usage": True}
    if four_bit:
        from transformers import BitsAndBytesConfig
        kwargs.update(device_map={"": 0}, quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16))
    elif torch.cuda.is_available():
        OFFLOAD.mkdir(parents=True, exist_ok=True)
        kwargs.update(dtype=torch.bfloat16, device_map="auto", offload_folder=str(OFFLOAD))
    else:
        kwargs.update(dtype=torch.float32)
    model = AutoModelForCausalLM.from_pretrained(base, **kwargs)
    model.eval()
    return model, tokenizer


# --- steps 3-4: weights -> LoRA, read straight from safetensors -------------

def _weight_files(base: pathlib.Path) -> dict[str, pathlib.Path]:
    index = base / "model.safetensors.index.json"
    if index.exists():
        weight_map = json.loads(index.read_text(encoding="utf-8"))["weight_map"]
        return {name: base / file for name, file in weight_map.items()}
    single = base / "model.safetensors"
    if not single.exists():
        raise FileNotFoundError(f"no safetensors weights in {base}")
    from safetensors import safe_open
    with safe_open(str(single), framework="pt") as fh:
        return {name: single for name in fh.keys()}


def _read(files: dict[str, pathlib.Path], name: str):
    from safetensors import safe_open
    if name not in files:
        raise KeyError(f"tensor {name} not found in base weights")
    with safe_open(str(files[name]), framework="pt") as fh:
        return fh.get_tensor(name)


def build_adapter(base: pathlib.Path, r, out: pathlib.Path, layers: list[int] | None = None,
                  embed: bool = True, scale: float = 1.0) -> dict:
    import torch
    from peft import LoraConfig
    from safetensors.torch import save_file

    config = json.loads((base / "config.json").read_text(encoding="utf-8"))
    n_layers = config["num_hidden_layers"]
    layers = list(range(n_layers)) if layers is None else layers
    r = unit(r)
    files = _weight_files(base)
    tensors = {}
    for i in layers:
        for target in LINEAR_TARGETS:
            name = f"model.layers.{i}.{target}"
            A, B = linear_factors(_read(files, name + ".weight"), r, scale)
            tensors[f"base_model.model.{name}.lora_A.weight"] = A
            tensors[f"base_model.model.{name}.lora_B.weight"] = B
    if embed:
        A, B = embedding_factors(_read(files, EMBED + ".weight"), r, scale)
        tensors[f"base_model.model.{EMBED}.lora_embedding_A"] = A
        tensors[f"base_model.model.{EMBED}.lora_embedding_B"] = B

    out.mkdir(parents=True, exist_ok=True)
    LoraConfig(r=1, lora_alpha=1, lora_dropout=0.0, bias="none", task_type="CAUSAL_LM",
               target_modules=target_regex(layers, embed),
               base_model_name_or_path=str(base)).save_pretrained(str(out))
    save_file({k: v.to(torch.float32).contiguous() for k, v in tensors.items()},
              str(out / "adapter_model.safetensors"))
    return {"layers": layers, "embed": embed, "tensors": len(tensors)}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="refusal-direction abliteration -> LoRA")
    p.add_argument("--base", type=pathlib.Path, required=True, help="local HF-format base model folder")
    p.add_argument("--harmful", type=pathlib.Path, required=True)
    p.add_argument("--harmless", type=pathlib.Path, required=True)
    p.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    p.add_argument("--layer", type=float, default=0.6,
                   help="hidden_states index; a value < 1 is a fraction of depth (default 0.6)")
    p.add_argument("--n", type=int, default=256, help="max prompts per set (sampled with --seed)")
    p.add_argument("--batch", type=int, default=8)
    p.add_argument("--seed", type=int, default=13)
    p.add_argument("--apply-layers", default="all", help="'all' or 'start:stop'")
    p.add_argument("--scale", type=float, default=1.0, help="1.0 = full projection removal")
    p.add_argument("--no-embed", action="store_true", help="leave embed_tokens untouched")
    p.add_argument("--no-4bit", action="store_true", help="bf16 activations (offloads on 16 GB)")
    p.add_argument("--direction", type=pathlib.Path,
                   help="reuse a saved refusal_direction.safetensors and skip step 1")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    import torch
    from safetensors.torch import load_file, save_file

    torch.manual_seed(args.seed)
    config = json.loads((args.base / "config.json").read_text(encoding="utf-8"))
    n_layers = config["num_hidden_layers"]
    layer = int(round(args.layer * n_layers)) if args.layer < 1 else int(args.layer)
    if not 1 <= layer <= n_layers:
        raise ValueError(f"--layer must resolve to 1..{n_layers}, got {layer}")
    harmful = sample(read_prompts(args.harmful), args.n, args.seed)
    harmless = sample(read_prompts(args.harmless), args.n, args.seed + 1)
    args.out.mkdir(parents=True, exist_ok=True)

    if args.direction:
        saved = load_file(str(args.direction))
        r = saved["direction"]
        print(f"reusing direction from {args.direction}")
    else:
        four_bit = not args.no_4bit and torch.cuda.is_available()
        print(f"collecting activations at layer {layer}/{n_layers} "
              f"({len(harmful)} + {len(harmless)} prompts, 4bit={four_bit})", flush=True)
        model, tokenizer = load_for_activations(args.base, four_bit)
        mu_harm = mean_activation(model, tokenizer, harmful, layer, args.batch)
        mu_safe = mean_activation(model, tokenizer, harmless, layer, args.batch)
        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        r = refusal_direction(mu_harm, mu_safe)
        save_file({"direction": r, "harmful_mean": mu_harm, "harmless_mean": mu_safe},
                  str(args.out / "refusal_direction.safetensors"))

    info = build_adapter(args.base, r, args.out, parse_layers(args.apply_layers, n_layers),
                         embed=not args.no_embed, scale=args.scale)
    meta = {
        "method": "refusal-direction orthogonalization (rank-1 LoRA per matrix)",
        "base": str(args.base), "layer": layer, "n_layers": n_layers,
        "harmful": {"file": str(args.harmful), "sha256": sha256(args.harmful), "used": len(harmful)},
        "harmless": {"file": str(args.harmless), "sha256": sha256(args.harmless), "used": len(harmless)},
        "seed": args.seed, "scale": args.scale, "apply_layers": args.apply_layers,
        "embed": info["embed"], "tensors": info["tensors"],
        "direction_from": str(args.direction) if args.direction else "computed",
    }
    (args.out / "nox_ablit.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"adapter saved to {args.out} ({info['tensors']} tensors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
