from __future__ import annotations

import json
import unittest
from pathlib import Path

from serveshed.acceptance import (
    AcceptanceThresholds,
    ModelAcceptanceError,
    assess_model_candidate,
)
from serveshed.artifacts import verify_checksums, write_checksums, write_json
from serveshed.env import parse_env_file
from serveshed.runs import discover_runs
from tests.helpers import TemporarySettings


class AcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporarySettings()
        self.settings = self.temp.settings

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self, name: str, payload: dict[str, object]) -> Path:
        run_dir = self.settings.eval_runs_dir / name
        run_dir.mkdir(parents=True)
        write_json(run_dir / "manifest.json", {"run_id": name, "kind": payload["kind"]})
        write_json(run_dir / "summary.json", payload)
        write_checksums(run_dir)
        return run_dir

    def test_accepts_verified_candidate_and_writes_decision_bundle(self) -> None:
        evaluation = self._run(
            "eval",
            {
                "run_id": "eval",
                "kind": "evaluation",
                "suite": "smoke",
                "model": "local/qwen-fast",
                "pass_rate": 1.0,
            },
        )
        benchmark = self._run(
            "bench",
            {
                "run_id": "bench",
                "kind": "benchmark",
                "suite": "interactive",
                "model": "local/qwen-fast",
                "success_rate": 1.0,
                "mean_completion_tokens_per_second": 31.0,
                "median_latency_ms": 700.0,
                "p95_latency_ms": 900.0,
            },
        )
        decision = assess_model_candidate(
            self.settings,
            evaluation_run=evaluation,
            benchmark_run=benchmark,
            thresholds=AcceptanceThresholds(
                min_completion_tokens_per_second=20.0,
                max_median_latency_ms=1000.0,
                max_p95_latency_ms=1200.0,
            ),
        )
        self.assertTrue(decision.accepted)
        self.assertFalse(decision.promoted)
        payload = json.loads((decision.run_dir / "decision.json").read_text(encoding="utf-8"))
        self.assertEqual("model-acceptance", payload["kind"])
        self.assertTrue(payload["accepted"])
        self.assertTrue(all(item.ok for item in verify_checksums(decision.run_dir)))
        discovered = discover_runs(self.settings.eval_runs_dir, kind="model-acceptance")
        self.assertEqual(1, len(discovered))
        self.assertEqual("local/qwen-fast", discovered[0].model)
        self.assertEqual(1.0, discovered[0].score)

    def test_passing_candidate_can_promote_after_gate(self) -> None:
        evaluation = self._run(
            "eval-promote",
            {
                "run_id": "eval-promote",
                "kind": "evaluation",
                "suite": "smoke",
                "model": "local/qwen-quality",
                "pass_rate": 1.0,
            },
        )
        benchmark = self._run(
            "bench-promote",
            {
                "run_id": "bench-promote",
                "kind": "benchmark",
                "suite": "interactive",
                "model": "local/qwen-quality",
                "success_rate": 1.0,
                "mean_completion_tokens_per_second": 20.0,
                "median_latency_ms": 1000.0,
                "p95_latency_ms": 1500.0,
            },
        )
        decision = assess_model_candidate(
            self.settings,
            evaluation_run=evaluation,
            benchmark_run=benchmark,
            promote=True,
        )
        self.assertTrue(decision.accepted)
        self.assertTrue(decision.promoted)
        values = parse_env_file(self.settings.env_file)
        self.assertEqual("local/qwen-quality", values["SERVESHED_DEFAULT_MODEL_ALIAS"])
        self.assertIsNotNone(decision.selection)
        self.assertIsNotNone(decision.selection.backup_file if decision.selection else None)

    def test_rejected_candidate_is_not_promoted(self) -> None:
        evaluation = self._run(
            "eval-low",
            {
                "run_id": "eval-low",
                "kind": "evaluation",
                "suite": "smoke",
                "model": "local/qwen-quality",
                "pass_rate": 0.8,
            },
        )
        benchmark = self._run(
            "bench-low",
            {
                "run_id": "bench-low",
                "kind": "benchmark",
                "suite": "interactive",
                "model": "local/qwen-quality",
                "success_rate": 1.0,
                "mean_completion_tokens_per_second": 10.0,
                "median_latency_ms": 1000.0,
                "p95_latency_ms": 1200.0,
            },
        )
        before = self.settings.env_file.read_text(encoding="utf-8")
        decision = assess_model_candidate(
            self.settings,
            evaluation_run=evaluation,
            benchmark_run=benchmark,
            promote=True,
        )
        self.assertFalse(decision.accepted)
        self.assertFalse(decision.promoted)
        self.assertEqual(before, self.settings.env_file.read_text(encoding="utf-8"))

    def test_tampered_source_bundle_is_rejected(self) -> None:
        evaluation = self._run(
            "eval-tampered",
            {
                "run_id": "eval-tampered",
                "kind": "evaluation",
                "suite": "smoke",
                "model": "local/qwen-fast",
                "pass_rate": 1.0,
            },
        )
        benchmark = self._run(
            "bench-valid",
            {
                "run_id": "bench-valid",
                "kind": "benchmark",
                "suite": "interactive",
                "model": "local/qwen-fast",
                "success_rate": 1.0,
                "mean_completion_tokens_per_second": 30.0,
                "median_latency_ms": 800.0,
                "p95_latency_ms": 1000.0,
            },
        )
        (evaluation / "summary.json").write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(ModelAcceptanceError, "checksum verification failed"):
            assess_model_candidate(
                self.settings,
                evaluation_run=evaluation,
                benchmark_run=benchmark,
            )


if __name__ == "__main__":
    unittest.main()
