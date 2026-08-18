from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from serveshed.evaluations import (
    grade_assertions,
    materialize_messages,
    plan_suite,
    run_suite,
)
from tests.helpers import TemporarySettings


class EvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporarySettings()
        self.settings = self.temp.settings

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_graders_cover_json_and_tool_calls(self) -> None:
        response = {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": '{"ready": true}',
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "get_gpu_status",
                                    "arguments": "{}",
                                }
                            }
                        ],
                    },
                }
            ]
        }
        results = grade_assertions(
            [
                {"type": "json_valid"},
                {
                    "type": "json_schema",
                    "schema": {
                        "type": "object",
                        "required": ["ready"],
                        "properties": {"ready": {"type": "boolean"}},
                    },
                },
                {"type": "tool_name", "value": "get_gpu_status"},
                {"type": "tool_arguments_json", "name": "get_gpu_status"},
                {"type": "finish_reason", "value": "tool_calls"},
            ],
            response=response,
            latency_ms=10,
        )
        self.assertTrue(all(result.passed for result in results))

    def test_qwen_plan_and_vision_materialization(self) -> None:
        plan = plan_suite(self.settings, "qwen")
        self.assertGreaterEqual(plan["case_count"], 5)
        vision = next(
            case
            for case in json.loads(
                "["
                + ",".join(
                    (self.settings.root / "evals/datasets/qwen.jsonl").read_text().splitlines()
                )
                + "]"
            )
            if case["id"] == "qwen-vision-red-square"
        )
        messages = materialize_messages(self.settings, vision)
        url = messages[0]["content"][0]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/png;base64,"))

    def test_run_writes_immutable_bundle(self) -> None:
        response = {
            "choices": [
                {"finish_reason": "stop", "message": {"role": "assistant", "content": "42"}}
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 1},
        }
        with patch("serveshed.evaluations.chat_completion", return_value=(response, 12.5)) as call:
            run_dir = run_suite(
                self.settings,
                "smoke",
                model="local/qwen-quality",
                limit=1,
            )
        summary = json.loads((run_dir / "summary.json").read_text())
        self.assertEqual(1, summary["passed"])
        self.assertEqual("evaluation", summary["kind"])
        self.assertEqual(1, summary["completion_tokens"])
        self.assertAlmostEqual(80.0, summary["mean_completion_tokens_per_second"])
        self.assertTrue((run_dir / "manifest.json").is_file())
        self.assertTrue((run_dir / "input-dataset.jsonl").is_file())
        self.assertEqual("evaluations", run_dir.parents[1].name)
        self.assertEqual(1, len((run_dir / "input-dataset.jsonl").read_text().splitlines()))
        manifest = json.loads((run_dir / "manifest.json").read_text())
        self.assertEqual(["exact-arithmetic"], manifest["selected_case_ids"])
        self.assertNotEqual(
            manifest["source_dataset_sha256"],
            manifest["input_dataset_sha256"],
        )
        self.assertIn("summary.json", (run_dir / "checksums.sha256").read_text())
        metadata = call.call_args.kwargs["metadata"]
        self.assertIn("dataset-sha256", metadata)
        self.assertNotIn("dataset-revision", metadata)


if __name__ == "__main__":
    unittest.main()
