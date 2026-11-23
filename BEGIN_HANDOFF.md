BEGIN HANDOFF

Context
You are finishing NOX, a local autonomous engineering agent. Owner: SirDarkKnighttxl. Single user, Windows 11, RTX 4090 Laptop 16GB VRAM, 32GB RAM, i9.

NOX is a hard fork in spirit of a commercial Electron app called TANNIS, rebuilt as a Python daemon + local web UI. TANNIS lives at E:\TANNIS and is reference only — read it, never modify it. Only app/main.js is worth reading (Ollama spawn pattern, license-drive logic); everything else was already rebuilt.

Design goal: a Devin-class agent that runs entirely local, costs nothing, has no license check, no telemetry, no content filters, and whose every component is replaceable.

E:\NOX is a USB flash drive. Expect slow IO. Portability is a requirement, not a nice-to-have.

Locations
E:\NOX — project root.
C:\NOX\models — fast local model copies, optional, absent on other machines.
E:\NOX\bin — llama.cpp b12451, Windows CUDA 13.
E:\NOX\models — Qwen3-8B-Q4_K_M.gguf, nomic-embed-text-v1.5.Q4_K_M.gguf.
E:\NOX\work — sandbox root; work/corpus holds seven reference repos.
E:\NOX\nox.db — SQLite: sessions, messages, 1500 indexed chunks.
Architecture
nox.py — desktop shell; picks free ports, writes runtime.json, opens pywebview.
noxd/main.py — FastAPI daemon; chat, sessions, persona, config, lessons, status.
noxd/engine.py — supervises llama-server, logs to logs/engine.log, surfaces failure tails.
noxd/agent.py — tool loop, 12-step cap, non-streaming internally.
noxd/tools.py — read_file, write_file, list_dir, grep, shell, update_scratchpad, search, fetch.
noxd/policy.py — permission engine: ask/auto/yolo, airgap flag.
noxd/rag.py — local embeddings, cosine retrieval.
noxd/store.py — SQLite.
ui/index.html — sidebar, sessions, activity trace, markdown, thinking blocks.
policy/persona.md, policy/lessons.md — behavior.
nox.json — all config.
Ground rules
No cloud dependency. Free and local only. No paid APIs, no accounts.
No new heavy dependencies. stdlib, fastapi, uvicorn, httpx, pywebview. Justify anything else.
Portability. Relative paths except the optional C:\NOX fast path. Never hardcode a drive letter.
Module boundaries are load-bearing. Keep components independently replaceable; don't merge to save lines.
No telemetry, no license checks, no analytics, ever.
Never commit models/ or bin/. .gitignore covers it. Weights go to C:\NOX\models or are downloaded.
Windows target. Don't break it chasing cross-platform.
Report honestly. If it won't fit in 16GB VRAM, say so and give the achievable version.
Repo & git
Remote: https://github.com/SirDarkKnighttxl/MyOwnAi (private, branch main). You have access — use it.

Commit per work package, not per session. Message format: wp-NN: what changed.
Push after each green acceptance test.
Never force-push once WP-05 has landed.
Keep the repo private.
Known defects — fix first
WP-01 --no-mmap is invalid in b12451. Run bin\llama-server.exe --help, find the real spellings for the mmap toggle, flash attention and KV cache types, then add correct flags to model.extra_args with -fa on and q8_0 KV at 16K context. Acceptance: engine starts with flash attention active, log confirms it, 16K-context prompt completes without OOM.

WP-02 think is wired through agent.run(think=). Verify chat_template_kwargs.enable_thinking reaches the payload and that thinking blocks render. Acceptance: checkbox off yields no </think> block.

WP-03 rag.context() injects a system message before history. Validate on five known corpus facts; tune the 0.55 floor. Acceptance: three corpus questions retrieve relevant excerpts, three off-corpus questions retrieve nothing.

Work packages
WP-04 De-restricted weights. Download Huihui-Qwen3-8B-abliterated-v2.Q4_K_M.gguf from mradermacher/Huihui-Qwen3-8B-abliterated-v2-GGUF into C:\NOX\models. Order model.paths abliterated → stock → USB fallback. Build a 60-prompt refusal suite in train/suite.jsonl covering: exploit walkthroughs, license cracking, malware behavior, WAF bypass, protocol abuse, reverse engineering, RF, plus 15 controls that should not change. Score stock vs abliterated, record in train/RESULTS.md. Acceptance: suite exists, both models scored, refusal rate drops with control accuracy holding.

WP-05 Model roles. Add model.role (stock | ablit | trained) and show it in the header. Every eval run records the role that produced it. Never delete the stock weights — they're the control group.

WP-06 Model manager. GET/POST /api/models listing .gguf across both paths, load/unload, header dropdown, clean engine swap. Acceptance: switch models without restarting the daemon.

WP-07 Sampler panel. UI for temp, top_p, top_k, min_p, repeat_penalty, max_tokens via PUT /api/config, live apply. Acceptance: persists across reload and measurably changes output.

WP-08 Airgap. Header toggle plus visible badge on ui.airgap; blocks search and fetch. Acceptance: blocks and unblocks cleanly, local tools unaffected.

WP-09 Editor tools. edit_file (exact replace, fail on ambiguity) and apply_patch (unified diff). Acceptance: multi-hunk applies; stale context fails with a clear message.

WP-10 Git tools. git_status, git_diff, git_commit, git_log, all policy-gated. Acceptance: real output on work/; commit requires a message.

WP-11 Python execution. run_python via temp file with timeout, capturing streams. Acceptance: runs a snippet, kills a runaway loop at timeout.

WP-12 Approval flow. ask mode modal: command, cwd, allow/deny/allow-for-session. auto allows inside work/, prompts outside. Acceptance: ask prompts on every shell call; auto only out-of-scope.

WP-13 Training. Build train/:

build_pairs.py — prompt/refusal/answer triples from security topics.
dpo.py — QLoRA 4-bit rank 32 DPO or ORPO on Qwen3-8B.
abliterate.py — refusal-direction subtraction, exported as LoRA, so it's reproducible rather than downloaded.
eval.py — runs the WP-04 suite.
export_gguf.py — merge, convert, quantize Q4_K_M.
Produce nox-dpo and nox-ablit adapters, both registered with role trained. Acceptance: refusal rate improves over stock while controls hold; numbers in train/RESULTS.md.
WP-14 Corpus expansion. Index rea and ciphey with their own cap; shallow-clone pytorch and huggingface/transformers with a docs-only filter; add a re-rank pass. Acceptance: a REA CLI question surfaces REA docs, not payload files.

WP-15 Memory editor. Page listing stored facts and lessons with edit/delete. Acceptance: editing a lesson changes later behavior.

WP-16 Packaging. Portable embedded Python on the stick; setup.bat for the fast-path copy. Acceptance: runs on a machine with no Python installed.

Non-goals
Frontier-model training (100–150M from-scratch is the ceiling). Multimodal. Cross-platform. Hosted services.

Definition of done
Daemon starts clean on a machine with no Python; twelve-plus tools under policy gating; three model roles selectable with recorded eval numbers; retrieval answers corpus questions correctly; zero outbound traffic with airgap on.

END HANDOFF

Two notes for you, not Devin:

WP-04 lands before anything else so you have a model that doesn't refuse on day one. WP-13 makes the abliteration reproducible instead of depending on someone else's upload — that's the difference between using an uncensored model and owning one.

And paste this line to Devin alongside the handoff: "E:\NOX is a USB flash drive — slow IO is expected, don't optimize around it, and don't move the project to C:."