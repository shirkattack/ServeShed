from __future__ import annotations

from pathlib import Path


class ProjectRootError(RuntimeError):
    """Raised when the serveshed repository root cannot be located."""


def find_project_root(start: Path | str | None = None) -> Path:
    """Find the nearest parent containing the serveshed project markers."""
    candidate = Path(start).expanduser() if start is not None else Path.cwd()
    candidate = candidate.resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for directory in (candidate, *candidate.parents):
        if (directory / "pyproject.toml").is_file() and (directory / "compose.yaml").is_file():
            return directory
    raise ProjectRootError(
        f"Could not find serveshed project root from {candidate}. Pass --root /path/to/serveshed."
    )
