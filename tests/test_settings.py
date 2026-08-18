from __future__ import annotations

import json
import unittest

from serveshed.settings import Settings
from tests.helpers import TemporarySettings


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporarySettings()
        self.settings = self.temp.settings

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_initialized_and_paths(self) -> None:
        self.assertTrue(self.settings.initialized)
        self.assertTrue(self.settings.data_dir.is_absolute())
        self.settings.require_initialized()

    def test_vllm_is_gated_by_default(self) -> None:
        self.assertFalse(self.settings.vllm_enabled)
        with self.assertRaisesRegex(RuntimeError, "vLLM is disabled"):
            self.settings.require_vllm_ready()

    def test_vllm_requires_reviewed_model(self) -> None:
        values = dict(self.settings.values)
        values["SERVESHED_ENABLE_VLLM"] = "true"
        gated = Settings(self.settings.root, self.settings.env_file, values)
        with self.assertRaisesRegex(RuntimeError, "VLLM_MODEL_ID"):
            gated.require_vllm_ready()

    def test_render_bifrost_config_drops_unset_tailscale_origin(self) -> None:
        template = json.loads(self.settings.bifrost_config_file().read_text())
        self.assertIn("env.BIFROST_TAILSCALE_ORIGIN", template["client"]["allowed_origins"])

        rendered_path = self.settings.render_bifrost_config()
        self.assertTrue(rendered_path.is_relative_to(self.settings.cache_dir))
        rendered = json.loads(rendered_path.read_text())
        self.assertNotIn("env.BIFROST_TAILSCALE_ORIGIN", rendered["client"]["allowed_origins"])
        self.assertIn("http://127.0.0.1:3000", rendered["client"]["allowed_origins"])

        # The tracked template itself must never be edited.
        self.assertEqual(template, json.loads(self.settings.bifrost_config_file().read_text()))

    def test_render_bifrost_config_resolves_set_tailscale_origin(self) -> None:
        values = dict(self.settings.values)
        values["BIFROST_TAILSCALE_ORIGIN"] = "https://example-machine.example-tailnet.ts.net"
        settings = Settings(self.settings.root, self.settings.env_file, values)

        rendered = json.loads(settings.render_bifrost_config().read_text())
        origins = rendered["client"]["allowed_origins"]
        self.assertIn("https://example-machine.example-tailnet.ts.net", origins)
        self.assertNotIn("env.BIFROST_TAILSCALE_ORIGIN", origins)

    def test_render_bifrost_config_eval_variant_uses_eval_template(self) -> None:
        normal = self.settings.render_bifrost_config(eval_logging=False)
        evaluation = self.settings.render_bifrost_config(eval_logging=True)
        self.assertNotEqual(normal, evaluation)
        self.assertEqual(normal.name, "config.json")
        self.assertEqual(evaluation.name, "config.eval.json")


if __name__ == "__main__":
    unittest.main()
