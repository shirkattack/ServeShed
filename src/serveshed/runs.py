from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from serveshed.artifacts import ArtifactError, verify_checksums


class RunError(RuntimeError):
    """Raised when stored run artifacts cannot be discovered or interpreted."""


@dataclass(frozen=True, slots=True)
class RunRecord:
    kind: str
    run_id: str
    suite: str
    model: str
    run_dir: Path
    score_name: str
    score: float
    median_latency_ms: float
    modified_ns: int

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["run_dir"] = str(self.run_dir)
        value.pop("modified_ns", None)
        return value


def discover_runs(
    base: Path,
    *,
    kind: str | None = None,
    suite: str | None = None,
    model: str | None = None,
    limit: int = 50,
) -> tuple[RunRecord, ...]:
    if limit < 1:
        raise RunError("limit must be at least 1")
    if not base.exists():
        return ()
    records: list[RunRecord] = []
    for summary_path in base.rglob("summary.json"):
        if "sources" in summary_path.relative_to(base).parts[:-1]:
            # An acceptance bundle embeds checksummed copies of its source
            # evaluation/benchmark summaries under sources/*/summary.json.
            # Those are not independent runs; skip them so each real run is
            # only ever counted once.
            continue
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        detected_kind = str(payload.get("kind") or _infer_kind(payload))
        detected_suite = str(payload.get("suite", ""))
        detected_model = str(payload.get("model", ""))
        if kind is not None and detected_kind != kind:
            continue
        if suite is not None and detected_suite != suite:
            continue
        if model is not None and detected_model != model:
            continue
        score_name, score = _score(payload, detected_kind)
        latency = float(payload.get("median_latency_ms") or payload.get("mean_latency_ms") or 0.0)
        run_dir = summary_path.parent
        records.append(
            RunRecord(
                kind=detected_kind,
                run_id=str(payload.get("run_id", run_dir.name)),
                suite=detected_suite,
                model=detected_model,
                run_dir=run_dir,
                score_name=score_name,
                score=score,
                median_latency_ms=latency,
                modified_ns=summary_path.stat().st_mtime_ns,
            )
        )
    records.sort(key=lambda item: item.modified_ns, reverse=True)
    return tuple(records[:limit])


def verify_run(run_dir: Path) -> tuple[dict[str, Any], ...]:
    try:
        return tuple(item.as_dict() for item in verify_checksums(run_dir))
    except ArtifactError as exc:
        raise RunError(str(exc)) from exc


def render_markdown_table(records: tuple[RunRecord, ...]) -> str:
    lines = [
        "| Kind | Suite | Model | Score | Median latency | Run |",
        "|---|---|---|---:|---:|---|",
    ]
    for record in records:
        lines.append(
            "| "
            + " | ".join(
                (
                    record.kind,
                    record.suite,
                    record.model,
                    f"{record.score_name}={record.score:.3f}",
                    f"{record.median_latency_ms:.1f} ms",
                    record.run_id,
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _infer_kind(payload: dict[str, Any]) -> str:
    if "pass_rate" in payload:
        return "evaluation"
    if "success_rate" in payload:
        return "benchmark"
    return "unknown"


def _score(payload: dict[str, Any], kind: str) -> tuple[str, float]:
    if kind == "evaluation":
        return "pass_rate", float(payload.get("pass_rate", 0.0))
    if kind == "benchmark":
        return "success_rate", float(payload.get("success_rate", 0.0))
    if kind == "model-acceptance":
        return "accepted", float(payload.get("score", 0.0))
    return "score", float(payload.get("score", 0.0))
