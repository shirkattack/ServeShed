from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from serveshed.artifacts import write_checksums
from serveshed.runs import discover_runs, render_markdown_table, verify_run


class RunTests(unittest.TestCase):
    def test_discover_filter_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            evaluation = base / "2026-01-01" / "eval-one"
            evaluation.mkdir(parents=True)
            (evaluation / "summary.json").write_text(
                json.dumps(
                    {
                        "run_id": "eval-one",
                        "kind": "evaluation",
                        "suite": "smoke",
                        "model": "local/qwen-fast",
                        "pass_rate": 1.0,
                        "median_latency_ms": 100.0,
                    }
                ),
                encoding="utf-8",
            )
            write_checksums(evaluation)

            benchmark = base / "benchmarks" / "2026-01-01" / "bench-one"
            benchmark.mkdir(parents=True)
            (benchmark / "summary.json").write_text(
                json.dumps(
                    {
                        "run_id": "bench-one",
                        "kind": "benchmark",
                        "suite": "interactive",
                        "model": "local/qwen-fast",
                        "success_rate": 1.0,
                        "median_latency_ms": 80.0,
                    }
                ),
                encoding="utf-8",
            )
            write_checksums(benchmark)

            all_runs = discover_runs(base)
            self.assertEqual(2, len(all_runs))
            eval_runs = discover_runs(base, kind="evaluation")
            self.assertEqual(1, len(eval_runs))
            self.assertEqual("eval-one", eval_runs[0].run_id)
            self.assertTrue(all(item["ok"] for item in verify_run(evaluation)))
            self.assertIn("local/qwen-fast", render_markdown_table(all_runs))

    def test_discover_ignores_summaries_embedded_in_acceptance_sources(self) -> None:
        # An acceptance bundle embeds checksummed copies of its source eval/
        # benchmark summaries under sources/*/summary.json (see docs/evals.md's
        # bundle layout). Those must not be double-counted as standalone runs.
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            evaluation = base / "evaluations" / "2026-01-01" / "eval-one"
            evaluation.mkdir(parents=True)
            evaluation_summary = {
                "run_id": "eval-one",
                "kind": "evaluation",
                "suite": "smoke",
                "model": "local/qwen-fast",
                "pass_rate": 1.0,
                "median_latency_ms": 100.0,
            }
            (evaluation / "summary.json").write_text(
                json.dumps(evaluation_summary), encoding="utf-8"
            )

            benchmark = base / "benchmarks" / "2026-01-01" / "bench-one"
            benchmark.mkdir(parents=True)
            benchmark_summary = {
                "run_id": "bench-one",
                "kind": "benchmark",
                "suite": "interactive",
                "model": "local/qwen-fast",
                "success_rate": 1.0,
                "median_latency_ms": 80.0,
            }
            (benchmark / "summary.json").write_text(json.dumps(benchmark_summary), encoding="utf-8")

            acceptance = base / "acceptance" / "2026-01-01" / "local-qwen-fast-one"
            (acceptance / "sources" / "evaluation").mkdir(parents=True)
            (acceptance / "sources" / "benchmark").mkdir(parents=True)
            (acceptance / "sources" / "evaluation" / "summary.json").write_text(
                json.dumps(evaluation_summary), encoding="utf-8"
            )
            (acceptance / "sources" / "benchmark" / "summary.json").write_text(
                json.dumps(benchmark_summary), encoding="utf-8"
            )
            (acceptance / "summary.json").write_text(
                json.dumps(
                    {
                        "run_id": "local-qwen-fast-one",
                        "kind": "model-acceptance",
                        "suite": "smoke+interactive",
                        "model": "local/qwen-fast",
                        "accepted": 0.0,
                        "median_latency_ms": 100.0,
                    }
                ),
                encoding="utf-8",
            )

            all_runs = discover_runs(base)
            self.assertEqual(3, len(all_runs), [item.run_id for item in all_runs])
            self.assertEqual(1, len(discover_runs(base, kind="evaluation")))
            self.assertEqual(1, len(discover_runs(base, kind="benchmark")))
            self.assertEqual(1, len(discover_runs(base, kind="model-acceptance")))


if __name__ == "__main__":
    unittest.main()
