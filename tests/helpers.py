from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from serveshed.env import initialize_project, parse_env_file
from serveshed.settings import Settings
from serveshed.shell import Runner, RunResult

REPOSITORY = Path(__file__).resolve().parents[1]


class TemporarySettings:
    def __init__(self, *, root: Path = REPOSITORY) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.base = Path(self._temporary.name)
        self.env_file = self.base / ".env"
        template = (root / ".env.example").read_text(encoding="utf-8")
        temporary_template_root = self.base / "template"
        temporary_template_root.mkdir()
        (temporary_template_root / ".env.example").write_text(template, encoding="utf-8")
        initialize_project(temporary_template_root, env_file=self.env_file)
        values = parse_env_file(self.env_file)
        values["SERVESHED_DATA_DIR"] = str(self.base / "data")
        values["SERVESHED_CACHE_DIR"] = str(self.base / "cache")
        values["SERVESHED_NAS_DIR"] = str(self.base / "nas")
        self.settings = Settings(root=root, env_file=self.env_file, values=values)
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings.cache_dir.mkdir(parents=True, exist_ok=True)

    def cleanup(self) -> None:
        self._temporary.cleanup()


class RecordingRunner(Runner):
    def __init__(self, *, dry_run: bool = True, results: list[RunResult] | None = None) -> None:
        super().__init__(dry_run=dry_run, verbose=False)
        self.commands: list[tuple[str, ...]] = []
        self._results = list(results or [])

    def run(self, command: Any, **kwargs: Any) -> RunResult:
        args = tuple(str(value) for value in command)
        self.commands.append(args)
        if self._results:
            return self._results.pop(0)
        return RunResult(args, 0, "", "", dry_run=self.dry_run)
