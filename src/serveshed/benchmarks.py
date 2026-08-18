from __future__ import annotations

import json
import statistics
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from serveshed.artifacts import (
    append_jsonl,
    create_run_dir,
    percentile,
    sha256_file,
    write_checksums,
    write_json,
    write_jsonl,
)
from serveshed.client import chat_completion
from serveshed.hardware import machine_snapshot
from serveshed.models import ModelRegistryError, get_model
from serveshed.settings import Settings


class BenchmarkError(RuntimeError):
    """Raised when a benchmark suite or run is invalid."""


@dataclass(frozen=True, slots=True)
class BenchmarkSample:
    case_id: str
    iteration: int
    warmup: bool
    success: bool
    latency_ms: float
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    completion_tokens_per_second: float | None
    response: dict[str, Any] | None
    error: str | None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["latency_ms"] = round(self.latency_ms, 3)
        if self.completion_tokens_per_second is not None:
            value["completion_tokens_per_second"] = round(self.completion_tokens_per_second, 3)
        return value


def benchmark_dataset(settings: Settings, suite: str) -> Path:
    if not suite or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in suite
    ):
        raise BenchmarkError(f"Invalid benchmark suite name {suite!r}")
    path = settings.root / "evals" / "benchmarks" / f"{suite}.jsonl"
    if not path.is_file():
        raise BenchmarkError(f"Benchmark dataset not found: {path}")
    return path


def load_benchmark_cases(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise BenchmarkError(f"Benchmark dataset not found: {path}")
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BenchmarkError(f"Invalid JSON on {path}:{line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise BenchmarkError(f"Case on {path}:{line_number} must be an object")
        case_id = value.get("id")
        messages = value.get("messages")
        if not isinstance(case_id, str) or not case_id:
            raise BenchmarkError(f"Case on {path}:{line_number} needs a non-empty id")
        if case_id in seen:
            raise BenchmarkError(f"Duplicate benchmark case id {case_id!r}")
        if not isinstance(messages, list) or not messages:
            raise BenchmarkError(f"Benchmark case {case_id!r} must contain messages")
        parameters = value.get("parameters", {})
        if not isinstance(parameters, dict):
            raise BenchmarkError(f"Benchmark case {case_id!r} parameters must be an object")
        seen.add(case_id)
        cases.append(value)
    if not cases:
        raise BenchmarkError(f"No benchmark cases found in {path}")
    return cases


def plan_benchmark(
    settings: Settings,
    suite: str,
    *,
    repetitions: int,
    warmup: int,
    limit: int | None = None,
) -> dict[str, Any]:
    _validate_counts(repetitions, warmup)
    dataset = benchmark_dataset(settings, suite)
    cases = load_benchmark_cases(dataset)
    if limit is not None:
        if limit < 1:
            raise BenchmarkError("--limit must be at least 1")
        cases = cases[:limit]
    return {
        "suite": suite,
        "dataset": str(dataset.relative_to(settings.root)),
        "dataset_sha256": sha256_file(dataset),
        "case_count": len(cases),
        "warmup_per_case": warmup,
        "recorded_repetitions_per_case": repetitions,
        "network_requests": len(cases) * (warmup + repetitions),
        "cases": [
            {
                "id": str(case["id"]),
                "tags": list(case.get("tags", []))
                if isinstance(case.get("tags", []), list)
                else [],
                "parameters": dict(case.get("parameters", {})),
            }
            for case in cases
        ],
    }


def run_benchmark(
    settings: Settings,
    suite: str,
    *,
    model: str,
    repetitions: int = 3,
    warmup: int = 1,
    limit: int | None = None,
    timeout: float = 900.0,
) -> Path:
    settings.require_initialized()
    plan = plan_benchmark(
        settings,
        suite,
        repetitions=repetitions,
        warmup=warmup,
        limit=limit,
    )
    dataset = benchmark_dataset(settings, suite)
    cases = load_benchmark_cases(dataset)
    if limit is not None:
        cases = cases[:limit]

    run_id, run_dir, now = create_run_dir(
        settings.eval_runs_dir,
        category="benchmarks",
        label=f"{suite}-{model}",
    )
    input_dataset = run_dir / "input-dataset.jsonl"
    write_jsonl(input_dataset, cases)
    source_dataset_digest = sha256_file(dataset)
    input_dataset_digest = sha256_file(input_dataset)
    try:
        model_spec = get_model(settings, model).as_dict()
    except ModelRegistryError:
        model_spec = {"alias": model, "gateway_model": model, "registry": "unregistered"}

    manifest = {
        "run_id": run_id,
        "kind": "benchmark",
        "suite": suite,
        "model": model,
        "model_spec": model_spec,
        "created_at": now.isoformat(),
        "source_dataset": plan["dataset"],
        "source_dataset_sha256": source_dataset_digest,
        "input_dataset": "input-dataset.jsonl",
        "input_dataset_sha256": input_dataset_digest,
        "dataset_sha256": input_dataset_digest,
        "selected_case_ids": [str(case["id"]) for case in cases],
        "warmup_per_case": warmup,
        "recorded_repetitions_per_case": repetitions,
        "hardware_before": machine_snapshot(settings.data_dir),
        "bifrost_url": f"{settings.bifrost_base_url}/v1",
        "methodology": (
            "Sequential requests through Bifrost. Warmups are retained in raw samples but "
            "excluded from aggregate latency and throughput metrics. Completion throughput "
            "is completion tokens divided by total end-to-end request latency."
        ),
    }
    write_json(run_dir / "manifest.json", manifest)

    samples: list[BenchmarkSample] = []
    output_path = run_dir / "samples.jsonl"
    for case in cases:
        case_id = str(case["id"])
        parameters = dict(case.get("parameters", {}))
        messages = _messages(case)
        total_iterations = warmup + repetitions
        for iteration in range(total_iterations):
            is_warmup = iteration < warmup
            metadata = {
                "workload": "benchmark",
                "experiment-id": run_id,
                "benchmark-suite": suite,
                "case-id": case_id,
                "iteration": iteration,
                "warmup": is_warmup,
                "dataset-sha256": input_dataset_digest,
                "runtime": str(model_spec.get("runtime", "unknown")),
                "model-revision": str(model_spec.get("revision", "unknown")),
                "quantization": str(model_spec.get("quantization", "unknown")),
            }
            try:
                response, latency_ms = chat_completion(
                    settings,
                    model=model,
                    messages=messages,
                    agent="eval",
                    metadata=metadata,
                    timeout=timeout,
                    **parameters,
                )
                usage = _usage(response)
                completion_tokens = usage.get("completion_tokens")
                throughput = (
                    float(completion_tokens) / (latency_ms / 1000.0)
                    if isinstance(completion_tokens, int)
                    and completion_tokens > 0
                    and latency_ms > 0
                    else None
                )
                sample = BenchmarkSample(
                    case_id=case_id,
                    iteration=iteration,
                    warmup=is_warmup,
                    success=True,
                    latency_ms=latency_ms,
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=completion_tokens,
                    total_tokens=usage.get("total_tokens"),
                    completion_tokens_per_second=throughput,
                    response=response,
                    error=None,
                )
            except Exception as exc:
                sample = BenchmarkSample(
                    case_id=case_id,
                    iteration=iteration,
                    warmup=is_warmup,
                    success=False,
                    latency_ms=0.0,
                    prompt_tokens=None,
                    completion_tokens=None,
                    total_tokens=None,
                    completion_tokens_per_second=None,
                    response=None,
                    error=f"{type(exc).__name__}: {exc}",
                )
            samples.append(sample)
            append_jsonl(output_path, sample.as_dict())

    recorded = [sample for sample in samples if not sample.warmup]
    successful = [sample for sample in recorded if sample.success]
    latencies = [sample.latency_ms for sample in successful]
    throughputs = [
        sample.completion_tokens_per_second
        for sample in successful
        if sample.completion_tokens_per_second is not None
    ]
    prompt_tokens = sum(sample.prompt_tokens or 0 for sample in successful)
    completion_tokens = sum(sample.completion_tokens or 0 for sample in successful)
    total_latency_seconds = sum(latencies) / 1000.0
    summary = {
        "run_id": run_id,
        "kind": "benchmark",
        "suite": suite,
        "model": model,
        "cases": len(cases),
        "warmup_samples": len(samples) - len(recorded),
        "recorded_samples": len(recorded),
        "successful_samples": len(successful),
        "failed_samples": len(recorded) - len(successful),
        "success_rate": len(successful) / len(recorded) if recorded else 0.0,
        "mean_latency_ms": statistics.fmean(latencies) if latencies else 0.0,
        "median_latency_ms": statistics.median(latencies) if latencies else 0.0,
        "p95_latency_ms": percentile(latencies, 95),
        "mean_completion_tokens_per_second": (
            statistics.fmean(throughputs) if throughputs else 0.0
        ),
        "aggregate_completion_tokens_per_second": (
            completion_tokens / total_latency_seconds if total_latency_seconds > 0 else 0.0
        ),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "hardware_after": machine_snapshot(settings.data_dir),
    }
    write_json(run_dir / "summary.json", summary)
    write_checksums(run_dir)
    return run_dir


def load_benchmark_summary(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "summary.json"
    if not path.is_file():
        raise BenchmarkError(f"Benchmark summary not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BenchmarkError(f"Invalid benchmark summary {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("kind") != "benchmark":
        raise BenchmarkError(f"Not a benchmark summary: {path}")
    return payload


def compare_benchmarks(run_dirs: list[Path]) -> dict[str, Any]:
    if len(run_dirs) < 2:
        raise BenchmarkError("At least two benchmark run directories are required")
    summaries = [load_benchmark_summary(path) for path in run_dirs]
    suites = {str(summary.get("suite")) for summary in summaries}
    if len(suites) != 1:
        raise BenchmarkError("Benchmark runs must use the same suite")
    rows: list[dict[str, Any]] = [
        {
            "run_dir": str(path),
            "run_id": summary.get("run_id"),
            "model": summary.get("model"),
            "success_rate": float(summary.get("success_rate", 0.0)),
            "median_latency_ms": float(summary.get("median_latency_ms", 0.0)),
            "p95_latency_ms": float(summary.get("p95_latency_ms", 0.0)),
            "mean_completion_tokens_per_second": float(
                summary.get("mean_completion_tokens_per_second", 0.0)
            ),
        }
        for path, summary in zip(run_dirs, summaries, strict=True)
    ]
    rows.sort(
        key=lambda row: (
            -row["success_rate"],
            -row["mean_completion_tokens_per_second"],
            row["median_latency_ms"],
        )
    )
    return {"suite": suites.pop(), "runs": rows}


def _validate_counts(repetitions: int, warmup: int) -> None:
    if repetitions < 1:
        raise BenchmarkError("--repetitions must be at least 1")
    if warmup < 0:
        raise BenchmarkError("--warmup cannot be negative")


def _messages(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = case.get("messages", [])
    if not isinstance(raw, list):
        raise BenchmarkError(f"Case {case.get('id')!r} messages must be a list")
    rendered: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise BenchmarkError(f"Case {case.get('id')!r} has an invalid message")
        rendered.append(dict(item))
    return rendered


def _usage(response: Mapping[str, Any]) -> dict[str, int | None]:
    raw = response.get("usage", {})
    if not isinstance(raw, Mapping):
        raw = {}

    def integer(name: str) -> int | None:
        value = raw.get(name)
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else None

    prompt = integer("prompt_tokens")
    completion = integer("completion_tokens")
    total = integer("total_tokens")
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }
