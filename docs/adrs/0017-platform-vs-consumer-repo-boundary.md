# ADR 0017: `serveshed` is the serving/governance platform; content-heavy eval harnesses live in separate repos

- Status: accepted
- Date: 2026-08-16

## Context

Asked whether Inspect AI/lm-evaluation-harness integration ("wiring the evals") could move to a separate repo. That question doesn't have one answer — `serveshed` currently conflates two different things under "evals":

1. The built-in deterministic eval/benchmark runner and the acceptance gate (`serveshed eval`, `serveshed benchmark`, `serveshed model accept`) — first-party code (`src/serveshed/evaluations.py`, `acceptance.py`, `runs.py`) that owns the model registry, the immutable checksummed bundle format, and the decision that blocks or allows `.env` promotion (ADR 0009).
2. Third-party evaluation content (Promptfoo, Inspect AI, lm-evaluation-harness) that Delivery Sequence phase 4 currently says lands as `uv add`-locked dependency groups inside this repo.

(2) sits in tension with a founding property of this repo: the CLI's zero-third-party-dependency bootstrap, preserved deliberately (README, Development section). Inspect AI and lm-evaluation-harness are not light — pulling their dependency trees into `serveshed`'s own lockfile trades that property away for tooling that, per `docs/evals.md`, doesn't even feed the acceptance gate directly today; it's reviewed as supplementary evidence.

There's already a precedent for where the seam should be: ADR 0001 makes Bifrost the sole gateway, and the project's data-flow diagram (README) draws Hermes Agent, Python agents, eval runners, notebooks, and Open WebUI as callers sitting *above* Bifrost, each with its own virtual key — not as code living inside this repo. Hermes Agent already follows this pattern: it's an external client, and `config/hermes/` is a thin adapter (env template + README), not an implementation.

Owner intent, stated directly: `serveshed` should be evaluated as a serving platform, not as a place that also hosts every application that talks to it. Secure connectivity to the platform (Bifrost auth, per-caller virtual keys and allowlists, Tailscale Serve for remote access) is `serveshed`'s job. What connects through that door is not.

## Decision

Draw the boundary by function, not by category:

- **Stays in `serveshed`**: anything that operates or tests the platform itself — Bifrost, Ollama/vLLM lifecycle, Phoenix/OTel, the model registry, the built-in deterministic eval/benchmark runner and the acceptance gate, and Promptfoo (it exercises Bifrost's own gateway contract — auth, allowlists, retries, red-team behavior — not model content quality). A light Phoenix client dependency group, if added later, stays here too, since it queries `serveshed`'s own observability store.
- **Moves out to separate repo(s)**: Inspect AI and lm-evaluation-harness. These evaluate model *content and capability*, not the platform, and they connect exactly like Hermes Agent does — an OpenAI-compatible client hitting Bifrost with a dedicated virtual key and an explicit `allowed_models` list, no different in kind from any other agent.
- Each new consumer repo gets its own Bifrost virtual key + allowlist, and may get a thin `config/<name>/` adapter folder here (env template + README, per the `config/hermes/` pattern) — never its dependencies, never its code.
- The built-in eval/benchmark bundle schema (manifest/summary/checksums, ADR 0008) is the integration seam if an external repo's results are ever meant to feed `model accept` directly: a consumer repo that emits bundles in that shape can be ingested by the gate without `serveshed` importing any of its dependencies. Absent that, external results stay supplementary evidence reviewed by hand, same as today.

## Consequences

- Delivery Sequence phase 4 (project instructions) and `docs/handoff.md` item 10 are corrected: they no longer describe adding Inspect/lm-eval as locked groups in this repo's `pyproject.toml`.
- `docs/evals.md`'s layer list is corrected to describe Inspect AI and lm-evaluation-harness as external Bifrost consumers rather than pending in-repo `uv` groups.
- The acceptance gate, ADR 0008's bundle format, and ADR 0009 are unaffected — they were never about third-party eval content in the first place.
- `serveshed`'s dependency bootstrap stays minimal by default; heavy eval-content dependencies never enter this repo's lockfile unless a future reviewed decision specifically wants a bundle-schema importer here.
- Anyone building an Inspect AI/lm-eval integration next should start a separate repo, request a virtual key (e.g., `vk-inspect`, `vk-lmeval`) with an explicit allowlist, and treat `config/hermes/` as the adapter-folder template.
