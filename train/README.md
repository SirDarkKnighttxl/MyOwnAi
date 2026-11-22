# NOX training pipeline (WP-13)

Separate from the daemon: install `train/requirements.txt` into `train\.venv`
(see the header of that file for the CUDA torch index). The daemon and
`runtime\python` never import torch.

User-supplied inputs (gitignored, and NOX ships no content for them):
- `train/pairs_src.jsonl`: preference rows `{"prompt", "chosen", "rejected"?}`
- `train/prompts/harmful.txt`, `train/prompts/harmless.txt`: one prompt per line
- a local HF-format Qwen3-8B folder, e.g. `models\hf\Qwen3-8B` (models/ is ignored)
- llama.cpp `convert_hf_to_gguf.py` from the same llama.cpp build as `bin\`

## Order of operations (Windows, repo root)

    set PY=train\.venv\Scripts\python

    rem 0. Baselines: stock and the downloaded ablit, through the same eval
    %PY% train\eval.py --model models\Qwen3-8B-Q4_K_M.gguf --label stock --role stock
    %PY% train\eval.py --model models\Huihui-Qwen3-8B-abliterated-v2.Q4_K_M.gguf --label ablit --role ablit

    rem 1. Pairs (add --sample-rejected with NOX's stock model serving on 127.0.0.1
    rem    to fill rows that have no "rejected")
    %PY% train\build_pairs.py --source train\pairs_src.jsonl

    rem 2. DPO adapter -> train\adapters\nox-dpo   (close NOX first: it holds VRAM)
    %PY% train\dpo.py --base models\hf\Qwen3-8B

    rem 3. Abliteration adapter -> train\adapters\nox-ablit
    %PY% train\abliterate.py --base models\hf\Qwen3-8B --harmful train\prompts\harmful.txt --harmless train\prompts\harmless.txt

    rem 4. Export both to models\nox-*.Q4_K_M.gguf (role=trained in the UI)
    %PY% train\export_gguf.py --base models\hf\Qwen3-8B --adapter train\adapters\nox-dpo --convert <llama.cpp>\convert_hf_to_gguf.py
    %PY% train\export_gguf.py --base models\hf\Qwen3-8B --adapter train\adapters\nox-ablit --convert <llama.cpp>\convert_hf_to_gguf.py

    rem 5. Eval both; each run fills its pending row in train\RESULTS.md
    %PY% train\eval.py --model models\nox-dpo.Q4_K_M.gguf --label nox-dpo --role trained
    %PY% train\eval.py --model models\nox-ablit.Q4_K_M.gguf --label nox-ablit --role trained

`eval.py --endpoint http://127.0.0.1:PORT --model NAME` evaluates an already
running local llama-server instead of spawning one. Non-local URLs are refused.

## What fits in 16 GB VRAM (estimates, not measured)
- `dpo.py`, QLoRA 4-bit, rank 32, max_len 1024, batch 1: ~12-14 GB peak. It should
  fit. 2048 tokens will not. Fallbacks: `--max-len 768`, `--precompute-ref`.
- `abliterate.py` activations with 4-bit loading: ~6.5 GB. Fits. bf16 (`--no-4bit`) is
  ~16.4 GB of weights and does not fit; it offloads to CPU/disk and is slow.
- `abliterate.py` weight deltas: CPU only, reads tensors one at a time (~1 GB RAM).
- `export_gguf.py` merge: CPU bf16, ~16-17 GB system RAM, plus ~16 GB disk for
  the merged folder and another ~16 GB for the bf16 GGUF (deleted afterwards).
- `eval.py`: Q4_K_M 8B in llama-server with 16K context. Same as normal NOX use.
- Full bf16 fine-tuning or merging on the GPU is not possible on 16 GB.
