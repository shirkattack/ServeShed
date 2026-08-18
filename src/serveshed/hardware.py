from __future__ import annotations

import platform
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from serveshed.shell import Runner, command_exists


@dataclass(frozen=True, slots=True)
class GpuSnapshot:
    index: int
    name: str
    driver_version: str
    memory_total_mib: float
    memory_used_mib: float
    utilization_percent: float | None
    temperature_c: float | None

    @property
    def memory_total_gib(self) -> float:
        return self.memory_total_mib / 1024.0

    @property
    def memory_used_gib(self) -> float:
        return self.memory_used_mib / 1024.0

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["memory_total_gib"] = round(self.memory_total_gib, 3)
        value["memory_used_gib"] = round(self.memory_used_gib, 3)
        return value


def memory_gib() -> float | None:
    path = Path("/proc/meminfo")
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) / (1024**2)
    return None


def query_gpus(*, runner: Runner | None = None) -> tuple[GpuSnapshot, ...]:
    runner = runner or Runner()
    if not command_exists("nvidia-smi"):
        return ()
    result = runner.run(
        (
            "nvidia-smi",
            "--query-gpu=index,name,driver_version,memory.total,memory.used,utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits",
        ),
        check=False,
        timeout=15,
    )
    if not result.ok:
        return ()
    devices: list[GpuSnapshot] = []
    for raw in result.stdout.splitlines():
        columns = [column.strip() for column in raw.split(",")]
        if len(columns) != 7:
            continue
        try:
            devices.append(
                GpuSnapshot(
                    index=int(columns[0]),
                    name=columns[1],
                    driver_version=columns[2],
                    memory_total_mib=float(columns[3]),
                    memory_used_mib=float(columns[4]),
                    utilization_percent=_optional_float(columns[5]),
                    temperature_c=_optional_float(columns[6]),
                )
            )
        except ValueError:
            continue
    return tuple(devices)


def primary_vram_gib(*, runner: Runner | None = None) -> float | None:
    devices = query_gpus(runner=runner)
    return devices[0].memory_total_gib if devices else None


def machine_snapshot(data_path: Path, *, runner: Runner | None = None) -> dict[str, Any]:
    runner = runner or Runner()
    disk_root = data_path if data_path.exists() else Path.home()
    disk = shutil.disk_usage(disk_root)
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "system_memory_gib": memory_gib(),
        "data_path": str(disk_root),
        "data_disk_free_gib": round(disk.free / (1024**3), 3),
        "gpus": [device.as_dict() for device in query_gpus(runner=runner)],
    }


def _optional_float(value: str) -> float | None:
    normalized = value.strip().lower()
    if not normalized or normalized in {"n/a", "na", "not supported", "[n/a]"}:
        return None
    return float(value)
