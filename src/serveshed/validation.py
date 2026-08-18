from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from serveshed.benchmarks import load_benchmark_cases
from serveshed.compose import ComposeManager
from serveshed.env import SECRET_KEYS, parse_env_file, placeholder_keys
from serveshed.evaluations import load_jsonl
from serveshed.models import ModelRegistry, load_registry
from serveshed.settings import Settings
from serveshed.shell import Runner


class ValidationStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class Finding:
    name: str
    status: ValidationStatus
    detail: str

    def as_dict(self) -> dict[str, str]:
        value = asdict(self)
        value["status"] = self.status.value
        return value


def _finding(name: str, ok: bool, success: str, failure: str) -> Finding:
    return Finding(
        name, ValidationStatus.PASS if ok else ValidationStatus.FAIL, success if ok else failure
    )


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalized_bifrost(config: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(config)
    client = normalized.get("client", {})
    client["disable_content_logging"] = "<content-control>"
    for plugin in normalized.get("plugins", []):
        if plugin.get("name") == "otel":
            plugin_config = plugin.setdefault("config", {})
            plugin_config["disable_content_logging"] = "<content-control>"
            plugin_config["disable_root_span_content"] = "<content-control>"
    return normalized


def _bifrost_aliases(config: dict[str, Any]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for provider in config.get("providers", {}).values():
        for key in provider.get("keys", []):
            aliases.update(
                {str(name): str(value) for name, value in key.get("aliases", {}).items()}
            )
    return aliases


def _bifrost_aliases_by_provider(config: dict[str, Any]) -> dict[str, dict[str, str]]:
    aliases: dict[str, dict[str, str]] = {}
    providers = config.get("providers", {})
    if not isinstance(providers, dict):
        return aliases
    for provider_name, provider in providers.items():
        provider_aliases: dict[str, str] = {}
        if not isinstance(provider, dict):
            continue
        for key in provider.get("keys", []):
            if not isinstance(key, dict):
                continue
            raw_aliases = key.get("aliases", {})
            if isinstance(raw_aliases, dict):
                provider_aliases.update(
                    {str(name): str(value) for name, value in raw_aliases.items()}
                )
        aliases[str(provider_name)] = provider_aliases
    return aliases


def _governance_model_errors(config: dict[str, Any]) -> list[str]:
    aliases_by_provider = _bifrost_aliases_by_provider(config)
    errors: list[str] = []
    governance = config.get("governance", {})
    virtual_keys = governance.get("virtual_keys", []) if isinstance(governance, dict) else []
    for virtual_key in virtual_keys:
        if not isinstance(virtual_key, dict):
            continue
        key_id = str(virtual_key.get("id", "<unknown>"))
        provider_configs = virtual_key.get("provider_configs", [])
        if not isinstance(provider_configs, list):
            continue
        for provider_config in provider_configs:
            if not isinstance(provider_config, dict):
                continue
            provider = str(provider_config.get("provider", ""))
            available = aliases_by_provider.get(provider, {})
            allowed = provider_config.get("allowed_models", [])
            if not isinstance(allowed, list):
                errors.append(f"{key_id}/{provider}: allowed_models is not a list")
                continue
            for alias in allowed:
                rendered = str(alias)
                if rendered not in available:
                    errors.append(f"{key_id}/{provider}: unknown alias {rendered}")
    return errors


def validate_repository(
    settings: Settings,
    *,
    docker: bool = False,
    runner: Runner | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    required = (
        "README.md",
        "compose.yaml",
        ".env.example",
        "pyproject.toml",
        "uv.lock",
        "config/bifrost/config.json",
        "config/bifrost/config.eval.json",
        "config/models/registry.yaml",
        "config/otel/collector.yaml",
        "config/postgres/init/10-create-databases.sh",
        "evals/datasets/smoke.jsonl",
        "evals/datasets/qwen.jsonl",
        "evals/promptfoo/promptfooconfig.yaml",
        "evals/benchmarks/interactive.jsonl",
        "evals/benchmarks/throughput.jsonl",
    )
    missing = [relative for relative in required if not (settings.root / relative).exists()]
    findings.append(
        _finding(
            "required-files",
            not missing,
            "All required scaffold files exist",
            f"Missing: {', '.join(missing)}",
        )
    )

    try:
        env = parse_env_file(settings.root / ".env.example")
        unresolved = set(placeholder_keys(env, keys=SECRET_KEYS))
        findings.append(
            _finding(
                "environment-template",
                set(SECRET_KEYS).issubset(unresolved),
                "Every generated secret is a placeholder in .env.example",
                f"Missing secret placeholders: {sorted(set(SECRET_KEYS) - unresolved)}",
            )
        )
    except Exception as exc:
        findings.append(Finding("environment-template", ValidationStatus.FAIL, str(exc)))

    registry: ModelRegistry | None = None
    try:
        registry = load_registry(settings)
        findings.append(
            Finding(
                "model-registry", ValidationStatus.PASS, f"Loaded {len(registry)} unique aliases"
            )
        )
        qwen_fast = registry.require("local/qwen-fast")
        qwen_quality = registry.require("local/qwen-quality")
        qwen_offload = registry.require("experimental/qwen38-offload")
        model_contract_ok = (
            registry.schema_version == 2
            and qwen_fast.runtime == "ollama"
            and qwen_fast.artifact == "qwen3.5:9b"
            and qwen_fast.local_context == 8192
            and qwen_fast.expected_disk_gib == 6.6
            and qwen_fast.tier == "daily"
            and qwen_quality.artifact == "qwen3.5:9b-q8_0"
            and qwen_offload.artifact == "qwen3.8:27b"
            and qwen_offload.cpu_offload == "required"
            and qwen_offload.experimental
        )
        findings.append(
            _finding(
                "model-fit-contract",
                model_contract_ok,
                "Daily, quality, and offload-only Qwen profiles match the 16 GB design",
                "Model registry drifted from the hardware-aware candidate matrix",
            )
        )
    except Exception as exc:
        findings.append(Finding("model-registry", ValidationStatus.FAIL, str(exc)))

    try:
        normal = _load_json(settings.root / "config/bifrost/config.json")
        evaluation = _load_json(settings.root / "config/bifrost/config.eval.json")
        findings.append(
            _finding(
                "bifrost-privacy-variant",
                _normalized_bifrost(normal) == _normalized_bifrost(evaluation),
                "Bifrost configs have no drift outside the normalized content-capture fields",
                "Bifrost normal and evaluation configs have unrelated drift",
            )
        )
        otel_plugins = [
            plugin
            for plugin in normal.get("plugins", [])
            if plugin.get("name") == "otel" and plugin.get("enabled")
        ]
        trace_type_ok = (
            len(otel_plugins) == 1
            and otel_plugins[0].get("config", {}).get("trace_type") == "genai_extension"
        )
        findings.append(
            _finding(
                "bifrost-otel-trace-format",
                trace_type_ok,
                "Bifrost uses the released OTel GenAI trace format",
                "Bifrost must use trace_type=genai_extension until OpenInference ships",
            )
        )
        unsupported_override_absent = all(
            "allow_per_request_content_storage_override" not in config.get("client", {})
            for config in (normal, evaluation)
        )
        findings.append(
            _finding(
                "bifrost-supported-content-fields",
                unsupported_override_absent,
                "Bifrost content controls use documented configuration fields",
                "Bifrost config contains an undocumented content-storage override",
            )
        )
        # Content capture is intentionally on in both configs — the earlier
        # normal-hides/eval-captures split was retired by explicit user
        # decision (ADR 0016): traces and the Postgres logs table are
        # treated as sensitive from here on, in exchange for actually being
        # able to read prompts/responses in Phoenix and Bifrost's own log
        # view. The two configs staying separate files (rather than one)
        # preserves the swap mechanism for any future difference that
        # isn't about content.
        normal_capture = not bool(normal.get("client", {}).get("disable_content_logging"))
        eval_capture = not bool(evaluation.get("client", {}).get("disable_content_logging"))
        findings.append(
            _finding(
                "bifrost-content-capture",
                normal_capture and eval_capture,
                "Content capture is intentionally on in both configs (ADR 0016)",
                "Bifrost content logging is not configured as intended — see ADR 0016",
            )
        )
        allowed = normal.get("client", {}).get("header_filter_config", {}).get("allowlist", [])
        headers_ok = bool(allowed) and all(str(item).startswith("x-bf-eh-") for item in allowed)
        findings.append(
            _finding(
                "bifrost-trace-headers",
                headers_ok,
                "Trace metadata uses allow-listed x-bf-eh-* headers",
                "Bifrost trace metadata allowlist is missing or uses the wrong prefix",
            )
        )
        if registry is not None:
            aliases = _bifrost_aliases(normal)
            expected_aliases = {
                spec.alias: spec.artifact
                for spec in registry.values()
                if spec.runtime == "ollama"
                and spec.artifact
                and spec.approval.startswith("approved")
            }
            findings.append(
                _finding(
                    "bifrost-model-aliases",
                    all(
                        aliases.get(alias) == artifact
                        for alias, artifact in expected_aliases.items()
                    ),
                    f"Bifrost maps all {len(expected_aliases)} approved Ollama artifacts",
                    "Model registry and Bifrost alias mappings differ",
                )
            )
            governance_errors = _governance_model_errors(normal)
            findings.append(
                _finding(
                    "bifrost-governance-models",
                    not governance_errors,
                    "Every virtual-key model permission resolves to a provider alias",
                    "; ".join(governance_errors),
                )
            )
            virtual_keys = {
                str(item.get("id")): item
                for item in normal.get("governance", {}).get("virtual_keys", [])
                if isinstance(item, dict)
            }
            access_contract = {
                "vk-hermes": ("ollama", "local/qwen-fast"),
                "vk-eval": ("vllm", "local/qwen-batch"),
                "vk-judge": ("ollama", "local/gemma-judge"),
                "vk-webui": ("ollama", "local/qwen-fast"),
            }
            missing_access: list[str] = []
            for key_id, (provider, required_alias) in access_contract.items():
                key = virtual_keys.get(key_id, {})
                provider_configs = key.get("provider_configs", []) if isinstance(key, dict) else []
                allowed = {
                    str(alias)
                    for item in provider_configs
                    if isinstance(item, dict) and item.get("provider") == provider
                    for alias in item.get("allowed_models", [])
                }
                if required_alias not in allowed:
                    missing_access.append(f"{key_id} lacks {provider}/{required_alias}")
            findings.append(
                _finding(
                    "bifrost-agent-access-contract",
                    not missing_access,
                    "Hermes, eval, and judge keys have their required model access",
                    "; ".join(missing_access),
                )
            )
    except Exception as exc:
        findings.append(Finding("bifrost-config", ValidationStatus.FAIL, str(exc)))

    compose_text = (settings.root / "compose.yaml").read_text(encoding="utf-8")
    compose_rules = {
        "localhost-only-ports": "127.0.0.1:${BIFROST_PORT" in compose_text
        and "127.0.0.1:${PHOENIX_PORT" in compose_text,
        "no-auto-restart": "restart:" not in compose_text,
        "no-floating-latest-tags": ":latest" not in compose_text,
        "no-docker-socket": "/var/run/docker.sock" not in compose_text,
        "two-gpu-services": compose_text.count("gpus: all") == 2,
        "no-egress-backend": 'enable_ip_masquerade: "false"' in compose_text
        and "internal: true" not in compose_text,
        "no-direct-ollama-port": "11434:11434" not in compose_text,
        "no-direct-vllm-port": "8000:8000" not in compose_text,
        "litellm-is-experimental": "profiles: [experimental]" in compose_text,
        "manual-profile-contract": "profiles: [chat]" in compose_text
        and "profiles: [eval]" in compose_text,
    }
    for name, ok in compose_rules.items():
        findings.append(
            _finding(name, ok, "Static Compose invariant holds", "Static Compose invariant failed")
        )

    promptfoo_chat = (settings.root / "evals/promptfoo/promptfooconfig.yaml").read_text(
        encoding="utf-8"
    )
    promptfoo_batch = (settings.root / "evals/promptfoo/promptfooconfig.batch.yaml").read_text(
        encoding="utf-8"
    )
    findings.append(
        _finding(
            "promptfoo-model-aliases",
            "ollama/local/qwen-fast" in promptfoo_chat
            and "vllm/local/qwen-batch" in promptfoo_batch
            and "local/batch" not in promptfoo_batch,
            "Promptfoo uses the daily and batch gateway aliases",
            "Promptfoo model aliases drifted from the model registry",
        )
    )

    litellm_text = (settings.root / "config/litellm/config.yaml").read_text(encoding="utf-8")
    litellm_active = "\n".join(
        line for line in litellm_text.splitlines() if not line.lstrip().startswith("#")
    ).lower()
    findings.append(
        _finding(
            "no-gateway-chaining",
            "bifrost" not in litellm_active,
            "Experimental LiteLLM is not chained through Bifrost",
            "LiteLLM active configuration references Bifrost",
        )
    )

    for suite in ("smoke", "qwen"):
        try:
            cases = load_jsonl(settings.root / "evals" / "datasets" / f"{suite}.jsonl")
            findings.append(
                Finding(f"eval-{suite}", ValidationStatus.PASS, f"Loaded {len(cases)} valid cases")
            )
        except Exception as exc:
            findings.append(Finding(f"eval-{suite}", ValidationStatus.FAIL, str(exc)))

    for suite in ("interactive", "throughput"):
        try:
            cases = load_benchmark_cases(settings.root / "evals" / "benchmarks" / f"{suite}.jsonl")
            findings.append(
                Finding(
                    f"benchmark-{suite}",
                    ValidationStatus.PASS,
                    f"Loaded {len(cases)} valid cases",
                )
            )
        except Exception as exc:
            findings.append(Finding(f"benchmark-{suite}", ValidationStatus.FAIL, str(exc)))

    init_scripts = sorted((settings.root / "config" / "postgres" / "init").glob("*.sh"))
    findings.append(
        _finding(
            "postgres-init-single-source",
            [path.name for path in init_scripts] == ["10-create-databases.sh"],
            "One idempotent PostgreSQL initialization script is present",
            f"Unexpected init scripts: {[path.name for path in init_scripts]}",
        )
    )

    gitignore = (settings.root / ".gitignore").read_text(encoding="utf-8")
    findings.append(
        _finding(
            "secrets-ignored",
            "\n.env\n" in f"\n{gitignore}" and ".env.*" in gitignore,
            "Local environment files are ignored",
            ".gitignore does not protect local environment files",
        )
    )

    if docker:
        try:
            ComposeManager(settings, runner=runner or Runner()).validate(use_example_env=True)
            findings.append(
                Finding(
                    "docker-compose-render", ValidationStatus.PASS, "Docker parsed all profiles"
                )
            )
        except Exception as exc:
            findings.append(Finding("docker-compose-render", ValidationStatus.FAIL, str(exc)))
    else:
        findings.append(
            Finding(
                "docker-compose-render",
                ValidationStatus.WARN,
                "Skipped; pass --docker on Ubuntu for authoritative Compose parsing",
            )
        )
    return findings
