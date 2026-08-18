# Evaluation, benchmarking, and model acceptance

Evaluation is a release gate, not a side script.

## Layers

1. Built-in deterministic checks: exact match, required/prohibited text, regex, JSON validity, minimal JSON Schema, tool names/arguments, finish reason, and latency limits.
2. Built-in full-path benchmarks: repeated sequential requests through Bifrost with warmups excluded from aggregates.
3. Promptfoo: reproducible gateway regressions and controlled red-team cases; stays in this repo because it exercises Bifrost's own gateway contract, not model content.
4. Inspect AI: tools, agents, coding, multimodal, and multi-step scenarios. Per ADR 0017, this lives in a separate repo and connects to Bifrost as an ordinary virtual-key caller (same pattern as Hermes Agent) rather than as a `uv` dependency group here.
5. lm-evaluation-harness: a curated standard benchmark subset. Same as Inspect AI — a separate repo, a dedicated Bifrost virtual key, not an in-repo dependency.
6. LLM judge: only for residual subjective qualities and preferably a different model family in a separate GPU phase.

Layers 4 and 5 produce supplementary evidence reviewed by hand unless a future reviewed decision teaches them to emit the built-in bundle schema (manifest/summary/checksums, ADR 0008) so `serveshed model accept` can ingest their results directly.

## Offline plans

These commands validate datasets and count requests without contacting a model:

```bash
uv run serveshed eval smoke --dry-run
uv run serveshed eval qwen --dry-run
uv run serveshed benchmark plan interactive --repetitions 3 --warmup 1
uv run serveshed benchmark plan throughput --repetitions 3 --warmup 1
```

## Live runs

```bash
uv run serveshed eval smoke --model local/qwen-fast
uv run serveshed eval qwen --model local/qwen-fast
uv run serveshed benchmark run interactive --model local/qwen-fast
uv run serveshed benchmark run throughput --model local/qwen-fast
```

The CLI starts the appropriate runtime through the safe lifecycle path and switches Bifrost to the explicit evaluation-content configuration.

## Immutable bundles

Evaluation bundle:

```text
evaluations/<date>/<run-id>/
├── manifest.json
├── input-dataset.jsonl
├── results.jsonl
├── summary.json
└── checksums.sha256
```

Benchmark bundle:

```text
benchmarks/<date>/<run-id>/
├── manifest.json
├── input-dataset.jsonl
├── samples.jsonl
├── summary.json
└── checksums.sha256
```

Acceptance bundle:

```text
acceptance/<date>/<run-id>/
├── decision.json
├── summary.json
├── sources/
│   ├── evaluation/{manifest.json,summary.json,checksums.sha256}
│   └── benchmark/{manifest.json,summary.json,checksums.sha256}
└── checksums.sha256
```

`input-dataset.jsonl` contains exactly the cases executed, including when `--limit` is used. The manifest records both the source-dataset digest and the selected-input digest. Runs also record model registry metadata, generation parameters, trace metadata, hardware snapshots, raw responses, errors, token usage, latency, throughput, aggregate scores, and checksums.

## Compare and verify

```bash
uv run serveshed eval compare <eval-a> <eval-b>
uv run serveshed benchmark compare <bench-a> <bench-b>
uv run serveshed runs list
uv run serveshed runs list --kind benchmark --model local/qwen-fast
uv run serveshed runs list --kind model-acceptance --markdown
uv run serveshed runs verify <run-directory>
```

Comparisons require the same suite. Checksum verification rejects mismatches, missing files, untracked files, symlinks, and unsafe paths; it must pass before results are used for a decision.

## Acceptance gate

```bash
uv run serveshed model accept \
  --eval-run <evaluation-run> \
  --benchmark-run <benchmark-run> \
  --min-pass-rate 1.0 \
  --min-success-rate 1.0 \
  --min-tokens-per-second 20 \
  --max-median-latency-ms 5000 \
  --max-p95-latency-ms 10000
```

The command requires both bundles to:

- have valid checksum manifests
- identify the same registered model alias
- have the expected bundle kinds
- satisfy every configured threshold

Add `--promote` to update the default only after acceptance. A failed gate still writes a decision bundle but never changes `.env`.

## Phoenix correlation

Bifrost sends OTLP to the collector, which exports to Phoenix. Runners attach `x-bf-eh-*` metadata including experiment ID, suite, case, dataset digest, model alias, runtime, quantization, and agent identity.

Content logging is on by default for all Bifrost traffic now, not just eval workflows (ADR 0016) — `config.json` and `config.eval.json` are currently identical on this. Eval workflows still switch to `config.eval.json` explicitly, in case something other than content logging needs to differ between normal and eval runs later. Treat Phoenix traces and eval bundles as sensitive.

## Single-GPU judging

1. Generate and save target outputs.
2. Stop/unload the target model.
3. Load the cross-family judge.
4. Judge the saved outputs without regenerating them.
5. Preserve target, judge, rubric, and human-calibration data.

Never use only self-grading, and never let a judge configuration change mutate the original target run.
