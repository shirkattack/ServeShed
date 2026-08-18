from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from serveshed.client import BifrostClient, chat_completion
from tests.helpers import TemporarySettings


class FakeResponse:
    status = 200

    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class ClientTests(unittest.TestCase):
    def test_bifrost_client_builds_openai_request_and_trace_headers(self) -> None:
        payload = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
        with patch("serveshed.client.urlopen", return_value=FakeResponse(payload)) as mocked:
            result = BifrostClient(
                base_url="http://127.0.0.1:8080",
                api_key="sk-bf-test",
            ).chat(
                model="ollama/local/qwen-quality",
                messages=[{"role": "user", "content": "test"}],
                metadata={"agent": "research", "workload": "unit-test"},
                session_id="session-1",
            )
        request = mocked.call_args.args[0]
        headers = {key.lower(): value for key, value in request.header_items()}
        sent = json.loads(request.data.decode("utf-8"))
        self.assertEqual("http://127.0.0.1:8080/v1/chat/completions", request.full_url)
        self.assertEqual("Bearer sk-bf-test", headers["authorization"])
        self.assertEqual("research", headers["x-bf-eh-agent-id"])
        self.assertEqual("session-1", headers["x-bf-session-id"])
        self.assertEqual("ollama/local/qwen-quality", sent["model"])
        self.assertEqual("ok", result.content)

    def test_project_client_resolves_alias_and_agent_key(self) -> None:
        temporary = TemporarySettings()
        payload = {"choices": [{"message": {"role": "assistant", "content": "42"}}]}
        try:
            with patch("serveshed.client.urlopen", return_value=FakeResponse(payload)) as mocked:
                response, _ = chat_completion(
                    temporary.settings,
                    model="local/qwen-quality",
                    messages=[{"role": "user", "content": "6*7"}],
                    agent="eval",
                    metadata={"eval-suite": "smoke"},
                    temperature=0,
                    max_tokens=16,
                )
            request = mocked.call_args.args[0]
            headers = {key.lower(): value for key, value in request.header_items()}
            sent = json.loads(request.data.decode("utf-8"))
            self.assertEqual("ollama/local/qwen-quality", sent["model"])
            self.assertEqual("eval", headers["x-bf-eh-agent-id"])
            self.assertEqual("smoke", headers["x-bf-eh-eval-suite"])
            self.assertEqual("42", response["choices"][0]["message"]["content"])
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
