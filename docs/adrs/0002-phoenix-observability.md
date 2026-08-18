# ADR 0002: Phoenix and OpenTelemetry

- Status: accepted
- Date: 2026-08-14

## Decision

Use an OpenTelemetry Collector between Bifrost/application instrumentation and Phoenix. Persist Phoenix in PostgreSQL. Phoenix is preferred over Langfuse for the first workstation deployment.

## Rationale

The project is evaluation-heavy and runs on an intermittently powered Ubuntu desktop. Phoenix provides tracing, datasets, experiments, and evaluations with a smaller initial operational footprint, while the collector preserves backend portability. This is a first-deployment choice, not a claim that Langfuse is unsuitable.

## Consequences

The collector keeps trace transport vendor-neutral and permits future fan-out. Phoenix is the initial eval-centric UI; replacing or supplementing it does not require rewiring every caller. A multi-user or production-style deployment may justify a later comparison through a new ADR.
