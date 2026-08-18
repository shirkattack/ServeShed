# Evaluations

The dependency-free runner is available through:

```bash
uv run serveshed eval smoke --dry-run
uv run serveshed eval qwen --dry-run
uv run serveshed eval smoke --model local/qwen-batch
uv run serveshed eval qwen --model local/qwen-fast
```

Actual runs go through Bifrost and create checksummed bundles under
`$SERVESHED_DATA_DIR/eval-runs/evaluations/<date>/<run-id>/` (benchmarks land under
`benchmarks/`, acceptance decisions under `acceptance/`). Raw prompt/response
content is logged for all traffic, not just eval runs — a deliberate, documented
choice (ADR 0016); treat traces and bundles as sensitive. Deterministic assertions
run before any LLM judge.

Promptfoo runs in its pinned container under the `tools` profile — it tests
Bifrost's own gateway contract, so it stays in this repo. Inspect AI and
lm-evaluation-harness deliberately never enter this repo's lockfile: per ADR 0017
they live in separate repos and connect through Bifrost with their own virtual
keys, like any other client. The `evals/inspect/` and `evals/lm_eval/` directories
hold only thin task definitions those external setups can point at.
