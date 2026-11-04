# Forge-LLM task × VRAM matrix (2026-11-03)

**Scope**: candidate shortlists only. Single-request 4K context, Q4 for language models by default. `!` = tight / quantized offload; `~` = insufficient quality for complex task; `—` = no recommendation. Larger tiers sometimes reuse smaller specialized models.

| Workload / VRAM | 2GB | 4GB | 8GB | 16GB | 24GB | 32GB | 48GB | 64GB | 96GB |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Deterministic & NLP** |  |  |  |  |  |  |  |  |  |
| Intent / request routing | `Q08`, `NERM`! | `Q2`, `NERL` | `Q2`, `Q4` | `Q2`, `Q4` | `Q2`, `Q4` | `Q2`, `Q4` | `Q2`, `Q4` | `Q2`, `Q4` | `Q2`, `Q4` |
| Text and document classification | `Q08` | `Q2` | `Q4`, `Q2` | `Q4`, `Q9` | `Q4`, `Q9` | `Q4`, `Q9` | `Q4`, `Q9` | `Q4`, `Q9` | `Q4`, `Q9` |
| Named entity recognition / span extraction | `NERS`, `NERM`! | `NERL`, `NERM` | `NERL`, `Q4` | `NERL`, `Q9` | `NERL`, `Q27` | `NERL`, `Q36` | `NERL`, `G31` | `NERL`, `NEXT80` | `NERL`, `Q122` |
| Financial facts / SEC extraction | `NERM`, `Q08` | `NERL`, `Q2` | `NERL`, `Q9` | `Q9`, `G12` | `Q38`, `G31` | `Q36`, `G31` | `Q36`, `G31` | `NEXT80`, `Q38` | `Q122`, `OSS120` |
| Schema-bound JSON / structured extraction | `Q08` | `Q2` | `Q4` | `Q9`, `G12` | `Q38`, `G31` | `Q36`, `G31` | `G31`, `Q36` | `NEXT80`, `Q38` | `OSS120`, `Q122` |
| Entity resolution / relationship extraction | `NERM`, `Q08` | `NERL`, `Q2` | `Q4`, `Q2` | `Q9`, `G12` | `Q38`, `G31` | `Q36`, `G31` | `G31`, `Q36` | `NEXT80`, `Q38` | `Q122`, `OSS120` |
| Prompt safety / content policy classification | `GU06` | `GU06` | `GU06` | `GU4` | `GU8` | `GU8` | `GU8` | `GU8` | `GU8` |
| **Knowledge / retrieval** |  |  |  |  |  |  |  |  |  |
| Text embeddings / semantic retrieval | `EG300`, `E06` | `E06`, `BM3` | `E06`, `BM3` | `E4`, `BM3` | `E8`, `E4` | `E8`, `E4` | `E8`, `E4` | `E8`, `E4` | `E8`, `E4` |
| Hybrid lexical + semantic search | `BM3` | `BM3`, `E06` | `BM3`, `E06` | `BM3`, `E4` | `BM3`, `E8` | `BM3`, `E8` | `BM3`, `E8` | `BM3`, `E8` | `BM3`, `E8` |
| Search reranking / relevance scoring | `R06` | `R06` | `R06` | `R4` | `R8` | `R8` | `R8` | `R8` | `R8` |
| Repository / code embeddings | `BM3`, `E06` | `BM3`, `E06` | `BM3`, `E06` | `E4`, `BM3` | `E8`, `E4` | `E8`, `E4` | `E8`, `E4` | `E8`, `E4` | `E8`, `E4` |
| Image and video semantic search | — | — | `VE2`!, `VR2`! | `VE2`, `VR2` | `VE8`, `VR8` | `VE8`, `VR8` | `VE8`, `VR8` | `VE8`, `VR8` | `VE8`, `VR8` |
| **Text / reasoning** |  |  |  |  |  |  |  |  |  |
| Conversational instructions / writing | `Q08` | `Q2`, `MIN3` | `Q4`, `GN4` | `Q9`, `G12` | `Q38`, `G31` | `G31`, `Q36` | `Q36`, `G31` | `NEXT80`, `L70` | `OSS120`, `Q122` |
| Short/medium document summaries | `Q08` | `Q2` | `Q4` | `G12`, `Q9` | `Q38`, `G31` | `Q36`, `G31` | `Q36`, `G31` | `NEXT80`, `L70` | `OSS120`, `Q122` |
| Long-form evidence-grounded synthesis | — | `Q2`~ | `Q4`~ | `G12`, `Q9` | `Q38`, `G31` | `Q36`, `G31` | `Q36`, `G31` | `NEXT80`, `L70` | `OSS120`, `Q122` |
| Multilingual translation / localization | `Q08`~ | `Q2` | `Q4`, `GN4` | `G12`, `Q9` | `Q38`, `G31` | `G31`, `Q36` | `G31`, `Q36` | `NEXT80`, `Q38` | `Q122`, `OSS120` |
| Simple planning / semantic reasoning | `Q08`~ | `Q2` | `Q4`, `GN4` | `G12`, `OSS20`! | `Q38`, `G31` | `G31`, `Q36` | `Q36`, `G31` | `NEXT80`, `L70` | `OSS120`, `Q122` |
| Deep multi-hop reasoning / critique | — | `Q2`~ | `Q9`~ | `OSS20`!, `G12` | `G31`, `Q38` | `G31`, `Q36` | `G31`, `Q36` | `NEXT80`, `L70` | `OSS120`, `Q122` |
| Tool selection / multi-step agents | `Q08`~ | `Q2`, `MIN3` | `Q4`, `GN4` | `OSS20`!, `G12` | `C30`!, `Q38` | `Q36`, `C30` | `Q36`, `G31` | `CN80`, `NEXT80` | `OSS120`, `Q122` |
| Workflow DAG / orchestration planning | — | `Q2`~ | `Q4`~ | `OSS20`!, `G12` | `Q38`, `G31` | `Q36`, `G31` | `G31`, `Q36` | `NEXT80`, `CN80` | `OSS120`, `Q122` |
| **Coding** |  |  |  |  |  |  |  |  |  |
| Code completion / small patches | `C05` | `C3`, `C15` | `C7`, `Q4` | `C14`, `Q9` | `C30`!, `C32`! | `C30`, `Q36` | `CN80`!, `C30` | `CN80`, `Q36` | `CN80`, `OSS120` |
| Functions / modules / test generation | `C05`~ | `C3` | `C7` | `C14`, `G12` | `C30`!, `C32`! | `C30`, `Q36` | `CN80`!, `Q36` | `CN80`, `Q36` | `CN80`, `OSS120` |
| Repository-scale coding / debugging | — | `C3`~ | `C7`~ | `C14`, `Q9` | `C30`!, `C32`! | `Q36`, `C30` | `CN80`!, `Q36` | `CN80`, `Q36` | `CN80`, `OSS120` |
| Security review / defect detection | — | `C3`~ | `C7` | `C14`, `G12` | `C30`!, `Q38` | `Q36`, `C30` | `CN80`!, `Q36` | `CN80`, `Q36` | `OSS120`, `CN80` |
| Test case generation / formal checks | `C05`~ | `C3` | `C7` | `C14`, `G12` | `C30`!, `Q38` | `Q36`, `G31` | `CN80`!, `G31` | `CN80`, `Q36` | `OSS120`, `CN80` |
| **Vision / documents** |  |  |  |  |  |  |  |  |  |
| Text OCR / document parsing | — | `FLO`, `VL2`! | `VL4`, `FLO` | `VL8`, `G12` | `VL30`!, `Q38` | `VL32`, `Q38` | `VL32`, `Q38` | `Q38`, `G31` | `Q38`, `G31` |
| Charts, tables and financial statement images | — | `VL2`! | `VL4` | `VL8`, `G12` | `VL30`!, `Q38` | `VL32`, `Q38` | `VL32`, `Q38` | `Q38`, `G31` | `Q38`, `G31` |
| Screenshot / web UI understanding | — | `VL2`! | `VL4`, `GN4` | `VL8`, `G12` | `VL30`!, `Q38` | `VL32`, `Q38` | `VL32`, `Q38` | `Q38`, `G31` | `Q38`, `G31` |
| Video frames / scene description | — | `VL2`! | `VL4` | `VL8`, `G12` | `Q38`, `VL30`! | `Q38`, `VL32` | `Q38`, `VL32` | `Q38`, `VL32` | `Q38`, `VL32` |
| **Audio** |  |  |  |  |  |  |  |  |  |
| Audio transcription multilingual | `WS`, `WT` | `PAR`, `WLT` | `WL`, `AS17` | `WL`, `AS17` | `WL`, `AS17` | `WL`, `AS17` | `WL`, `AS17` | `WL`, `AS17` | `WL`, `AS17` |
| Forced alignment / word timestamps | — | `ALIGN` | `ALIGN` | `ALIGN` | `ALIGN` | `ALIGN` | `ALIGN` | `ALIGN` | `ALIGN` |
| Text-to-speech synthesis | `KOK` | `TTS06`, `KOK` | `TTS17`, `KOK` | `TTS17`, `KOK` | `TTS17`, `KOK` | `TTS17`, `KOK` | `TTS17`, `KOK` | `TTS17`, `KOK` | `TTS17`, `KOK` |
| Speech to translated text | `WT`~ | `AS06` | `AS17` | `G12`, `AS17` | `G12`, `AS17` | `G12`, `AS17` | `G12`, `AS17` | `G12`, `AS17` | `G12`, `AS17` |
| **Media generation** |  |  |  |  |  |  |  |  |  |
| Text-to-image generation | — | `SD15`! | `SDXL`! | `FK4`, `SD35` | `FK9`, `QI21`! | `FK9`, `QI21` | `FD32`!, `FK9` | `FD32`, `FK9` | `FD32`, `FK9` |
| Image-to-image / controlled editing | — | `SD15`! | `SDXL`! | `FK4`, `SD35` | `FK9`, `QI21`! | `FK9`, `QI21` | `FD32`!, `FK9` | `FD32`, `FK9` | `FD32`, `FK9` |
| Text-to-video generation | — | — | — | `LTX`! | `WAN5`!, `LTX` | `WAN5`!, `LTX` | `HUN`!, `WAN5` | `HUN`, `WAN5` | `WAN14`, `HUN` |
| Image-to-video / video continuation | — | — | — | `LTX`! | `WAN5`!, `LTX` | `WAN5`!, `LTX` | `HUN`!, `WAN5` | `HUN`, `WAN5` | `WANI14`, `HUN` |
| **Forecasting** |  |  |  |  |  |  |  |  |  |
| Time-series forecasting / numeric sequences | — | `TF3` | `TF3` | `TF3` | `TF3` | `TF3` | `TF3` | `TF3` | `TF3` |
| **Adaptation** |  |  |  |  |  |  |  |  |  |
| QLoRA / lightweight fine-tuning (experimental) | — | — | `Q08`! | `Q2`!, `Q08` | `Q4`!, `Q2` | `Q9`!, `Q4` | `Q9`, `Q4` | `Q27`!, `Q9` | `G31`!, `Q27` |

## Alias → model repository

| Alias | Official model ID | Min nominal tier | Precision | License gate |
|---|---|---:|---|---|
| `Q08` | [Qwen/Qwen3.5-0.8B](https://huggingface.co/Qwen/Qwen3.5-0.8B) | 2 GB | Q4 | apache-2.0 |
| `Q2` | [Qwen/Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B) | 4 GB | Q4 | apache-2.0 |
| `Q4` | [Qwen/Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) | 8 GB | Q4 | apache-2.0 |
| `Q9` | [Qwen/Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B) | 8 GB | Q4 | apache-2.0 |
| `Q27` | [Qwen/Qwen3.5-27B](https://huggingface.co/Qwen/Qwen3.5-27B) | 24 GB | Q4 | apache-2.0 |
| `Q35` | [Qwen/Qwen3.5-35B-A3B](https://huggingface.co/Qwen/Qwen3.5-35B-A3B) | 24 GB | Q4 | apache-2.0 |
| `Q36` | [Qwen/Qwen3.6-35B-A3B](https://huggingface.co/Qwen/Qwen3.6-35B-A3B) | 24 GB | Q4 | apache-2.0 |
| `Q38` | [Qwen/Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B) | 24 GB | Q4 | apache-2.0 |
| `Q122` | [Qwen/Qwen3.5-122B-A10B](https://huggingface.co/Qwen/Qwen3.5-122B-A10B) | 96 GB | Q4 | apache-2.0 |
| `GN2` | [google/gemma-4-E2B-it](https://huggingface.co/google/gemma-4-E2B-it) | 4 GB | Q4 | gemma-license |
| `GN4` | [google/gemma-4-E4B-it](https://huggingface.co/google/gemma-4-E4B-it) | 8 GB | Q4 | gemma-license |
| `G12` | [google/gemma-4-12B-it](https://huggingface.co/google/gemma-4-12B-it) | 16 GB | Q4 | gemma-license |
| `G26` | [google/gemma-4-26B-A4B-it](https://huggingface.co/google/gemma-4-26B-A4B-it) | 24 GB | Q4 | gemma-license |
| `G31` | [google/gemma-4-31B-it](https://huggingface.co/google/gemma-4-31B-it) | 24 GB | Q4 | gemma-license |
| `OSS20` | [openai/gpt-oss-20b](https://huggingface.co/openai/gpt-oss-20b) | 16 GB | MXFP4 | apache-2.0 |
| `OSS120` | [openai/gpt-oss-120b](https://huggingface.co/openai/gpt-oss-120b) | 96 GB | MXFP4 | apache-2.0 |
| `NEXT80` | [Qwen/Qwen3-Next-80B-A3B-Thinking](https://huggingface.co/Qwen/Qwen3-Next-80B-A3B-Thinking) | 48 GB | Q3 | apache-2.0 |
| `LC1` | [meta-llama/Llama-3.2-1B-Instruct](https://huggingface.co/meta-llama/Llama-3.2-1B-Instruct) | 2 GB | Q4 | llama-community-license |
| `LC3` | [meta-llama/Llama-3.2-3B-Instruct](https://huggingface.co/meta-llama/Llama-3.2-3B-Instruct) | 4 GB | Q4 | llama-community-license |
| `L70` | [meta-llama/Llama-3.3-70B-Instruct](https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct) | 48 GB | Q4 | llama-community-license |
| `MIN3` | [mistralai/Ministral-3-3B-Instruct-2512](https://huggingface.co/mistralai/Ministral-3-3B-Instruct-2512) | 4 GB | Q4 | review |
| `MIN8` | [mistralai/Ministral-3-8B-Instruct-2512](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512) | 8 GB | Q4 | review |
| `MIN14` | [mistralai/Ministral-3-14B-Instruct-2512](https://huggingface.co/mistralai/Ministral-3-14B-Instruct-2512) | 16 GB | Q4 | review |
| `C05` | [Qwen/Qwen2.5-Coder-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-0.5B-Instruct) | 2 GB | Q4 | apache-2.0 |
| `C15` | [Qwen/Qwen2.5-Coder-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct) | 4 GB | Q4 | apache-2.0 |
| `C3` | [Qwen/Qwen2.5-Coder-3B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct) | 4 GB | Q4 | apache-2.0 |
| `C7` | [Qwen/Qwen2.5-Coder-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct) | 8 GB | Q4 | apache-2.0 |
| `C14` | [Qwen/Qwen2.5-Coder-14B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-14B-Instruct) | 16 GB | Q4 | apache-2.0 |
| `C32` | [Qwen/Qwen2.5-Coder-32B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-32B-Instruct) | 24 GB | Q4 | apache-2.0 |
| `C30` | [Qwen/Qwen3-Coder-30B-A3B-Instruct](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct) | 24 GB | Q4 | apache-2.0 |
| `CN80` | [Qwen/Qwen3-Coder-Next](https://huggingface.co/Qwen/Qwen3-Coder-Next) | 48 GB | Q3 | apache-2.0 |
| `EG300` | [google/embeddinggemma-300m](https://huggingface.co/google/embeddinggemma-300m) | 2 GB | FP16 | gemma-license |
| `EG2` | [google/embeddinggemma-2](https://huggingface.co/google/embeddinggemma-2) | 2 GB | FP16 | gemma-license |
| `BM3` | [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) | 2 GB | FP16 | mit |
| `E06` | [Qwen/Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) | 2 GB | FP16 | apache-2.0 |
| `E4` | [Qwen/Qwen3-Embedding-4B](https://huggingface.co/Qwen/Qwen3-Embedding-4B) | 16 GB | FP16 | apache-2.0 |
| `E8` | [Qwen/Qwen3-Embedding-8B](https://huggingface.co/Qwen/Qwen3-Embedding-8B) | 24 GB | FP16 | apache-2.0 |
| `R06` | [Qwen/Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) | 2 GB | FP16 | apache-2.0 |
| `R4` | [Qwen/Qwen3-Reranker-4B](https://huggingface.co/Qwen/Qwen3-Reranker-4B) | 16 GB | FP16 | apache-2.0 |
| `R8` | [Qwen/Qwen3-Reranker-8B](https://huggingface.co/Qwen/Qwen3-Reranker-8B) | 24 GB | FP16 | apache-2.0 |
| `VE2` | [Qwen/Qwen3-VL-Embedding-2B](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B) | 8 GB | FP16 | apache-2.0 |
| `VE8` | [Qwen/Qwen3-VL-Embedding-8B](https://huggingface.co/Qwen/Qwen3-VL-Embedding-8B) | 24 GB | FP16 | apache-2.0 |
| `VR2` | [Qwen/Qwen3-VL-Reranker-2B](https://huggingface.co/Qwen/Qwen3-VL-Reranker-2B) | 8 GB | FP16 | apache-2.0 |
| `VR8` | [Qwen/Qwen3-VL-Reranker-8B](https://huggingface.co/Qwen/Qwen3-VL-Reranker-8B) | 24 GB | FP16 | apache-2.0 |
| `NERS` | [urchade/gliner_small-v2.1](https://huggingface.co/urchade/gliner_small-v2.1) | 2 GB | FP16 | apache-2.0 |
| `NERM` | [urchade/gliner_multi-v2.1](https://huggingface.co/urchade/gliner_multi-v2.1) | 2 GB | FP16 | apache-2.0 |
| `NERL` | [urchade/gliner_large-v2.1](https://huggingface.co/urchade/gliner_large-v2.1) | 4 GB | FP16 | apache-2.0 |
| `GU06` | [Qwen/Qwen3Guard-Stream-0.6B](https://huggingface.co/Qwen/Qwen3Guard-Stream-0.6B) | 2 GB | FP16 | apache-2.0 |
| `GU4` | [Qwen/Qwen3Guard-Stream-4B](https://huggingface.co/Qwen/Qwen3Guard-Stream-4B) | 16 GB | FP16 | apache-2.0 |
| `GU8` | [Qwen/Qwen3Guard-Stream-8B](https://huggingface.co/Qwen/Qwen3Guard-Stream-8B) | 24 GB | FP16 | apache-2.0 |
| `VL2` | [Qwen/Qwen3-VL-2B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct) | 4 GB | Q4 | apache-2.0 |
| `VL4` | [Qwen/Qwen3-VL-4B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct) | 8 GB | Q4 | apache-2.0 |
| `VL8` | [Qwen/Qwen3-VL-8B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct) | 16 GB | Q4 | apache-2.0 |
| `VL30` | [Qwen/Qwen3-VL-30B-A3B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-30B-A3B-Instruct) | 24 GB | Q4 | apache-2.0 |
| `VL32` | [Qwen/Qwen3-VL-32B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-32B-Instruct) | 24 GB | Q4 | apache-2.0 |
| `FLO` | [microsoft/Florence-2-base](https://huggingface.co/microsoft/Florence-2-base) | 4 GB | FP16 | mit |
| `WT` | [openai/whisper-tiny](https://huggingface.co/openai/whisper-tiny) | 2 GB | FP16 | mit |
| `WB` | [openai/whisper-base](https://huggingface.co/openai/whisper-base) | 2 GB | FP16 | mit |
| `WS` | [openai/whisper-small](https://huggingface.co/openai/whisper-small) | 2 GB | FP16 | mit |
| `WM` | [openai/whisper-medium](https://huggingface.co/openai/whisper-medium) | 4 GB | FP16 | mit |
| `WL` | [openai/whisper-large-v3](https://huggingface.co/openai/whisper-large-v3) | 8 GB | FP16 | mit |
| `WLT` | [openai/whisper-large-v3-turbo](https://huggingface.co/openai/whisper-large-v3-turbo) | 4 GB | FP16 | mit |
| `PAR` | [nvidia/parakeet-tdt-0.6b-v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) | 4 GB | FP16 | review |
| `AS06` | [Qwen/Qwen3-ASR-0.6B-hf](https://huggingface.co/Qwen/Qwen3-ASR-0.6B-hf) | 4 GB | FP16 | apache-2.0 |
| `AS17` | [Qwen/Qwen3-ASR-1.7B-hf](https://huggingface.co/Qwen/Qwen3-ASR-1.7B-hf) | 8 GB | FP16 | apache-2.0 |
| `ALIGN` | [Qwen/Qwen3-ForcedAligner-0.6B-hf](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B-hf) | 4 GB | FP16 | apache-2.0 |
| `KOK` | [hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) | 2 GB | FP16 | apache-2.0 |
| `TTS06` | [Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice) | 4 GB | FP16 | apache-2.0 |
| `TTS17` | [Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice) | 8 GB | FP16 | apache-2.0 |
| `SD15` | [stable-diffusion-v1-5/stable-diffusion-v1-5](https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5) | 4 GB | FP16 | openrail |
| `SDXL` | [stabilityai/stable-diffusion-xl-base-1.0](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0) | 8 GB | FP16 | openrail |
| `SD35` | [stabilityai/stable-diffusion-3.5-medium](https://huggingface.co/stabilityai/stable-diffusion-3.5-medium) | 16 GB | FP16 | stability-community |
| `FK4` | [black-forest-labs/FLUX.2-klein-4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B) | 16 GB | FP8 | review |
| `FK9` | [black-forest-labs/FLUX.2-klein-9B](https://huggingface.co/black-forest-labs/FLUX.2-klein-9B) | 24 GB | FP8 | review |
| `FD32` | [black-forest-labs/FLUX.2-dev](https://huggingface.co/black-forest-labs/FLUX.2-dev) | 48 GB | quantized | flux-non-commercial |
| `QI21` | [Qwen/Qwen-Image-2.1-Turbo](https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo) | 24 GB | BF16 | qwen-research |
| `LTX` | [Lightricks/LTX-Video](https://huggingface.co/Lightricks/LTX-Video) | 16 GB | quantized | review |
| `WAN5` | [Wan-AI/Wan2.2-TI2V-5B](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B) | 24 GB | offload | apache-2.0 |
| `WAN14` | [Wan-AI/Wan2.2-T2V-A14B](https://huggingface.co/Wan-AI/Wan2.2-T2V-A14B) | 96 GB | BF16 | apache-2.0 |
| `WANI14` | [Wan-AI/Wan2.2-I2V-A14B](https://huggingface.co/Wan-AI/Wan2.2-I2V-A14B) | 96 GB | BF16 | apache-2.0 |
| `HUN` | [tencent/HunyuanVideo-1.5](https://huggingface.co/tencent/HunyuanVideo-1.5) | 48 GB | quantized | review |
| `TF3` | [google/timesfm-3.0-pytorch](https://huggingface.co/google/timesfm-3.0-pytorch) | 4 GB | FP16 | review |

## Implementation

- Use JSON as the source of truth, the matrix as human-readable view.
- Models are *unapproved candidates*. A scheduler must not treat editorial VRAM tiers as measured capacity.
- Actual deployment requires exact artifact revision/checksum, serving runtime, license, GPU model, peak VRAM and quality gate.
- Do not schedule multimodal generation based on parameter counts.
- Unverified model/runtime/precision combinations are rejected by default.
