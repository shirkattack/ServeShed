# Inspect AI integration

Per ADR 0017, Inspect AI is a *consumer* of this platform, not part of it: it
evaluates model content and capability, so it lives in its own repo/environment
with its own locked dependencies and connects to Bifrost exactly like any other
client — OpenAI-compatible endpoint, dedicated virtual key, explicit
`allowed_models` list. Its dependency tree never enters this repo's `uv.lock`.

This directory holds only a thin task definition (`smoke.py`) that an external
Inspect setup can point at.

From that separate environment (with `inspect-ai` installed there, not here):

```bash
export OPENAI_API_KEY="<the Inspect virtual key issued for this consumer>"
inspect eval path/to/serveshed/evals/inspect/smoke.py \
  --model openai/ollama/local/qwen-fast \
  --model-base-url http://127.0.0.1:8080/v1 \
  --temperature 0 \
  --max-connections 1
```

Treat the command as a host-validation target. Confirm the current Inspect
OpenAI-compatible adapter behavior before accepting results, and store its log
directory under `$SERVESHED_DATA_DIR/eval-runs`. Results are supplementary
evidence reviewed by hand unless the external repo emits bundles in the ADR 0008
schema, which is the only path into `model accept`.
