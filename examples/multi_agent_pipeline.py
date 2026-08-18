"""Sequential multi-agent example using one gateway and one loaded model.

This demonstrates separate Bifrost virtual-key identities without pretending that
LiteLLM or Bifrost is the agent orchestrator. It makes three sequential calls and
executes no tools or shell commands.
"""

from __future__ import annotations

import argparse
import secrets
from typing import Any

from serveshed.client import chat_completion
from serveshed.settings import Settings


def text(response: dict[str, Any]) -> str:
    return str(response.get("choices", [{}])[0].get("message", {}).get("content", ""))


def ask(
    settings: Settings,
    *,
    agent: str,
    model: str,
    session_id: str,
    task: str,
) -> str:
    response, _ = chat_completion(
        settings,
        model=model,
        agent=agent,
        messages=[{"role": "user", "content": task}],
        metadata={
            "workload": "multi-agent-example",
            "session-id": session_id,
            "prompt-revision": "pipeline-v1",
        },
        temperature=0,
        max_tokens=512,
    )
    return text(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task")
    parser.add_argument("--model", default="local/qwen-fast")
    args = parser.parse_args()

    settings = Settings.load()
    session_id = f"example-{secrets.token_hex(6)}"
    research = ask(
        settings,
        agent="research",
        model=args.model,
        session_id=session_id,
        task=f"Research the following task locally. State assumptions and evidence needed:\n{args.task}",
    )
    implementation = ask(
        settings,
        agent="coding",
        model=args.model,
        session_id=session_id,
        task=(
            "Create a concrete implementation proposal from the research below. "
            "Do not claim to have changed files.\n\n"
            f"TASK:\n{args.task}\n\nRESEARCH:\n{research}"
        ),
    )
    critique = ask(
        settings,
        agent="judge",
        model=args.model,
        session_id=session_id,
        task=(
            "Critique this proposal for correctness, safety, observability, and testability. "
            "Return the three most important fixes.\n\n"
            f"PROPOSAL:\n{implementation}"
        ),
    )

    print("## Research\n" + research)
    print("\n## Implementation proposal\n" + implementation)
    print("\n## Critique\n" + critique)
    print(f"\nsession_id={session_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
