# Operations runbook

## Initialize

```bash
uv sync --locked
uv run serveshed init
uv run serveshed doctor
uv run serveshed config validate
```

Review `.env` names but never paste its values into issues, logs, traces, or chat.

## Start only the control plane

```bash
uv run serveshed up core
uv run serveshed status
```

Expected localhost services:

- Bifrost: `127.0.0.1:8080`
- Phoenix: `127.0.0.1:6006`

PostgreSQL and OTLP remain on the private Docker network.

## Select and pull a daily candidate

```bash
uv run serveshed model recommend --workload agents
uv run serveshed model show local/qwen-fast
uv run serveshed model pull local/qwen-fast
```

Large downloads require explicit confirmation. Pulling does not make a model accepted or default.

## Start interactive inference

```bash
uv run serveshed up chat
uv run serveshed model inventory
uv run serveshed status
```

The default profile starts at 8K context, one loaded model, and one parallel request. `status` also reports the active Ollama model and its reported CPU/GPU processor split, which is useful when validating whether a candidate fully fits the GPU.

## Measure a model

```bash
uv run serveshed eval smoke --model local/qwen-fast
uv run serveshed eval qwen --model local/qwen-fast
uv run serveshed benchmark run interactive --model local/qwen-fast
uv run serveshed benchmark run throughput --model local/qwen-fast
```

Verify and compare bundles before making a decision.

## Gate promotion

```bash
uv run serveshed model accept \
  --eval-run <evaluation-run> \
  --benchmark-run <benchmark-run> \
  --min-pass-rate 1.0 \
  --min-success-rate 1.0
```

Review `decision.json`, then repeat with `--promote` when the thresholds represent the desired workstation experience.

## Start batch inference

```bash
uv run serveshed up eval
```

This is blocked until `SERVESHED_ENABLE_VLLM=true` and a reviewed `VLLM_MODEL_ID` replace the placeholders. It stops Ollama first.

## Release the GPU

```bash
uv run serveshed gpu-off
nvidia-smi
```

Confirm no serveshed process retains material VRAM before gaming, rendering, video editing, image generation, or another CUDA workload.

## Stop without deleting data

```bash
uv run serveshed down
```

Never use `-v`, `--volumes`, Docker prune, or volume deletion as troubleshooting steps.

## Troubleshooting order

1. `uv run serveshed doctor`
2. `uv run serveshed config validate`
3. `uv run serveshed config validate --docker`
4. `uv run serveshed status`
5. `uv run serveshed logs <service>`
6. `uv run serveshed model inventory`
7. `uv run serveshed runs verify <run-directory>`
8. Inspect `nvidia-smi`, disk, RAM, swap, and container logs.
