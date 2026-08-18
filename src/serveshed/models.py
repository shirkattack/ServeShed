from __future__ import annotations

import json
import secrets
import shutil
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from serveshed.compose import ComposeManager
from serveshed.env import parse_env_file, update_env_text
from serveshed.settings import Settings


class ModelRegistryError(RuntimeError):
    """Raised when model metadata or a model action is unsafe."""


@dataclass(frozen=True, slots=True)
class ModelSpec:
    alias: str
    gateway_model: str
    purpose: str
    runtime: str
    upstream_repo: str
    revision: str
    artifact: str
    quantization: str
    context_tokens: int
    modalities: tuple[str, ...]
    tools: bool
    license: str
    approximate_disk_gib: float | None
    approval: str
    notes: str
    artifact_digest: str = ""
    tier: str = "experimental"
    enabled: bool = True
    workloads: tuple[str, ...] = ()
    min_vram_gib: float | None = None
    recommended_vram_gib: float | None = None
    recommended_ram_gib: float | None = None
    cpu_offload: str = "unknown"
    tags: tuple[str, ...] = ()
    default_parameters: Mapping[str, Any] = field(default_factory=dict)
    runtime_parameters: Mapping[str, Any] = field(default_factory=dict)

    @property
    def pullable(self) -> bool:
        return (
            self.enabled
            and self.runtime == "ollama"
            and bool(self.artifact)
            and self.approval.startswith("approved")
        )

    @property
    def local_context(self) -> int:
        return self.context_tokens

    @property
    def expected_disk_gib(self) -> float | None:
        return self.approximate_disk_gib

    @property
    def experimental(self) -> bool:
        return self.tier == "experimental" or self.alias.startswith("experimental/")

    def fit_for_vram(self, vram_gib: float | None) -> str:
        if vram_gib is None:
            return "unknown"
        if self.recommended_vram_gib is not None and vram_gib >= self.recommended_vram_gib:
            return "comfortable"
        if self.min_vram_gib is not None and vram_gib >= self.min_vram_gib:
            return "tight"
        if self.cpu_offload in {"optional", "required"} and self.artifact:
            return "offload"
        return "does-not-fit"

    def as_dict(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "gateway_model": self.gateway_model,
            "purpose": self.purpose,
            "runtime": self.runtime,
            "upstream_repo": self.upstream_repo,
            "revision": self.revision,
            "artifact": self.artifact,
            "artifact_digest": self.artifact_digest,
            "quantization": self.quantization,
            "context_tokens": self.context_tokens,
            "modalities": list(self.modalities),
            "tools": self.tools,
            "license": self.license,
            "approximate_disk_gib": self.approximate_disk_gib,
            "approval": self.approval,
            "notes": self.notes,
            "tier": self.tier,
            "enabled": self.enabled,
            "workloads": list(self.workloads),
            "min_vram_gib": self.min_vram_gib,
            "recommended_vram_gib": self.recommended_vram_gib,
            "recommended_ram_gib": self.recommended_ram_gib,
            "cpu_offload": self.cpu_offload,
            "tags": list(self.tags),
            "default_parameters": dict(self.default_parameters),
            "runtime_parameters": dict(self.runtime_parameters),
        }


@dataclass(frozen=True, slots=True)
class ModelRecommendation:
    alias: str
    score: int
    fit: str
    runtime: str
    tier: str
    artifact: str
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "score": self.score,
            "fit": self.fit,
            "runtime": self.runtime,
            "tier": self.tier,
            "artifact": self.artifact,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class ModelSelection:
    env_file: Path
    previous_alias: str
    selected_alias: str
    changed: bool
    executed: bool
    backup_file: Path | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "env_file": str(self.env_file),
            "previous_alias": self.previous_alias,
            "selected_alias": self.selected_alias,
            "changed": self.changed,
            "executed": self.executed,
            "backup_file": str(self.backup_file) if self.backup_file else None,
        }


@dataclass(frozen=True, slots=True)
class ModelRegistry:
    path: Path
    schema_version: int
    _models: dict[str, ModelSpec]

    def __len__(self) -> int:
        return len(self._models)

    def __iter__(self) -> Iterator[str]:
        return iter(self._models)

    def __getitem__(self, alias: str) -> ModelSpec:
        return self._models[alias]

    def get(self, alias: str) -> ModelSpec | None:
        return self._models.get(alias)

    def values(self) -> tuple[ModelSpec, ...]:
        return tuple(self._models.values())

    def require(self, alias: str) -> ModelSpec:
        try:
            return self._models[alias]
        except KeyError as exc:
            raise ModelRegistryError(
                f"Unknown model alias {alias!r}. Run `serveshed model list`."
            ) from exc

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "models": [model.as_dict() for model in self.values()],
        }


def _optional_float(item: Mapping[str, Any], key: str) -> float | None:
    value = item.get(key)
    return float(value) if value is not None else None


def _mapping(item: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = item.get(key, {})
    if not isinstance(value, Mapping):
        raise TypeError(f"{key} must be an object")
    return dict(value)


def load_registry(source: Settings | Path) -> ModelRegistry:
    path = source.model_registry_file if isinstance(source, Settings) else source
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModelRegistryError(f"Model registry not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ModelRegistryError(
            f"Model registry is not valid JSON-compatible YAML: {exc}"
        ) from exc

    schema_version = payload.get("schema_version")
    if schema_version not in {1, 2} or not isinstance(payload.get("models"), list):
        raise ModelRegistryError("Registry must contain schema_version 1 or 2 and a models list")

    models: dict[str, ModelSpec] = {}
    gateway_models: set[str] = set()
    for index, item in enumerate(payload["models"], 1):
        if not isinstance(item, Mapping):
            raise ModelRegistryError(f"Registry entry {index} must be an object")
        try:
            spec = ModelSpec(
                alias=str(item["alias"]),
                gateway_model=str(item["gateway_model"]),
                purpose=str(item["purpose"]),
                runtime=str(item["runtime"]),
                upstream_repo=str(item["upstream_repo"]),
                revision=str(item["revision"]),
                artifact=str(item.get("artifact", "")),
                quantization=str(item["quantization"]),
                context_tokens=int(item["context_tokens"]),
                modalities=tuple(str(value) for value in item.get("modalities", [])),
                tools=bool(item.get("tools", False)),
                license=str(item["license"]),
                approximate_disk_gib=_optional_float(item, "approximate_disk_gib"),
                approval=str(item["approval"]),
                notes=str(item.get("notes", "")),
                artifact_digest=str(item.get("artifact_digest", "")),
                tier=str(item.get("tier", "experimental")),
                enabled=bool(item.get("enabled", True)),
                workloads=tuple(str(value) for value in item.get("workloads", [])),
                min_vram_gib=_optional_float(item, "min_vram_gib"),
                recommended_vram_gib=_optional_float(item, "recommended_vram_gib"),
                recommended_ram_gib=_optional_float(item, "recommended_ram_gib"),
                cpu_offload=str(item.get("cpu_offload", "unknown")),
                tags=tuple(str(value) for value in item.get("tags", [])),
                default_parameters=_mapping(item, "default_parameters"),
                runtime_parameters=_mapping(item, "runtime_parameters"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelRegistryError(f"Invalid registry entry {index}: {exc}") from exc

        if not spec.alias:
            raise ModelRegistryError(f"Registry entry {index} has an empty alias")
        if spec.alias in models:
            raise ModelRegistryError(f"Duplicate model alias: {spec.alias}")
        if spec.gateway_model in gateway_models:
            raise ModelRegistryError(f"Duplicate gateway model: {spec.gateway_model}")
        if spec.runtime not in {"ollama", "vllm"}:
            raise ModelRegistryError(f"Unsupported runtime for {spec.alias}: {spec.runtime}")
        expected_prefix = f"{spec.runtime}/"
        if not spec.gateway_model.startswith(expected_prefix):
            raise ModelRegistryError(
                f"{spec.alias} gateway_model must start with {expected_prefix!r}"
            )
        if spec.context_tokens < 0:
            raise ModelRegistryError(f"context_tokens cannot be negative for {spec.alias}")
        if spec.cpu_offload not in {"none", "optional", "required", "unknown"}:
            raise ModelRegistryError(
                f"Unsupported cpu_offload value for {spec.alias}: {spec.cpu_offload}"
            )
        if (
            spec.min_vram_gib is not None
            and spec.recommended_vram_gib is not None
            and spec.min_vram_gib > spec.recommended_vram_gib
        ):
            raise ModelRegistryError(f"min_vram_gib exceeds recommended_vram_gib for {spec.alias}")

        models[spec.alias] = spec
        gateway_models.add(spec.gateway_model)

    return ModelRegistry(path=path, schema_version=int(schema_version), _models=models)


def get_model(settings: Settings, alias: str) -> ModelSpec:
    return load_registry(settings).require(alias)


def resolve_gateway_model(settings: Settings, alias_or_model: str) -> str:
    spec = load_registry(settings).get(alias_or_model)
    return spec.gateway_model if spec else alias_or_model


def free_disk_gib(path: Path) -> float:
    path.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(path).free / (1024**3)


def model_rows(registry: ModelRegistry) -> list[tuple[str, ...]]:
    rows: list[tuple[str, ...]] = []
    for spec in registry.values():
        size = (
            "unknown"
            if spec.approximate_disk_gib is None
            else f"{spec.approximate_disk_gib:.1f} GiB"
        )
        rows.append(
            (
                spec.alias,
                spec.tier,
                spec.runtime,
                spec.artifact or "not selected",
                size,
                spec.approval,
            )
        )
    return rows


def recommend_models(
    registry: ModelRegistry,
    *,
    vram_gib: float | None,
    workload: str = "general",
    runtime: str | None = None,
    multimodal: bool = False,
    tools: bool = False,
    include_experimental: bool = False,
) -> tuple[ModelRecommendation, ...]:
    recommendations: list[ModelRecommendation] = []
    for spec in registry.values():
        if not spec.enabled:
            continue
        if spec.experimental and not include_experimental:
            continue
        if runtime is not None and spec.runtime != runtime:
            continue
        if multimodal and "image" not in spec.modalities:
            continue
        if tools and not spec.tools:
            continue

        fit = spec.fit_for_vram(vram_gib)
        if fit == "does-not-fit":
            continue
        score = {
            "comfortable": 55,
            "tight": 35,
            "offload": 10,
            "unknown": 20,
            "does-not-fit": -80,
        }[fit]
        reasons: list[str] = [f"VRAM fit: {fit}"]

        if workload in spec.workloads:
            score += 35
            reasons.append(f"declared for {workload}")
        elif "general" in spec.workloads:
            score += 12
            reasons.append("general-purpose profile")
        elif spec.workloads:
            score -= 8

        tier_scores = {"daily": 18, "quality": 14, "batch": 10, "judge": 4, "experimental": -15}
        score += tier_scores.get(spec.tier, 0)
        reasons.append(f"tier: {spec.tier}")

        if spec.approval.startswith("approved"):
            score += 10
            reasons.append("approved for local measurement")
        else:
            score -= 20
            reasons.append("artifact still review-gated")

        if spec.tools and workload in {"agents", "coding", "tools"}:
            score += 12
            reasons.append("tool-call support")
        if "image" in spec.modalities and multimodal:
            score += 10
            reasons.append("multimodal")
        if spec.cpu_offload == "required":
            score -= 18
            reasons.append("CPU offload required")
        elif spec.cpu_offload == "optional":
            score -= 4
            reasons.append("CPU offload may be needed")
        if not spec.artifact:
            score -= 12
            reasons.append("no pinned runtime artifact")

        recommendations.append(
            ModelRecommendation(
                alias=spec.alias,
                score=score,
                fit=fit,
                runtime=spec.runtime,
                tier=spec.tier,
                artifact=spec.artifact,
                reasons=tuple(reasons),
            )
        )
    return tuple(sorted(recommendations, key=lambda item: (-item.score, item.alias)))


def select_default_model(
    settings: Settings,
    alias: str,
    *,
    execute: bool,
    allow_experimental: bool = False,
) -> ModelSelection:
    spec = get_model(settings, alias)
    if not spec.enabled:
        raise ModelRegistryError(f"{alias} is disabled in the model registry")
    if spec.experimental and not allow_experimental:
        raise ModelRegistryError(
            f"{alias} is experimental; pass the explicit experimental override to select it"
        )
    if not settings.env_file.is_file():
        raise ModelRegistryError(f"{settings.env_file} does not exist. Run `serveshed init` first.")

    values = parse_env_file(settings.env_file)
    previous = values.get("SERVESHED_DEFAULT_MODEL_ALIAS", settings.default_model_alias)
    changed = previous != alias
    backup: Path | None = None
    if execute and changed:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup = settings.env_file.with_name(
            f"{settings.env_file.name}.bak-model-{stamp}-{secrets.token_hex(2)}"
        )
        shutil.copy2(settings.env_file, backup)
        rendered = update_env_text(
            settings.env_file.read_text(encoding="utf-8"),
            {"SERVESHED_DEFAULT_MODEL_ALIAS": alias},
        )
        settings.env_file.write_text(rendered, encoding="utf-8")
        settings.env_file.chmod(0o600)
    return ModelSelection(
        env_file=settings.env_file,
        previous_alias=previous,
        selected_alias=alias,
        changed=changed,
        executed=execute,
        backup_file=backup,
    )


def pull_model(
    settings: Settings,
    manager: ComposeManager,
    alias: str,
    *,
    approved: bool,
) -> ModelSpec:
    spec = get_model(settings, alias)
    if not approved:
        raise ModelRegistryError("Model download was not explicitly approved")
    if not spec.pullable:
        raise ModelRegistryError(
            f"{alias} is not approved for an Ollama pull; status is {spec.approval!r}"
        )
    free = free_disk_gib(settings.data_dir)
    if spec.approximate_disk_gib is not None:
        required = spec.approximate_disk_gib + max(5.0, spec.approximate_disk_gib * 0.20)
        if free < required:
            raise ModelRegistryError(
                f"Insufficient free disk: {free:.1f} GiB available; "
                f"approximately {required:.1f} GiB required with safety margin"
            )
    manager.pull_ollama(spec.artifact)
    return spec
