from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from serveshed.status import collect_status
from tests.helpers import TemporarySettings


class StatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporarySettings()
        self.settings = self.temporary.settings

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @patch("serveshed.status.inspect_nas")
    @patch("serveshed.status.hardware_snapshot")
    @patch("serveshed.status.collect_service_health")
    @patch("serveshed.status.ComposeManager")
    @patch("serveshed.status.command_exists", return_value=True)
    def test_status_includes_ollama_processor_split(
        self,
        _command_exists: Mock,
        compose_manager: Mock,
        collect_health: Mock,
        hardware: Mock,
        inspect_nas: Mock,
    ) -> None:
        process = Mock()
        process.as_dict.return_value = {
            "name": "qwen3.5:9b",
            "model_id": "abc123",
            "size": "7.4 GB",
            "processor": "48%/52% CPU/GPU",
            "until": "4 minutes from now",
        }
        manager = compose_manager.return_value
        manager.status.return_value = [{"Service": "ollama", "State": "running"}]
        manager.ollama_processes.return_value = (process,)
        collect_health.return_value = ()
        hardware.return_value = {"nvidia_smi": "RTX 5070 Ti, 16303, 4096"}
        nas = Mock()
        nas.as_dict.return_value = {
            "path": "/mnt/synology-ai",
            "reason": "not mounted",
        }
        inspect_nas.return_value = nas

        payload = collect_status(self.settings)

        self.assertEqual("48%/52% CPU/GPU", payload["ollama_processes"][0]["processor"])
        self.assertEqual("ollama", payload["services"][0]["Service"])
        self.assertIsNone(payload["compose_error"])


if __name__ == "__main__":
    unittest.main()
