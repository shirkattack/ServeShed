# ADR 0011: Two startup workarounds for the pinned Bifrost `v1.6.10`

- Status: accepted, revisit on next Bifrost image bump
- Date: 2026-08-14

## Context

Bringing up `core` against real Bifrost `v1.6.10` (not just static/offline
validation) surfaced two upstream defects, back to back, both fatal at
startup:

1. **Governance `key_ids` resolves only by internal UUID, not by the `name`
   the docs tell config.json users to write.** `config/bifrost/config.json`
   declared `"key_ids": ["ollama-local"]` / `["vllm-local-batch"]`, matching
   each provider key's `name` exactly, per
   `docs.getbifrost.ai/features/governance/virtual-keys`. Bifrost still
   exited with `failed to sync governance config: ... could not resolve
   keys: key_id=ollama-local`. This is a confirmed, still-open upstream bug:
   [maximhq/bifrost#5981](https://github.com/maximhq/bifrost/pull/5981)
   ("governance - resolve config.json key_ids entries by key name"), not yet
   merged into a release as of this pin.

2. **Model-catalog init fetches three datasheets from getbifrost.ai at
   startup, two of them fatal on failure.** After (1) was worked around,
   Bifrost exited again on the pricing fetch:
   `failed to initialize pricing manager: ... failed to download pricing
   data: Get "https://getbifrost.ai/datasheet": dial tcp ...: i/o timeout`.
   This exact failure mode was reported and fixed once already
   ([maximhq/bifrost#451](https://github.com/maximhq/bifrost/issues/451)),
   then regressed in `v1.6.7` per a later comment on the same issue; the
   proper fix ([maximhq/bifrost#3959](https://github.com/maximhq/bifrost/pull/3959),
   an airgapped-deployment `disable_sync` flag) is open, not yet released.
   Pointing `pricing_url` at a local file (below) only cleared the first
   blocker: `framework/modelcatalog/main.go`'s `Init` then blocked on
   `model_parameters_url` with the identical fatal-on-failure pattern
   (`paramsErr` fails `Init` the same way `pricingErr` does), and — had that
   also been fixed — would next have blocked (non-fatally, but indefinitely
   retrying) on `mcp_library_url`. `backend` has no internet route by
   design (ADR 0010), so none of the three can ever succeed against the
   real internet.

## Decision

Apply two config-only workarounds, both reversible with a one-line revert
once upstream ships a fixed release:

1. Every `"key_ids"` entry in `config/bifrost/config.json` and
   `config.eval.json` is `["*"]` ("allow all keys for this provider")
   instead of the specific key name. Each provider (`ollama`, `vllm`) has
   exactly one configured key, so `["*"]` is behaviorally identical to
   naming that one key and does not touch the actual access boundary —
   `allowed_models` per virtual key is unchanged and still does the real
   enforcement.

2. `framework.pricing` in both config files sets `pricing_url`,
   `model_parameters_url`, and `mcp_library_url` to `file:///app/data/...`
   URLs — a scheme each of the three loaders
   (`framework/modelcatalog/datasheet/sync.go`, `.../datasheet/params.go`,
   `.../mcp_library_sync.go`) reads straight off the container filesystem
   via `os.ReadFile`/`os.Open`, bypassing the network path (and
   `bifrost.ValidateExternalURL`) entirely. Each points at a matching empty
   file bind-mounted read-only into the bifrost container by
   `compose.yaml`: `pricing.empty.json` and `model-parameters.empty.json`
   are both `{}` (each loader unmarshals into an empty `map[string]...`,
   zero entries, no error); `mcp-library.empty.json` is `{"servers": []}`,
   the wrapper shape `MCPLibraryPayload` expects. Empty datasheets are
   intentional: only local self-hosted models run through this gateway, so
   no cost/pricing/parameter data or a remote MCP server catalog is
   meaningful here, mirroring the workaround the original #451 reporter
   wanted.

## Consequences

Both workarounds are narrowly scoped and self-documenting (comments at each
edit site point back to this ADR and the upstream issue/PR). Revisit when
`BIFROST_IMAGE` is next bumped: if the target release includes #5981 and
either #3959 or a re-fix of #451's regression, restore `key_ids` to the
documented per-key form and drop the `file://` pricing override (or keep
it deliberately, since fetching real-time market pricing for providers this
project doesn't route to has no value here either way). Until then, no
provider gains a broader key grant than it already effectively had, and no
component silently reaches the internet to get the gateway to boot.
