from __future__ import annotations

import base64
import json
import mimetypes
import re
import statistics
import subprocess
from collections.abc import Iterable, Mapping
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
from serveshed.doctor import hardware_snapshot
from serveshed.models import ModelRegistryError, get_model
from serveshed.settings import Settings


class EvaluationError(RuntimeError):
    """Raised for invalid evaluation input or a failed run setup."""


@dataclass(frozen=True, slots=True)
class AssertionResult:
    kind: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    passed: bool
    latency_ms: float
    response: dict[str, Any] | None
    error: str | None
    assertions: tuple[AssertionResult, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "latency_ms": round(self.latency_ms, 3),
            "response": self.response,
            "error": self.error,
            "assertions": [item.as_dict() for item in self.assertions],
        }


def dataset_for_suite(settings: Settings, suite: str) -> Path:
    if suite not in {"smoke", "qwen"}:
        raise EvaluationError(f"Unsupported evaluation suite {suite!r}")
    path = settings.root / "evals" / "datasets" / f"{suite}.jsonl"
    if not path.is_file():
        raise EvaluationError(f"Dataset not found: {path}")
    return path


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise EvaluationError(f"Dataset not found: {path}")
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvaluationError(f"Invalid JSON on {path}:{line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise EvaluationError(f"Case on {path}:{line_number} must be an object")
        case_id = value.get("id")
        if not isinstance(case_id, str) or not case_id:
            raise EvaluationError(f"Case on {path}:{line_number} needs a non-empty string id")
        if case_id in seen:
            raise EvaluationError(f"Duplicate case id {case_id!r} in {path}")
        messages = value.get("messages")
        assertions = value.get("assertions")
        if not isinstance(messages, list) or not messages:
            raise EvaluationError(f"Case {case_id!r} must contain messages")
        if not isinstance(assertions, list) or not assertions:
            raise EvaluationError(f"Case {case_id!r} must contain assertions")
        seen.add(case_id)
        cases.append(value)
    if not cases:
        raise EvaluationError(f"No cases found in {path}")
    return cases


def _asset_data_uri(path: Path) -> str:
    if not path.is_file():
        raise EvaluationError(f"Evaluation asset not found: {path}")
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def materialize_messages(settings: Settings, case: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_messages = case.get("messages")
    if not isinstance(raw_messages, list):
        raise EvaluationError(f"Case {case.get('id')!r} messages must be a list")
    messages: list[dict[str, Any]] = []
    for raw_message in raw_messages:
        if not isinstance(raw_message, Mapping):
            raise EvaluationError(f"Case {case.get('id')!r} has an invalid message")
        message = dict(raw_message)
        content = message.get("content")
        if isinstance(content, list):
            rendered: list[Any] = []
            for item in content:
                if isinstance(item, Mapping) and item.get("type") == "image_path":
                    relative = Path(str(item.get("path", "")))
                    asset = relative if relative.is_absolute() else settings.root / relative
                    rendered.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": _asset_data_uri(asset)},
                        }
                    )
                else:
                    rendered.append(dict(item) if isinstance(item, Mapping) else item)
            message["content"] = rendered
        messages.append(message)
    return messages


def _assistant_message(response: Mapping[str, Any]) -> Mapping[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return {}
    choice = choices[0]
    if not isinstance(choice, Mapping):
        return {}
    message = choice.get("message")
    return message if isinstance(message, Mapping) else {}


def _text_content(response: Mapping[str, Any]) -> str:
    content = _assistant_message(response).get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, Mapping):
                parts.append(str(item.get("text", "")))
        return "\n".join(parts)
    return str(content or "")


def _json_candidate(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, count=1)
        stripped = re.sub(r"\s*```$", "", stripped, count=1)
    return stripped


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _minimal_schema(value: Any, schema: Mapping[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    expected = schema.get("type")
    if isinstance(expected, str) and not _matches_type(value, expected):
        return [f"{path} expected {expected}, got {type(value).__name__}"]
    if isinstance(value, dict):
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if key not in value:
                    errors.append(f"{path}.{key} is required")
        properties = schema.get("properties", {})
        if isinstance(properties, Mapping):
            for key, child_schema in properties.items():
                if key in value and isinstance(child_schema, Mapping):
                    errors.extend(_minimal_schema(value[key], child_schema, f"{path}.{key}"))
        if schema.get("additionalProperties") is False and isinstance(properties, Mapping):
            extras = set(value) - set(properties)
            errors.extend(f"{path}.{key} is not allowed" for key in sorted(extras))
    if isinstance(value, list) and isinstance(schema.get("items"), Mapping):
        for index, item in enumerate(value):
            errors.extend(_minimal_schema(item, schema["items"], f"{path}[{index}]"))
    return errors


def _tool_calls(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    calls = _assistant_message(response).get("tool_calls", [])
    if not isinstance(calls, list):
        return []
    return [call for call in calls if isinstance(call, Mapping)]


def grade_assertions(
    assertions: Iterable[Mapping[str, Any]],
    *,
    response: Mapping[str, Any],
    latency_ms: float,
) -> tuple[AssertionResult, ...]:
    text = _text_content(response)
    results: list[AssertionResult] = []
    for assertion in assertions:
        kind = str(assertion.get("type", ""))
        value = assertion.get("value")
        passed = False
        detail = ""
        if kind == "exact":
            passed = text.strip() == str(value).strip()
            detail = f"expected exact {value!r}; received {text.strip()!r}"
        elif kind == "contains":
            case_sensitive = bool(assertion.get("case_sensitive", False))
            haystack = text if case_sensitive else text.lower()
            needle = str(value) if case_sensitive else str(value).lower()
            passed = needle in haystack
            detail = f"required substring {value!r}"
        elif kind == "not_contains":
            case_sensitive = bool(assertion.get("case_sensitive", False))
            haystack = text if case_sensitive else text.lower()
            needle = str(value) if case_sensitive else str(value).lower()
            passed = needle not in haystack
            detail = f"prohibited substring {value!r}"
        elif kind == "regex":
            passed = re.search(str(value), text, flags=re.MULTILINE) is not None
            detail = f"required regex {value!r}"
        elif kind == "json_valid":
            try:
                json.loads(_json_candidate(text))
                passed = True
                detail = "response parses as JSON"
            except json.JSONDecodeError as exc:
                detail = str(exc)
        elif kind == "json_schema":
            schema = assertion.get("schema", {})
            try:
                parsed = json.loads(_json_candidate(text))
                errors = _minimal_schema(parsed, schema if isinstance(schema, Mapping) else {})
                passed = not errors
                detail = "; ".join(errors) if errors else "minimal schema checks passed"
            except json.JSONDecodeError as exc:
                detail = str(exc)
        elif kind == "tool_name":
            names = [
                str(call.get("function", {}).get("name", "")) for call in _tool_calls(response)
            ]
            passed = str(value) in names
            detail = f"tool calls: {names}"
        elif kind == "tool_arguments_json":
            name = str(assertion.get("name", ""))
            matching = [
                call
                for call in _tool_calls(response)
                if call.get("function", {}).get("name") == name
            ]
            if matching:
                raw_arguments = matching[0].get("function", {}).get("arguments", "")
                try:
                    json.loads(str(raw_arguments))
                    passed = True
                    detail = f"arguments for {name!r} parse as JSON"
                except json.JSONDecodeError as exc:
                    detail = str(exc)
            else:
                detail = f"no tool call named {name!r}"
        elif kind == "max_latency_ms":
            limit = float(value or 0.0)
            passed = latency_ms <= limit
            detail = f"{latency_ms:.1f} ms <= {limit:.1f} ms"
        elif kind == "finish_reason":
            choices = response.get("choices", [])
            actual = (
                choices[0].get("finish_reason")
                if isinstance(choices, list) and choices and isinstance(choices[0], Mapping)
                else None
            )
            passed = actual == value
            detail = f"finish_reason={actual!r}"
        else:
            detail = f"unknown assertion type {kind!r}"
        results.append(AssertionResult(kind, passed, detail))
    return tuple(results)


def _git_commit(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def plan_suite(
    settings: Settings,
    suite: str,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    dataset = dataset_for_suite(settings, suite)
    selected = load_jsonl(dataset)
    if limit is not None:
        if limit < 1:
            raise EvaluationError("--limit must be at least 1")
        selected = selected[:limit]
    return {
        "suite": suite,
        "dataset": str(dataset.relative_to(settings.root)),
        "dataset_sha256": sha256_file(dataset),
        "case_count": len(selected),
        "cases": [
            {
                "id": case["id"],
                "assertion_types": [item.get("type") for item in case.get("assertions", [])],
            }
            for case in selected
        ],
    }


def run_suite(
    settings: Settings,
    suite: str,
    *,
    model: str,
    limit: int | None = None,
    timeout: float = 900.0,
) -> Path:
    settings.require_initialized()
    dataset = dataset_for_suite(settings, suite)
    selected = load_jsonl(dataset)
    if limit is not None:
        if limit < 1:
            raise EvaluationError("--limit must be at least 1")
        selected = selected[:limit]
    if not selected:
        raise EvaluationError(f"No cases selected for suite {suite!r}")

    run_id, run_dir, now = create_run_dir(
        settings.eval_runs_dir,
        category="evaluations",
        label=f"{suite}-{model}",
    )
    input_dataset = run_dir / "input-dataset.jsonl"
    write_jsonl(input_dataset, selected)
    source_dataset_digest = sha256_file(dataset)
    input_dataset_digest = sha256_file(input_dataset)

    try:
        model_spec = get_model(settings, model).as_dict()
    except ModelRegistryError:
        model_spec = {"alias": model, "gateway_model": model, "registry": "unregistered"}

    manifest = {
        "run_id": run_id,
        "kind": "evaluation",
        "suite": suite,
        "model": model,
        "model_spec": model_spec,
        "created_at": now.isoformat(),
        "source_dataset": str(dataset.relative_to(settings.root)),
        "source_dataset_sha256": source_dataset_digest,
        "input_dataset": "input-dataset.jsonl",
        "input_dataset_sha256": input_dataset_digest,
        "dataset_sha256": input_dataset_digest,
        "selected_case_ids": [str(case["id"]) for case in selected],
        "git_commit": _git_commit(settings.root),
        "hardware": hardware_snapshot(settings),
        "generation_policy": "case-defined; gateway retries and semantic cache disabled",
        "bifrost_url": f"{settings.bifrost_base_url}/v1",
        "content_logging_requested": True,
    }
    write_json(run_dir / "manifest.json", manifest)

    results: list[CaseResult] = []
    recorded_metrics: list[dict[str, Any]] = []
    output_path = run_dir / "results.jsonl"
    for case in selected:
        parameters = case.get("parameters", {})
        if not isinstance(parameters, dict):
            parameters = {}
        messages = materialize_messages(settings, case)
        metadata = {
            "workload": "evaluation",
            "experiment-id": run_id,
            "eval-suite": suite,
            "case-id": str(case["id"]),
            "dataset-sha256": input_dataset_digest,
            "runtime": str(model_spec.get("runtime", "unknown")),
            "model-revision": str(model_spec.get("revision", "unknown")),
            "quantization": str(model_spec.get("quantization", "unknown")),
            "git-commit": str(manifest.get("git_commit") or "uncommitted"),
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
            assertions = grade_assertions(
                case.get("assertions", []),
                response=response,
                latency_ms=latency_ms,
            )
            result = CaseResult(
                case_id=str(case["id"]),
                passed=all(item.passed for item in assertions),
                latency_ms=latency_ms,
                response=response,
                error=None,
                assertions=assertions,
            )
        except Exception as exc:
            result = CaseResult(
                case_id=str(case["id"]),
                passed=False,
                latency_ms=0.0,
                response=None,
                error=f"{type(exc).__name__}: {exc}",
                assertions=(),
            )
        results.append(result)
        metrics = _response_metrics(result.response, result.latency_ms)
        recorded_metrics.append(metrics)
        row = result.as_dict()
        row["metrics"] = metrics
        row["request"] = {
            "model": model,
            "messages": messages,
            "parameters": parameters,
        }
        append_jsonl(output_path, row)

    passed_count = sum(result.passed for result in results)
    latencies = [result.latency_ms for result in results if result.latency_ms > 0]
    prompt_tokens = sum(int(item.get("prompt_tokens") or 0) for item in recorded_metrics)
    completion_tokens = sum(int(item.get("completion_tokens") or 0) for item in recorded_metrics)
    throughputs = [
        float(item["completion_tokens_per_second"])
        for item in recorded_metrics
        if item.get("completion_tokens_per_second") is not None
    ]
    summary = {
        "run_id": run_id,
        "kind": "evaluation",
        "suite": suite,
        "model": model,
        "cases": len(results),
        "passed": passed_count,
        "failed": len(results) - passed_count,
        "pass_rate": passed_count / len(results),
        "mean_latency_ms": statistics.fmean(latencies) if latencies else 0.0,
        "median_latency_ms": statistics.median(latencies) if latencies else 0.0,
        "p95_latency_ms": percentile(latencies, 95),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "mean_completion_tokens_per_second": (
            statistics.fmean(throughputs) if throughputs else 0.0
        ),
    }
    write_json(run_dir / "summary.json", summary)
    write_checksums(run_dir)
    return run_dir


def _response_metrics(response: Mapping[str, Any] | None, latency_ms: float) -> dict[str, Any]:
    usage = response.get("usage", {}) if isinstance(response, Mapping) else {}
    if not isinstance(usage, Mapping):
        usage = {}

    def token_value(name: str) -> int | None:
        value = usage.get(name)
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else None

    prompt = token_value("prompt_tokens")
    completion = token_value("completion_tokens")
    total = token_value("total_tokens")
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    throughput = (
        completion / (latency_ms / 1000.0)
        if completion is not None and completion > 0 and latency_ms > 0
        else None
    )
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "completion_tokens_per_second": throughput,
    }


def load_evaluation_summary(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "summary.json"
    if not path.is_file():
        raise EvaluationError(f"Evaluation summary not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"Invalid evaluation summary {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise EvaluationError(f"Evaluation summary is not an object: {path}")
    if payload.get("kind") not in {None, "evaluation"}:
        raise EvaluationError(f"Not an evaluation summary: {path}")
    return payload


def compare_evaluations(run_dirs: list[Path]) -> dict[str, Any]:
    if len(run_dirs) < 2:
        raise EvaluationError("At least two evaluation run directories are required")
    summaries = [load_evaluation_summary(path) for path in run_dirs]
    suites = {str(summary.get("suite")) for summary in summaries}
    if len(suites) != 1:
        raise EvaluationError("Evaluation runs must use the same suite")
    rows: list[dict[str, Any]] = [
        {
            "run_dir": str(path),
            "run_id": summary.get("run_id"),
            "model": summary.get("model"),
            "pass_rate": float(summary.get("pass_rate", 0.0)),
            "median_latency_ms": float(
                summary.get("median_latency_ms", summary.get("mean_latency_ms", 0.0))
            ),
            "p95_latency_ms": float(
                summary.get("p95_latency_ms", summary.get("mean_latency_ms", 0.0))
            ),
            "mean_completion_tokens_per_second": float(
                summary.get("mean_completion_tokens_per_second", 0.0)
            ),
        }
        for path, summary in zip(run_dirs, summaries, strict=True)
    ]
    rows.sort(
        key=lambda row: (
            -row["pass_rate"],
            row["median_latency_ms"],
            -row["mean_completion_tokens_per_second"],
        )
    )
    return {"suite": suites.pop(), "runs": rows}
