# Synology integration

The NAS is not connected and is not a dependency.

## Intended data split

Keep local:

- active Ollama and Hugging Face model caches
- vLLM compilation cache
- live PostgreSQL data
- current eval scratch files

Archive to Synology later:

- pinned model artifacts and checksums
- datasets and completed immutable eval bundles
- PostgreSQL dumps
- project/config backups

## Safety gate

`serveshed backup` writes only when both are true:

1. `SERVESHED_NAS_DIR` is a real mount point.
2. The root contains `.serveshed-nas`.

This prevents a failed mount from silently filling the local root filesystem at the intended mount path.

Choose NFSv4 or SMB after inspecting the Synology, network, permissions, snapshot policy, and expected Linux UID/GID behavior. Test one backup and a restore before scheduling anything.

## Bundle contents

`serveshed backup --execute` writes one immutable, checksummed bundle per run, named by UTC timestamp (`$SERVESHED_NAS_DIR/<YYYYMMDDTHHMMSSZ>/`):

```text
<timestamp>/
├── manifest.json          # created_at, source paths, what was included
├── checksums.sha256       # every file below, in plain sha256sum format
├── postgres/
│   ├── phoenix.sql        # pg_dump --no-owner --no-privileges --clean --if-exists
│   └── bifrost.sql        # same flags
├── project/                # repository files, secrets excluded (no .env, no config/hermes/.env)
└── eval-runs/              # present only if $SERVESHED_DATA_DIR/eval-runs existed at backup time
```

`--clean --if-exists` means each `.sql` dump already contains its own `DROP ... IF EXISTS` statements — it's safe to replay against a database that still has the old schema in it.

## Restore (there is no `serveshed restore` command yet — this is the manual path)

1. **Verify the bundle before trusting it:**
   ```bash
   cd "$SERVESHED_NAS_DIR/<timestamp>"
   sha256sum -c checksums.sha256
   ```
2. **Stop the stack** so nothing writes to Postgres mid-restore: `uv run serveshed down`.
3. **Bring up just Postgres:** `uv run serveshed up core` (or start the `core` profile and immediately stop the others once healthy).
4. **Replay each dump** against the running container, using the same admin user Postgres was initialized with (`POSTGRES_SUPERUSER` in `.env`, default `serveshed_admin`):
   ```bash
   docker compose exec -T postgres psql --username serveshed_admin --dbname phoenix < postgres/phoenix.sql
   docker compose exec -T postgres psql --username serveshed_admin --dbname bifrost  < postgres/bifrost.sql
   ```
5. **Restore config/project files, if needed** — `project/` is a point-in-time snapshot; for the current repo, prefer `git` history over overwriting from a backup unless you're rebuilding the whole host. `eval-runs/`, if present, can be copied straight back to `$SERVESHED_DATA_DIR/eval-runs/`.
6. **Bring the stack back up and verify**: `uv run serveshed up core`, then confirm Bifrost/Phoenix are healthy and a request traces correctly before trusting the restore.

Test this end to end — a real backup followed by a real restore into a scratch Postgres — before ever relying on it. A backup you have never restored is a hope, not a backup.
