# lm-evaluation-harness integration

Per ADR 0017, the harness never enters this repo's lockfile: it evaluates model content, not the platform, so it lives in its own repo/environment with its own pinned dependencies and connects to Bifrost as an ordinary virtual-key caller. This directory holds only the task definitions an external setup points at.

Initial workflow:

1. Set `SERVESHED_ENABLE_VLLM=true` and pin `VLLM_MODEL_ID` to a verified checkpoint revision.
2. Start `uv run serveshed up eval`.
3. In a separate repo/environment, install a pinned lm-eval release (its own lock, not this repo's).
4. Begin with `evals/lm_eval/tasks/serveshed_exact.yaml`.
5. Preserve raw generations, task config, model revision, quantization, runtime flags, hardware snapshot, and summary in an immutable eval bundle.

Do not use the target model as the only judge. Run deterministic metrics first and load a separate-family judge in a later GPU phase when needed.
