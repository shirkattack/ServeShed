"""Minimal dependency-free request through Bifrost.

Run after `uv run serveshed up chat` and after the selected model is available:
    uv run python examples/simple_client.py "Explain local-first in one sentence."
"""

from __future__ import annotations

import argparse
from typing import Any

from serveshed.client import chat_completion
from serveshed.settings import Settings


def assistant_text(response: dict[str, Any]) -> str:
    return str(response.get("choices", [{}])[0].get("message", {}).get("content", ""))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt")
    parser.add_argument("--model", default="local/qwen-fast")
    parser.add_argument(
        "--agent",
        choices=("hermes", "research", "coding", "eval", "judge"),
        default="research",
    )
    args = parser.parse_args()

    settings = Settings.load()
    response, latency_ms = chat_completion(
        settings,
        model=args.model,
        agent=args.agent,
        messages=[{"role": "user", "content": args.prompt}],
        metadata={"workload": "example", "prompt-revision": "simple-client-v1"},
        temperature=0,
        max_tokens=256,
    )
    print(assistant_text(response))
    print(f"\nlatency_ms={latency_ms:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
