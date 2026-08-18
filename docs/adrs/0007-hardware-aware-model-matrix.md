# ADR 0007: Hardware-aware model matrix

- Status: accepted for measurement
- Date: 2026-08-14

## Decision

Use `local/qwen-fast` (`qwen3.5:9b`, Q4_K_M) as the default daily candidate on the 16 GB RTX 5070 Ti. Keep Q8 and NVFP4 Qwen3.5 variants as measured comparisons, Gemma 4 12B as the cross-family judge, Hermes 4 14B and the vLLM quant as review-gated candidates, and Qwen3.8-27B as an offload-only experiment.

## Consequences

Model selection is workload- and hardware-aware. Advertised architectural context is not the workstation operating context. No candidate becomes accepted merely because it starts; it must produce eval, benchmark, provenance, and acceptance artifacts.
