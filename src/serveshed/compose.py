from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from serveshed.env import parse_env_file
from serveshed.settings import Settings
from serveshed.shell import Runner, RunResult, command_exists

ALL_PROFILES = ("core", "chat", "eval", "tools", "experimental")
PROFILE_SERVICES: dict[str, tuple[str, ...]] = {
    "core": ("postgres", "phoenix", "otel-collector", "bifrost"),
    "chat": ("postgres", "phoenix", "otel-collector", "bifrost", "ollama", "open-webui"),
    "eval": ("postgres", "phoenix", "otel-collector", "bifrost", "vllm"),
}
TARGET_PROFILES: dict[str, tuple[str, ...]] = {
    "core": ("core",),
    "chat": ("core", "chat"),
    "eval": ("core", "eval"),
}


@dataclass(frozen=True, slots=True)
class OllamaProcess:
    name: str
    model_id: str
    size: str
    processor: str
    context: str
    until: str

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "model_id": self.model_id,
            "size": self.size,
            "processor": self.processor,
            "context": self.context,
            "until": self.until,
        }


@dataclass(frozen=True, slots=True)
class OllamaModel:
    name: str
    model_id: str
    size: str
    modified: str

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "model_id": self.model_id,
            "size": self.size,
            "modified": self.modified,
        }


@dataclass(frozen=True, slots=True)
class GpuOffReport:
    unloaded_models: tuple[str, ...]
    stopped_services: tuple[str, ...]
    gpu_memory: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "unloaded_models": list(self.unloaded_models),
            "stopped_services": list(self.stopped_services),
            "gpu_memory": self.gpu_memory,
        }


class ComposeManager:
    """Explicit Docker Compose wrapper that never deletes persistent data."""

    def __init__(self, settings: Settings, *, runner: Runner | None = None) -> None:
        self.settings = settings
        self.runner = runner or Runner()

    def _ensure_available(self) -> None:
        if self.runner.dry_run:
            return
        if not command_exists("docker"):
            raise RuntimeError("Docker is unavailable. Run `uv run serveshed doctor`.")
        result = self.runner.run(("docker", "compose", "version"), check=False, timeout=15)
        if not result.ok:
            raise RuntimeError("The Docker Compose plugin is unavailable.")

    def _using_example_env(self) -> bool:
        return self.runner.dry_run and not self.settings.env_file.is_file()

    def _active_env_file(self) -> Path:
        if self._using_example_env():
            return self.settings.root / ".env.example"
        return self.settings.env_file

    def _require_initialized_for_execution(self) -> None:
        if not self.runner.dry_run:
            self.settings.require_initialized()

    def _command(
        self,
        profiles: Sequence[str],
        *arguments: str,
        env_file: Path | None = None,
    ) -> list[str]:
        command = [
            "docker",
            "compose",
            "--project-directory",
            str(self.settings.root),
            "--env-file",
            str(env_file or self._active_env_file()),
            "--file",
            str(self.settings.compose_file),
        ]
        for profile in profiles:
            command.extend(("--profile", profile))
        command.extend(arguments)
        return command

    def _environment(
        self,
        overrides: Mapping[str, str] | None = None,
        *,
        use_example_env: bool = False,
    ) -> dict[str, str]:
        environment = self.settings.compose_env
        if use_example_env or self._using_example_env():
            environment.update(parse_env_file(self.settings.root / ".env.example"))
        if overrides:
            environment.update(overrides)
        return environment

    def _bifrost_override(self, *, eval_logging: bool) -> dict[str, str]:
        # Dry runs never write files; fall back to the tracked template path
        # (Bifrost's client.allowed_origins won't have the Tailscale origin
        # resolved in that case, but nothing actually starts either).
        config_path = (
            self.settings.render_bifrost_config(eval_logging=eval_logging)
            if not self.runner.dry_run
            else self.settings.bifrost_config_file(eval_logging=eval_logging)
        )
        return {"BIFROST_CONFIG_FILE": str(config_path)}

    def validate(self, *, use_example_env: bool = False) -> RunResult:
        if not use_example_env:
            self._require_initialized_for_execution()
        self._ensure_available()
        env_file = (
            self.settings.root / ".env.example" if use_example_env else self.settings.env_file
        )
        return self.runner.run(
            self._command(ALL_PROFILES, "config", "--quiet", env_file=env_file),
            cwd=self.settings.root,
            env=self._environment(use_example_env=use_example_env),
            check=True,
        )

    def stop_service(self, service: str, *, profile: str) -> RunResult:
        self._ensure_available()
        return self.runner.run(
            self._command((profile,), "stop", service),
            cwd=self.settings.root,
            env=self._environment(),
            check=False,
        )

    def ollama_processes(self) -> tuple[OllamaProcess, ...]:
        if self.runner.dry_run:
            return ()
        result = self.runner.run(
            self._command(("chat",), "exec", "-T", "ollama", "ollama", "ps"),
            cwd=self.settings.root,
            env=self._environment(),
            check=False,
        )
        if not result.ok:
            return ()
        processes: list[OllamaProcess] = []
        # `ollama ps` (pinned 0.32.9) prints NAME ID SIZE PROCESSOR CONTEXT
        # UNTIL. An earlier version of this regex had no CONTEXT group, so
        # that column silently ran into UNTIL (e.g. until == "8192   About a
        # minute from now") -- caught by rendering it directly rather than
        # by the mocked test, whose fixture predated CONTEXT and never
        # exercised a real captured line. Re-verify this shape if the
        # pinned Ollama image bumps.
        pattern = re.compile(
            r"^(?P<name>\S+)\s+(?P<id>[0-9a-fA-F]+)\s+"
            r"(?P<size>[0-9.]+\s+\S+)\s+"
            r"(?P<processor>(?:[0-9]+%/[0-9]+%|[0-9]+%)\s+\S+(?:/\S+)?)\s+"
            r"(?P<context>[0-9]+)\s+"
            r"(?P<until>.+)$"
        )
        for raw in result.stdout.splitlines():
            line = raw.strip()
            if not line or line.upper().startswith("NAME"):
                continue
            match = pattern.match(line)
            if match:
                processes.append(
                    OllamaProcess(
                        name=match.group("name"),
                        model_id=match.group("id"),
                        size=match.group("size"),
                        processor=match.group("processor"),
                        context=match.group("context"),
                        until=match.group("until"),
                    )
                )
        return tuple(processes)

    def _running_ollama_models(self) -> list[str]:
        return [process.name for process in self.ollama_processes()]

    def unload_ollama_models(self) -> list[str]:
        unloaded: list[str] = []
        for model in self._running_ollama_models():
            result = self.runner.run(
                self._command(("chat",), "exec", "-T", "ollama", "ollama", "stop", model),
                cwd=self.settings.root,
                env=self._environment(),
                check=False,
            )
            if result.ok or self.runner.dry_run:
                unloaded.append(model)
        return unloaded

    def up(self, target: str, *, eval_logging: bool = False) -> RunResult:
        self._require_initialized_for_execution()
        self._ensure_available()
        if target not in PROFILE_SERVICES:
            raise RuntimeError(f"Unknown service target {target!r}")

        if target == "chat":
            self.stop_service("vllm", profile="eval")
        elif target == "eval":
            if not self.runner.dry_run:
                self.settings.require_vllm_enabled()
            self.unload_ollama_models()
            self.stop_service("ollama", profile="chat")
            eval_logging = True

        return self.runner.run(
            self._command(
                TARGET_PROFILES[target],
                "up",
                "--detach",
                "--remove-orphans",
                *PROFILE_SERVICES[target],
            ),
            cwd=self.settings.root,
            env=self._environment(self._bifrost_override(eval_logging=eval_logging)),
            check=True,
            capture=False,
        )

    def down(self) -> RunResult:
        self._require_initialized_for_execution()
        self._ensure_available()
        return self.runner.run(
            self._command(ALL_PROFILES, "down", "--remove-orphans"),
            cwd=self.settings.root,
            env=self._environment(),
            check=True,
            capture=False,
        )

    def gpu_off(self) -> GpuOffReport:
        self._require_initialized_for_execution()
        self._ensure_available()
        unloaded = self.unload_ollama_models()
        stopped: list[str] = []
        for service, profile in (("ollama", "chat"), ("vllm", "eval")):
            result = self.stop_service(service, profile=profile)
            if result.ok or self.runner.dry_run:
                stopped.append(service)

        gpu_memory: str | None = None
        if command_exists("nvidia-smi") and not self.runner.dry_run:
            time.sleep(1)
            result = self.runner.run(
                (
                    "nvidia-smi",
                    "--query-gpu=name,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ),
                check=False,
            )
            if result.ok:
                gpu_memory = result.stdout.strip()
        return GpuOffReport(tuple(unloaded), tuple(stopped), gpu_memory)

    def status(self) -> list[dict[str, Any]]:
        self._ensure_available()
        if not self.settings.env_file.exists():
            return []
        result = self.runner.run(
            self._command(ALL_PROFILES, "ps", "--format", "json"),
            cwd=self.settings.root,
            env=self._environment(),
            check=False,
        )
        if not result.ok or not result.stdout.strip():
            return []
        text = result.stdout.strip()
        try:
            payload = json.loads(text)
            if isinstance(payload, list):
                return [item for item in payload if isinstance(item, dict)]
            if isinstance(payload, dict):
                return [payload]
        except json.JSONDecodeError:
            pass
        rows: list[dict[str, Any]] = []
        for line in text.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows

    def logs(self, service: str | None, *, follow: bool = False, tail: int = 200) -> RunResult:
        self._require_initialized_for_execution()
        self._ensure_available()
        arguments = ["logs", "--tail", str(tail)]
        if follow:
            arguments.append("--follow")
        if service:
            arguments.append(service)
        return self.runner.run(
            self._command(ALL_PROFILES, *arguments),
            cwd=self.settings.root,
            env=self._environment(),
            check=True,
            capture=False,
        )

    def pull_ollama(self, artifact: str) -> None:
        self._require_initialized_for_execution()
        self._ensure_available()
        self.stop_service("vllm", profile="eval")
        self.runner.run(
            self._command(("chat",), "up", "--detach", "ollama"),
            cwd=self.settings.root,
            env=self._environment(),
            check=True,
            capture=False,
        )
        self.runner.run(
            self._command(("chat",), "exec", "-T", "ollama", "ollama", "pull", artifact),
            cwd=self.settings.root,
            env=self._environment(),
            check=True,
            capture=False,
        )

    def ollama_inventory(self) -> tuple[OllamaModel, ...]:
        self._require_initialized_for_execution()
        self._ensure_available()
        result = self.runner.run(
            self._command(("chat",), "exec", "-T", "ollama", "ollama", "list"),
            cwd=self.settings.root,
            env=self._environment(),
            check=False,
        )
        if not result.ok:
            raise RuntimeError(
                "Cannot read the Ollama inventory. Start the chat profile first with "
                "`uv run serveshed up chat`."
            )
        models: list[OllamaModel] = []
        pattern = re.compile(
            r"^(?P<name>\S+)\s+(?P<id>[0-9a-fA-F]+)\s+"
            r"(?P<size>[0-9.]+\s+\S+)\s+(?P<modified>.+)$"
        )
        for raw in result.stdout.splitlines():
            line = raw.strip()
            if not line or line.upper().startswith("NAME"):
                continue
            match = pattern.match(line)
            if match:
                models.append(
                    OllamaModel(
                        name=match.group("name"),
                        model_id=match.group("id"),
                        size=match.group("size"),
                        modified=match.group("modified"),
                    )
                )
        return tuple(models)

    def run_promptfoo(
        self,
        *,
        runtime: str = "chat",
        output_name: str = "promptfoo-results.json",
    ) -> tuple[RunResult, Path]:
        if runtime not in {"chat", "eval"}:
            raise RuntimeError(f"Unsupported Promptfoo runtime: {runtime}")
        self._require_initialized_for_execution()
        self._ensure_available()
        self.up(runtime, eval_logging=True)
        relative = Path("promptfoo") / output_name
        output = self.settings.eval_runs_dir / relative
        config_name = "promptfooconfig.yaml" if runtime == "chat" else "promptfooconfig.batch.yaml"
        if not self.runner.dry_run:
            output.parent.mkdir(parents=True, exist_ok=True)
            # The official Promptfoo image drops to a fixed non-root user
            # (uid 100/gid 101) that owns neither this bind-mounted host
            # directory nor its group, so mode 0o755 (the mkdir default)
            # leaves it unable to write its results file. Every other
            # service in this stack runs as root and doesn't hit this, so
            # widen write access on just this results directory rather than
            # broaden any container's privileges. Unconditional so a
            # directory left over from before this fix also gets corrected.
            output.parent.chmod(0o777)
        result = self.runner.run(
            self._command(
                ("core", "tools"),
                "run",
                "--rm",
                "promptfoo",
                "eval",
                "--config",
                f"/workspace/{config_name}",
                "--no-cache",
                "--output",
                f"/results/{relative.as_posix()}",
            ),
            cwd=self.settings.root,
            env=self._environment(self._bifrost_override(eval_logging=True)),
            check=True,
            capture=False,
        )
        return result, output

    def dump_database(self, database: str) -> str:
        self._require_initialized_for_execution()
        self._ensure_available()
        admin_user = self.settings.get("POSTGRES_SUPERUSER", "serveshed_admin")
        result = self.runner.run(
            self._command(
                ("core",),
                "exec",
                "-T",
                "postgres",
                "pg_dump",
                "--no-owner",
                "--no-privileges",
                "--clean",
                "--if-exists",
                "--username",
                admin_user,
                "--dbname",
                database,
            ),
            cwd=self.settings.root,
            env=self._environment(),
            check=True,
        )
        return result.stdout
