from __future__ import annotations

import hashlib
import json
import math
import secrets
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any


class ArtifactError(RuntimeError):
    """Raised when an immutable run artifact is invalid or cannot be verified."""


@dataclass(frozen=True, slots=True)
class ChecksumEntry:
    path: str
    expected: str
    actual: str | None
    ok: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Mapping[str, Any] | Sequence[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{secrets.token_hex(4)}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()


def write_jsonl(path: Path, payloads: Iterable[Mapping[str, Any]]) -> None:
    """Atomically write an exact JSONL input set for a reproducible run."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{secrets.token_hex(4)}")
    with temporary.open("w", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
    temporary.replace(path)


def create_run_dir(base: Path, *, category: str, label: str) -> tuple[str, Path, datetime]:
    now = datetime.now(UTC)
    safe_category = _safe_component(category)
    safe_label = _safe_component(label)
    run_id = f"{safe_label}-{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
    run_dir = base / safe_category / now.strftime("%Y-%m-%d") / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_id, run_dir, now


def write_checksums(run_dir: Path, *, filename: str = "checksums.sha256") -> Path:
    checksum_file = run_dir / filename
    rows: list[str] = []
    for path in sorted(run_dir.rglob("*")):
        if path.is_symlink():
            raise ArtifactError(f"Run bundles cannot contain symlinks: {path}")
        if path.is_file() and path != checksum_file:
            rows.append(f"{sha256_file(path)}  {path.relative_to(run_dir).as_posix()}")
    checksum_file.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return checksum_file


def verify_checksums(
    run_dir: Path, *, filename: str = "checksums.sha256"
) -> tuple[ChecksumEntry, ...]:
    run_root = run_dir.resolve()
    checksum_file = run_dir / filename
    if not checksum_file.is_file():
        raise ArtifactError(f"Checksum manifest not found: {checksum_file}")
    results: list[ChecksumEntry] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(checksum_file.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if "  " not in line:
            raise ArtifactError(f"Invalid checksum line {line_number} in {checksum_file}")
        expected, relative = line.split("  ", 1)
        if len(expected) != 64 or any(
            character not in "0123456789abcdef" for character in expected
        ):
            raise ArtifactError(f"Invalid SHA-256 digest on line {line_number} in {checksum_file}")
        posix_path = PurePosixPath(relative)
        if posix_path.is_absolute() or ".." in posix_path.parts or "\\" in relative:
            raise ArtifactError(
                f"Unsafe checksum path {relative!r} on line {line_number} in {checksum_file}"
            )
        if relative in seen:
            raise ArtifactError(f"Duplicate checksum path {relative!r} in {checksum_file}")
        seen.add(relative)
        candidate = run_dir / Path(*posix_path.parts)
        target = candidate.resolve()
        if not target.is_relative_to(run_root):
            raise ArtifactError(f"Checksum path escapes the run directory: {relative!r}")
        if candidate.is_symlink():
            results.append(
                ChecksumEntry(relative, expected, None, False, "symlinks are not allowed")
            )
            continue
        if not target.is_file():
            results.append(ChecksumEntry(relative, expected, None, False, "file is missing"))
            continue
        actual = sha256_file(target)
        results.append(
            ChecksumEntry(
                relative,
                expected,
                actual,
                actual == expected,
                "checksum matches" if actual == expected else "checksum mismatch",
            )
        )
    if not results:
        raise ArtifactError(f"Checksum manifest is empty: {checksum_file}")
    for path in sorted(run_dir.rglob("*")):
        if path == checksum_file:
            continue
        relative = path.relative_to(run_dir).as_posix()
        if path.is_symlink():
            results.append(
                ChecksumEntry(relative, "", None, False, "untracked symlink is not allowed")
            )
        elif path.is_file() and relative not in seen:
            results.append(
                ChecksumEntry(
                    relative,
                    "",
                    sha256_file(path),
                    False,
                    "file is not listed in the checksum manifest",
                )
            )
    return tuple(results)


def percentile(values: Iterable[float], percentile_value: float) -> float:
    samples = sorted(float(value) for value in values)
    if not samples:
        return 0.0
    if percentile_value < 0 or percentile_value > 100:
        raise ValueError("percentile must be between 0 and 100")
    if len(samples) == 1:
        return samples[0]
    position = (len(samples) - 1) * (percentile_value / 100.0)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return samples[lower]
    fraction = position - lower
    return samples[lower] + (samples[upper] - samples[lower]) * fraction


def _safe_component(value: str) -> str:
    rendered = "".join(
        character if character.isalnum() or character in "-_" else "-" for character in value
    )
    rendered = rendered.strip("-")
    return rendered or "run"
