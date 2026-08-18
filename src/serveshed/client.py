from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from serveshed.settings import Settings
from serveshed.telemetry import request_headers


class GatewayError(RuntimeError):
    """Raised when Bifrost returns an invalid or unsuccessful response."""


@dataclass(frozen=True, slots=True)
class ChatResult:
    content: str
    message: dict[str, Any]
    response: dict[str, Any]
    latency_ms: float


class BifrostClient:
    def __init__(self, *, base_url: str, api_key: str, timeout: float = 900.0) -> None:
        if not api_key:
            raise GatewayError("A Bifrost virtual key is required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def chat(
        self,
        *,
        model: str,
        messages: Sequence[Mapping[str, Any]],
        metadata: Mapping[str, object],
        session_id: str,
        max_tokens: int = 256,
        temperature: float = 0.0,
        tools: Sequence[Mapping[str, Any]] | None = None,
        response_format: Mapping[str, Any] | None = None,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "stream": False,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = list(tools)
            payload["tool_choice"] = "auto"
        if response_format:
            payload["response_format"] = dict(response_format)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "serveshed-eval/0.2",
            **request_headers(metadata, session_id=session_id),
        }
        request = Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GatewayError(f"Bifrost HTTP {exc.code}: {detail[:1000]}") from exc
        except (OSError, URLError) as exc:
            raise GatewayError(f"Cannot reach Bifrost at {self.base_url}: {exc}") from exc
        latency_ms = (time.perf_counter() - started) * 1000
        try:
            decoded = json.loads(raw)
            message = decoded["choices"][0]["message"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise GatewayError(f"Unexpected Bifrost response: {raw[:1000]}") from exc
        content = message.get("content") or ""
        return ChatResult(str(content), dict(message), decoded, latency_ms)


def chat_completion(
    settings: Settings,
    *,
    model: str,
    messages: list[dict[str, Any]],
    agent: str = "research",
    metadata: Mapping[str, object] | None = None,
    timeout: float = 900.0,
    **parameters: Any,
) -> tuple[dict[str, Any], float]:
    """Dependency-free OpenAI-compatible request through Bifrost."""

    from serveshed.models import resolve_gateway_model

    if not isinstance(settings, Settings):
        raise TypeError("settings must be a Settings instance")
    settings.require_initialized()
    key_names = {
        "hermes": "BIFROST_VK_HERMES",
        "research": "BIFROST_VK_RESEARCH",
        "coding": "BIFROST_VK_CODING",
        "eval": "BIFROST_VK_EVAL",
        "judge": "BIFROST_VK_JUDGE",
    }
    try:
        key_name = key_names[agent]
    except KeyError as exc:
        raise GatewayError(f"Unknown agent identity {agent!r}") from exc
    api_key = settings.get(key_name)
    if not api_key:
        raise GatewayError(f"{key_name} is not configured")

    payload: dict[str, Any] = {
        "model": resolve_gateway_model(settings, model),
        "messages": messages,
        "stream": False,
    }
    payload.update({key: value for key, value in parameters.items() if value is not None})
    session = None
    if metadata:
        session_value = metadata.get("session-id") or metadata.get("session_id")
        session = str(session_value) if session_value else None
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "serveshed-control/0.2",
        "x-bf-eh-agent-id": agent,
        "x-bf-eh-model-alias": model,
        **request_headers(metadata, session_id=session),
    }
    request = Request(
        f"{settings.bifrost_base_url}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GatewayError(f"Bifrost HTTP {exc.code}: {detail[:1000]}") from exc
    except (OSError, URLError) as exc:
        raise GatewayError(f"Cannot reach Bifrost at {settings.bifrost_base_url}: {exc}") from exc
    latency_ms = (time.perf_counter() - started) * 1000
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GatewayError(f"Unexpected Bifrost response: {raw[:1000]}") from exc
    if not isinstance(decoded, dict):
        raise GatewayError("Bifrost response was not a JSON object")
    return decoded, latency_ms
