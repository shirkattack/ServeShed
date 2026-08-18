# Local benchmark suites

These JSONL suites measure the complete request path through Bifrost. They are not model-quality leaderboards.

- `interactive.jsonl` mixes short instruction, structured output, and small coding requests.
- `throughput.jsonl` requests a longer response so generation throughput is easier to observe.

Every case contains `id`, `messages`, optional `tags`, and OpenAI-compatible `parameters`. Warmup requests are retained in raw samples but excluded from aggregate metrics.
