# Security and privacy

## Baseline controls

- No public ports; every published port binds to localhost.
- Tailnet access uses Tailscale Serve, never Funnel.
- Bifrost authentication remains enabled even behind Tailscale.
- Each agent has a separate virtual key and provider/model allow-list.
- PostgreSQL, Ollama, vLLM, and OTLP are not directly exposed remotely.
- `.env` is ignored by Git and generated with mode `0600`.
- No cloud provider appears in the baseline gateway configuration.
- Model fallback, semantic cache, and provider retries are disabled for eval reproducibility.
- Large downloads and host changes require explicit user action.

## Trace content

Content logging is on by default for all traffic through Bifrost — `config/bifrost/config.json` and `config.eval.json` both set `disable_content_logging: false` (ADR 0016, an explicit, reviewed decision, not the original default). Bifrost has no per-virtual-key content scoping, so this applies uniformly: every caller — Open WebUI, agents, eval runs — has its prompts and responses recorded in Phoenix and Bifrost's own `logs` table. Treat eval bundles, Phoenix traces, and the Bifrost logs table as sensitive data, use retention controls, and never place secrets in prompts or metadata. If content needs to be private for some traffic again, that requires either a second, differently-configured Bifrost instance or waiting on native per-key content control — not a single config edit.

Never assume tailnet reachability alone is sufficient authorization.

## Agent tools

Shell, filesystem, browser, MCP, messaging, and network tools are privileged. Add them one at a time with allow-lists and red-team tests for prompt injection, secret exfiltration, unintended writes, and network egress.

## Supply chain

Before the first pull and every upgrade:

1. Verify image existence and publisher.
2. Record the immutable digest.
3. Review release notes and migration steps.
4. Update `.env.example` and an ADR.
5. Run config, persistence, auth, trace, streaming, and eval regressions.

Do not use floating `latest` tags in the accepted baseline.
