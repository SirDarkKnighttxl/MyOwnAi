"""QLoRA preference tuning (DPO, optional ORPO) for Qwen3-8B -> train/adapters/nox-dpo.

    python train\\dpo.py --base models\\hf\\Qwen3-8B       (any local HF-format folder)
    python train\\dpo.py --base <path> --orpo               (reference-free ORPO)

Defaults: 4-bit NF4 base (double quant, bf16 compute), LoRA rank 32 / alpha 64 /
dropout 0.05 on q,k,v,o,gate,up,down, gradient checkpointing, max_len 1024,
batch 1 x grad-accum 8, paged 8-bit AdamW, beta 0.1, 1 epoch, seed 13.
Data: train/pairs/{train,val}.jsonl from train/build_pairs.py.

VRAM estimate for Qwen3-8B on a 16 GB GPU (estimated, not measured):
  4-bit weights ~4 GB + bf16 embed_tokens/lm_head (151,936 x 4,096 each, kept
  unquantized) ~2.5 GB                                           ~6.5 GB
  LoRA r=32 on 7 projections x 36 layers ~87M params, fp32 weights + grads
  + paged 8-bit Adam states                                       ~1 GB
  activations with checkpointing, chosen+rejected at 1024 tokens   ~1-2 GB
  logits 2 x 1024 x 151,936 in fp32 plus log-softmax copy          ~2.5 GB
  CUDA context / allocator slack                                   ~1-1.5 GB
  => ~12-14 GB peak. It should fit at max_len 1024, batch 1. 2048 will not.
  If it OOMs: --max-len 768, or --precompute-ref (reference log-probs computed
  once up front, DPO only), or close other GPU apps (NOX's llama-server!).
The reference model costs no extra VRAM: with a LoRA adapter, TRL uses the
base with the adapter disabled as the reference.

Requires train/requirements.txt (torch with CUDA, bitsandbytes). --no-4bit
loads bf16/fp32 instead (CPU smoke tests on tiny models; 8B in bf16 needs
~16.4 GB for weights alone and will not fit a 16 GB GPU).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_TRAIN = ROOT / "train" / "pairs" / "train.jsonl"
DEFAULT_VAL = ROOT / "train" / "pairs" / "val.jsonl"
DEFAULT_OUT = ROOT / "train" / "adapters" / "nox-dpo"
LORA_TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="QLoRA DPO/ORPO for NOX")
    p.add_argument("--base", type=pathlib.Path, required=True, help="local HF-format base model folder")
    p.add_argument("--train", type=pathlib.Path, default=DEFAULT_TRAIN)
    p.add_argument("--val", type=pathlib.Path, default=DEFAULT_VAL)
    p.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    p.add_argument("--orpo", action="store_true", help="ORPO instead of DPO (trl.experimental)")
    p.add_argument("--rank", type=int, default=32)
    p.add_argument("--alpha", type=int, default=64)
    p.add_argument("--dropout", type=float, default=0.05)
    p.add_argument("--max-len", type=int, default=1024)
    p.add_argument("--beta", type=float, default=0.1)
    p.add_argument("--lr", type=float, default=2e-5)
    p.add_argument("--epochs", type=float, default=1.0)
    p.add_argument("--max-steps", type=int, default=-1)
    p.add_argument("--batch", type=int, default=1)
    p.add_argument("--grad-accum", type=int, default=8)
    p.add_argument("--seed", type=int, default=13)
    p.add_argument("--precompute-ref", action="store_true", help="DPO: precompute reference log-probs")
    p.add_argument("--no-4bit", action="store_true", help="skip bitsandbytes (CPU smoke tests only)")
    return p.parse_args(argv)


def load_pairs(path: pathlib.Path) -> list[dict]:
    """JSONL pairs -> TRL conversational preference rows."""
    rows = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        row = json.loads(raw)
        for key in ("prompt", "chosen", "rejected"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"{path.name}:{line_no}: '{key}' must be a non-empty string")
        prompt = []
        if row.get("system"):
            prompt.append({"role": "system", "content": row["system"]})
        prompt.append({"role": "user", "content": row["prompt"]})
        rows.append({
            "prompt": prompt,
            "chosen": [{"role": "assistant", "content": row["chosen"]}],
            "rejected": [{"role": "assistant", "content": row["rejected"]}],
        })
    if not rows:
        raise ValueError(f"{path}: no pairs")
    return rows


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    import torch
    from datasets import Dataset
    from peft import LoraConfig, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed

    set_seed(args.seed)
    cuda = torch.cuda.is_available()
    if not args.no_4bit and not cuda:
        print("4-bit QLoRA needs a CUDA GPU; use --no-4bit only for tiny smoke tests.", file=sys.stderr)
        return 2

    tokenizer = AutoTokenizer.from_pretrained(args.base)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    load = {"dtype": torch.bfloat16 if cuda else torch.float32}
    if not args.no_4bit:
        from transformers import BitsAndBytesConfig
        load["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16)
        load["device_map"] = {"": 0}
    model = AutoModelForCausalLM.from_pretrained(args.base, **load)
    model.config.use_cache = False
    if not args.no_4bit:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

    peft_config = LoraConfig(r=args.rank, lora_alpha=args.alpha, lora_dropout=args.dropout,
                             target_modules=LORA_TARGETS, bias="none", task_type="CAUSAL_LM")
    train_ds = Dataset.from_list(load_pairs(args.train))
    val_ds = Dataset.from_list(load_pairs(args.val)) if args.val.exists() else None

    common = dict(
        output_dir=str(args.out / "checkpoints"),
        per_device_train_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        beta=args.beta,
        max_length=args.max_len,
        gradient_checkpointing=True,
        bf16=cuda,
        optim="paged_adamw_8bit" if not args.no_4bit else "adamw_torch",
        lr_scheduler_type="cosine",
        warmup_steps=0.05,  # float in [0, 1) = ratio of total steps (transformers 5)
        logging_steps=5,
        save_strategy="no",
        eval_strategy="epoch" if val_ds is not None else "no",
        seed=args.seed,
        report_to="none",
    )
    if args.orpo:
        from trl.experimental.orpo import ORPOConfig, ORPOTrainer
        trainer = ORPOTrainer(model=model, args=ORPOConfig(**common), train_dataset=train_ds,
                              eval_dataset=val_ds, processing_class=tokenizer, peft_config=peft_config)
    else:
        from trl import DPOConfig, DPOTrainer
        trainer = DPOTrainer(model=model, args=DPOConfig(precompute_ref_log_probs=args.precompute_ref, **common),
                             train_dataset=train_ds, eval_dataset=val_ds,
                             processing_class=tokenizer, peft_config=peft_config)
    trainer.train()
    args.out.mkdir(parents=True, exist_ok=True)
    trainer.model.save_pretrained(str(args.out))
    tokenizer.save_pretrained(str(args.out))
    meta = {k: (str(v) if isinstance(v, pathlib.Path) else v) for k, v in vars(args).items()}
    (args.out / "nox_train.json").write_text(json.dumps({"method": "orpo" if args.orpo else "dpo", **meta},
                                                        indent=2) + "\n", encoding="utf-8")
    print(f"adapter saved to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
