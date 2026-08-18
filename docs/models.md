# Model policy and measurement workflow

The source of truth is `config/models/registry.yaml`. It uses JSON syntax, which is valid YAML and allows the dependency-free control plane to parse it without PyYAML.

## Current candidate matrix

| Alias | Artifact | Approx. artifact size | Fit intent on 16 GB | Role |
|---|---|---:|---|---|
| `local/qwen-fast` | `qwen3.5:9b` Q4_K_M | 6.6 GiB | Comfortable starting point | Daily default candidate |
| `local/qwen-quality` | `qwen3.5:9b-q8_0` | 11 GiB | Tight as context grows | Quality comparison |
| `experimental/qwen-nvfp4` | `qwen3.5:9b-nvfp4` | 8.9 GiB | Measure on Blackwell | Quantization experiment |
| `experimental/qwen-abliterated` | `huihui_ai/qwen3.5-abliterated:9b-q4_K` | 6.6 GiB | Comfortable starting point | Refusal-ablated research/creative candidate |
| `local/qwen-batch` | Reviewed quantized checkpoint | TBD | Must be measured | vLLM concurrency/batch |
| `local/gemma-judge` | `gemma4:12b` Q4_K_M | 7.4 GiB | Comfortable starting point | Cross-family judge |
| `experimental/hermes-agent` | Reviewed Hermes 4 14B artifact | TBD | Likely tight | Tool/JSON challenger |
| `experimental/qwen38-offload` | `qwen3.8:27b` Q4_K_M + projector | 18 GiB | CPU offload required | Occasional large comparison |
| `local/embed` | TBD | TBD | Separate evaluation | Embeddings/RAG |

Artifact size is not total VRAM use. Context/KV cache, runtime buffers, multimodal components, and the Ubuntu display also consume memory. The configured 8K context is a conservative workstation profile, not a claim about the model's architectural maximum.

## Why Qwen3.5-9B is the baseline

Qwen3.5-9B retains multimodal input, tool-use support, reasoning modes, and official vLLM guidance while offering practical Ollama quantizations for a 16 GB GPU. The official source model advertises a much larger context window, but this project begins at 8K and expands only after measuring memory and stability.

The Q4 profile is the default candidate. Q8 is a quality ceiling for comparison, not automatically the better desktop choice. NVFP4 is explicitly experimental until throughput, quality, and runtime behavior are measured on the RTX 5070 Ti.

## Qwen3.8-27B policy

Qwen3.8-27B remains available only as `experimental/qwen38-offload`.

Rules:

- It is never selected automatically.
- Concurrency stays at one.
- Initial context is 4096.
- Keep-alive is zero so it unloads after use.
- CPU offload and reduced desktop responsiveness are expected.
- It cannot pass the default-model gate solely by starting successfully.
- It must beat smaller candidates on user-relevant quality enough to justify its latency and memory cost.

## Abliterated model policy

`experimental/qwen-abliterated` (`huihui_ai/qwen3.5-abliterated:9b-q4_K`) is a refusal-ablated variant of the same Qwen3.5-9B base as `local/qwen-fast`. Abliteration is activation-space editing — it removes the refusal circuit, not a retrained model — so most other behavior is unchanged, but the maintainer's own model card describes the implementation as a "crude, proof-of-concept" with no rigorous safety review, and independent benchmarking shows measurable degradation on truthfulness/coherence metrics versus the unmodified base.

Rules:

- Never used in the judge (`local/gemma-judge`) or eval-grader role — an uncensored judge undermines the judging function.
- Treated as experimental until measured the same as any other candidate; a successful pull is not acceptance.
- Only `huihui_ai` (the current most active, highest-track-record maintainer on Ollama for this specific technique) is used as a source for now — not arbitrary community abliteration uploads, per the general "do not fill placeholders with arbitrary community artifacts" rule.

## vLLM policy

`local/qwen-batch` is a routing and lifecycle contract, not an accepted model artifact. Before enabling vLLM:

1. Select a quantized checkpoint with clear provenance.
2. Pin repository, revision, file set, tokenizer/template, license, and immutable digest.
3. Set `VLLM_MODEL_ID`, `VLLM_SERVED_MODEL_NAME`, and `SERVESHED_ENABLE_VLLM=true` in `.env`.
4. Validate the container and parser flags against the pinned vLLM release.
5. Start with 8K context, two sequences, and 0.80 GPU utilization.
6. Run the same deterministic eval and benchmark suites used for Ollama.

Do not silently replace the review-gated vLLM profile with an arbitrary community quant.

## Hermes policy

Hermes 4 14B remains an important structured-output and tool-use challenger. The registry intentionally leaves its artifact blank until the exact GGUF or Ollama artifact, chat template, license, checksum, and memory behavior are reviewed. Hermes Agent itself uses Bifrost and may target `local/qwen-fast` before a Hermes model is accepted.

The name collision is coincidental, not structural: "Hermes Agent" (the client, `docs/handoff.md`) and `experimental/hermes-agent` (this model alias, NousResearch's Hermes 4 14B) are unrelated. Hermes Agent doesn't default to the Hermes model, and the Hermes model isn't specific to the Hermes Agent client.

## Judge policy

Use deterministic graders first. Generate target outputs, unload the target, load `local/gemma-judge`, and judge saved outputs in a separate phase. Calibrate local judge scores against human-reviewed examples and never treat one local model as an unquestioned oracle.

## Commands

Recommend models:

```bash
uv run serveshed model recommend --workload general
uv run serveshed model recommend --vram-gib 16 --workload agents --tools
uv run serveshed model recommend --vram-gib 16 --workload multimodal --multimodal
uv run serveshed model recommend --vram-gib 16 --workload evaluation --include-experimental
```

Inspect and pull:

```bash
uv run serveshed model list
uv run serveshed model show local/qwen-fast
uv run serveshed model pull local/qwen-fast
uv run serveshed model inventory
```

Measure:

```bash
uv run serveshed eval smoke --model local/qwen-fast
uv run serveshed eval qwen --model local/qwen-fast
uv run serveshed benchmark run interactive --model local/qwen-fast
uv run serveshed benchmark run throughput --model local/qwen-fast
```

Accept and optionally promote:

```bash
uv run serveshed model accept \
  --eval-run <evaluation-run> \
  --benchmark-run <benchmark-run> \
  --min-pass-rate 1.0 \
  --min-success-rate 1.0 \
  --min-tokens-per-second 20 \
  --max-median-latency-ms 5000

uv run serveshed model accept \
  --eval-run <evaluation-run> \
  --benchmark-run <benchmark-run> \
  --min-pass-rate 1.0 \
  --min-success-rate 1.0 \
  --promote
```

Promotion verifies both source bundles and records an immutable acceptance decision. A rejected model is not written to `.env`.

## Required provenance

Before a profile moves beyond measurement-only status, record:

- upstream repository and immutable revision
- runtime artifact/tag and full local digest
- quantization producer and method
- tokenizer, processor, projector, and chat-template provenance
- runtime/container version and digest
- context, KV cache, parallelism, thinking mode, and sampling configuration
- GPU driver, CUDA/runtime, VRAM, RAM, swap, and desktop load
- cold load, time to first token, total latency, prompt rate, output rate, and errors
- deterministic eval bundle, benchmark bundle, and acceptance decision bundle

## Upstream references

- Qwen3.5-9B: https://huggingface.co/Qwen/Qwen3.5-9B
- Ollama Qwen3.5 9B Q4: https://ollama.com/library/qwen3.5:9b
- Ollama Qwen3.5 9B Q8: https://ollama.com/library/qwen3.5:9b-q8_0
- Ollama Qwen3.5 9B NVFP4: https://ollama.com/library/qwen3.5:9b-nvfp4
- Gemma 4 12B: https://huggingface.co/google/gemma-4-12B
- Ollama Gemma 4 12B: https://ollama.com/library/gemma4:12b
- Hermes 4 14B: https://huggingface.co/NousResearch/Hermes-4-14B
- Qwen3.8-27B: https://huggingface.co/Qwen/Qwen3.8-27B
- Ollama Qwen3.8 27B: https://ollama.com/library/qwen3.8:27b
