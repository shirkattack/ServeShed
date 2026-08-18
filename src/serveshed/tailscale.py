from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from serveshed.settings import Settings
from serveshed.shell import Runner, command_exists


@dataclass(frozen=True, slots=True)
class TailscalePlan:
    installed: bool
    status: str
    commands: tuple[str, ...]
    rollback: tuple[str, ...]
    notes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["commands"] = list(self.commands)
        value["rollback"] = list(self.rollback)
        value["notes"] = list(self.notes)
        return value


def plan(settings: Settings, runner: Runner | None = None) -> TailscalePlan:
    runner = runner or Runner()
    installed = command_exists("tailscale")
    status = "not installed"
    if installed:
        result = runner.run(("tailscale", "status", "--json"), check=False, timeout=15)
        if result.ok:
            try:
                payload = json.loads(result.stdout)
                status = str(payload.get("BackendState", "unknown"))
            except json.JSONDecodeError:
                status = result.stdout.strip() or "unknown"
        else:
            status = result.stderr.strip() or "unknown"

    commands = (
        "tailscale serve --help",
        f"sudo tailscale serve --bg --https=443 http://127.0.0.1:{settings.bifrost_port}",
        f"sudo tailscale serve --bg --https=8443 http://127.0.0.1:{settings.phoenix_port}",
        f"sudo tailscale serve --bg --https=8444 http://127.0.0.1:{settings.openwebui_port}",
        "tailscale serve status",
    )
    rollback = ("sudo tailscale serve reset",)
    notes = (
        "This is a non-executing review plan; serveshed never changes Tailscale automatically.",
        "Confirm syntax against the installed client before applying the commands.",
        "Use Serve, never Funnel, and restrict access with tailnet grants.",
        "Bifrost authentication remains required even inside the tailnet.",
        "Open WebUI needs its own multi-account mode (WEBUI_AUTH=true) before it's meaningful to "
        "reach from another person's device; single-user mode has no separate accounts.",
        "Sharing this host with specific people outside your tailnet (e.g. family) is a Tailscale "
        "admin-console action (Share this device), not a serveshed or tailscale-CLI command.",
        "Do not expose Ollama, vLLM, PostgreSQL, or OTLP directly.",
        "Tailscale SSH is optional and intentionally excluded from the default plan.",
    )
    return TailscalePlan(installed, status, commands, rollback, notes)
