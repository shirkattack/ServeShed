from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from serveshed.artifacts import (
    create_run_dir,
    sha256_file,
    verify_checksums,
    write_checksums,
    write_json,
)
from serveshed.models import ModelRegistryError, ModelSelection, get_model, select_default_model
from serveshed.settings import Settings


class ModelAcceptanceError(RuntimeError):
    """Raised when model acceptance inputs are invalid or fail integrity checks."""


@dataclass(frozen=True, slots=True)
class AcceptanceThresholds:
    min_pass_rate: float = 1.0
    min_success_rate: float = 1.0
    min_completion_tokens_per_second: float = 0.0
    max_median_latency_ms: float | None = None
    max_p95_latency_ms: float | None = None

    def validate(self) -> None:
        for name, value in (
            ("min_pass_rate", self.min_pass_rate),
            ("min_success_rate", self.min_success_rate),
        ):
            if value < 0.0 or value > 1.0:
                raise ModelAcceptanceError(f"{name} must be between 0 and 1")
        if self.min_completion_tokens_per_second < 0.0:
            raise ModelAcceptanceError("min_completion_tokens_per_second cannot be negative")
        for name, limit in (
            ("max_median_latency_ms", self.max_median_latency_ms),
            ("max_p95_latency_ms", self.max_p95_latency_ms),
        ):
            if limit is not None and limit <= 0.0:
                raise ModelAcceptanceError(f"{name} must be greater than zero")

    def as_dict(self) -> dict[str, float | None]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AcceptanceCheck:
    name: str
    observed: float | str | bool
    requirement: float | str | bool
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AcceptanceDecision:
    run_id: str
    run_dir: Path
    model: str
    accepted: bool
    promoted: bool
    checks: tuple[AcceptanceCheck, ...]
    selection: ModelSelection | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "model": self.model,
            "accepted": self.accepted,
            "promoted": self.promoted,
            "checks": [item.as_dict() for item in self.checks],
            "selection": self.selection.as_dict() if self.selection else None,
        }


def assess_model_candidate(
    settings: Settings,
    *,
    evaluation_run: Path,
    benchmark_run: Path,
    thresholds: AcceptanceThresholds | None = None,
    promote: bool = False,
    allow_experimental: bool = False,
) -> AcceptanceDecision:
    thresholds = thresholds or AcceptanceThresholds()
    thresholds.validate()
    evaluation_run = evaluation_run.resolve()
    benchmark_run = benchmark_run.resolve()

    evaluation = _load_verified_summary(evaluation_run, expected_kind="evaluation")
    benchmark = _load_verified_summary(benchmark_run, expected_kind="benchmark")
    evaluation_model = str(evaluation.get("model", ""))
    benchmark_model = str(benchmark.get("model", ""))
    if not evaluation_model or evaluation_model != benchmark_model:
        raise ModelAcceptanceError(
            "Evaluation and benchmark bundles must name the same non-empty model alias"
        )
    try:
        spec = get_model(settings, evaluation_model)
    except ModelRegistryError as exc:
        raise ModelAcceptanceError(str(exc)) from exc

    checks = _build_checks(evaluation, benchmark, thresholds)
    accepted = all(item.passed for item in checks)
    selection: ModelSelection | None = None
    if promote and accepted:
        selection = select_default_model(
            settings,
            spec.alias,
            execute=True,
            allow_experimental=allow_experimental,
        )

    run_id, run_dir, created_at = create_run_dir(
        settings.eval_runs_dir,
        category="acceptance",
        label=spec.alias,
    )
    _copy_source_metadata(evaluation_run, run_dir / "sources" / "evaluation")
    _copy_source_metadata(benchmark_run, run_dir / "sources" / "benchmark")
    decision_payload = {
        "run_id": run_id,
        "kind": "model-acceptance",
        "created_at": created_at.isoformat(),
        "model": spec.alias,
        "model_spec": spec.as_dict(),
        "accepted": accepted,
        "promote_requested": promote,
        "promoted": selection is not None,
        "thresholds": thresholds.as_dict(),
        "checks": [item.as_dict() for item in checks],
        "source_runs": {
            "evaluation": _source_reference(evaluation_run),
            "benchmark": _source_reference(benchmark_run),
        },
        "selection": selection.as_dict() if selection else None,
    }
    write_json(run_dir / "decision.json", decision_payload)
    write_json(
        run_dir / "summary.json",
        {
            "run_id": run_id,
            "kind": "model-acceptance",
            "suite": f"{evaluation.get('suite', 'evaluation')}+{benchmark.get('suite', 'benchmark')}",
            "model": spec.alias,
            "accepted": accepted,
            "score": 1.0 if accepted else 0.0,
            "median_latency_ms": float(benchmark.get("median_latency_ms", 0.0)),
            "pass_rate": float(evaluation.get("pass_rate", 0.0)),
            "success_rate": float(benchmark.get("success_rate", 0.0)),
            "mean_completion_tokens_per_second": float(
                benchmark.get("mean_completion_tokens_per_second", 0.0)
            ),
        },
    )
    write_checksums(run_dir)
    return AcceptanceDecision(
        run_id=run_id,
        run_dir=run_dir,
        model=spec.alias,
        accepted=accepted,
        promoted=selection is not None,
        checks=checks,
        selection=selection,
    )


def _load_verified_summary(run_dir: Path, *, expected_kind: str) -> dict[str, Any]:
    if not run_dir.is_dir():
        raise ModelAcceptanceError(f"Run directory not found: {run_dir}")
    verification = verify_checksums(run_dir)
    failures = [item for item in verification if not item.ok]
    if failures:
        details = "; ".join(f"{item.path}: {item.detail}" for item in failures)
        raise ModelAcceptanceError(f"Run checksum verification failed: {details}")
    summary_path = run_dir / "summary.json"
    if not summary_path.is_file():
        raise ModelAcceptanceError(f"Run summary not found: {summary_path}")
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ModelAcceptanceError(f"Invalid run summary {summary_path}: {exc}") from exc
    detected_kind = payload.get("kind") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or detected_kind != expected_kind:
        raise ModelAcceptanceError(
            f"Expected a {expected_kind} bundle at {run_dir}; found {detected_kind!r}"
        )
    return payload


def _build_checks(
    evaluation: dict[str, Any],
    benchmark: dict[str, Any],
    thresholds: AcceptanceThresholds,
) -> tuple[AcceptanceCheck, ...]:
    checks: list[AcceptanceCheck] = []
    checks.append(
        _minimum_check(
            "evaluation-pass-rate",
            float(evaluation.get("pass_rate", 0.0)),
            thresholds.min_pass_rate,
        )
    )
    checks.append(
        _minimum_check(
            "benchmark-success-rate",
            float(benchmark.get("success_rate", 0.0)),
            thresholds.min_success_rate,
        )
    )
    checks.append(
        _minimum_check(
            "completion-throughput",
            float(benchmark.get("mean_completion_tokens_per_second", 0.0)),
            thresholds.min_completion_tokens_per_second,
            unit=" tokens/s",
        )
    )
    median = float(benchmark.get("median_latency_ms", 0.0))
    if thresholds.max_median_latency_ms is not None:
        checks.append(
            _maximum_check(
                "median-latency",
                median,
                thresholds.max_median_latency_ms,
                unit=" ms",
            )
        )
    p95 = float(benchmark.get("p95_latency_ms", 0.0))
    if thresholds.max_p95_latency_ms is not None:
        checks.append(
            _maximum_check(
                "p95-latency",
                p95,
                thresholds.max_p95_latency_ms,
                unit=" ms",
            )
        )
    return tuple(checks)


def _minimum_check(
    name: str,
    observed: float,
    requirement: float,
    *,
    unit: str = "",
) -> AcceptanceCheck:
    passed = observed >= requirement
    return AcceptanceCheck(
        name=name,
        observed=observed,
        requirement=requirement,
        passed=passed,
        detail=f"{observed:.4f}{unit} {'>=' if passed else '<'} {requirement:.4f}{unit}",
    )


def _maximum_check(
    name: str,
    observed: float,
    requirement: float,
    *,
    unit: str = "",
) -> AcceptanceCheck:
    passed = observed <= requirement
    return AcceptanceCheck(
        name=name,
        observed=observed,
        requirement=requirement,
        passed=passed,
        detail=f"{observed:.4f}{unit} {'<=' if passed else '>'} {requirement:.4f}{unit}",
    )


def _copy_source_metadata(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for filename in ("manifest.json", "summary.json", "checksums.sha256"):
        path = source / filename
        if path.is_file():
            shutil.copy2(path, destination / filename)


def _source_reference(run_dir: Path) -> dict[str, str]:
    summary = run_dir / "summary.json"
    checksum = run_dir / "checksums.sha256"
    return {
        "path": str(run_dir),
        "summary_sha256": sha256_file(summary),
        "checksum_manifest_sha256": sha256_file(checksum),
    }
