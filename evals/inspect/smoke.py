"""Inspect AI smoke task for the serveshed gateway.

Install Inspect through a reviewed uv dependency group before running this file.
The CLI model should use the OpenAI-compatible adapter pointed at Bifrost.
"""

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import exact
from inspect_ai.solver import generate


@task
def serveshed_smoke() -> Task:
    return Task(
        dataset=MemoryDataset(
            samples=[
                Sample(
                    input="Compute 6 multiplied by 7. Respond with only the integer.",
                    target="42",
                ),
                Sample(
                    input=(
                        "Name the Linux distribution targeted by this project. "
                        "Respond with exactly two words."
                    ),
                    target="Ubuntu Desktop",
                ),
            ]
        ),
        solver=[generate()],
        scorer=exact(),
    )
