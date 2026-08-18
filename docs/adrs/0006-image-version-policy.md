# ADR 0006: Pin and verify container images

- Status: provisional
- Date: 2026-08-14

## Decision

`.env.example` pins exact version tags for the initial scaffold. Before first deployment, verify each tag and publisher, record its immutable digest, and test migrations. The current tags are candidate pins recorded for reproducible first-host testing; they were not pulled or schema-tested in the scaffold environment.

Do not switch to floating `latest` tags to solve availability problems.
