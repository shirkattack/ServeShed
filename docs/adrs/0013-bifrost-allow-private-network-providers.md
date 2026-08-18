# ADR 0013: `allow_private_network: true` for the ollama and vllm providers

- Status: accepted
- Date: 2026-08-14

## Context

The first real chat completion through Bifrost (`ollama/local/qwen-fast`,
non-streaming, after the model pull and network fixes in ADRs 0010–0012)
failed with `502` and `"connection to private IP 172.18.0.3 is not
allowed"`. This is not a bug: Bifrost's `network_config.allow_private_network`
defaults to `false` as an SSRF guard, appropriate for a gateway that might
route to an operator-supplied or third-party base URL. `ollama` and `vllm`
resolve to container hostnames (`OLLAMA_URL`, `VLLM_URL`) on the private
`backend` network by design (ADR 0010), which always resolve to RFC 1918
addresses — exactly what the guard blocks by default.

## Decision

Both `providers.ollama.network_config` and `providers.vllm.network_config`
in `config.json` and `config.eval.json` set `"allow_private_network": true`.
No other provider is configured, so this does not widen the SSRF guard for
anything reaching a real third-party endpoint — there isn't one in the
baseline.

## Consequences

If a future provider is added that points at a real external base URL,
its `network_config` must not inherit this setting; each provider's
`network_config` is independent, so no action is needed there, but a
reviewer should check this explicitly since copy-pasting an existing
provider block is the likely path to adding a new one.
