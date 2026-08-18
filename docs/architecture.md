# Architecture

## Design goals

1. Preserve Ubuntu Desktop responsiveness and release the GPU on demand.
2. Keep inference, prompts, traces, eval artifacts, and routing local by default.
3. Give agents one authenticated OpenAI-compatible endpoint and stable aliases.
4. Make measurement and provenance prerequisites for changing the default model.
5. Operate without the Synology and add it later as a durable tier.
6. Avoid hidden cloud fallbacks, retries, substitutions, and caches during evals.

## Components

| Component | Responsibility | GPU | Profile |
|---|---|---:|---|
| PostgreSQL | Phoenix and Bifrost persistence | No | core |
| Phoenix | Trace UI, datasets, experiments, annotations | No | core |
| OTel Collector | Vendor-neutral trace transport | No | core |
| Bifrost | Auth, aliases, per-agent virtual keys, traces | No | core |
| Ollama | Interactive local model serving | Yes | chat |
| Open WebUI | Browser chat interface with history; Bifrost client only | No | chat |
| vLLM | Reviewed quant for concurrency/batch generation | Yes | eval |
| Promptfoo | Containerized gateway regressions | No | tools |
| LiteLLM | Isolated gateway comparison only | No | experimental |
| `serveshed` CLI | Lifecycle, model registry, evals, benchmarks, acceptance | No | host |

## Request routing

Applications send aliases such as `local/qwen-fast` to Bifrost. Provider-key aliases resolve them to Ollama or vLLM artifacts. Virtual keys constrain each agent's providers and models. Static validation rejects permissions that refer to nonexistent provider aliases.

The baseline has no model fallback and sets provider retries to zero. Eval callers attach `x-bf-eh-*` metadata, which Bifrost emits on OpenTelemetry spans.

## Model control loop

```text
registry -> recommend -> pull -> inventory -> eval + benchmark
                                             |
                                      checksum verification
                                             |
                                        acceptance gate
                                             |
                                      optional .env promotion
```

Starting a model is not acceptance. The default changes only through an explicit selection or a passing measured promotion.

## Networking

All published ports bind to `127.0.0.1`. The `backend` Docker network has masquerade (outbound NAT) disabled, so postgres, phoenix, otel-collector, bifrost, and open-webui have no route to the internet, while 127.0.0.1 port publishing for bifrost, phoenix, and open-webui still works; see ADR 0010 for why a Compose-internal network cannot do both. The `egress` network is attached only to inference services that may need approved model downloads. PostgreSQL, Ollama, vLLM, and OTLP are never published directly.

Tailscale Serve, when explicitly approved, proxies localhost Bifrost, Phoenix, and Open WebUI to the tailnet. It does not make services public.

## GPU lifecycle

- `up chat`: stop vLLM, start core and Ollama.
- `up eval`: unload/stop Ollama, validate the vLLM gate, start core and vLLM.
- `gpu-off`: unload Ollama models and stop both serveshed GPU services.
- `down`: stop all profiles without deleting persistent data.

Direct manual Compose commands can bypass these guards and are not the supported operational path.

## Storage

Local NVMe is the hot tier for databases, active model caches, Hugging Face caches, compilation caches, and current eval runs. The future NAS receives immutable completed runs, model archives, datasets, PostgreSQL dumps, and configuration backups after mount-marker validation.
