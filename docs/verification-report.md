# Verification report

This report has two parts:

1. **Build-environment verification** (2026-08-14, release 0.2.0) — repository logic, offline packaging, static configuration contracts, and archive hygiene, verified without hardware. Counts in that part (tests, profiles, validation passes) are a snapshot as of 0.2.0; the suite has since grown (71 tests, 9 registry aliases at the time of the host verification below).
2. **Host verification** (2026-08-15/16) — what was then exercised end to end on the real Ubuntu Desktop with the RTX 5070 Ti.

## Part 2: Host verification (2026-08-15/16)

Performed on the target machine: Ubuntu 24.04 Desktop, RTX 5070 Ti 16 GB, native Docker Engine with the NVIDIA Container Toolkit. Verified live, not inferred:

- `uv run serveshed config validate --docker` passes with the generated `.env` (authoritative Compose render).
- All four core services (PostgreSQL, Phoenix, OTel Collector, Bifrost) start healthy, publish only `127.0.0.1` ports, and persist across restarts.
- Backend network egress is genuinely blocked at the Docker bridge level while localhost publishing still works — the bugs found getting there are ADRs 0010 and 0012.
- Bifrost authentication is enforced; pinned `v1.6.10` required the startup workarounds recorded in ADRs 0011 and 0013, and its missing token-limit forwarding to Ollama is documented as a standing condition in ADR 0018.
- GPU passthrough into containers works; `gpu-off` releases serveshed GPU memory, confirmed with `nvidia-smi`.
- `local/qwen-fast` (`qwen3.5:9b`) pulled, loaded, and exercised through Bifrost; the smoke eval suite ran live (and caught a mis-specified case, fixed — mean latency on it dropped from 25.0 s to 2.6 s).
- One streaming and one non-streaming completion traced end to end into Phoenix; content logging is deliberately on for all traffic (ADR 0016).
- Open WebUI runs as a Bifrost-only client in multi-account mode (ADRs 0014–0015).
- Tailscale Serve access verified from a real remote browser session; the CORS/origin failure it exposed and the config-rendering fix are ADR 0019.
- The `homelab` → `serveshed` rename was re-verified end to end against the live stack, which surfaced and fixed several latent defects (see the changelog).

Still pending on the host: immutable image digests (ADR 0006 remains provisional), the full qwen eval and benchmark suites plus an acceptance decision for `local/qwen-fast`, the vLLM quantized candidate review, the judge workflow, Hermes Agent key validation, LiteLLM comparison, and Synology — tracked in `docs/handoff.md`.

## Part 1: Build-environment verification (2026-08-14, release 0.2.0)

- Project: `serveshed`
- Release: `0.2.0`
- Verification date: 2026-08-14
- Build interpreter: CPython 3.13.5
- Supported project range: Python `>=3.12,<3.14`
- Build package manager: `uv 0.10.0`
- Verification scope: repository logic, offline packaging, static configuration contracts, and archive hygiene

## Verified in the build environment

### Python control plane

- `uv lock --check --offline --python python3.13` completed successfully.
- `uv sync --locked --offline --python python3.13` completed from the committed lock.
- Every module under `src/serveshed` imports and compiles successfully.
- Python under `src`, `tests`, `examples`, and `evals/inspect` compiles successfully.
- 50 tests pass with the standard-library `unittest` runner.
- The same 50 tests pass with the independently available `pytest` runner.
- The installed CLI reports `serveshed 0.2.0`.
- An isolated wheel installation runs the console entry point and all repository configuration checks.

### Implemented 0.2 control-plane behavior

Tests exercise and verify:

- hardware-aware model registry loading, fit classification, recommendation, and safe default selection;
- explicit model pulls and parsed Ollama inventory;
- active Ollama model parsing, including reported CPU/GPU processor split;
- mutually exclusive Ollama and vLLM lifecycle planning;
- full-path benchmark planning, warmup handling, token and latency metrics, and comparisons;
- deterministic evaluation planning, multimodal input materialization, grading, metrics, and comparisons;
- exact selected-input JSONL archives when a run uses `--limit`;
- separate source-dataset and selected-input SHA-256 digests;
- immutable evaluation, benchmark, and acceptance bundles;
- model acceptance thresholds and promotion blocking on failed gates;
- checksum mismatch, missing-file, untracked-file, symlink, and unsafe-path detection;
- Bifrost request construction, trace metadata, virtual-key/model access contracts, and alias resolution;
- fail-closed NAS backup behavior and non-public Tailscale Serve planning.

### Configuration and safety contracts

`serveshed config validate` reports 30 passes, no failures, and one expected warning because Docker is unavailable in the build environment. Verified contracts include:

- the model registry contains eight unique hardware-aware profiles;
- Qwen3.5-9B Q4 is the default daily candidate, while Qwen3.8-27B is offload-only and experimental;
- normal and evaluation Bifrost configurations differ only in explicit content-capture controls;
- normal tracing suppresses prompt/response content and explicit eval mode captures it;
- every Bifrost virtual-key model permission resolves to a configured provider alias;
- Hermes, evaluation, and judge identities have their required model access;
- caller metadata uses allow-listed `x-bf-eh-*` headers;
- every published Compose port binds to `127.0.0.1`;
- Ollama and vLLM have no direct host ports;
- no automatic container restart policy, Docker socket mount, floating `latest` image, or cloud fallback is present;
- LiteLLM remains isolated under an `experimental` profile and is not chained with Bifrost;
- Tailscale planning uses Serve only, never Funnel;
- Synology writes require both a real mount and the reviewed marker file.

### Data, scripts, and plans

- All repository JSON, JSONL, and YAML files parse successfully.
- All project shell scripts pass `sh -n`.
- The smoke dataset contains three valid cases.
- The Qwen dataset contains five valid cases, including structured output, tools, code, multilingual text, and an image input.
- The interactive benchmark contains three valid cases.
- The throughput benchmark contains one valid case.
- Offline eval and benchmark planning commands complete without a model or `.env`.
- The 16 GiB agent-workload recommendation path ranks `local/qwen-fast` as the preferred daily candidate.

### Packaging

- The dependency-free PEP 517 backend builds `serveshed-0.2.0-py3-none-any.whl` and `serveshed-0.2.0.tar.gz` offline.
- Wheel metadata reports version `0.2.0` and Python `>=3.12,<3.14`.
- The wheel installs into an isolated environment without external dependencies.
- Wheel and source-distribution scans found no `.env`, `.env.phoenix`, environment backups, virtual environments, caches, generated eval runs, Git state, or nested build distributions.
- `scripts/package.sh` stages the repository while excluding secrets and generated state.

## Model registry basis

The registry uses current upstream artifacts as measurement candidates rather than assuming that advertised model context or benchmark results translate directly to this workstation:

- `local/qwen-fast`: Ollama `qwen3.5:9b`, approximately 6.6 GB, Q4_K_M.
- `local/qwen-quality`: Ollama `qwen3.5:9b-q8_0`, approximately 11 GB, Q8_0.
- `experimental/qwen-nvfp4`: Ollama `qwen3.5:9b-nvfp4`, approximately 8.9 GB.
- `local/gemma-judge`: Ollama `gemma4:12b`, approximately 7.4 GB, Q4_K_M.
- `experimental/qwen38-offload`: Ollama `qwen3.8:27b`, approximately 18 GB, Q4_K_M plus its multimodal projector.

Artifact size is not total VRAM usage. Context/KV cache, runtime buffers, vision components, and Ubuntu Desktop also consume GPU memory. Every candidate remains subject to the real host benchmark and acceptance workflow.

## Deliberately not validated here

The following require the actual Ubuntu Desktop host and remain hard gates rather than assumed successes:

- Docker Engine and authoritative Docker Compose rendering of every profile;
- NVIDIA driver and NVIDIA Container Toolkit access to the RTX 5070 Ti;
- live image pulls, image architecture compatibility, and immutable image digests;
- startup and persistence for PostgreSQL, Phoenix, OpenTelemetry Collector, and Bifrost;
- Bifrost authentication, streaming, governance, and end-to-end trace ingestion into Phoenix;
- Ollama model downloads, local artifact IDs, CPU/GPU split, cold load, TTFT, throughput, context stability, tool calls, vision, and desktop responsiveness;
- selection and pinning of the vLLM quantized checkpoint and Hermes model artifact;
- real multi-agent concurrency and batch behavior;
- Tailscale login, grants, HTTPS, Serve syntax for the installed client, and remote access;
- the future Synology mount, permissions, snapshot policy, backup, and restore test.

No model was downloaded. No package, driver, firewall, Tailscale configuration, mount, or running service was changed on a user machine.

## Tooling intentionally deferred

The bootstrap lock has no third-party runtime or development dependencies. Ruff and mypy are pinned in `pyproject.toml` for `./scripts/check.sh --full`, but those tool packages were unavailable in this environment's offline cache and package-index access was unavailable. Their full checks were therefore not claimed. Compilation, imports, 50 unit tests, Pytest, data parsing, shell parsing, package installation, and project-specific static invariants all pass.

## Upstream references reviewed

- Qwen3.5-9B: https://huggingface.co/Qwen/Qwen3.5-9B
- Ollama Qwen3.5 9B Q4: https://ollama.com/library/qwen3.5:9b
- Ollama Qwen3.5 9B Q8: https://ollama.com/library/qwen3.5:9b-q8_0
- Ollama Qwen3.5 9B NVFP4: https://ollama.com/library/qwen3.5:9b-nvfp4
- Gemma 4 12B: https://huggingface.co/google/gemma-4-12B
- Ollama Gemma 4 12B: https://ollama.com/library/gemma4:12b
- Hermes 4 14B: https://huggingface.co/NousResearch/Hermes-4-14B
- Qwen3.8-27B: https://huggingface.co/Qwen/Qwen3.8-27B
- Ollama Qwen3.8 27B: https://ollama.com/library/qwen3.8:27b
