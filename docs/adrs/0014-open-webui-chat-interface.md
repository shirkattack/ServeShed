# ADR 0014: Open WebUI as the browser chat interface

- Status: accepted
- Date: 2026-08-15

## Context

Interacting with the stack required either raw `curl` against Bifrost or the bundled dependency-free Python examples — no way to browse chat history, and no UI a non-technical session would reach for. A self-hosted chat UI that speaks plain OpenAI-compatible API fits the existing "one gateway" architecture directly, as long as it goes through Bifrost like everything else rather than adding a second path to Ollama.

## Decision

Add `open-webui` (`ghcr.io/open-webui/open-webui:v0.11.0`, pinned per ADR 0006) to the `chat` Compose profile, alongside Ollama:

- **Bifrost only.** `ENABLE_OLLAMA_API=false`, `ENABLE_OPENAI_API=true`, `OPENAI_API_BASE_URLS=http://bifrost:8080/v1`. It cannot reach Ollama directly even if someone later adds an `OLLAMA_URL` — the same "direct Ollama access is diagnostic-only" rule the rest of the project follows.
- **Its own governance identity.** A new Bifrost virtual key, `vk-webui` / `BIFROST_VK_WEBUI`, scoped to the models a human should actually see in the UI's picker: `local/qwen-fast`, `local/qwen-quality`, `local/gemma-judge`. Not `local/qwen-batch` — vLLM is mutually exclusive with the `chat` profile this service runs under, so offering it would list a model that's never actually reachable while Open WebUI is up.
- **`backend` network only** (ADR 0010) — no internet route, matching the other core services. It doesn't need one: `OFFLINE_MODE=true`, `HF_HUB_OFFLINE=1`, and the RAG/Whisper auto-update flags are all disabled, so nothing tries to phone home at startup. (Verified this mattered: without these, Open WebUI's default RAG embedding-model fetch from Hugging Face fails on this network — non-fatal here, unlike Bifrost's pricing-datasheet fetch in ADR 0011, but real. RAG/document-upload features do not work out of the box as a result; that's an accepted trade-off, not something this ADR tries to fix.)
- ~~**Single-user mode**, `WEBUI_AUTH=false`~~ — **superseded by [ADR 0015](0015-open-webui-multi-account-mode.md)** the same day, once family/remote access became a real goal.
- **Persisted to local NVMe**, `$SERVESHED_DATA_DIR/open-webui` — chat history and settings, same storage tier as everything else (ADR 0004).
- **Not part of `gpu-off`.** It holds no VRAM itself; only Ollama/vLLM need to be stopped to release the GPU.

`BIFROST_VK_WEBUI` had to be added to `bifrost`'s own `environment:` block in `compose.yaml`, not just referenced from `config.json` — Bifrost only resolves `env.*` references against variables actually injected into its container, not everything in `.env`. Missing this the first time produced a fatal `failed to prune governance config: ... foreign key constraint` error at Bifrost startup (the referenced env var silently failed to resolve, so the provider-config row it should have belonged to never got created either).

## Consequences

`up chat` now brings up five services instead of four; `PROFILE_SERVICES["chat"]` in `compose.py` reflects that, along with the corresponding test. Verified end-to-end on the reference host: Open WebUI's model picker shows exactly the three allow-listed models (governance confirmed working, not just configured), and a real chat completion sent through the UI's own API landed as a Bifrost/Phoenix trace like any other request.

Widening `vk-webui`'s `allowed_models` is a reviewed decision, not a routine edit — it's the one virtual key a human directly drives, so it's the most exposed to "just picking whatever's in the dropdown."
