# ADR 0008: Immutable evaluation and benchmark bundles

- Status: accepted
- Date: 2026-08-14

## Decision

Every built-in evaluation and benchmark run writes raw records, a manifest, summary, hardware metadata, dataset digest, and SHA-256 manifest to a unique run directory outside Git. Warmups remain in benchmark raw data but are excluded from aggregate metrics.

## Consequences

Comparisons and future judges operate on preserved outputs. Results can be checked for tampering, rerun decisions do not mutate prior evidence, and completed bundles can later be archived to Synology.
