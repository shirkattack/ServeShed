# ADR 0009: Verified model acceptance gate

- Status: accepted
- Date: 2026-08-14

## Decision

A measured model promotion consumes one checksummed deterministic-evaluation bundle and one checksummed benchmark bundle for the same registered alias. Explicit thresholds determine acceptance. Promotion is optional and can occur only after every threshold passes.

## Consequences

A failed decision is still preserved for audit but cannot change `.env`. Manual selection remains available for controlled experiments, while the preferred default-model workflow is evidence-based and reproducible.
