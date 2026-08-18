from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from serveshed.benchmarks import compare_benchmarks, plan_benchmark, run_benchmark
from tests.helpers import TemporarySettings


class BenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporarySettings()
        self.settings = self.temp.settings

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_plan_is_offline_and_counts_requests(self) -> None:
        plan = plan_benchmark(
            self.settings,
            "interactive",
            repetitions=3,
            warmup=1,
        )
        self.assertEqual(3, plan["case_count"])
        self.assertEqual(12, plan["network_requests"])

    def test_run_writes_metrics_and_excludes_warmup(self) -> None:
        response = {
            "choices": [
                {"finish_reason": "stop", "message": {"role": "assistant", "content": "READY"}}
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        with patch("serveshed.benchmarks.chat_completion", return_value=(response, 100.0)):
            run_dir = run_benchmark(
                self.settings,
                "interactive",
                model="local/qwen-fast",
                repetitions=2,
                warmup=1,
                limit=1,
            )
        summary = json.loads((run_dir / "summary.json").read_text())
        self.assertEqual(2, summary["recorded_samples"])
        self.assertEqual(1, summary["warmup_samples"])
        self.assertEqual(10, summary["completion_tokens"])
        self.assertAlmostEqual(50.0, summary["mean_completion_tokens_per_second"])
        self.assertTrue((run_dir / "checksums.sha256").is_file())
        self.assertEqual("benchmarks", run_dir.parents[1].name)
        input_rows = (run_dir / "input-dataset.jsonl").read_text().splitlines()
        self.assertEqual(1, len(input_rows))
        manifest = json.loads((run_dir / "manifest.json").read_text())
        self.assertEqual(["short-exact"], manifest["selected_case_ids"])
        self.assertNotEqual(
            manifest["source_dataset_sha256"],
            manifest["input_dataset_sha256"],
        )

    def test_compare_orders_success_then_throughput(self) -> None:
        response = {
            "choices": [
                {"finish_reason": "stop", "message": {"role": "assistant", "content": "READY"}}
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }
        with patch("serveshed.benchmarks.chat_completion", return_value=(response, 200.0)):
            slower = run_benchmark(
                self.settings,
                "interactive",
                model="local/qwen-fast",
                repetitions=1,
                warmup=0,
                limit=1,
            )
        with patch("serveshed.benchmarks.chat_completion", return_value=(response, 100.0)):
            faster = run_benchmark(
                self.settings,
                "interactive",
                model="local/qwen-quality",
                repetitions=1,
                warmup=0,
                limit=1,
            )
        comparison = compare_benchmarks([slower, faster])
        self.assertEqual("local/qwen-quality", comparison["runs"][0]["model"])


if __name__ == "__main__":
    unittest.main()
