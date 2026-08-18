from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from serveshed.env import SECRET_KEYS, contains_placeholder, parse_env_file, placeholder_keys
from serveshed.paths import find_project_root


@dataclass(frozen=True, slots=True)
class Settings:
    root: Path
    env_file: Path
    values: Mapping[str, str]

    @classmethod
    def load(
        cls,
        *,
        root: Path | str | None = None,
        env_file: Path | str | None = None,
    ) -> Settings:
        project_root = find_project_root(root)
        selected = Path(env_file).expanduser() if env_file else project_root / ".env"
        if not selected.is_absolute():
            selected = project_root / selected
        selected = selected.resolve()
        return cls(project_root, selected, parse_env_file(selected))

    def get(self, key: str, default: str = "") -> str:
        return os.environ.get(key, self.values.get(key, default))

    def get_int(self, key: str, default: int) -> int:
        value = self.get(key, str(default))
        try:
            return int(value)
        except ValueError as exc:
            raise RuntimeError(f"{key} must be an integer, got {value!r}") from exc

    def get_float(self, key: str, default: float) -> float:
        value = self.get(key, str(default))
        try:
            return float(value)
        except ValueError as exc:
            raise RuntimeError(f"{key} must be a number, got {value!r}") from exc

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.get(key, "true" if default else "false").strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
        raise RuntimeError(f"{key} must be true or false, got {value!r}")

    @property
    def secret_placeholders(self) -> list[str]:
        merged = dict(self.values)
        merged.update({key: os.environ[key] for key in SECRET_KEYS if key in os.environ})
        return placeholder_keys(merged, keys=SECRET_KEYS)

    @property
    def placeholders(self) -> list[str]:
        return self.secret_placeholders

    @property
    def initialized(self) -> bool:
        return self.env_file.is_file() and not self.secret_placeholders

    @property
    def data_dir(self) -> Path:
        return Path(self.get("SERVESHED_DATA_DIR", "~/.local/share/serveshed")).expanduser()

    @property
    def cache_dir(self) -> Path:
        return Path(self.get("SERVESHED_CACHE_DIR", "~/.cache/serveshed")).expanduser()

    @property
    def eval_runs_dir(self) -> Path:
        return self.data_dir / "eval-runs"

    @property
    def nas_dir(self) -> Path:
        return Path(self.get("SERVESHED_NAS_DIR", "/mnt/synology-ai")).expanduser()

    @property
    def nas_marker(self) -> str:
        return self.get("SERVESHED_NAS_MARKER", ".serveshed-nas")

    @property
    def bifrost_port(self) -> int:
        return self.get_int("BIFROST_PORT", 8080)

    @property
    def phoenix_port(self) -> int:
        return self.get_int("PHOENIX_PORT", 6006)

    @property
    def openwebui_port(self) -> int:
        return self.get_int("OPENWEBUI_PORT", 3000)

    @property
    def bifrost_base_url(self) -> str:
        return self.get("BIFROST_BASE_URL", f"http://127.0.0.1:{self.bifrost_port}").rstrip("/")

    @property
    def default_model_alias(self) -> str:
        return self.get("SERVESHED_DEFAULT_MODEL_ALIAS", "local/qwen-fast")

    @property
    def target_vram_gib(self) -> float:
        return self.get_float("SERVESHED_TARGET_VRAM_GIB", 16.0)

    @property
    def vllm_enabled(self) -> bool:
        return self.get_bool("SERVESHED_ENABLE_VLLM", False)

    @property
    def compose_file(self) -> Path:
        return self.root / "compose.yaml"

    @property
    def model_registry_file(self) -> Path:
        return self.root / "config" / "models" / "registry.yaml"

    @property
    def compose_env(self) -> dict[str, str]:
        environment = dict(os.environ)
        environment.update(self.values)
        return environment

    def bifrost_config_file(self, *, eval_logging: bool = False) -> Path:
        name = "config.eval.json" if eval_logging else "config.json"
        return (self.root / "config" / "bifrost" / name).resolve()

    _TAILSCALE_ORIGIN_PLACEHOLDER = "env.BIFROST_TAILSCALE_ORIGIN"

    def render_bifrost_config(self, *, eval_logging: bool = False) -> Path:
        """Materialize config/bifrost/config*.json with host-specific values
        Bifrost's own "env." substitution can't reach, since that mechanism
        only resolves specific typed schema fields (secrets, provider keys),
        never plain array elements like client.allowed_origins (ADR 0019).

        Never edits the tracked template. Writes the rendered copy under the
        cache dir (regenerable, gitignored by being outside the repo) and
        returns its path; compose.py mounts that path into the container
        instead of the template directly. If BIFROST_TAILSCALE_ORIGIN is
        unset, the placeholder is simply dropped rather than left dangling.
        """
        template = self.bifrost_config_file(eval_logging=eval_logging)
        payload = json.loads(template.read_text(encoding="utf-8"))
        origins = payload.get("client", {}).get("allowed_origins")
        if isinstance(origins, list) and self._TAILSCALE_ORIGIN_PLACEHOLDER in origins:
            resolved = [o for o in origins if o != self._TAILSCALE_ORIGIN_PLACEHOLDER]
            tailscale_origin = self.get("BIFROST_TAILSCALE_ORIGIN", "").strip()
            if tailscale_origin:
                resolved.append(tailscale_origin)
            payload["client"]["allowed_origins"] = resolved
        rendered_dir = self.cache_dir / "bifrost"
        rendered_dir.mkdir(parents=True, exist_ok=True)
        rendered_path = rendered_dir / template.name
        rendered_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return rendered_path

    def require_initialized(self) -> None:
        if not self.env_file.is_file():
            raise RuntimeError(
                f"{self.env_file} does not exist. Run `uv run serveshed init` first."
            )
        if self.secret_placeholders:
            raise RuntimeError(
                f"{self.env_file} still contains secret placeholders: "
                + ", ".join(self.secret_placeholders)
                + ". Run `uv run serveshed init --force` or replace them manually."
            )

    def require_vllm_enabled(self) -> None:
        self.require_initialized()
        model_id = self.get("VLLM_MODEL_ID", "")
        if not self.vllm_enabled:
            raise RuntimeError(
                "vLLM is disabled. Set SERVESHED_ENABLE_VLLM=true only after reviewing "
                "and pinning the model in config/models/registry.yaml."
            )
        if not model_id.strip() or contains_placeholder(model_id) or "REVIEW_REQUIRED" in model_id:
            raise RuntimeError("VLLM_MODEL_ID is empty or still review-gated")

    def require_vllm_ready(self) -> None:
        self.require_vllm_enabled()
