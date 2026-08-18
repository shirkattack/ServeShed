from __future__ import annotations

import unittest
from unittest.mock import patch

from serveshed.compose import ComposeManager
from serveshed.shell import RunResult
from tests.helpers import RecordingRunner, TemporarySettings


class ComposeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporarySettings()
        self.settings = self.temp.settings

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_chat_stops_vllm_and_starts_explicit_services(self) -> None:
        runner = RecordingRunner(dry_run=True)
        ComposeManager(self.settings, runner=runner).up("chat")
        commands = [" ".join(command) for command in runner.commands]
        self.assertTrue(any("stop vllm" in command for command in commands))
        start = commands[-1]
        self.assertIn("up --detach --remove-orphans", start)
        self.assertIn("postgres phoenix otel-collector bifrost ollama open-webui", start)

    def test_eval_dry_run_stops_ollama(self) -> None:
        runner = RecordingRunner(dry_run=True)
        ComposeManager(self.settings, runner=runner).up("eval")
        commands = [" ".join(command) for command in runner.commands]
        self.assertTrue(any("stop ollama" in command for command in commands))
        self.assertIn("vllm", commands[-1])

    def test_real_eval_is_blocked_before_compose_start(self) -> None:
        runner = RecordingRunner(dry_run=False)
        with (
            patch("serveshed.compose.command_exists", return_value=True),
            self.assertRaisesRegex(RuntimeError, "vLLM is disabled"),
        ):
            ComposeManager(self.settings, runner=runner).up("eval")
        self.assertFalse(any(" up " in f" {' '.join(command)} " for command in runner.commands[1:]))

    def test_bifrost_override_renders_config_only_when_not_dry_run(self) -> None:
        live = ComposeManager(self.settings, runner=RecordingRunner(dry_run=False))
        rendered = live._bifrost_override(eval_logging=False)["BIFROST_CONFIG_FILE"]
        self.assertTrue(rendered.startswith(str(self.settings.cache_dir)))

        dry = ComposeManager(self.settings, runner=RecordingRunner(dry_run=True))
        template = dry._bifrost_override(eval_logging=False)["BIFROST_CONFIG_FILE"]
        self.assertEqual(template, str(self.settings.bifrost_config_file()))

    def test_dry_run_without_env_uses_example_environment(self) -> None:
        self.settings.env_file.unlink(missing_ok=True)
        runner = RecordingRunner(dry_run=True)
        ComposeManager(self.settings, runner=runner).up("core")
        command = " ".join(runner.commands[-1])
        self.assertIn(str(self.settings.root / ".env.example"), command)

    def test_promptfoo_eval_uses_batch_configuration(self) -> None:
        runner = RecordingRunner(dry_run=True)
        result, _ = ComposeManager(self.settings, runner=runner).run_promptfoo(
            runtime="eval",
            output_name="result.json",
        )
        self.assertIn("/workspace/promptfooconfig.batch.yaml", result.command)

    def test_down_never_deletes_volumes(self) -> None:
        runner = RecordingRunner(dry_run=True)
        ComposeManager(self.settings, runner=runner).down()
        command = " ".join(runner.commands[-1])
        self.assertIn("down --remove-orphans", command)
        self.assertNotIn("--volumes", command)
        self.assertNotIn(" -v", command)

    def test_ollama_processes_parse_processor_split(self) -> None:
        # Real captured output from the pinned ollama/ollama:0.32.9 image —
        # NAME ID SIZE PROCESSOR CONTEXT UNTIL. An older fixture here had no
        # CONTEXT column and never caught that column running into UNTIL.
        output = (
            "NAME                 ID              SIZE      PROCESSOR          CONTEXT    UNTIL\n"
            "qwen3.5:9b           6488c96fa5fa    7.4 GB    100% GPU           8192       4 minutes from now\n"
            "qwen3.8:27b          22130167c4c2    20 GB     48%/52% CPU/GPU    4096       30 seconds from now\n"
        )
        runner = RecordingRunner(
            dry_run=False,
            results=[RunResult(("docker",), 0, output, "", dry_run=False)],
        )
        with patch("serveshed.compose.command_exists", return_value=True):
            processes = ComposeManager(self.settings, runner=runner).ollama_processes()
        self.assertEqual(2, len(processes))
        self.assertEqual("100% GPU", processes[0].processor)
        self.assertEqual("8192", processes[0].context)
        self.assertEqual("4 minutes from now", processes[0].until)
        self.assertEqual("48%/52% CPU/GPU", processes[1].processor)
        self.assertEqual("4096", processes[1].context)
        self.assertEqual("30 seconds from now", processes[1].until)

    def test_ollama_inventory_parses_cli_table(self) -> None:
        output = (
            "NAME                 ID              SIZE      MODIFIED\n"
            "qwen3.5:9b           6488c96fa5fa    6.6 GB    2 hours ago\n"
            "gemma4:12b           112233aabbcc    7.4 GB    3 days ago\n"
        )
        runner = RecordingRunner(
            dry_run=True,
            results=[RunResult(("docker",), 0, output, "", dry_run=True)],
        )
        models = ComposeManager(self.settings, runner=runner).ollama_inventory()
        self.assertEqual(2, len(models))
        self.assertEqual("qwen3.5:9b", models[0].name)
        self.assertEqual("6488c96fa5fa", models[0].model_id)
        self.assertEqual("6.6 GB", models[0].size)
        self.assertEqual("2 hours ago", models[0].modified)


if __name__ == "__main__":
    unittest.main()
