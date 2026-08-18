# ADR 0001: Bifrost is the default gateway

- Status: accepted
- Date: 2026-08-14

## Decision

Agents and eval clients use Bifrost as the sole default OpenAI-compatible gateway. LiteLLM may run only as an isolated experimental alternative on a separate port and must connect directly to test backends, never through Bifrost or vice versa.

## Consequences

Routing, aliases, authentication, virtual keys, retries, and gateway traces have one source of truth. A future replacement requires comparative evidence and a new ADR.
