# Tailscale

Tailscale is installed and authenticated on the Ubuntu host, not in Docker.

The project only plans commands:

```bash
uv run serveshed tailscale plan
```

Before applying anything:

1. Inspect `tailscale serve --help` from the installed version.
2. Review tailnet grants for the intended users/devices.
3. Confirm Bifrost, Phoenix, and Open WebUI are bound to localhost.
4. Keep Bifrost authentication enabled.
5. Verify Ollama, vLLM, PostgreSQL, and OTLP are not reachable directly.
6. If proxying Open WebUI for anyone other than yourself, confirm `WEBUI_AUTH=true` first — single-user mode has no per-person accounts, so remote access without it means anyone reaching the URL is you.

Use Serve for tailnet-only access. Never replace it with Funnel. Tailscale SSH is a separate decision and requires explicit approval.

## Reaching this from family devices without full tailnet membership

Adding a family member as a full tailnet member gives them visibility into every device on your tailnet, which is more than "let them use the chat UI." Tailscale's **device sharing** (Tailscale admin console → the device → **Share**) instead grants one external Tailscale account access to *just that one machine* — they can't see or reach anything else on your network, and can't initiate connections back into it from their side. This is a web-console action on [login.tailscale.com/admin/machines](https://login.tailscale.com/admin/machines), not a CLI command — `serveshed` and the `tailscale` CLI can't do it for you.

Each invited person installs the Tailscale app, accepts the share, and bookmarks this host's `https://<machine>.<tailnet>.ts.net` URL (visible in the admin console once Serve is configured) — no VPN client configuration, no exposing anything to the public internet.
