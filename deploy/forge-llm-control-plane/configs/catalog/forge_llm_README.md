# Forge-LLM model-selection registry v0.2

Updated: 2026-11-03. Status: curated **candidate list**, not a certified model benchmark, model artifact manifest, or production deployment decision.

## Contents

- `forge_llm_catalog_2026-11-03.json` — canonical 82-model catalog, 39 tasks × 9 VRAM tiers, capability/type/license metadata, model-card sources, required promotion metrics.
- `forge_llm_catalog_2026-11-03_matrix.csv` — flat 39-task matrix with nine VRAM tiers.
- `forge_llm_catalog_2026-11-03_matrix.md` — readable matrix and 82-alias model-ID dictionary.
- `forge_llm_catalog_2026-11-03_models.csv` — flat model registry with repository URL per row.
- `forge_llm_catalog_2026-11-03.xlsx` — human-friendly workbook with matrix, model registry, and policy.
- `forge_llm_selector.py` — stdlib-only model candidate shortlisting; **never** approves deployment.
- `test_forge_llm_catalog.py` — integrity and no-autopromote tests.

## Example

```bash
python forge_llm_selector.py --task code_repo --free-vram 24 --runtime llama.cpp
python forge_llm_selector.py --task finance_facts --free-vram 4 --active 2 --context 2048
python forge_llm_selector.py --task asr --free-vram 4 --language uk
python -m unittest -q test_forge_llm_catalog.py
```

## Architecture

Treat these as distinct, immutable data layers:

1. **Model registry:** publisher checkpoint ID, official URL, architecture, native supported modalities and task tags, licensing gate. No Ollama tag or quantization inferred from the base checkpoint.
2. **Artifact registry:** concrete revision, file SHA-256, tokenizer/template, GGUF/AWQ/GPTQ/FP8/MXFP4 artifact ID, precision, download location, compliance result, runtime support result.
3. **Runtime/node capability registry:** GPU UUID and architecture, *actual free* VRAM, bandwidth/interconnect, runtime version, available RAM, supported kernels, quotas, scheduling reservations.
4. **Measured deployment profiles:** exact artifact × engine × GPU × context × active slots, peak memory, prefill/decode rates, p50/p95, OOM/error rate, energy (optional), quality benchmark.
5. **Task routing policy:** hard eligibility filters, task-specific benchmark quality gates and priorities, fallback/escalation, historical accepted-output metrics and traceability.

## Routing procedure

1. Use deterministic code / NLP for tasks whose acceptance is exact (dates, numeric facts, regex, math) before involving a general LLM.
2. Infer a typed `task_id`, input modalities, context budget, expected response length, deadline, privacy/tenant policies, required output schema, quality floor, and max active slots.
3. Filter by exact model capabilities, verified language allowlist where available, policy and license; disallow unapproved models in production.
4. Filter by **observed** runtime support and a pinned deployment artifact; do not assume `GGUF`, `Q4`, or MoE implies engine compatibility.
5. Filter by available GPU VRAM and measured peak for requested context/concurrency, plus >=15% headroom (configurable). Do not sum GPU VRAM unless a validated sharding profile exists.
6. Rank by task-specific quality *and* verified throughput/latency (successful tasks per GPU-second is a useful primary measure for Forge workloads), with an optional energy/cost term.
7. Execute with a strict output contract and independent deterministic checks. Retry a larger candidate only if the measured total cost of success justifies escalation.
8. Log source hashes, chosen artifacts, benchmark revision and evidence. Promote only after winning quality/SLO tests against the existing baseline; rollback on regressions.

## Important caveats

- All tier matches are an initial **engineering estimate** for mostly Q4 LLMs, 4K context, one active request. They do NOT certify that a model fits a GPU.
- The `!` marker indicates likely tight fit, aggressive quantization, reduced context, or CPU offload. The `~` marker indicates that model quality is likely inadequate for the purpose even if the model loads. `—` means no candidate.
- MoE **total** parameters (all experts) govern weight memory. Active parameters govern approximate arithmetic requirements, not model residency.
- Vision, ASR, TTS, image and video tasks need their own end-to-end model pipeline profiling. Resolutions, frames, audio lengths and encoder/decoder components can dominate memory.
- Licenses in the dataset are *flags to review*, not legal clearance. Qwen Image 2.1 Turbo is research-licensed and FLUX.2-dev is noncommercial/gated; do not enable them for commercial Forge workloads without authorization.
- The model ID is a Hugging Face repo ID, not an existing artifact at runtime. Validate availability, license, SHA/revision, tokenizer, compatible model files and runtime on the deployment node.
- `forge-llm` can own registry/serving/routing; let `forge-model` continue owning deterministic-first reasoning experiments and reproducible task-quality evaluation, without duplicating those concerns.
- For Ukrainian ASR, NVIDIA Parakeet v3 explicitly supports `uk`; the Qwen3-ASR documented language list does not. For other models, do not assume language support if no exhaustive allowlist is supplied.
- On Granite/T2000 4GB use Qwen3.5-2B Q4 or specialized NLP candidates first; keep 5–10 clients queued, start with 2 measured *active* requests. Do not presume that 10 connected clients imply 10 concurrent GPU sequences.

## Source families

- Qwen official: https://huggingface.co/Qwen/models
- Qwen3.5: https://huggingface.co/collections/Qwen/qwen35
- Gemma 4 official: https://huggingface.co/collections/google/gemma-4
- GPT-OSS: https://huggingface.co/openai/gpt-oss-20b and https://huggingface.co/openai/gpt-oss-120b
- Qwen Embedding: https://huggingface.co/Qwen/Qwen3-Embedding-0.6B
- Qwen3 VL: https://huggingface.co/collections/Qwen/qwen3-vl
- Wan: https://huggingface.co/Wan-AI/Wan2.2-T2V-A14B
- FLUX.2: https://huggingface.co/collections/black-forest-labs/flux2

## Next steps for promotion

1. Probe the installed Granite T2000 4GB GPUs and the EPYC/2×3090 nodes (when installed). Run `nvidia-smi`, gather actual GPU free VRAM and architecture, and enumerate exact local Ollama/GGUF/checkpoint artifacts.
2. Validate a minimal seed batch on each candidate: warm-up, throughput over 10+ representative short requests, latency distribution, peak GPU memory, concurrency 1/2/4, 2K/4K/8K contexts; record exact engine and artifact revisions.
3. Run task-specific golden evaluations. For reasoning integrate the existing `forge-model` 48-case test set and deterministic answer validation; for SEC-FIC use source-grounded financial fact correctness/coverage/contradiction metrics.
4. Promote winner profiles only if they meet the predeclared nonregression criteria and total validated tasks/min improves. Keep baseline artifact and rollback pointer intact.

This archive contains **no actual runtime benchmark measurements**; populated quality/memory metrics would need to be supplied from Forge nodes.
