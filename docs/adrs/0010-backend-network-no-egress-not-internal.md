# ADR 0010: Backend network blocks egress via disabled masquerade, not `internal: true`

- Status: accepted
- Date: 2026-08-14

## Context

The `backend` Docker network originally used Compose's `internal: true` to
deny postgres, phoenix, otel-collector, and bifrost any outbound route to
the internet. On first real-host validation, `serveshed up core` reported
bifrost and phoenix as started and healthy, but neither was reachable at
their published `127.0.0.1` ports — `docker inspect` showed the intended
`HostConfig.PortBindings`, yet `NetworkSettings.Ports` was empty, no
`docker-proxy` process was listening, and `curl` got connection refused.

A minimal repro on the target host confirmed the cause: a container
published on an `internal: true` network is never reachable on the host,
regardless of the recorded port binding. Docker's `internal` flag removes
the network from routing in both directions, not just outbound. A second
repro confirmed the fix: a normal (non-internal) bridge network with the
`com.docker.network.bridge.enable_ip_masquerade: "false"` driver option
keeps host port publishing working while still blocking the container's
outbound internet route (`wget` to an external host timed out; the
published port still answered).

## Decision

`backend` is a normal bridge network with
`driver_opts: {com.docker.network.bridge.enable_ip_masquerade: "false"}`
instead of `internal: true`. This applies to all four core services;
postgres and otel-collector keep no published ports and gain nothing new,
while bifrost and phoenix keep the no-egress property `internal: true` was
meant to provide and additionally become reachable at their intended
`127.0.0.1` ports. The `egress` network (unchanged, plain bridge) remains
the only network with an outbound route, attached only to `ollama` and
`vllm` for approved model downloads.

`src/serveshed/validation.py`'s static Compose check now asserts the actual
invariant (`enable_ip_masquerade: "false"` present, `internal: true`
absent) rather than the invariant that silently broke publishing.

## Consequences

Core services still cannot reach the internet at the network level, which
is a stronger backing for "no cloud fallback" than an app-level toggle
alone. Anyone reintroducing `internal: true` on `backend` will fail the
`no-egress-backend` static check and, if they actually start the stack,
reproduce the same unreachable-port failure this ADR fixes. Docker-level
inter-service DNS and routing among the four core services is unaffected;
masquerade only concerns the network's own outbound path, not the
`backend` bridge's internal L2/L3 forwarding.
