from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Any


def print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def print_table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
    rendered = [[str(value) for value in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in rendered:
        if len(row) != len(headers):
            raise ValueError("Every table row must have the same number of columns as the headers")
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    def line(values: Sequence[str]) -> str:
        return "  ".join(value.ljust(widths[index]) for index, value in enumerate(values))

    print(line(headers))
    print(line(tuple("-" * width for width in widths)))
    for row in rendered:
        print(line(row))
