from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RunResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def display(self) -> str:
        return shlex.join(self.command)


class CommandError(RuntimeError):
    def __init__(self, result: RunResult) -> None:
        self.result = result
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        super().__init__(f"Command failed ({result.returncode}): {result.display}\n{detail}")


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _timeout_stream(stream: str | bytes | None) -> str:
    # subprocess.TimeoutExpired carries bytes even when the run requested text mode.
    if isinstance(stream, bytes):
        return stream.decode("utf-8", errors="replace")
    return stream or ""


class Runner:
    def __init__(self, *, dry_run: bool = False, verbose: bool = False) -> None:
        self.dry_run = dry_run
        self.verbose = verbose

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = False,
        capture: bool = True,
        input_text: str | None = None,
        timeout: float | None = None,
    ) -> RunResult:
        args = tuple(str(value) for value in command)
        if self.verbose or self.dry_run:
            print(f"$ {shlex.join(args)}")
        if self.dry_run:
            return RunResult(args, 0, "", "", dry_run=True)
        try:
            completed = subprocess.run(
                args,
                cwd=cwd,
                env=dict(os.environ if env is None else env),
                check=False,
                text=True,
                capture_output=capture,
                input=input_text,
                timeout=timeout,
            )
            result = RunResult(
                args,
                completed.returncode,
                completed.stdout or "",
                completed.stderr or "",
            )
        except FileNotFoundError:
            result = RunResult(args, 127, "", f"Executable not found: {args[0]}")
        except subprocess.TimeoutExpired as exc:
            result = RunResult(
                args,
                124,
                _timeout_stream(exc.stdout) or "",
                _timeout_stream(exc.stderr) or "Command timed out",
            )
        if check and not result.ok:
            raise CommandError(result)
        return result
