from __future__ import annotations

import os
import re
import secrets
import shutil
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from string import Template

_ENV_LINE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_SECRET_MARKERS = ("CHANGE_ME", "GENERATE_ME")
_CONFIG_MARKERS = (*_SECRET_MARKERS, "REVIEW_REQUIRED")

SECRET_KEYS = frozenset(
    (
        "POSTGRES_SUPERUSER_PASSWORD",
        "PHOENIX_DB_PASSWORD",
        "BIFROST_DB_PASSWORD",
        "BIFROST_ADMIN_PASSWORD",
        "BIFROST_ENCRYPTION_KEY",
        "BIFROST_VK_HERMES",
        "BIFROST_VK_RESEARCH",
        "BIFROST_VK_CODING",
        "BIFROST_VK_EVAL",
        "BIFROST_VK_JUDGE",
        "BIFROST_VK_WEBUI",
        "BIFROST_VK_REFUSAL_PILOT",
        "VLLM_API_KEY",
        "LITELLM_MASTER_KEY",
        "OPENWEBUI_SECRET_KEY",
    )
)

_SECRET_GENERATORS: dict[str, Callable[[], str]] = {
    "POSTGRES_SUPERUSER_PASSWORD": lambda: secrets.token_urlsafe(32),
    "PHOENIX_DB_PASSWORD": lambda: secrets.token_urlsafe(32),
    "BIFROST_DB_PASSWORD": lambda: secrets.token_urlsafe(32),
    "BIFROST_ADMIN_PASSWORD": lambda: secrets.token_urlsafe(32),
    "BIFROST_ENCRYPTION_KEY": lambda: secrets.token_hex(32),
    "BIFROST_VK_HERMES": lambda: f"sk-bf-{secrets.token_urlsafe(32)}",
    "BIFROST_VK_RESEARCH": lambda: f"sk-bf-{secrets.token_urlsafe(32)}",
    "BIFROST_VK_CODING": lambda: f"sk-bf-{secrets.token_urlsafe(32)}",
    "BIFROST_VK_EVAL": lambda: f"sk-bf-{secrets.token_urlsafe(32)}",
    "BIFROST_VK_JUDGE": lambda: f"sk-bf-{secrets.token_urlsafe(32)}",
    "BIFROST_VK_WEBUI": lambda: f"sk-bf-{secrets.token_urlsafe(32)}",
    "BIFROST_VK_REFUSAL_PILOT": lambda: f"sk-bf-{secrets.token_urlsafe(32)}",
    "VLLM_API_KEY": lambda: f"vllm-{secrets.token_urlsafe(32)}",
    "LITELLM_MASTER_KEY": lambda: f"sk-{secrets.token_urlsafe(32)}",
    "OPENWEBUI_SECRET_KEY": lambda: secrets.token_hex(32),
}


class EnvFileError(RuntimeError):
    """Raised for invalid or unsafe dotenv input."""


@dataclass(frozen=True, slots=True)
class InitResult:
    env_file: Path
    phoenix_env_file: Path
    backup_file: Path | None
    created_env: bool
    updated_keys: tuple[str, ...]
    created_directories: tuple[Path, ...]


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_env_text(text: str, *, source: str = "<text>") -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ENV_LINE.match(line)
        if not match:
            raise EnvFileError(f"Invalid line {line_number} in {source}: {raw_line!r}")
        key, value = match.groups()
        parsed[key] = _unquote(value)
    return parsed


def parse_env_file(path: Path, *, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    if not path.exists():
        return {}
    parsed = parse_env_text(path.read_text(encoding="utf-8"), source=str(path))
    expansion = dict(os.environ if base_env is None else base_env)
    expansion.update(parsed)
    for _ in range(8):
        changed = False
        for key, value in list(parsed.items()):
            expanded = os.path.expanduser(Template(value).safe_substitute(expansion))
            if expanded != value:
                parsed[key] = expanded
                expansion[key] = expanded
                changed = True
        if not changed:
            break
    return parsed


def contains_secret_placeholder(value: str) -> bool:
    return any(marker in value for marker in _SECRET_MARKERS)


def contains_placeholder(value: str) -> bool:
    """Return whether a configuration value is intentionally review-gated."""
    return any(marker in value for marker in _CONFIG_MARKERS)


def placeholder_keys(values: Mapping[str, str], *, keys: Iterable[str] | None = None) -> list[str]:
    selected = keys if keys is not None else tuple(values)
    return sorted(
        key for key in selected if key in values and contains_secret_placeholder(values[key])
    )


def update_env_text(template_text: str, replacements: Mapping[str, str]) -> str:
    output: list[str] = []
    found: set[str] = set()
    for raw_line in template_text.splitlines():
        match = _ENV_LINE.match(raw_line.strip())
        if not match:
            output.append(raw_line)
            continue
        key, _ = match.groups()
        if key in replacements:
            output.append(f"{key}={replacements[key]}")
            found.add(key)
        else:
            output.append(raw_line)
    missing = set(replacements) - found
    if missing:
        output.extend(("", "# Added by serveshed init"))
        output.extend(f"{key}={replacements[key]}" for key in sorted(missing))
    return "\n".join(output).rstrip() + "\n"


def initialize_project(
    root: Path, *, env_file: Path | None = None, force: bool = False
) -> InitResult:
    template = root / ".env.example"
    if not template.exists():
        raise EnvFileError(f"Missing template: {template}")
    destination = env_file or root / ".env"
    if not destination.is_absolute():
        destination = root / destination

    template_text = template.read_text(encoding="utf-8")
    backup: Path | None = None
    created = not destination.exists()
    updated: dict[str, str] = {}

    if created:
        updated = {key: generator() for key, generator in _SECRET_GENERATORS.items()}
        rendered = update_env_text(template_text, updated)
    else:
        current_text = destination.read_text(encoding="utf-8")
        current_values = parse_env_text(current_text, source=str(destination))
        unresolved = [
            key
            for key in _SECRET_GENERATORS
            if key not in current_values or contains_secret_placeholder(current_values[key])
        ]
        if unresolved and not force:
            raise EnvFileError(
                f"{destination} contains unresolved secrets: {', '.join(unresolved)}. "
                "Run `uv run serveshed init --force`; existing valid secrets will be preserved."
            )
        if force and unresolved:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            backup = destination.with_name(f"{destination.name}.bak-{stamp}")
            shutil.copy2(destination, backup)
            updated = {key: _SECRET_GENERATORS[key]() for key in unresolved}
            rendered = update_env_text(current_text, updated)
        else:
            rendered = current_text

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")
    destination.chmod(0o600)

    values = parse_env_file(destination)
    phoenix_port = values.get("PHOENIX_PORT", "6006")
    phoenix_env = destination.with_name(".env.phoenix")
    phoenix_env.write_text(
        "# Generated by `uv run serveshed init`; safe to regenerate.\n"
        "PHOENIX_PROJECT_NAME=serveshed\n"
        f"PHOENIX_COLLECTOR_ENDPOINT=http://127.0.0.1:{phoenix_port}\n"
        f"OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:{phoenix_port}/v1/traces\n"
        "OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf\n",
        encoding="utf-8",
    )
    phoenix_env.chmod(0o600)

    data_dir = Path(values.get("SERVESHED_DATA_DIR", "~/.local/share/serveshed")).expanduser()
    cache_dir = Path(values.get("SERVESHED_CACHE_DIR", "~/.cache/serveshed")).expanduser()
    directories = (
        data_dir,
        cache_dir,
        data_dir / "postgres",
        data_dir / "bifrost",
        data_dir / "ollama",
        data_dir / "eval-runs",
        data_dir / "backups" / "staging",
        cache_dir / "huggingface",
        cache_dir / "work",
    )
    created_directories: list[Path] = []
    for directory in directories:
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            created_directories.append(directory)

    return InitResult(
        env_file=destination.resolve(),
        phoenix_env_file=phoenix_env.resolve(),
        backup_file=backup.resolve() if backup else None,
        created_env=created,
        updated_keys=tuple(sorted(updated)),
        created_directories=tuple(path.resolve() for path in created_directories),
    )
