from __future__ import annotations

import platform
import shutil
import socket
import sys
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from serveshed.backup import inspect_nas
from serveshed.models import load_registry, recommend_models
from serveshed.settings import Settings
from serveshed.shell import Runner, command_exists


class CheckStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    status: CheckStatus
    summary: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        value = asdict(self)
        value["status"] = self.status.value
        return value


def checks_as_dict(checks: tuple[DoctorCheck, ...]) -> list[dict[str, str]]:
    return [check.as_dict() for check in checks]


def _memory_gib() -> float | None:
    path = Path("/proc/meminfo")
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) / (1024**2)
    return None


def _port_available(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def hardware_snapshot(settings: Settings, *, runner: Runner | None = None) -> dict[str, Any]:
    runner = runner or Runner()
    disk = shutil.disk_usage(settings.data_dir if settings.data_dir.exists() else Path.home())
    snapshot: dict[str, Any] = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "machine": platform.machine(),
        "memory_gib": _memory_gib(),
        "data_disk_free_gib": disk.free / (1024**3),
        "nvidia_smi": None,
        "git_commit": None,
    }
    if command_exists("nvidia-smi"):
        result = runner.run(
            (
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total,memory.used",
                "--format=csv,noheader,nounits",
            ),
            check=False,
            timeout=15,
        )
        if result.ok:
            snapshot["nvidia_smi"] = result.stdout.strip()
    if command_exists("git"):
        result = runner.run(
            ("git", "rev-parse", "HEAD"), cwd=settings.root, check=False, timeout=10
        )
        if result.ok:
            snapshot["git_commit"] = result.stdout.strip()
    return snapshot


def collect_doctor(settings: Settings, *, runner: Runner | None = None) -> tuple[DoctorCheck, ...]:
    runner = runner or Runner()
    checks: list[DoctorCheck] = []

    version_ok = sys.version_info >= (3, 12)
    checks.append(
        DoctorCheck(
            "python",
            CheckStatus.PASS if version_ok else CheckStatus.FAIL,
            sys.version.split()[0],
            "Python 3.12 or newer is required by this scaffold.",
        )
    )

    uv_path = shutil.which("uv")
    checks.append(
        DoctorCheck(
            "uv",
            CheckStatus.PASS if uv_path else CheckStatus.FAIL,
            uv_path or "not found",
            "Use uv for every project-owned Python dependency and command.",
        )
    )

    if not settings.env_file.exists():
        checks.append(
            DoctorCheck(
                "environment",
                CheckStatus.WARN,
                ".env not initialized",
                "Run `uv run serveshed init` before starting services.",
            )
        )
    elif settings.secret_placeholders:
        checks.append(
            DoctorCheck(
                "environment",
                CheckStatus.FAIL,
                "secret placeholders remain",
                ", ".join(settings.secret_placeholders),
            )
        )
    else:
        checks.append(
            DoctorCheck("environment", CheckStatus.PASS, "initialized", str(settings.env_file))
        )

    docker_ok = command_exists("docker")
    compose_detail = "Docker not found"
    compose_ok = False
    if docker_ok:
        result = runner.run(("docker", "compose", "version"), check=False, timeout=15)
        compose_ok = result.ok
        compose_detail = result.stdout.strip() or result.stderr.strip()
    checks.append(
        DoctorCheck(
            "docker-compose",
            CheckStatus.PASS if compose_ok else CheckStatus.FAIL,
            compose_detail,
            "Native Docker Engine and the Compose plugin are required on Ubuntu.",
        )
    )

    gpu_detail = "nvidia-smi not found"
    gpu_status = CheckStatus.FAIL
    if command_exists("nvidia-smi"):
        result = runner.run(
            (
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ),
            check=False,
            timeout=15,
        )
        if result.ok:
            gpu_detail = result.stdout.strip()
            gpu_status = CheckStatus.PASS if "5070 Ti" in gpu_detail else CheckStatus.WARN
    checks.append(
        DoctorCheck(
            "nvidia-gpu",
            gpu_status,
            gpu_detail,
            "The target is an RTX 5070 Ti 16 GB with a working host driver.",
        )
    )

    memory = _memory_gib()
    if memory is None:
        memory_status = CheckStatus.WARN
        memory_summary = "unknown"
    else:
        memory_status = CheckStatus.PASS if memory >= 32 else CheckStatus.WARN
        memory_summary = f"{memory:.1f} GiB"
    checks.append(
        DoctorCheck(
            "system-memory",
            memory_status,
            memory_summary,
            "32 GiB supports the daily 9B profiles; 64 GiB or more is preferred for offload, quantization, and larger eval jobs.",
        )
    )

    disk_root = settings.data_dir if settings.data_dir.exists() else Path.home()
    free_gib = shutil.disk_usage(disk_root).free / (1024**3)
    checks.append(
        DoctorCheck(
            "free-disk",
            CheckStatus.PASS if free_gib >= 40 else CheckStatus.WARN,
            f"{free_gib:.1f} GiB free",
            f"Measured at {disk_root}; leave room for models, caches, databases, and eval bundles.",
        )
    )

    try:
        registry = load_registry(settings)
        default_model = registry.require(settings.default_model_alias)
        recommendations = recommend_models(
            registry,
            vram_gib=settings.target_vram_gib,
            workload="general",
        )
        top = recommendations[0].alias if recommendations else "none"
        checks.append(
            DoctorCheck(
                "model-registry",
                CheckStatus.PASS,
                f"{len(registry)} aliases; default {default_model.alias}; recommended {top}",
                str(settings.model_registry_file),
            )
        )
    except RuntimeError as exc:
        checks.append(DoctorCheck("model-registry", CheckStatus.FAIL, "invalid", str(exc)))

    for name, port in (
        ("bifrost-port", settings.bifrost_port),
        ("phoenix-port", settings.phoenix_port),
    ):
        available = _port_available(port)
        checks.append(
            DoctorCheck(
                name,
                CheckStatus.PASS if available else CheckStatus.WARN,
                f"127.0.0.1:{port} {'available' if available else 'in use'}",
                "An in-use port is expected when the corresponding service is running.",
            )
        )

    tailscale = command_exists("tailscale")
    checks.append(
        DoctorCheck(
            "tailscale",
            CheckStatus.PASS if tailscale else CheckStatus.WARN,
            shutil.which("tailscale") or "not installed",
            "Tailscale is optional for local use and should run on the Ubuntu host.",
        )
    )

    nas = inspect_nas(settings)
    checks.append(
        DoctorCheck(
            "synology",
            CheckStatus.PASS if nas.ready else CheckStatus.WARN,
            nas.reason,
            "The NAS is optional and never blocks local startup.",
        )
    )
    return tuple(checks)
