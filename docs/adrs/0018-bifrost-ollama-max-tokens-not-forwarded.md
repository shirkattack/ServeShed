# ADR 0018: Bifrost `v1.6.10` never forwards a token-limit field to Ollama's `num_predict`

- Status: accepted, revisit on next Bifrost image bump
- Date: 2026-08-17

## Context

Real testing (`serveshed eval smoke`, `eval qwen`, `eval promptfoo`) surfaced `local/qwen-fast` failing cases with tight `max_tokens` budgets (32, 48 tokens) — the model spent its entire budget on `reasoning`/`thinking` output and returned empty `content`. The registry's `default_parameters.max_tokens: 2048` didn't help either; several live runs saw `completion_tokens` in the thousands, capped only by the model's 8192-token context window (`finish_reason: "length"`), not by any requested limit.

Isolated the cause with the containerized Ollama's own native API, reached directly over the `backend` Docker network (bypassing Bifrost entirely):

```text
POST http://ollama:11434/api/chat
{"model":"qwen3.5:9b", "options":{"num_predict":32}, ...}
-> eval_count: 32, done_reason: "length"   # respected exactly
```

Ollama itself honors `num_predict` precisely. The same request through Bifrost's OpenAI-compatible endpoint does not. Tested every field a translation layer could reasonably use, one at a time, against the identical prompt:

| Request field sent to Bifrost | `finish_reason` | `completion_tokens` |
|---|---|---|
| `max_tokens: 32` | `stop` | 7229 |
| `max_completion_tokens: 32` | `length` | 8167 (hit the 8192 context ceiling) |
| `options: {"num_predict": 32}` (hoping for passthrough) | `stop` | 4012 |

None came anywhere close to 32. Bifrost's own docs describe Ollama support as "delegates to the OpenAI implementation... parameters pass through with minimal conversion" — in practice, for this pinned version, the token-limit conversion specifically does not happen. This is a distinct defect from the two ADR 0011 startup workarounds; it's a runtime request-translation gap, not a boot-time failure. No specific upstream `maximhq/bifrost` issue number was found to cite (searched; none matched precisely) — noted here as an open item rather than a fabricated citation.

Also checked whether the model itself could be told to skip "thinking" instead, sidestepping the token-budget question entirely:

- Ollama's native API supports `"think": false` and it works — confirmed directly against `ollama:11434`, dropped straight to `content` in 2 tokens.
- Bifrost does not forward a `think` field either (tested; silently ignored, same as the token-limit fields).
- Ollama's Modelfile format has no `PARAMETER think false` — it's an open upstream feature request (`ollama/ollama#14809`, `#14617`, `#10961`), not yet available in any release. There is no way to bake "don't think by default" into a custom model tag.

Net result: **there is currently no governed way, through Bifrost, to cap Ollama's generation length or to disable thinking mode** for a hybrid-reasoning model like `qwen3.5:9b`. This is not eval-specific — it affects every real caller through the gateway, including Open WebUI chat and Hermes Agent, all of which believe they're setting a token limit that silently does nothing.

## Decision

First tried raising `smoke.jsonl`'s `concise-instruction` and `qwen.jsonl`'s `qwen-multilingual` from their original 32/48-token budgets to 2048, assuming a bigger declared budget would give reasoning room to finish before answering. Verified live and it did **not** help — `concise-instruction` still burned 8152 tokens and returned empty `content`, unchanged from the 32-token run, which is exactly what the isolation above predicts: since Bifrost never forwards the value at all, 32 and 2048 produce identical behavior. Left `max_tokens: 2048` on both cases anyway (harmless, documents intent, will start mattering the day this gets fixed upstream) but it is not what fixed anything.

What actually fixed each case, once measured instead of assumed:

- **`qwen-multilingual`**: unrelated to this ADR — a rename-induced bug (see the multilingual-assertion fix earlier this session) where the translatable prompt text no longer matched its assertion. Already fixed; this case was never really about token budgets.
- **`concise-instruction`**: a second, independent problem the runaway reasoning trace happened to expose. The prompt — "Name the Linux distribution targeted by this project" — gave the model no way to derive "Ubuntu Desktop" from the conversation itself; every call is stateless with no system context establishing what "this project" is. The model's own `reasoning` output confirmed it: *"There is no context provided about what 'this project' refers to... this looks like a trick question."* Reworded the prompt to state the fact in-context ("This deployment runbook targets one operating system: Ubuntu Desktop. Name that operating system...") so the case measures what it's meant to measure — concise output-format compliance — not private-repo trivia recall. Verified live: 3/3 smoke cases pass, mean latency dropped from 25.0s to 2.6s (the model no longer has anything ambiguous to reason about), and `eval qwen` is 5/5.

The acceptance gate's `--max-median-latency-ms`/`--max-p95-latency-ms` thresholds remain the real backstop for the underlying "how slow can a single request get" question — they're already correctly catching it (`model accept` rejected `local/qwen-fast` on p95 latency in this session's own eval+benchmark bundles) and nothing here loosens that gate.

## Consequences

- No request through Bifrost — eval, benchmark, Open WebUI, Hermes Agent, anything — can currently rely on `max_tokens` (or `max_completion_tokens`) actually bounding Ollama generation length. Latency and GPU-hold time for any single request are effectively unbounded until the model produces a natural stop or exhausts the context window.
- This is a real, felt UX cost, not just a test artifact: a trivial Open WebUI chat message can legitimately take 10–70+ seconds and thousands of tokens with no way for the caller to say "stop sooner." On a single shared desktop GPU, that's a real resource-governance gap this project otherwise cares a great deal about.
- `local/qwen-fast`'s registry status (`approved-for-measurement-only`) has not been upgraded to a passing acceptance decision, and this ADR is part of why: it hasn't earned it under real measurement, exactly as ADR 0009 intends. Whether it should remain the daily default *despite* this — or whether a non-thinking-by-default candidate should be measured instead — is a real product decision, not something this ADR resolves.
- Revisit when `BIFROST_IMAGE` is next bumped: retest all three request shapes above; if `num_predict` conversion starts working, the eval-dataset budgets raised here can shrink back down, and the deeper latency question gets meaningfully easier to govern.
