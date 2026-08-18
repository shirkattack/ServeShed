# ADR 0012: Explicit `gw_priority` for services on both `backend` and `egress`

- Status: accepted
- Date: 2026-08-14

## Context

`ollama` and `vllm` are the two services meant to reach the internet (for
approved model downloads), attached to both `backend` (no egress, ADR 0010)
and `egress` (plain bridge, has egress). The first real pull —
`serveshed model pull local/qwen-fast` — failed:
`Error: pull model manifest: Get "https://registry.ollama.ai/...": dial tcp
...: i/o timeout`, even though `egress` was attached and otherwise correctly
configured.

`docker inspect` explained it: both networks reported `"GwPriority": 0`, and
Docker's tie-break for equal `gw_priority` picked `backend` — the network
with no internet route — as the container's default gateway. `egress` was
attached and functional, just never used, because nothing told Docker to
prefer it.

## Decision

Both `ollama` and `vllm` now declare their networks with `backend` at the
default `gw_priority` (0, implicit) and `egress: {gw_priority: 1}`,
overriding Docker's tie-break so `egress` is always the default route for
these two services.

## Consequences

Any future service attached to both `backend` and `egress` needs the same
explicit `gw_priority` on `egress`, or it will silently reproduce this
failure — attached to the internet-capable network, routed through the one
that isn't. `postgres`, `phoenix`, `otel-collector`, and `bifrost` are
unaffected; they are `backend`-only and were never meant to reach the
internet at all.
