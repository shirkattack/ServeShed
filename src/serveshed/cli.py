from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from serveshed import __version__, banner
from serveshed.acceptance import (
    AcceptanceThresholds,
    ModelAcceptanceError,
    assess_model_candidate,
)
from serveshed.backup import execute_backup, initialize_nas, inspect_nas, plan_backup
from serveshed.benchmarks import (
    BenchmarkError,
    compare_benchmarks,
    plan_benchmark,
    run_benchmark,
)
from serveshed.compose import ComposeManager
from serveshed.doctor import CheckStatus, checks_as_dict, collect_doctor
from serveshed.env import EnvFileError, initialize_project
from serveshed.evaluations import (
    EvaluationError,
    compare_evaluations,
    plan_suite,
    run_suite,
)
from serveshed.hardware import primary_vram_gib
from serveshed.models import (
    ModelRegistryError,
    free_disk_gib,
    get_model,
    load_registry,
    model_rows,
    pull_model,
    recommend_models,
    select_default_model,
)
from serveshed.output import print_json, print_table
from serveshed.paths import ProjectRootError
from serveshed.runs import RunError, discover_runs, render_markdown_table, verify_run
from serveshed.settings import Settings
from serveshed.shell import CommandError, Runner
from serveshed.status import collect_status
from serveshed.tailscale import plan as tailscale_plan
from serveshed.validation import ValidationStatus, validate_repository


def _add_dry_run(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true", help="Print or describe actions only")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="serveshed",
        description="ServeShed — operate and evaluate the local-first LLM workstation safely.",
    )
    parser.add_argument("--root", type=Path, help="Repository root; auto-detected by default")
    parser.add_argument("--env-file", type=Path, help="Dotenv file; defaults to <root>/.env")
    parser.add_argument("--verbose", action="store_true", help="Print executed commands")
    parser.add_argument("--version", action="version", version=f"serveshed {__version__}")

    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser("init", help="Generate .env secrets and local directories")
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Fill unresolved placeholders without rotating existing valid secrets",
    )

    doctor_parser = commands.add_parser("doctor", help="Run read-only host readiness checks")
    doctor_parser.add_argument("--json", action="store_true")

    status_parser = commands.add_parser(
        "status", help="Show services, health, GPU, disk, and NAS state"
    )
    status_parser.add_argument("--json", action="store_true")

    up_parser = commands.add_parser("up", help="Start a safe Compose target")
    up_parser.add_argument("target", choices=("core", "chat", "eval"))
    up_parser.add_argument(
        "--eval-logging",
        action="store_true",
        help="Use the content-capturing Bifrost config for an explicit evaluation session",
    )
    _add_dry_run(up_parser)

    down_parser = commands.add_parser(
        "down", help="Stop the stack without deleting persistent data"
    )
    _add_dry_run(down_parser)

    gpu_parser = commands.add_parser("gpu-off", help="Unload models and stop both GPU runtimes")
    _add_dry_run(gpu_parser)
    gpu_parser.add_argument("--json", action="store_true")

    logs_parser = commands.add_parser("logs", help="Show Compose logs")
    logs_parser.add_argument("service", nargs="?", help="Optional service name")
    logs_parser.add_argument("--follow", action="store_true")
    logs_parser.add_argument("--tail", type=int, default=200)

    model_parser = commands.add_parser("model", help="Inspect or explicitly pull registered models")
    model_commands = model_parser.add_subparsers(dest="model_command", required=True)
    model_list = model_commands.add_parser("list", help="List model aliases")
    model_list.add_argument("--json", action="store_true")
    model_show = model_commands.add_parser("show", help="Show one model entry")
    model_show.add_argument("alias")
    model_show.add_argument("--json", action="store_true")
    model_pull = model_commands.add_parser("pull", help="Pull an approved Ollama artifact")
    model_pull.add_argument("alias")
    model_pull.add_argument("--yes", action="store_true", help="Approve the displayed download")
    _add_dry_run(model_pull)
    model_recommend = model_commands.add_parser(
        "recommend", help="Rank registered models against workload and GPU constraints"
    )
    model_recommend.add_argument("--vram-gib", type=float)
    model_recommend.add_argument(
        "--workload",
        default="general",
        choices=(
            "general",
            "agents",
            "coding",
            "tools",
            "multimodal",
            "evaluation",
            "batch",
            "judge",
            "rag",
        ),
    )
    model_recommend.add_argument("--runtime", choices=("ollama", "vllm"))
    model_recommend.add_argument("--multimodal", action="store_true")
    model_recommend.add_argument("--tools", action="store_true")
    model_recommend.add_argument("--include-experimental", action="store_true")
    model_recommend.add_argument("--limit", type=int, default=5)
    model_recommend.add_argument("--json", action="store_true")
    model_select = model_commands.add_parser(
        "select", help="Plan or update the default model alias in .env"
    )
    model_select.add_argument("alias")
    model_select.add_argument("--execute", action="store_true")
    model_select.add_argument("--allow-experimental", action="store_true")
    model_select.add_argument("--json", action="store_true")
    model_inventory = model_commands.add_parser(
        "inventory", help="Compare installed Ollama artifacts with the registry"
    )
    model_inventory.add_argument("--json", action="store_true")
    model_accept = model_commands.add_parser(
        "accept", help="Gate default-model promotion on verified eval and benchmark bundles"
    )
    model_accept.add_argument("--eval-run", required=True, type=Path)
    model_accept.add_argument("--benchmark-run", required=True, type=Path)
    model_accept.add_argument("--min-pass-rate", type=float, default=1.0)
    model_accept.add_argument("--min-success-rate", type=float, default=1.0)
    model_accept.add_argument("--min-tokens-per-second", type=float, default=0.0)
    model_accept.add_argument("--max-median-latency-ms", type=float)
    model_accept.add_argument("--max-p95-latency-ms", type=float)
    model_accept.add_argument("--promote", action="store_true")
    model_accept.add_argument("--allow-experimental", action="store_true")
    model_accept.add_argument("--json", action="store_true")

    eval_parser = commands.add_parser("eval", help="Plan or run evaluation workflows")
    eval_commands = eval_parser.add_subparsers(dest="eval_command", required=True)
    for suite in ("smoke", "qwen"):
        suite_parser = eval_commands.add_parser(suite, help=f"Plan or run the {suite} suite")
        suite_parser.add_argument("--model", help="Registry alias or provider/model identifier")
        suite_parser.add_argument("--limit", type=int)
        suite_parser.add_argument("--timeout", type=float, default=900.0)
        suite_parser.add_argument("--dry-run", action="store_true", help="Validate cases only")
        suite_parser.add_argument("--json", action="store_true")
    promptfoo = eval_commands.add_parser("promptfoo", help="Run the containerized Promptfoo suite")
    promptfoo.add_argument("--runtime", choices=("chat", "eval"), default="chat")
    promptfoo.add_argument("--output", help="Result filename under eval-runs/promptfoo")
    _add_dry_run(promptfoo)
    eval_commands.add_parser("inspect-plan", help="Show the uv-based Inspect AI integration plan")
    eval_commands.add_parser("lm-eval-plan", help="Show the uv-based lm-eval integration plan")
    eval_compare = eval_commands.add_parser(
        "compare", help="Compare two or more completed evaluation bundles"
    )
    eval_compare.add_argument("run_dirs", nargs="+", type=Path)
    eval_compare.add_argument("--json", action="store_true")

    benchmark_parser = commands.add_parser(
        "benchmark", help="Measure full-path latency and token throughput"
    )
    benchmark_commands = benchmark_parser.add_subparsers(dest="benchmark_command", required=True)
    benchmark_plan = benchmark_commands.add_parser("plan", help="Validate a benchmark plan")
    benchmark_plan.add_argument("suite", nargs="?", default="interactive")
    benchmark_plan.add_argument("--repetitions", type=int, default=3)
    benchmark_plan.add_argument("--warmup", type=int, default=1)
    benchmark_plan.add_argument("--limit", type=int)
    benchmark_plan.add_argument("--json", action="store_true")
    benchmark_run = benchmark_commands.add_parser("run", help="Run a benchmark through Bifrost")
    benchmark_run.add_argument("suite", nargs="?", default="interactive")
    benchmark_run.add_argument("--model")
    benchmark_run.add_argument("--repetitions", type=int, default=3)
    benchmark_run.add_argument("--warmup", type=int, default=1)
    benchmark_run.add_argument("--limit", type=int)
    benchmark_run.add_argument("--timeout", type=float, default=900.0)
    benchmark_run.add_argument("--dry-run", action="store_true")
    benchmark_run.add_argument("--json", action="store_true")
    benchmark_compare = benchmark_commands.add_parser(
        "compare", help="Compare two or more completed benchmark bundles"
    )
    benchmark_compare.add_argument("run_dirs", nargs="+", type=Path)
    benchmark_compare.add_argument("--json", action="store_true")

    runs_parser = commands.add_parser("runs", help="Discover and verify stored run bundles")
    runs_commands = runs_parser.add_subparsers(dest="runs_command", required=True)
    runs_list = runs_commands.add_parser("list", help="List recent evaluation and benchmark runs")
    runs_list.add_argument("--kind", choices=("evaluation", "benchmark", "model-acceptance"))
    runs_list.add_argument("--suite")
    runs_list.add_argument("--model")
    runs_list.add_argument("--limit", type=int, default=20)
    runs_list.add_argument("--json", action="store_true")
    runs_list.add_argument("--markdown", action="store_true")
    runs_verify = runs_commands.add_parser("verify", help="Verify a run checksum manifest")
    runs_verify.add_argument("run_dir", type=Path)
    runs_verify.add_argument("--json", action="store_true")

    tailscale_parser = commands.add_parser("tailscale", help="Plan Tailscale-only remote access")
    tailscale_commands = tailscale_parser.add_subparsers(dest="tailscale_command", required=True)
    tailscale_show = tailscale_commands.add_parser(
        "plan", help="Print commands without applying them"
    )
    tailscale_show.add_argument("--json", action="store_true")

    nas_parser = commands.add_parser("nas", help="Inspect or initialize the future Synology mount")
    nas_commands = nas_parser.add_subparsers(dest="nas_command", required=True)
    nas_status = nas_commands.add_parser("status", help="Check mount and guard marker")
    nas_status.add_argument("--json", action="store_true")
    nas_init = nas_commands.add_parser(
        "init", help="Create the guard marker and archive directories"
    )
    nas_init.add_argument(
        "--execute", action="store_true", help="Write only after mount validation"
    )
    nas_init.add_argument("--json", action="store_true")

    backup_parser = commands.add_parser("backup", help="Plan or execute a fail-closed NAS backup")
    backup_parser.add_argument("--execute", action="store_true")
    backup_parser.add_argument("--json", action="store_true")

    config_parser = commands.add_parser("config", help="Validate repository contracts")
    config_commands = config_parser.add_subparsers(dest="config_command", required=True)
    config_validate = config_commands.add_parser("validate", help="Run static validation")
    config_validate.add_argument(
        "--docker", action="store_true", help="Also render with Docker Compose"
    )
    config_validate.add_argument("--json", action="store_true")
    return parser


def _settings(args: argparse.Namespace) -> Settings:
    return Settings.load(root=args.root, env_file=args.env_file)


def _runner(args: argparse.Namespace, *, dry_run: bool = False) -> Runner:
    return Runner(dry_run=dry_run, verbose=bool(args.verbose))


def _run_init(args: argparse.Namespace) -> int:
    settings = _settings(args)
    result = initialize_project(settings.root, env_file=settings.env_file, force=args.force)
    print(f"Environment: {result.env_file}")
    print(f"Phoenix SDK environment: {result.phoenix_env_file}")
    print(f"Created .env: {'yes' if result.created_env else 'no'}")
    if result.backup_file:
        print(f"Backup: {result.backup_file}")
    if result.updated_keys:
        print(f"Initialized values: {len(result.updated_keys)} (values not displayed)")
    if result.created_directories:
        print("Created directories:")
        for path in result.created_directories:
            print(f"  {path}")
    else:
        print("Local directories already exist.")
    print("No packages, containers, models, mounts, or Tailscale settings were changed.")
    return 0


def _run_doctor(args: argparse.Namespace) -> int:
    checks = collect_doctor(_settings(args), runner=_runner(args))
    if args.json:
        print_json(checks_as_dict(checks))
    else:
        print_table(
            ("CHECK", "STATUS", "SUMMARY", "DETAIL"),
            ((item.name, item.status.value, item.summary, item.detail) for item in checks),
        )
    return 1 if any(item.status is CheckStatus.FAIL for item in checks) else 0


def _run_status(args: argparse.Namespace) -> int:
    payload = collect_status(_settings(args), runner=_runner(args))
    if args.json:
        print_json(payload)
        return 0
    print("Service probes")
    print_table(
        ("SERVICE", "OK", "ENDPOINT", "STATUS", "DETAIL"),
        (
            (
                probe["service"],
                "yes" if probe["ok"] else "no",
                probe["endpoint"],
                probe["status"],
                probe["detail"],
            )
            for probe in payload["health"]
        ),
    )
    print("\nCompose services")
    if payload["services"]:
        print_table(
            ("SERVICE", "STATE", "HEALTH", "IMAGE"),
            (
                (
                    row.get("Service") or row.get("Name", ""),
                    row.get("State", ""),
                    row.get("Health", ""),
                    row.get("Image", ""),
                )
                for row in payload["services"]
            ),
        )
    else:
        print(payload.get("compose_error") or "No serveshed containers are running.")
    print("\nActive Ollama models")
    if payload["ollama_processes"]:
        print_table(
            ("MODEL", "ID", "SIZE", "PROCESSOR", "UNTIL"),
            (
                (
                    row["name"],
                    row["model_id"],
                    row["size"],
                    row["processor"],
                    row["until"],
                )
                for row in payload["ollama_processes"]
            ),
        )
    else:
        print("No loaded Ollama model was reported.")
    print("\nGPU")
    print(payload["hardware"].get("nvidia_smi") or "nvidia-smi unavailable")
    print("\nSynology")
    print(f"{payload['nas']['reason']}: {payload['nas']['path']}")
    return 0


def _run_up(args: argparse.Namespace) -> int:
    settings = _settings(args)
    manager = ComposeManager(settings, runner=_runner(args, dry_run=args.dry_run))
    manager.up(args.target, eval_logging=args.eval_logging)
    if args.dry_run and args.target == "eval" and not settings.vllm_enabled:
        print(
            "Note: the real eval start stays blocked until vLLM is explicitly reviewed and enabled."
        )
    elif not args.dry_run:
        try:
            rig = banner.build_rig(
                settings,
                manager,
                target=args.target,
                eval_logging=args.eval_logging or args.target == "eval",
            )
            print(banner.render(rig))
        except Exception as exc:  # the banner must never undo a successful start
            print(f"Started target: {args.target} (banner unavailable: {exc})")
    return 0


def _run_down(args: argparse.Namespace) -> int:
    ComposeManager(_settings(args), runner=_runner(args, dry_run=args.dry_run)).down()
    if not args.dry_run:
        print("Stopped serveshed containers. Persistent data was not deleted.")
    return 0


def _run_gpu_off(args: argparse.Namespace) -> int:
    report = ComposeManager(_settings(args), runner=_runner(args, dry_run=args.dry_run)).gpu_off()
    if args.json:
        print_json(report.as_dict())
    else:
        print(f"Unloaded models: {', '.join(report.unloaded_models) or 'none detected'}")
        print(f"Stopped services: {', '.join(report.stopped_services) or 'none'}")
        if report.gpu_memory:
            print(f"GPU after stop: {report.gpu_memory}")
    return 0


def _run_logs(args: argparse.Namespace) -> int:
    if args.tail < 1:
        raise RuntimeError("--tail must be at least 1")
    ComposeManager(_settings(args), runner=_runner(args)).logs(
        args.service, follow=args.follow, tail=args.tail
    )
    return 0


def _run_model(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if args.model_command == "list":
        registry = load_registry(settings)
        if args.json:
            print_json([record.as_dict() for record in registry.values()])
        else:
            print_table(
                ("ALIAS", "TIER", "RUNTIME", "ARTIFACT", "DISK", "APPROVAL"),
                model_rows(registry),
            )
        return 0

    if args.model_command == "recommend":
        if args.limit < 1:
            raise ModelRegistryError("--limit must be at least 1")
        vram = args.vram_gib
        source = "explicit"
        if vram is None:
            vram = primary_vram_gib(runner=_runner(args))
            source = "nvidia-smi"
        if vram is None:
            vram = settings.target_vram_gib
            source = "configured target"
        if vram <= 0:
            raise ModelRegistryError("VRAM must be greater than zero")
        recommendations = recommend_models(
            load_registry(settings),
            vram_gib=vram,
            workload=args.workload,
            runtime=args.runtime,
            multimodal=args.multimodal,
            tools=args.tools,
            include_experimental=args.include_experimental,
        )[: args.limit]
        payload = {
            "vram_gib": vram,
            "vram_source": source,
            "workload": args.workload,
            "recommendations": [item.as_dict() for item in recommendations],
        }
        if args.json:
            print_json(payload)
        else:
            print(f"VRAM: {vram:.1f} GiB ({source})")
            print(f"Workload: {args.workload}")
            if recommendations:
                print_table(
                    ("ALIAS", "SCORE", "FIT", "RUNTIME", "TIER", "WHY"),
                    (
                        (
                            item.alias,
                            str(item.score),
                            item.fit,
                            item.runtime,
                            item.tier,
                            "; ".join(item.reasons),
                        )
                        for item in recommendations
                    ),
                )
            else:
                print("No registered models match the requested constraints.")
        return 0

    if args.model_command == "inventory":
        registry = load_registry(settings)
        installed = ComposeManager(settings, runner=_runner(args)).ollama_inventory()
        aliases_by_artifact: dict[str, list[str]] = {}
        for spec in registry.values():
            if spec.runtime == "ollama" and spec.artifact:
                aliases_by_artifact.setdefault(spec.artifact, []).append(spec.alias)
        rows: list[dict[str, Any]] = [
            {
                **model.as_dict(),
                "aliases": aliases_by_artifact.get(model.name, []),
                "registered": model.name in aliases_by_artifact,
            }
            for model in installed
        ]
        if args.json:
            print_json(rows)
        elif rows:
            print_table(
                ("ARTIFACT", "ID", "SIZE", "MODIFIED", "ALIASES"),
                (
                    (
                        str(row["name"]),
                        str(row["model_id"]),
                        str(row["size"]),
                        str(row["modified"]),
                        ", ".join(row["aliases"]) or "unregistered",
                    )
                    for row in rows
                ),
            )
        else:
            print("No installed Ollama models were reported.")
        return 0

    if args.model_command == "accept":
        decision = assess_model_candidate(
            settings,
            evaluation_run=args.eval_run,
            benchmark_run=args.benchmark_run,
            thresholds=AcceptanceThresholds(
                min_pass_rate=args.min_pass_rate,
                min_success_rate=args.min_success_rate,
                min_completion_tokens_per_second=args.min_tokens_per_second,
                max_median_latency_ms=args.max_median_latency_ms,
                max_p95_latency_ms=args.max_p95_latency_ms,
            ),
            promote=args.promote,
            allow_experimental=args.allow_experimental,
        )
        if args.json:
            print_json(decision.as_dict())
        else:
            print(f"Model: {decision.model}")
            print(f"Decision: {'ACCEPTED' if decision.accepted else 'REJECTED'}")
            print_table(
                ("CHECK", "PASS", "OBSERVED", "REQUIREMENT", "DETAIL"),
                (
                    (
                        check.name,
                        "yes" if check.passed else "no",
                        str(check.observed),
                        str(check.requirement),
                        check.detail,
                    )
                    for check in decision.checks
                ),
            )
            print(f"Decision bundle: {decision.run_dir}")
            if decision.promoted:
                print(f"Promoted {decision.model} as the default model.")
            elif args.promote and not decision.accepted:
                print("Promotion was requested but blocked by the acceptance gate.")
        return 0 if decision.accepted else 1

    if args.model_command == "select":
        selection = select_default_model(
            settings,
            args.alias,
            execute=args.execute,
            allow_experimental=args.allow_experimental,
        )
        if args.json:
            print_json(selection.as_dict())
        else:
            action = "Updated" if selection.executed and selection.changed else "Planned"
            print(f"{action}: {selection.previous_alias} -> {selection.selected_alias}")
            print(f"Environment: {selection.env_file}")
            if selection.backup_file:
                print(f"Backup: {selection.backup_file}")
            if not args.execute:
                print("No file was changed. Pass --execute to update the default alias.")
        return 0

    record = get_model(settings, args.alias)
    if args.model_command == "show":
        if args.json:
            print_json(record.as_dict())
        else:
            for key, value in record.as_dict().items():
                print(f"{key}: {value}")
        return 0

    free = free_disk_gib(settings.data_dir)
    print(f"Alias: {record.alias}")
    print(f"Artifact: {record.artifact or 'not selected'}")
    print(f"Expected download: {record.expected_disk_gib or 'unknown'} GiB")
    print(f"Free disk at data directory: {free:.1f} GiB")
    print(f"Approval: {record.approval}")
    print(f"Expected CPU offload: {record.cpu_offload}")
    approved = bool(args.yes)
    if not approved and not args.dry_run:
        if not sys.stdin.isatty():
            raise ModelRegistryError("Use --yes for an explicit non-interactive model pull")
        approved = input("Type the exact alias to approve the pull: ").strip() == record.alias
    if args.dry_run:
        print("Dry-run: no container was started and no model was downloaded.")
        return 0
    pulled = pull_model(
        settings,
        ComposeManager(settings, runner=_runner(args)),
        record.alias,
        approved=approved,
    )
    print(f"Pulled {pulled.artifact}. Run evaluation and benchmark suites before accepting it.")
    return 0


def _run_eval(args: argparse.Namespace) -> int:
    settings = _settings(args)
    command = args.eval_command
    if command in {"smoke", "qwen"}:
        model = args.model or settings.default_model_alias
        if args.dry_run:
            payload = plan_suite(settings, command, limit=args.limit)
            payload["model"] = model
            payload["network_requests"] = 0
            if args.json:
                print_json(payload)
            else:
                print(f"Suite: {payload['suite']}")
                print(f"Dataset: {payload['dataset']}")
                print(f"Cases: {payload['case_count']}")
                print_table(
                    ("CASE", "ASSERTIONS"),
                    ((case["id"], ", ".join(case["assertion_types"])) for case in payload["cases"]),
                )
            return 0

        runtime = "chat"
        registered = load_registry(settings).get(model)
        if registered and registered.runtime == "vllm":
            runtime = "eval"
        ComposeManager(settings, runner=_runner(args)).up(runtime, eval_logging=True)
        run_dir = run_suite(
            settings,
            command,
            model=model,
            limit=args.limit,
            timeout=args.timeout,
        )
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        if args.json:
            print_json({"run_dir": str(run_dir), "summary": summary})
        else:
            print(f"Evaluation bundle: {run_dir}")
            print(
                f"Passed {summary['passed']}/{summary['cases']} "
                f"({summary['pass_rate']:.1%}); mean latency {summary['mean_latency_ms']:.1f} ms"
            )
        return 1 if summary["failed"] else 0

    if command == "compare":
        payload = compare_evaluations([path.resolve() for path in args.run_dirs])
        if args.json:
            print_json(payload)
        else:
            print(f"Suite: {payload['suite']}")
            print_table(
                ("MODEL", "PASS RATE", "MEDIAN", "P95", "TOKENS/S", "RUN"),
                (
                    (
                        str(row["model"]),
                        f"{float(row['pass_rate']):.1%}",
                        f"{float(row['median_latency_ms']):.1f} ms",
                        f"{float(row['p95_latency_ms']):.1f} ms",
                        f"{float(row['mean_completion_tokens_per_second']):.2f}",
                        str(row["run_id"]),
                    )
                    for row in payload["runs"]
                ),
            )
        return 0

    if command == "promptfoo":
        output_name = (
            args.output or f"promptfoo-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        manager = ComposeManager(settings, runner=_runner(args, dry_run=args.dry_run))
        result, output = manager.run_promptfoo(runtime=args.runtime, output_name=output_name)
        if args.dry_run:
            print(f"Dry-run result path: {output}")
            print(f"Last command: {result.display}")
        else:
            print(f"Promptfoo result: {output}")
        return 0

    if command == "inspect-plan":
        print("Inspect AI integration plan (not executed):")
        print("  1. Pin inspect-ai with `uv add --group eval inspect-ai` after host review.")
        print("  2. Point the OpenAI-compatible adapter at Bifrost, never directly at Ollama.")
        print("  3. Run evals/inspect/smoke.py with BIFROST_VK_EVAL.")
        print("  4. Export experiment and case metadata as x-bf-eh-* headers.")
        return 0

    if command == "lm-eval-plan":
        print("lm-evaluation-harness integration plan (not executed):")
        print("  1. Pin lm-eval in an isolated uv dependency group.")
        print("  2. Use vLLM only after the candidate model is reviewed and enabled.")
        print("  3. Save raw generations before judge or aggregate scoring.")
        print("  4. Import summaries into the immutable eval-run convention.")
        return 0
    raise RuntimeError(f"Unsupported eval command {command!r}")


def _run_benchmark(args: argparse.Namespace) -> int:
    settings = _settings(args)
    command = args.benchmark_command
    if command == "plan":
        payload = plan_benchmark(
            settings,
            args.suite,
            repetitions=args.repetitions,
            warmup=args.warmup,
            limit=args.limit,
        )
        if args.json:
            print_json(payload)
        else:
            print(f"Suite: {payload['suite']}")
            print(f"Dataset: {payload['dataset']}")
            print(f"Cases: {payload['case_count']}")
            print(f"Network requests: {payload['network_requests']}")
            print_table(
                ("CASE", "TAGS", "PARAMETERS"),
                (
                    (
                        str(case["id"]),
                        ", ".join(case["tags"]),
                        json.dumps(case["parameters"], sort_keys=True),
                    )
                    for case in payload["cases"]
                ),
            )
        return 0

    if command == "compare":
        payload = compare_benchmarks([path.resolve() for path in args.run_dirs])
        if args.json:
            print_json(payload)
        else:
            print(f"Suite: {payload['suite']}")
            print_table(
                ("MODEL", "SUCCESS", "MEDIAN", "P95", "TOKENS/S", "RUN"),
                (
                    (
                        str(row["model"]),
                        f"{float(row['success_rate']):.1%}",
                        f"{float(row['median_latency_ms']):.1f} ms",
                        f"{float(row['p95_latency_ms']):.1f} ms",
                        f"{float(row['mean_completion_tokens_per_second']):.2f}",
                        str(row["run_id"]),
                    )
                    for row in payload["runs"]
                ),
            )
        return 0

    model = args.model or settings.default_model_alias
    if args.dry_run:
        payload = plan_benchmark(
            settings,
            args.suite,
            repetitions=args.repetitions,
            warmup=args.warmup,
            limit=args.limit,
        )
        payload["model"] = model
        if args.json:
            print_json(payload)
        else:
            print(f"Dry-run benchmark: {args.suite} on {model}")
            print(f"Cases: {payload['case_count']}; requests: {payload['network_requests']}")
        return 0

    runtime = "chat"
    registered = load_registry(settings).get(model)
    if registered and registered.runtime == "vllm":
        runtime = "eval"
    ComposeManager(settings, runner=_runner(args)).up(runtime, eval_logging=True)
    run_dir = run_benchmark(
        settings,
        args.suite,
        model=model,
        repetitions=args.repetitions,
        warmup=args.warmup,
        limit=args.limit,
        timeout=args.timeout,
    )
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    if args.json:
        print_json({"run_dir": str(run_dir), "summary": summary})
    else:
        print(f"Benchmark bundle: {run_dir}")
        print(
            f"Success {summary['successful_samples']}/{summary['recorded_samples']}; "
            f"median {summary['median_latency_ms']:.1f} ms; "
            f"mean {summary['mean_completion_tokens_per_second']:.2f} completion tokens/s"
        )
    return 1 if summary["failed_samples"] else 0


def _run_runs(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if args.runs_command == "list":
        records = discover_runs(
            settings.eval_runs_dir,
            kind=args.kind,
            suite=args.suite,
            model=args.model,
            limit=args.limit,
        )
        if args.json:
            print_json([record.as_dict() for record in records])
        elif args.markdown:
            print(render_markdown_table(records), end="")
        elif records:
            print_table(
                ("KIND", "SUITE", "MODEL", "SCORE", "MEDIAN", "RUN"),
                (
                    (
                        record.kind,
                        record.suite,
                        record.model,
                        f"{record.score_name}={record.score:.3f}",
                        f"{record.median_latency_ms:.1f} ms",
                        record.run_id,
                    )
                    for record in records
                ),
            )
        else:
            print("No stored runs matched the filters.")
        return 0

    results = verify_run(args.run_dir.resolve())
    if args.json:
        print_json(results)
    else:
        print_table(
            ("FILE", "OK", "DETAIL"),
            (
                (str(item["path"]), "yes" if item["ok"] else "no", str(item["detail"]))
                for item in results
            ),
        )
    return 1 if any(not bool(item["ok"]) for item in results) else 0


def _run_tailscale(args: argparse.Namespace) -> int:
    result = tailscale_plan(_settings(args), runner=_runner(args))
    if args.json:
        print_json(result.as_dict())
    else:
        print(f"Installed: {'yes' if result.installed else 'no'}")
        print(f"Status: {result.status}")
        print("Commands to review:")
        for command in result.commands:
            print(f"  {command}")
        print("Rollback:")
        for command in result.rollback:
            print(f"  {command}")
        print("Notes:")
        for note in result.notes:
            print(f"  - {note}")
    return 0


def _run_nas(args: argparse.Namespace) -> int:
    settings = _settings(args)
    state = (
        inspect_nas(settings)
        if args.nas_command == "status"
        else initialize_nas(settings, execute=args.execute)
    )
    if args.nas_command == "init" and not args.execute:
        print("Plan only: pass --execute after verifying the mount target.")
    if args.json:
        print_json(state.as_dict())
    else:
        print(f"Path: {state.path}")
        print(f"Mounted: {'yes' if state.mounted else 'no'}")
        print(f"Marker: {'present' if state.marker_present else 'absent'}")
        print(f"Ready: {'yes' if state.ready else 'no'}")
        print(f"Reason: {state.reason}")
    return 0


def _run_backup(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if not args.execute:
        plan = plan_backup(settings)
        if args.json:
            print_json(plan.as_dict())
        else:
            print(f"NAS: {plan.nas.reason}")
            print(f"Destination: {plan.destination or 'blocked'}")
            print("Includes:")
            for item in plan.includes:
                print(f"  - {item}")
            print("No files were written. Use --execute only after mount and marker verification.")
        return 0
    destination = execute_backup(
        settings,
        compose=ComposeManager(settings, runner=_runner(args)),
    )
    if args.json:
        print_json({"destination": str(destination)})
    else:
        print(f"Backup completed: {destination}")
    return 0


def _run_config(args: argparse.Namespace) -> int:
    findings = validate_repository(_settings(args), docker=args.docker, runner=_runner(args))
    if args.json:
        print_json([finding.as_dict() for finding in findings])
    else:
        print_table(
            ("CHECK", "STATUS", "DETAIL"),
            ((item.name, item.status.value, item.detail) for item in findings),
        )
    return 1 if any(item.status is ValidationStatus.FAIL for item in findings) else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "init": _run_init,
        "doctor": _run_doctor,
        "status": _run_status,
        "up": _run_up,
        "down": _run_down,
        "gpu-off": _run_gpu_off,
        "logs": _run_logs,
        "model": _run_model,
        "eval": _run_eval,
        "benchmark": _run_benchmark,
        "runs": _run_runs,
        "tailscale": _run_tailscale,
        "nas": _run_nas,
        "backup": _run_backup,
        "config": _run_config,
    }
    try:
        return handlers[args.command](args)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except (
        BenchmarkError,
        ModelAcceptanceError,
        CommandError,
        EnvFileError,
        EvaluationError,
        ModelRegistryError,
        ProjectRootError,
        RunError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
