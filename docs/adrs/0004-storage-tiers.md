# ADR 0004: Local hot tier and optional Synology durable tier

- Status: accepted
- Date: 2026-08-14

## Decision

Keep active databases, models, and caches on local NVMe. Add Synology later for archives, completed evals, datasets, checksummed models, and dumps. Backups fail closed unless the mount and marker are verified.
