# ADR 0019: Render `config/bifrost/config*.json` locally for the Tailscale CORS origin

- Status: accepted
- Date: 2026-08-17

## Context

Bifrost's own dashboard, when reached over Tailscale Serve, failed its live-updating WebSocket connection: `websocket upgrade error: websocket: request origin not allowed by FastHTTPUpgrader.CheckOrigin`, `403`. Confirmed live and reproducing continuously (every ~30s, from a real open browser session) throughout this session, not a hypothetical. Root cause: `client.allowed_origins` in `config/bifrost/config.json`/`config.eval.json` only ever listed Open WebUI's `127.0.0.1:3000`/`localhost:3000`; nothing covered the tailnet hostname (`https://<machine>.<tailnet>.ts.net`) Bifrost's own dashboard is actually served from over Serve.

First attempt: add the origin to the tracked config as `"env.BIFROST_TAILSCALE_ORIGIN"`, matching Bifrost's own documented `env.` substitution convention used everywhere else in this file (`"value": "env.BIFROST_VK_HERMES"`, `"host": "env.PG_HOST"`, etc.). Verified empirically that this does **not** work: recreated the Bifrost container with `BIFROST_TAILSCALE_ORIGIN` set in `.env`, queried Bifrost's own `/api/config` afterward, and the literal unresolved string `"env.BIFROST_TAILSCALE_ORIGIN"` was sitting in the live `allowed_origins` array — the real WebSocket request still failed identically. Bifrost's `env.` substitution resolves specific typed schema fields (secrets, provider key URLs) via a dedicated `EnvVar` struct; it does not walk plain string array elements.

The tailnet hostname is real, host-specific, and mildly identifying (a real device name on a real tailnet). It shouldn't be hardcoded into `config/bifrost/config.json`/`config.eval.json` — both tracked files, both about to be public. `.env` (gitignored) is where host-specific values belong; the problem was purely that Bifrost itself has no way to read this particular one out of it for this particular field shape.

## Decision

Added `Settings.render_bifrost_config(eval_logging=...)`: reads the tracked template (`config/bifrost/config.json` or `.eval.json`), resolves the `"env.BIFROST_TAILSCALE_ORIGIN"` placeholder ourselves — substituted with the real `BIFROST_TAILSCALE_ORIGIN` value if set, dropped cleanly from the array if unset — and writes the result under `$SERVESHED_CACHE_DIR/bifrost/` (regenerable, already outside the repo tree, no `.gitignore` entry needed). `ComposeManager._bifrost_override` mounts that rendered path via `BIFROST_CONFIG_FILE` instead of the tracked template directly. The tracked template is never edited by this mechanism; the placeholder stays as plain, readable text in the file everyone sees.

Guarded behind `not self.runner.dry_run`: a `--dry-run` command must never write files, so dry runs fall back to reporting the template path directly (nothing starts either way, so the exact value shown doesn't matter operationally).

Verified end to end, not just at the code level: recreated Bifrost with the render wired in, confirmed via `/api/config` that `allowed_origins` now contains the real tailnet origin and the placeholder is gone, then watched the *same real, already-failing browser session* (unchanged, no user action) succeed on its next retry — `http.status_code: 101` (Switching Protocols), replacing the `403` that had been repeating every ~30 seconds all session.

## Consequences

- `BIFROST_TAILSCALE_ORIGIN` joins `.env.example` as an optional, empty-by-default field — safe to leave unset (Serve not applied yet, or don't want the dashboard reachable that way), and the render step's job is exactly to make "unset" behave as if the array entry were never there.
- Any future host-specific value Bifrost's config needs that hits this same array-substitution limitation follows the same pattern: placeholder in the tracked template, real resolution in `render_bifrost_config`, never a literal value in a tracked file.
- The render step adds one more thing `compose.py` does before starting Bifrost; it's cheap (a JSON read/write) and only runs when actually bringing the stack up for real, not on every CLI invocation.
- Revisit if a future Bifrost release adds real array-element `env.` substitution (unlikely to be announced explicitly; would show up as this same empirical test — recreate, check `/api/config` — starting to resolve the placeholder itself). If it does, this whole mechanism can be dropped in favor of the native one, same spirit as ADR 0011's "revisit on next Bifrost image bump."
