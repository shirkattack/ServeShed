from __future__ import annotations

import unittest

from serveshed.telemetry import request_headers


class TelemetryTests(unittest.TestCase):
    def test_metadata_uses_canonical_bifrost_headers(self) -> None:
        headers = request_headers(
            {
                "agent-id": "eval",
                "dataset-sha256": "abc123",
                "model_alias": "local/qwen-quality",
            },
            session_id="session-1",
        )
        self.assertEqual("eval", headers["x-bf-eh-agent-id"])
        self.assertEqual("abc123", headers["x-bf-eh-dataset-sha256"])
        self.assertEqual("local/qwen-quality", headers["x-bf-eh-model-alias"])
        self.assertEqual("session-1", headers["x-bf-session-id"])
        self.assertNotIn("x-bf-eh-agent", headers)


if __name__ == "__main__":
    unittest.main()
