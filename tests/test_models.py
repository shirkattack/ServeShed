from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from serveshed.env import parse_env_file
from serveshed.models import (
    ModelRegistryError,
    load_registry,
    recommend_models,
    resolve_gateway_model,
    select_default_model,
)
from tests.helpers import REPOSITORY, TemporarySettings


class ModelRegistryTests(unittest.TestCase):
    def test_registry_loads_hardware_aware_candidates(self) -> None:
        registry = load_registry(REPOSITORY / "config/models/registry.yaml")
        self.assertEqual(2, registry.schema_version)

        fast = registry["local/qwen-fast"]
        self.assertEqual("qwen3.5:9b", fast.artifact)
        self.assertEqual("ollama/local/qwen-fast", fast.gateway_model)
        self.assertTrue(fast.pullable)
        self.assertEqual("comfortable", fast.fit_for_vram(16.0))

        quality = registry["local/qwen-quality"]
        self.assertEqual("qwen3.5:9b-q8_0", quality.artifact)
        self.assertEqual("tight", quality.fit_for_vram(16.0))

        offload = registry["experimental/qwen38-offload"]
        self.assertEqual("qwen3.8:27b", offload.artifact)
        self.assertTrue(offload.experimental)
        self.assertEqual("required", offload.cpu_offload)

    def test_recommendation_prefers_daily_qwen_for_agents(self) -> None:
        registry = load_registry(REPOSITORY / "config/models/registry.yaml")
        recommendations = recommend_models(
            registry,
            vram_gib=16.0,
            workload="agents",
            tools=True,
        )
        self.assertTrue(recommendations)
        self.assertEqual("local/qwen-fast", recommendations[0].alias)
        self.assertNotIn(
            "experimental/qwen38-offload",
            {item.alias for item in recommendations},
        )

    def test_alias_resolves_for_gateway(self) -> None:
        temp = TemporarySettings()
        try:
            self.assertEqual(
                "ollama/local/qwen-fast",
                resolve_gateway_model(temp.settings, "local/qwen-fast"),
            )
            self.assertEqual("ollama/custom", resolve_gateway_model(temp.settings, "ollama/custom"))
        finally:
            temp.cleanup()

    def test_select_default_model_plans_and_updates_env(self) -> None:
        temp = TemporarySettings()
        try:
            planned = select_default_model(
                temp.settings,
                "local/qwen-quality",
                execute=False,
            )
            self.assertFalse(planned.executed)
            self.assertEqual("local/qwen-fast", planned.previous_alias)
            self.assertEqual(
                "local/qwen-fast",
                parse_env_file(temp.env_file)["SERVESHED_DEFAULT_MODEL_ALIAS"],
            )

            selected = select_default_model(
                temp.settings,
                "local/qwen-quality",
                execute=True,
            )
            self.assertTrue(selected.executed)
            self.assertTrue(selected.changed)
            self.assertIsNotNone(selected.backup_file)
            self.assertEqual(
                "local/qwen-quality",
                parse_env_file(temp.env_file)["SERVESHED_DEFAULT_MODEL_ALIAS"],
            )
        finally:
            temp.cleanup()

    def test_experimental_selection_requires_override(self) -> None:
        temp = TemporarySettings()
        try:
            with self.assertRaisesRegex(ModelRegistryError, "experimental"):
                select_default_model(
                    temp.settings,
                    "experimental/qwen-nvfp4",
                    execute=False,
                )
        finally:
            temp.cleanup()

    def test_duplicate_alias_is_rejected(self) -> None:
        payload = json.loads((REPOSITORY / "config/models/registry.yaml").read_text())
        payload["models"].append(dict(payload["models"][0]))
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "registry.yaml"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ModelRegistryError, "Duplicate model alias"):
                load_registry(path)


if __name__ == "__main__":
    unittest.main()
