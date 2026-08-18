# ADR 0005: Qwen3.8-27B as the primary quality model

- Status: superseded by ADR 0007
- Date: 2026-08-14

## Original decision

Use the Ollama `qwen3.8:27b` artifact as the on-demand quality model with 4096 context, concurrency one, short keep-alive, and measured CPU offload.

## Supersession

The artifact is larger than the GPU's physical VRAM before runtime and desktop overhead. ADR 0007 replaces it with a hardware-aware Qwen3.5-9B daily/quality matrix and retains Qwen3.8 only as an explicit offload experiment.
