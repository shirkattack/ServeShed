from __future__ import annotations

from typing import Any

from serveshed.backup import inspect_nas
from serveshed.compose import ComposeManager
from serveshed.doctor import hardware_snapshot
from serveshed.health import collect_service_health
from serveshed.settings import Settings
from serveshed.shell import Runner, command_exists


def collect_status(settings: Settings, *, runner: Runner | None = None) -> dict[str, Any]:
    runner = runner or Runner()
    services: list[dict[str, Any]] = []
    ollama_processes: list[dict[str, str]] = []
    compose_error: str | None = None
    if command_exists("docker") and settings.env_file.exists():
        try:
            manager = ComposeManager(settings, runner=runner)
            services = manager.status()
            ollama_processes = [item.as_dict() for item in manager.ollama_processes()]
        except RuntimeError as exc:
            compose_error = str(exc)
    else:
        compose_error = "Docker or .env is unavailable"
    return {
        "health": [probe.as_dict() for probe in collect_service_health(settings)],
        "services": services,
        "compose_error": compose_error,
        "ollama_processes": ollama_processes,
        "hardware": hardware_snapshot(settings, runner=runner),
        "nas": inspect_nas(settings).as_dict(),
    }
