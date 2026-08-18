# ADR 0003: Manual-first lifecycle

- Status: accepted
- Date: 2026-08-14

## Decision

Application containers do not use automatic restart policies. Docker and Tailscale may start with Ubuntu, but core and GPU profiles start explicitly. Ollama and vLLM are mutually exclusive in the supported CLI path.
