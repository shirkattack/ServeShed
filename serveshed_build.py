"""Tiny dependency-free PEP 517/660 backend used to bootstrap the project offline.

The project can switch to uv-build or hatchling later through an ADR. Keeping the
bootstrap backend local lets `uv sync --locked` work before external Python
packages are available.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import tarfile
import tomllib
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
_PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
NAME = str(_PROJECT["name"])
VERSION = str(_PROJECT["version"])
DIST_INFO = f"{NAME}-{VERSION}.dist-info"
WHEEL_NAME = f"{NAME}-{VERSION}-py3-none-any.whl"


def _metadata_text() -> str:
    return (
        "Metadata-Version: 2.3\n"
        f"Name: {NAME}\n"
        f"Version: {VERSION}\n"
        "Summary: Local-first LLM workstation lifecycle, diagnostics, and evaluation tooling\n"
        "Requires-Python: >=3.12,<3.14\n"
        "License: MIT\n"
        "\n"
    )


def _wheel_text() -> str:
    return (
        "Wheel-Version: 1.0\n"
        "Generator: serveshed-build 1\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
        "\n"
    )


def _entry_points_text() -> str:
    return "[console_scripts]\nserveshed = serveshed.cli:main\n"


def _record_line(path: str, data: bytes) -> tuple[str, str, str]:
    digest = hashlib.sha256(data).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return path, f"sha256={encoded}", str(len(data))


def _write_wheel(wheel_path: Path, files: dict[str, bytes]) -> None:
    record_rows: list[tuple[str, str, str]] = []
    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, data in sorted(files.items()):
            archive.writestr(path, data)
            record_rows.append(_record_line(path, data))
        record_path = f"{DIST_INFO}/RECORD"
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerows(record_rows)
        writer.writerow((record_path, "", ""))
        archive.writestr(record_path, output.getvalue().encode("utf-8"))


def _dist_info_files() -> dict[str, bytes]:
    return {
        f"{DIST_INFO}/METADATA": _metadata_text().encode(),
        f"{DIST_INFO}/WHEEL": _wheel_text().encode(),
        f"{DIST_INFO}/entry_points.txt": _entry_points_text().encode(),
    }


def get_requires_for_build_wheel(config_settings: dict[str, Any] | None = None) -> list[str]:
    return []


def get_requires_for_build_editable(config_settings: dict[str, Any] | None = None) -> list[str]:
    return []


def prepare_metadata_for_build_wheel(
    metadata_directory: str, config_settings: dict[str, Any] | None = None
) -> str:
    target = Path(metadata_directory, DIST_INFO)
    target.mkdir(parents=True, exist_ok=True)
    (target / "METADATA").write_text(_metadata_text(), encoding="utf-8")
    (target / "WHEEL").write_text(_wheel_text(), encoding="utf-8")
    (target / "entry_points.txt").write_text(_entry_points_text(), encoding="utf-8")
    return DIST_INFO


def prepare_metadata_for_build_editable(
    metadata_directory: str, config_settings: dict[str, Any] | None = None
) -> str:
    return prepare_metadata_for_build_wheel(metadata_directory, config_settings)


def build_wheel(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    root = ROOT
    files = _dist_info_files()
    for source in sorted((root / "src" / NAME).rglob("*.py")):
        relative = source.relative_to(root / "src").as_posix()
        files[relative] = source.read_bytes()
    target = Path(wheel_directory, WHEEL_NAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_wheel(target, files)
    return WHEEL_NAME


def build_editable(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    root = ROOT
    files = _dist_info_files()
    files[f"_{NAME}_editable.pth"] = f"{root / 'src'}{os.linesep}".encode()
    target = Path(wheel_directory, WHEEL_NAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_wheel(target, files)
    return WHEEL_NAME


def build_sdist(sdist_directory: str, config_settings: dict[str, Any] | None = None) -> str:
    root = ROOT
    filename = f"{NAME}-{VERSION}.tar.gz"
    target = Path(sdist_directory, filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    excluded_parts = {
        ".git",
        ".venv",
        ".state",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "eval-runs",
    }
    excluded_names = {".env", ".env.phoenix"}
    with tarfile.open(target, "w:gz") as archive:
        for source in sorted(root.rglob("*")):
            relative = source.relative_to(root)
            if any(part in excluded_parts for part in relative.parts):
                continue
            if source.name in excluded_names or source.name.startswith(".env.bak-"):
                continue
            if source.suffix == ".pyc":
                continue
            archive.add(
                source,
                arcname=Path(f"{NAME}-{VERSION}") / relative,
                recursive=False,
            )
    return filename
