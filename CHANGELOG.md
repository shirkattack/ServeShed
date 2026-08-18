# Changelog

## Unreleased

- Renamed the project `homelab` → `serveshed`: package, CLI, entry point, env vars (`HOMELAB_*` → `SERVESHED_*`), Compose project name, and all documentation; re-verified end to end against the live stack, not just offline checks.
- Added Open WebUI as the browser chat interface — a Bifrost-only client with its own virtual key, multi-account mode, fully offline (ADRs 0014–0015).
- Enabled content logging for all traffic as a reviewed owner decision; both Bifrost configs are kept in lockstep by a static check (ADR 0016).
- Drew the platform/consumer repo boundary: Inspect AI and lm-evaluation-harness live in separate repos as ordinary Bifrost virtual-key callers and never enter this lockfile (ADR 0017).
- Documented Bifrost `v1.6.10` never forwarding a token limit to Ollama as a standing condition (ADR 0018) and added local config rendering so the tailnet origin never lives in tracked files (ADR 0019).
- Added a startup banner for `serveshed up` showing live model residency, gateway health from an authenticated probe, the default model's acceptance standing, and degraded-state warnings; the banner is exception-guarded, honors configured ports, and never claims GPU state it cannot see.
- Fixed live-verification bugs: double-counted runs in discovery, a Promptfoo results-permission failure, an `ollama ps` parsing gap, unresolved Promptfoo `apiKey` interpolation, and two eval dataset defects.
- Verified Tailscale Serve remote access from a real browser session, including the Bifrost dashboard WebSocket fix (ADR 0019).
- Brought the codebase to a clean `ruff check`, `ruff format`, and strict `mypy` baseline; `check.sh --full` now runs in CI on every push.
- Grew the offline test suite from 50 to 76 tests.

## 0.2.0 - 2026-08-14

- Pivoted the daily model strategy to hardware-aware Qwen3.5-9B profiles while retaining Qwen3.8-27B as an offload-only experiment.
- Added model tiers, VRAM/RAM fit metadata, workload tags, recommendations, safe default selection, and installed Ollama inventory.
- Added full-path interactive and throughput benchmarks with warmups, token metrics, hardware snapshots, comparisons, and checksums.
- Archived the exact selected input for limited eval and benchmark runs, with separate source and selected-input digests.
- Expanded deterministic evaluation summaries with median/p95 latency, token totals, and throughput.
- Added run discovery, Markdown reporting, and checksum verification.
- Hardened bundle verification against unsafe paths, symlinks, missing files, and untracked files.
- Added a verified model acceptance gate with configurable quality/performance thresholds and optional promotion.
- Added active Ollama model and CPU/GPU processor-split reporting to status output.
- Corrected Bifrost, Promptfoo, Hermes, LiteLLM-experimental, and example aliases for the daily and vLLM batch profiles.
- Added static validation for Bifrost governance permissions and agent access contracts.
- Expanded tests, model/eval documentation, runbooks, ADRs, and handoff guidance.

## 0.1.0 - 2026-08-14

- Added a dependency-free `uv` control plane and offline build backend.
- Added manual Docker Compose profiles for core, Ollama, vLLM, Promptfoo, and an isolated LiteLLM comparison.
- Added Bifrost routing, per-agent keys, privacy/eval trace modes, OTel Collector, Phoenix, PostgreSQL, model gating, deterministic evals, Tailscale planning, and fail-closed Synology backups.
- Added Ubuntu runbooks, ADRs, examples, tests, and handoff guidance.
