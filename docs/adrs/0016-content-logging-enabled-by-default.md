# ADR 0016: Content logging enabled by default, not just in eval mode

- Status: accepted
- Date: 2026-08-16

## Context

The original design (see the project instructions' "normal mode suppresses prompt/response content" rule, and the now-retired `bifrost-content-modes` static check) suppressed prompt/response text in Phoenix and Bifrost's own logs by default, capturing it only during explicit `serveshed eval` runs. That was verified working exactly as designed — a live check confirmed `content_hidden = true` on every row in Bifrost's `logs` table during normal Open WebUI traffic, with `input_history`/`output_message` empty.

Having verified it works, the actual owner explicitly asked for the opposite: real day-to-day visibility into what was actually asked and answered, not just latency/token/error metadata. Checked first: Bifrost's `disable_content_logging` is a single global switch — `client`-level and per-otel-plugin-level, not scopable per virtual key. There is no way to log Open WebUI's traffic without also logging Hermes/research/coding/eval traffic, or vice versa. Confirmed this scope explicitly before proceeding, since it also means every future Open WebUI account (family members, once approved) has its content logged the same way, not just the owner's.

## Decision

`disable_content_logging` (both `client` and the `otel` plugin config) is `false` in `config/bifrost/config.json` — the config that was previously "normal/private" mode. `config/bifrost/config.eval.json` already had it `false`. The two files are now byte-identical (confirmed: `diff` after normalization produces no output).

Both files stay as separate files rather than collapsing to one. The `BIFROST_CONFIG_FILE` swap mechanism (`compose.py`'s `eval_logging` parameter, `serveshed eval`'s explicit config selection) isn't doing anything content-related anymore, but it's cheap to keep for whatever, if anything, needs to differ between normal and eval runs next — rate limits, retention, plugin set — rather than ripping out a mechanism to save one currently-redundant file.

The static check formerly named `bifrost-content-modes` (asserted normal hides / eval captures) is renamed `bifrost-content-capture` and now asserts both configs capture content, with a comment pointing back here — the old assertion would otherwise silently start failing `config validate` for describing a policy that's no longer true.

## Consequences

Traces in Phoenix and rows in Bifrost's `logs` table (Postgres) now contain real prompt/response text for all traffic through Bifrost, not just eval runs. This was already the documented policy for eval bundles ("treat traces and eval artifacts as sensitive") — that sentence now applies to *all* traffic, not a carved-out subset, and should be read that way going forward: this Postgres database, and anything derived from it (backups, Phoenix's own storage), holds real conversation content now.

This is a real, deliberate trade of the previous default-private posture for default-visible. Nothing about Bifrost's authentication, network isolation (ADR 0010), or governance (per-virtual-key `allowed_models`) changed — only whether content is recorded alongside the metadata those systems already captured. If a future need arises to keep some caller's content private again (e.g., a family member's chats), that requires either a second, differently-configured Bifrost instance, or waiting on native per-key content control — not something achievable by editing these two config files alone.

## Addendum: a second, independent content-hiding switch

After the restart, `client.disable_content_logging: false` was confirmed synced into Bifrost's own `config_client` Postgres table — but a live test message still showed `content_hidden = true` on the resulting `logs` row, empty `input_history`/`output_message`.

Cause: `disable_content_logging` isn't only a `client`-level and `otel`-plugin-level setting — Bifrost's schema has it on at least six different plugins independently (`logging`, `datadog`, `bigquery`, `kafka`, `pubsub`, plus the generic `otel_profile_config`). Our `config.json`/`config.eval.json` only ever had an explicit `plugins` entry for `otel`; the `logging` plugin — the one that actually writes the Postgres `logs` table Bifrost's own dashboard reads — was running on Bifrost's internal default the whole time, unaffected by the `client`-level toggle.

Fixed by adding an explicit `logging` plugin entry with `disable_content_logging: false` to both config files. Verified for real this time — not just restarted and assumed — by sending a live request and reading the resulting Postgres row directly: `content_hidden = f`, `input_history`/`output_message` populated with the actual message text, in both Bifrost's own `logs` table and Phoenix's span attributes.

The lesson, stated plainly since it's the second time a "one flag should control this" assumption was wrong this project (see ADR 0015's addendum for the Open WebUI equivalent): a top-level toggle in one of these apps does not necessarily cascade to every subsystem that independently gates the same behavior. Verify against the actual stored/emitted data, not just that a restart happened and no error was thrown.
