from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from serveshed.cli import main
from tests.helpers import REPOSITORY


class CliTests(unittest.TestCase):
    def test_model_list(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--root", str(REPOSITORY), "model", "list"])
        self.assertEqual(0, code)
        self.assertIn("local/qwen-quality", output.getvalue())

    def test_eval_dry_run_requires_no_environment(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--root", str(REPOSITORY), "eval", "smoke", "--dry-run"])
        self.assertEqual(0, code)
        self.assertIn("Cases: 3", output.getvalue())

    def test_model_recommend_uses_target_vram(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(
                [
                    "--root",
                    str(REPOSITORY),
                    "model",
                    "recommend",
                    "--vram-gib",
                    "16",
                    "--workload",
                    "agents",
                ]
            )
        self.assertEqual(0, code)
        self.assertIn("local/qwen-fast", output.getvalue())

    def test_benchmark_plan_requires_no_environment(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(
                [
                    "--root",
                    str(REPOSITORY),
                    "benchmark",
                    "plan",
                    "interactive",
                    "--repetitions",
                    "2",
                ]
            )
        self.assertEqual(0, code)
        self.assertIn("Network requests", output.getvalue())

    def test_static_config_validation(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--root", str(REPOSITORY), "config", "validate"])
        self.assertEqual(0, code)
        self.assertIn("required-files", output.getvalue())


if __name__ == "__main__":
    unittest.main()
