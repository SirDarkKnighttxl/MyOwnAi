"""Merge a LoRA adapter into the base, convert to GGUF, quantize to Q4_K_M.

    python train\\export_gguf.py --base models\\hf\\Qwen3-8B ^
        --adapter train\\adapters\\nox-dpo --convert <llama.cpp>\\convert_hf_to_gguf.py

Steps (intermediates in work\\export, which is gitignored):
 1. merge: base (bf16, CPU) + adapter -> work\\export\\<name>-merged (HF safetensors).
    Needs ~16-17 GB free RAM for Qwen3-8B, plus ~16 GB of disk.
 2. convert: llama.cpp convert_hf_to_gguf.py -> work\\export\\<name>-bf16.gguf (~16 GB).
 3. quantize: bin\\llama-quantize -> models\\<name>.Q4_K_M.gguf (~5 GB).
The output is always named nox-<name>.Q4_K_M.gguf. The `nox-` prefix is what
noxd/models.py uses to give the file role=trained in /api/models and the UI
(nox-ablit is ours, not the downloaded abliterated model). Intermediates are
deleted unless --keep. Nothing is committed: models/ and work/ are ignored.
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
WORK = ROOT / "work" / "export"
MODELS = ROOT / "models"
QUANT = "Q4_K_M"


def model_name(raw: str) -> str:
    """'dpo' / 'nox-dpo' / 'nox-dpo.Q4_K_M.gguf' -> 'nox-dpo'."""
    name = re.sub(r"(\.q4_k_m)?\.gguf$", "", raw.strip(), flags=re.I)
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-.")
    if not name:
        raise ValueError("model name is empty")
    if not name.lower().startswith("nox-"):
        name = "nox-" + name
    if re.search(r"embed|nomic", name, re.I):
        raise ValueError("names containing 'embed'/'nomic' are treated as embedding models")
    return name


def output_path(name: str, out_dir: pathlib.Path = MODELS) -> pathlib.Path:
    return out_dir / f"{model_name(name)}.{QUANT}.gguf"


def quantize_binary(bin_dir: pathlib.Path = BIN) -> pathlib.Path:
    exe = "llama-quantize.exe" if sys.platform == "win32" else "llama-quantize"
    return bin_dir / exe


def convert_cmd(convert: pathlib.Path, merged: pathlib.Path, gguf: pathlib.Path) -> list[str]:
    return [sys.executable, str(convert), str(merged), "--outfile", str(gguf), "--outtype", "bf16"]


def quantize_cmd(quantize: pathlib.Path, src: pathlib.Path, dst: pathlib.Path) -> list[str]:
    return [str(quantize), str(src), str(dst), QUANT]


def merge(base: pathlib.Path, adapter: pathlib.Path, merged: pathlib.Path) -> None:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model = AutoModelForCausalLM.from_pretrained(base, dtype=torch.bfloat16,
                                                 low_cpu_mem_usage=True, device_map="cpu")
    model = PeftModel.from_pretrained(model, str(adapter)).merge_and_unload()
    merged.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(merged), max_shard_size="2GB")
    tok_src = adapter if (adapter / "tokenizer_config.json").exists() else base
    AutoTokenizer.from_pretrained(tok_src).save_pretrained(str(merged))


def file_sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def run(cmd: list[str]) -> None:
    print("> " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="merge adapter -> GGUF Q4_K_M in models/")
    p.add_argument("--base", type=pathlib.Path, required=True, help="local HF-format base model folder")
    p.add_argument("--adapter", type=pathlib.Path, required=True, help="e.g. train/adapters/nox-dpo")
    p.add_argument("--convert", type=pathlib.Path, required=True,
                   help="path to llama.cpp convert_hf_to_gguf.py (same llama.cpp build as bin/)")
    p.add_argument("--name", help="output name (default: adapter folder name)")
    p.add_argument("--quantize", type=pathlib.Path, default=quantize_binary())
    p.add_argument("--out-dir", type=pathlib.Path, default=MODELS)
    p.add_argument("--work", type=pathlib.Path, default=WORK)
    p.add_argument("--keep", action="store_true", help="keep merged folder and bf16 GGUF")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    name = model_name(args.name or args.adapter.name)
    for need in (args.base, args.adapter, args.convert, args.quantize):
        if not need.exists():
            print(f"missing: {need}", file=sys.stderr)
            return 2
    merged = args.work / f"{name}-merged"
    bf16 = args.work / f"{name}-bf16.gguf"
    out = output_path(name, args.out_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/3] merging {args.adapter} into {args.base}", flush=True)
    merge(args.base, args.adapter, merged)
    print("[2/3] converting to GGUF (bf16)", flush=True)
    run(convert_cmd(args.convert, merged, bf16))
    print(f"[3/3] quantizing to {QUANT}", flush=True)
    run(quantize_cmd(args.quantize, bf16, out))
    if not args.keep:
        shutil.rmtree(merged, ignore_errors=True)
        bf16.unlink(missing_ok=True)
    print(f"wrote {out} ({out.stat().st_size:,} bytes, sha256 {file_sha256(out)})")
    print("It appears in the NOX model picker as role TRAINED if its folder is in nox.json model.paths.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
