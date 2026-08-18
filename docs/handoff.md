# Engineering handoff

Read `README.md`, this file, `docs/verification-report.md`, and all ADRs before changing architecture.

## What exists in 0.2.0

- Dependency-free `uv` package, offline build backend, and typed CLI.
- Safe initialization, host diagnostics, service lifecycle, logs, status, Tailscale planning, and fail-closed NAS backup commands.
- Docker Compose contracts for PostgreSQL, Phoenix, OTel Collector, Bifrost, Ollama, vLLM, Promptfoo, and isolated LiteLLM.
- Hardware-aware model registry with Qwen3.5 daily/quality/NVFP4 profiles, Gemma judge, review-gated vLLM/Hermes/embedding profiles, and Qwen3.8 offload-only profile.
- Model recommendation, explicit pull, installed inventory, manual selection, and measured acceptance commands.
- Built-in deterministic evaluations and full-path benchmarks.
- Immutable checksummed evaluation, benchmark, and acceptance bundles.
- Exact selected-input archives for limited runs, plus source and selected dataset digests.
- Strict checksum verification that rejects unsafe paths, symlinks, and untracked files.
- Run discovery, comparison, Markdown reporting, and integrity verification.
- Active Ollama model and CPU/GPU processor-split reporting in `serveshed status`.
- Bifrost virtual-key/model permission validation and corrected daily/batch aliases.
- Promptfoo, Inspect AI, and lm-eval scaffolding.
- Unit tests, static architecture checks, ADRs, and operational documentation.

## Verification snapshot

`docs/verification-report.md` has two parts: the 0.2.0 build-environment verification (offline; hardware-dependent behavior intentionally not claimed there) and the host verification that followed on the real Ubuntu Desktop — core bring-up, Bifrost auth, end-to-end traces, `local/qwen-fast` pulled and exercised, `gpu-off`, Open WebUI, and Tailscale Serve. ADRs 0010–0019 document what broke and what was decided while doing it.

## Completed on the Ubuntu host

- `./scripts/check.sh` passes, and `check.sh --full` (ruff, mypy) runs in CI on every push.
- `uv run serveshed config validate --docker` passes with the generated `.env`.
- Core started and verified: persistence, Bifrost authentication, one streaming and one non-streaming trace end to end in Phoenix (ADRs 0010–0013 record the bugs found doing it).
- Docker GPU access and `gpu-off` validated; `nvidia-smi` confirms release.
- `local/qwen-fast` pulled, loaded, and exercised through Bifrost; smoke eval run live.
- Open WebUI up as a Bifrost-only client, multi-account mode (ADRs 0014–0015).
- Tailscale Serve verified from a real remote session (ADR 0019).
- Content logging reviewed and deliberately enabled for all traffic (ADR 0016) — the earlier "normal vs. eval privacy mode" distinction no longer exists; both configs are kept in lockstep by a static check.

## Remaining tasks on Ubuntu

1. Verify every container tag and publisher, record immutable image digests, and update ADR 0006 (still provisional).
2. Run the full qwen eval plus interactive and throughput benchmark suites; create an acceptance decision for `local/qwen-fast` before promoting anything.
3. Review a vLLM quantized Qwen3.5-9B candidate and pin its revision only after provenance and compatibility checks.
4. Run the Q8/NVFP4 comparisons and the Gemma judge calibration workflow.
5. Validate Hermes Agent through its own Bifrost virtual key.
6. Add a locked Phoenix client dependency group here only if this repo needs to query Phoenix's own store directly. Inspect AI and lm-evaluation-harness are out of scope for this repo — per ADR 0017, they live in separate repos and connect to Bifrost as ordinary virtual-key callers, same pattern as Hermes Agent.
7. Synology: reviewed mount, archive, backup, and restore test (never required for startup).

## Do not do

- Do not revert the default to Qwen3.8-27B.
- Do not fill review-gated model artifacts with arbitrary community checkpoints.
- Do not chain LiteLLM and Bifrost.
- Do not weaken localhost-only publication, authentication, privacy, checksum, NAS marker, or vLLM gates to make a smoke test pass.
- Do not install host software, alter drivers, apply Tailscale rules, mount the NAS, or download large models without user approval.
- Do not use `pip`, delete volumes, prune Docker, or mutate completed run bundles.
