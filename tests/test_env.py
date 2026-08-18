from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from serveshed.env import (
    EnvFileError,
    initialize_project,
    parse_env_file,
    placeholder_keys,
)
from tests.helpers import REPOSITORY


class EnvironmentTests(unittest.TestCase):
    def test_init_generates_secrets_and_private_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / ".env.example").write_bytes((REPOSITORY / ".env.example").read_bytes())
            result = initialize_project(root)
            values = parse_env_file(result.env_file)
            self.assertTrue(result.created_env)
            self.assertEqual([], placeholder_keys(values))
            self.assertEqual(0o600, result.env_file.stat().st_mode & 0o777)
            self.assertTrue(result.phoenix_env_file.is_file())
            self.assertEqual(0o600, result.phoenix_env_file.stat().st_mode & 0o777)
            self.assertIn(
                "OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:6006/v1/traces",
                result.phoenix_env_file.read_text(encoding="utf-8"),
            )
            self.assertTrue(values["BIFROST_VK_EVAL"].startswith("sk-bf-"))
            self.assertTrue(Path(values["SERVESHED_DATA_DIR"]).is_dir())

    def test_force_preserves_valid_values_and_fills_only_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / ".env.example").write_bytes((REPOSITORY / ".env.example").read_bytes())
            first = initialize_project(root)
            values = parse_env_file(first.env_file)
            original = values["BIFROST_VK_EVAL"]
            text = first.env_file.read_text(encoding="utf-8").replace(
                f"BIFROST_VK_JUDGE={values['BIFROST_VK_JUDGE']}",
                "BIFROST_VK_JUDGE=sk-bf-CHANGE_ME_JUDGE",
            )
            first.env_file.write_text(text, encoding="utf-8")
            with self.assertRaises(EnvFileError):
                initialize_project(root)
            second = initialize_project(root, force=True)
            updated = parse_env_file(second.env_file)
            self.assertEqual(original, updated["BIFROST_VK_EVAL"])
            self.assertNotIn("CHANGE_ME", updated["BIFROST_VK_JUDGE"])
            self.assertIsNotNone(second.backup_file)


if __name__ == "__main__":
    unittest.main()
