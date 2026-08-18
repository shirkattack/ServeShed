#!/usr/bin/env python3
"""Generate the README's model matrix table from config/models/registry.yaml.

The registry is the single source of truth (docs/models.md); this
keeps the README from silently drifting out of sync with it. Status is
derived entirely from registry fields (tier, approval) — nothing here is
hand-typed prose that can go stale independently of the data.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from serveshed.models import ModelSpec, load_registry  # noqa: E402

BEGIN = "<!-- BEGIN GENERATED MODEL MATRIX (scripts/generate-model-matrix.py) -->"
END = "<!-- END GENERATED MODEL MATRIX -->"

RUNTIME_LABELS = {"ollama": "Ollama", "vllm": "vLLM"}


def runtime_label(runtime: str) -> str:
    return RUNTIME_LABELS.get(runtime, runtime.capitalize())


def status_label(spec: ModelSpec, *, default_alias: str) -> str:
    parts: list[str] = []
    if spec.tier == "experimental":
        parts.append("Experimental")
    if spec.approval == "not-approved":
        parts.append("Review-gated")
    elif spec.approval == "approved-for-measurement-only":
        parts.append("Measurement approved")
    else:
        parts.append(spec.approval)
    label = ", ".join(parts)
    if spec.alias == default_alias:
        label += " — **default**"
    return label


def render_table(registry_path: Path, *, default_alias: str) -> str:
    registry = load_registry(registry_path)
    lines = [
        "| Alias | Runtime | Role | Status |",
        "|---|---|---|---|",
    ]
    for spec in registry.values():
        lines.append(
            f"| `{spec.alias}` | {runtime_label(spec.runtime)} | {spec.purpose} | "
            f"{status_label(spec, default_alias=default_alias)} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--readme", type=Path, default=ROOT / "README.md")
    parser.add_argument(
        "--registry", type=Path, default=ROOT / "config" / "models" / "registry.yaml"
    )
    parser.add_argument("--default-alias", default="local/qwen-fast")
    args = parser.parse_args()

    table = render_table(args.registry, default_alias=args.default_alias)
    readme_text = args.readme.read_text(encoding="utf-8")

    if BEGIN not in readme_text or END not in readme_text:
        raise SystemExit(f"Markers {BEGIN!r}/{END!r} not found in {args.readme}")

    before, rest = readme_text.split(BEGIN, 1)
    _, after = rest.split(END, 1)
    rendered = f"{before}{BEGIN}\n{table}\n{END}{after}"

    if args.check:
        if rendered != readme_text:
            raise SystemExit(
                f"{args.readme} model matrix is stale; run "
                "`uv run python scripts/generate-model-matrix.py`"
            )
        print("PASS README model matrix matches config/models/registry.yaml")
        return 0

    args.readme.write_text(rendered, encoding="utf-8")
    print(f"Wrote model matrix into {args.readme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
