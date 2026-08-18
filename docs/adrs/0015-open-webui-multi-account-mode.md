# ADR 0015: Open WebUI switches to multi-account mode

- Status: accepted
- Date: 2026-08-15

## Context

ADR 0014 set `WEBUI_AUTH=false` (single-user mode) to match a localhost-only, single-operator deployment, and flagged the switch to multi-account mode as a reviewed decision for whenever remote/family access became a real goal — noting explicitly that Open WebUI's docs warn the switch cannot be reversed later without losing existing sessions.

That moment arrived the same day: making the chat UI usable by family members over Tailscale requires per-person accounts and per-group model restrictions, both of which are structurally unavailable in single-user mode — verified against Open WebUI's own docs, which describe group-based model access control as inherently a multi-account feature (`{{ USER_GROUPS }}` bindings that don't exist without accounts).

## Decision

`WEBUI_AUTH=true` in `.env` and `.env.example`. First signup becomes the admin account. No groups are configured yet — the immediate ask was "just me for now"; per-person/per-group model restrictions (e.g. a restricted group scoped to `local/qwen-fast` only) are a follow-up once specific family members are actually being added, configured from Workspace → Models in the Open WebUI admin panel, not from `config.json` or any `serveshed` command.

The switch happened before any real conversation history existed in the single-user session, so the "can't reverse without losing sessions" cost was effectively zero at the time of the change — worth recording so a future reader doesn't wonder why ADR 0014 and this one landed hours apart.

## Consequences

Every Open WebUI account today still shares the one Bifrost identity, `BIFROST_VK_WEBUI` — Open WebUI's own user/group system is a layer on top of that single virtual key, not a separate Bifrost governance identity per person. Phoenix traces and Bifrost's own request log see "open-webui" as one caller regardless of which Open WebUI account made the request. If per-person governance (separate rate limits, separate `allowed_models`, separate trace attribution at the Bifrost layer) becomes necessary later, that requires either multiple Bifrost virtual keys manually mapped to Open WebUI connections, or waiting on native support — not something multi-account mode alone provides.

Reaching this from another person's device is a separate decision (Tailscale device sharing, not tailnet membership — see `docs/tailscale.md`) and is not automatically implied by this ADR.

## Addendum: `ENABLE_SIGNUP` didn't follow the flip

After restarting with `WEBUI_AUTH=true`, the sign-in page had no sign-up option. Cause: Open WebUI persists many feature toggles — `ui.enable_signup` among them — to a `config` table in its own sqlite database (`$SERVESHED_DATA_DIR/open-webui/webui.db`) after first boot, and does not re-read them from the environment on later restarts. Single-user mode's earlier boot had seeded that row `false`; flipping `WEBUI_AUTH` (which *does* re-read from env each boot — it controls the auth code path directly, not a persisted toggle) didn't touch it.

Fixed by updating the row directly (`sqlite3`/`python3 -c "..."` inside the container — no `sqlite3` CLI in the image) and restarting for it to load into memory. `compose.yaml` now also sets `ENABLE_SIGNUP: "true"` explicitly, so a genuinely fresh `$SERVESHED_DATA_DIR` (no existing `webui.db`) seeds correctly from the first boot — but that env var **will not** fix this again on an existing install if it drifts; the database is the one that matters once it exists. If another persisted setting needs correcting later, check `/api/config` against what's expected first, the same way this was diagnosed, rather than guessing from environment variables alone.
