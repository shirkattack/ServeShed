from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from serveshed.compose import ComposeManager
from serveshed.settings import Settings


@dataclass(frozen=True, slots=True)
class NasState:
    path: Path
    mounted: bool
    marker_present: bool
    ready: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["path"] = str(self.path)
        return value


@dataclass(frozen=True, slots=True)
class BackupPlan:
    nas: NasState
    destination: Path | None
    includes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "nas": self.nas.as_dict(),
            "destination": str(self.destination) if self.destination else None,
            "includes": list(self.includes),
        }


def inspect_nas(settings: Settings) -> NasState:
    path = settings.nas_dir
    mounted = path.exists() and os.path.ismount(path)
    marker_present = (path / settings.nas_marker).is_file() if path.exists() else False
    ready = mounted and marker_present and os.access(path, os.W_OK)
    if not path.exists():
        reason = "mount path does not exist"
    elif not mounted:
        reason = "path exists but is not a mount point"
    elif not marker_present:
        reason = f"guard marker {settings.nas_marker!r} is absent"
    elif not os.access(path, os.W_OK):
        reason = "mount is not writable"
    else:
        reason = "ready"
    return NasState(path, mounted, marker_present, ready, reason)


def initialize_nas(settings: Settings, *, execute: bool = False) -> NasState:
    state = inspect_nas(settings)
    if not execute:
        return state
    if not state.mounted:
        raise RuntimeError(f"Refusing to initialize NAS: {state.reason}")
    (state.path / settings.nas_marker).write_text(
        json.dumps(
            {
                "project": "serveshed",
                "initialized_at": datetime.now(UTC).isoformat(),
                "purpose": "fail-closed guard for serveshed NAS writes",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    for relative in (
        "backups/serveshed",
        "models/huggingface",
        "models/gguf",
        "models/quantized",
        "datasets",
        "eval-runs",
    ):
        (state.path / relative).mkdir(parents=True, exist_ok=True)
    return inspect_nas(settings)


def plan_backup(settings: Settings, *, now: datetime | None = None) -> BackupPlan:
    nas = inspect_nas(settings)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    destination = nas.path / "backups" / "serveshed" / stamp if nas.ready else None
    return BackupPlan(
        nas=nas,
        destination=destination,
        includes=(
            "repository configuration and documentation, excluding secrets and Git metadata",
            "completed local evaluation bundles",
            "plain SQL dumps for Phoenix and Bifrost",
            "SHA-256 checksums and a backup manifest",
        ),
    )


def _backup_ignore(_directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if (
            name in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
            or name in {".env", ".env.phoenix"}
            or name.startswith(".env.bak-")
            or name.endswith(".pyc")
        ):
            ignored.add(name)
    return ignored


def _copy_project_files(root: Path, destination: Path) -> None:
    for relative in (
        Path(".editorconfig"),
        Path(".env.example"),
        Path(".gitignore"),
        Path(".python-version"),
        Path("CHANGELOG.md"),
        Path("CONTRIBUTING.md"),
        Path("LICENSE"),
        Path("README.md"),
        Path("SCAFFOLD_MANIFEST.json"),
        Path("compose.yaml"),
        Path("serveshed_build.py"),
        Path("pyproject.toml"),
        Path("uv.lock"),
        Path("config"),
        Path("docs"),
        Path("evals"),
        Path("examples"),
        Path("scripts"),
        Path("src"),
        Path("tests"),
    ):
        source = root / relative
        target = destination / "project" / relative
        if not source.exists():
            continue
        if source.is_dir():
            shutil.copytree(
                source,
                target,
                dirs_exist_ok=True,
                ignore=_backup_ignore,
            )
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def _write_checksums(root: Path) -> None:
    rows: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "checksums.sha256":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(f"{digest}  {path.relative_to(root).as_posix()}")
    (root / "checksums.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")


def execute_backup(
    settings: Settings,
    *,
    compose: ComposeManager,
    now: datetime | None = None,
) -> Path:
    """Create a fail-closed NAS backup after an explicit CLI --execute flag."""
    settings.require_initialized()
    plan = plan_backup(settings, now=now)
    if not plan.nas.ready or plan.destination is None:
        raise RuntimeError(f"Refusing NAS backup: {plan.nas.reason}")

    destination = plan.destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f".{destination.name}.partial")
    if destination.exists() or partial.exists():
        raise RuntimeError(f"Backup destination already exists: {destination}")

    partial.mkdir(parents=True, exist_ok=False)
    try:
        _copy_project_files(settings.root, partial)
        if settings.eval_runs_dir.exists():
            shutil.copytree(
                settings.eval_runs_dir,
                partial / "eval-runs",
                dirs_exist_ok=True,
            )
        dumps = partial / "postgres"
        dumps.mkdir(parents=True, exist_ok=True)
        databases = (
            (settings.get("PHOENIX_DB_NAME", "phoenix"), "phoenix.sql"),
            (settings.get("BIFROST_DB_NAME", "bifrost"), "bifrost.sql"),
        )
        for database, filename in databases:
            (dumps / filename).write_text(compose.dump_database(database), encoding="utf-8")
        metadata = {
            "created_at": (now or datetime.now(UTC)).isoformat(),
            "source_root": str(settings.root),
            "source_data_dir": str(settings.data_dir),
            "destination": str(destination),
            "includes": list(plan.includes),
        }
        (partial / "manifest.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _write_checksums(partial)
        partial.rename(destination)
    except Exception:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return destination
