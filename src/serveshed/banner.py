"""Startup banner for `serveshed up`.

Standard library only — no third-party runtime dependency, consistent with
the rest of the control plane.

Two probing rules the layout depends on:

  1. Anything that changes between runs, or that can fail silently, gets a
     permanent line. Anything static belongs in the README, not here.
  2. Degraded conditions are the only things allowed to appear conditionally.
     A quiet banner means nothing is wrong — that is the whole signal.

Ollama's /api/ps is queried for control-plane introspection only. This is
not an inference path and does not bypass the one-door rule; no completion
ever leaves this module.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from serveshed.compose import ComposeManager
    from serveshed.settings import Settings

# ── ansi ───────────────────────────────────────────────────────────────
RESET, BOLD = "\x1b[0m", "\x1b[1m"


def _rgb(hexcode: str) -> str:
    r, g, b = (int(hexcode[i : i + 2], 16) for i in (1, 3, 5))
    return f"\x1b[38;2;{r};{g};{b}m"


LAMP = _rgb("#e8a33d")  # the shed's worklight
INK = _rgb("#d4d4d8")
CHROME = _rgb("#6b7280")
LIVE = _rgb("#4ade80")
WARM = _rgb("#fbbf24")
DEAD = _rgb("#f87171")

COLOUR = (
    not os.environ.get("NO_COLOR")
    and os.environ.get("TERM") not in (None, "dumb")
    and sys.stdout.isatty()
)


def c(text: str, *styles: str) -> str:
    return f"{''.join(styles)}{text}{RESET}" if COLOUR and styles else text


def link(url: str) -> str:
    return f"\x1b]8;;{url}\x1b\\{url}\x1b]8;;\x1b\\" if COLOUR else url


def plain_len(text: str) -> int:
    """Visible length, ignoring both SGR colour codes and OSC 8 hyperlinks.

    The two escape kinds terminate differently and must be told apart: SGR
    (`\\x1b[...m`, the only CSI shape this module emits) ends at the first
    literal `m`; OSC 8 (`\\x1b]8;;URL\\x1b\\`) ends at the two-character ST
    sequence `\\x1b\\`, not at the first bare backslash. Scanning for "the
    first m or backslash" — the previous approach — undercounts real
    hyperlinks whenever the URL itself contains either character (any
    ".com"/".io"/etc. domain has an "m"), corrupting header/column padding.
    """
    out, i = 0, 0
    while i < len(text):
        if text[i] == "\x1b" and i + 1 < len(text) and text[i + 1] == "]":
            end = text.find("\x1b\\", i)
            i = (end + 2) if end != -1 else len(text)
        elif text[i] == "\x1b":
            end = i + 1
            while end < len(text) and text[end] != "m":
                end += 1
            i = end + 1
        else:
            out += 1
            i += 1
    return out


# ── data ───────────────────────────────────────────────────────────────
@dataclass
class Service:
    name: str
    port: int
    note: str = ""
    host: str = "127.0.0.1"

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def listening(self, timeout: float = 0.2) -> bool:
        with socket.socket() as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((self.host, self.port)) == 0


GATEWAY_NOTE = "authenticated · sole endpoint"


def default_gateway() -> Service:
    return Service("Bifrost", 8080, GATEWAY_NOTE)


def default_surfaces() -> list[Service]:
    return [
        Service("Open WebUI", 3000, "chat + history"),
        Service("Phoenix", 6006, "traces · content logging ON"),
    ]


@dataclass
class Model:
    """One registry alias and where it currently lives."""

    alias: str
    standing: str  # default | approved | experimental | review-gated
    residency: str = "registered"  # resident | spilling | cached | registered
    gib: float | None = None
    gpu_fraction: float | None = None  # size_vram / size
    ttl: str | None = None  # keep-alive remaining

    @property
    def mark(self) -> str:
        return {
            "resident": c("●", LIVE),
            "spilling": c("◐", WARM),
            "cached": c("○", CHROME),
        }.get(self.residency, c("·", CHROME))

    @property
    def detail(self) -> str:
        if self.residency == "resident":
            bits = ["100% GPU"]
            if self.gib:
                bits.append(f"{self.gib:.1f}G")
            if self.ttl:
                bits.append(f"ttl {self.ttl}")
            return c("  ".join(bits), CHROME)
        if self.residency == "spilling":
            pct = f"{(self.gpu_fraction or 0) * 100:.0f}% GPU"
            return c(pct, WARM) + c("  spilling to CPU", WARM)
        if self.residency == "cached":
            return c(f"cached{f'  {self.gib:.1f}G' if self.gib else ''}", CHROME)
        if self.residency == "unknown":
            return c("inventory unavailable", CHROME)
        return c("not pulled", CHROME)


@dataclass
class Rig:
    profile: str = "chat"
    runtime: str | None = "ollama"  # None: core only, no serveshed runtime on the GPU
    gpu: dict[str, Any] = field(default_factory=dict)
    models: list[Model] = field(default_factory=list)
    gateway: Service = field(default_factory=default_gateway)
    surfaces: list[Service] = field(default_factory=default_surfaces)
    gateway_key_present: bool = True
    gateway_aliases: int | None = None  # from an authenticated probe; None: probe failed/skipped
    warnings: list[str] = field(default_factory=list)


# ── probes ─────────────────────────────────────────────────────────────
def read_gpu() -> dict[str, Any]:
    query = "name,memory.used,memory.total,temperature.gpu,power.draw,power.limit"
    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    rows = result.stdout.strip().splitlines()
    if not rows:
        return {}
    parts = [p.strip() for p in rows[0].split(",")]

    def num(v: str) -> float | None:
        try:
            return float(v)
        except ValueError:
            return None  # nvidia-smi prints [N/A] on some parts

    return {
        "name": parts[0].replace("NVIDIA ", ""),
        "used_gib": (num(parts[1]) or 0) / 1024,
        "total_gib": (num(parts[2]) or 0) / 1024,
        "temp_c": num(parts[3]),
        "watts": num(parts[4]),
        "cap_w": num(parts[5]),
    }


# Residency (which models are actually loaded) is deliberately NOT read here
# via a direct HTTP call to 127.0.0.1:11434. On a machine that also has a
# host-native Ollama install (a real, confirmed scenario on at least one
# dev box this project runs on), that port belongs to the WRONG Ollama —
# a separate systemd service with its own model library. The containerized
# Ollama this project manages has no published host port at all, by design
# (the `no-direct-ollama-port` static check exists specifically to keep it
# that way). The only correct path is `docker compose exec ollama ollama
# ps`, which is what `ComposeManager.ollama_processes()` already does —
# see `build_rig()` below, which calls it instead of reinventing it here.


def parse_size_gib(text: str) -> float | None:
    """Parse Ollama's "5.6 GB" / "6.6 GiB"-style size strings into GiB."""
    parts = text.strip().split()
    if len(parts) != 2:
        return None
    try:
        value = float(parts[0])
    except ValueError:
        return None
    unit = parts[1].upper()
    if unit in ("GB", "GIB"):
        return value
    if unit in ("MB", "MIB"):
        return value / 1024
    if unit in ("TB", "TIB"):
        return value * 1024
    return None


def parse_processor_split(text: str) -> tuple[str, float | None]:
    """Ollama's processor column: "100% GPU", "100% CPU", or a split like
    "43%/57% CPU/GPU". Returns (residency, gpu_fraction)."""
    text = text.strip()
    if "/" not in text:
        if "GPU" in text:
            return "resident", 1.0
        return "spilling", 0.0
    numbers = [float(p.rstrip("%")) for p in text.split()[0].split("/") if p.rstrip("%").strip()]
    if len(numbers) == 2:
        _cpu_pct, gpu_pct = numbers
        return "spilling", gpu_pct / 100
    return "spilling", None


def check_host_ollama_collision(container_port_bound: bool = False) -> str | None:
    """Detect a non-containerized Ollama already listening on 11434 -- the
    exact host-native-systemd-service collision found on real hardware this
    session. Never true positive from the container itself: its port isn't
    published to the host at all, so anything answering on the host's own
    11434 is, by construction, a different Ollama."""
    with socket.socket() as sock:
        sock.settimeout(0.2)
        reachable = sock.connect_ex(("127.0.0.1", 11434)) == 0
    if not reachable:
        return None
    return "A host-native Ollama is also listening on :11434 (separate install, outside serveshed) — GPU contention risk if both load a model"


def check_stale_containers(root: str, expected_project: str) -> str | None:
    """Detect containers from this repo's compose.yaml still running under a
    different Compose project name -- exactly what a rename (or manually
    edited COMPOSE_PROJECT_NAME) leaves behind: orphaned, port-colliding,
    invisible to `docker compose -p <current-name> ...` from then on."""
    try:
        result = subprocess.run(
            [
                "docker",
                "ps",
                "--filter",
                f"label=com.docker.compose.project.working_dir={root}",
                "--format",
                '{{index .Labels "com.docker.compose.project"}}',
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    projects = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    stale = sorted(projects - {expected_project})
    if not stale:
        return None
    names = ", ".join(stale)
    return f"containers still running under a stale project name ({names}) — stop with `docker compose -p <name> down` before the next `up`"


def probe_gateway(key: str, url: str) -> int | None:
    """Authenticated round trip. Proves the gateway is up, the virtual key is
    valid, AND provider aliases resolved — none of which an open TCP port does.
    """
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return len(json.load(response).get("data", []))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def check_headroom(path: str, floor_gib: float = 25.0) -> str | None:
    """Model pulls are ~7 GiB and eval bundles only accumulate."""
    try:
        free = shutil.disk_usage(path).free / 2**30
    except OSError:
        return None
    return f"{free:.0f} GiB free on the data volume — pulls need ~7" if free < floor_gib else None


def vram_bar(used: float, total: float, cells: int = 20) -> str:
    ratio = 0.0 if total <= 0 else min(used / total, 1.0)
    filled = round(ratio * cells)
    tone = LAMP if ratio < 0.80 else WARM if ratio < 0.92 else DEAD
    return c("█" * filled, tone) + c("░" * (cells - filled), CHROME)


# Standing but currently-permanent, unlike the conditional warnings above:
# not a per-run fact, a documented open upstream limitation (ADR 0018).
# Remove by hand only as part of actually doing that ADR's "revisit on next
# Bifrost image bump" step -- never auto-hidden by a version-string check,
# since bumping the pin doesn't by itself prove the behavior was retested.
ADR_0018_WARNING = (
    "Bifrost doesn't cap Ollama generation length (ADR 0018) -- "
    "any request's latency is effectively unbounded"
)


def check_default_model_acceptance(settings: Settings) -> str | None:
    """Surface the most recent acceptance decision for the current default
    alias. This already lived in `runs list` -- nowhere you'd see it just
    from starting the stack, even though it's exactly the "evidence, not
    vibes" fact this project is built around (ADR 0009)."""
    from serveshed.runs import discover_runs

    alias = settings.default_model_alias
    decisions = discover_runs(settings.eval_runs_dir, kind="model-acceptance", model=alias, limit=1)
    if not decisions:
        return f"{alias} (default) has no acceptance decision on record -- never measured"
    latest = decisions[0]
    if latest.score < 1.0:
        return f"{alias} (default) last acceptance decision was REJECTED -- see {latest.run_dir}"
    return None


def build_rig(
    settings: Settings, manager: ComposeManager, *, target: str, eval_logging: bool
) -> Rig:
    """Assemble a Rig from live project state. The only place in this
    module that imports the rest of `serveshed` -- kept out of the
    module-level imports so the pure rendering/probe functions above stay
    usable standalone, per the "standard library only" header."""
    from serveshed.models import load_registry

    registry = load_registry(settings)
    runtime = {"eval": "vllm", "chat": "ollama"}.get(target)

    models: list[Model] = []
    if runtime == "ollama":
        processes = {p.name: p for p in manager.ollama_processes()}
        inventory: dict[str, Any] | None
        try:
            inventory = {m.name: m for m in manager.ollama_inventory()}
        except RuntimeError:
            inventory = None
        default_alias = settings.default_model_alias
        for spec in registry.values():
            if spec.runtime != "ollama":
                continue
            standing = (
                "default"
                if spec.alias == default_alias
                else "experimental"
                if spec.experimental
                else "approved"
                if spec.approval.startswith("approved")
                else "review-gated"
            )
            proc = processes.get(spec.artifact) if spec.artifact else None
            inv = inventory.get(spec.artifact) if inventory and spec.artifact else None
            if proc is not None:
                residency, gpu_fraction = parse_processor_split(proc.processor)
                gib = parse_size_gib(proc.size)
                ttl = proc.until
            elif inv is not None:
                residency, gpu_fraction, ttl = "cached", None, None
                gib = parse_size_gib(inv.size)
            elif inventory is None:
                # `ollama list` failed: absence of evidence, not "not pulled".
                residency, gpu_fraction, gib, ttl = "unknown", None, None, None
            else:
                residency, gpu_fraction, gib, ttl = "registered", None, None, None
            models.append(
                Model(
                    alias=spec.alias,
                    standing=standing,
                    residency=residency,
                    gib=gib,
                    gpu_fraction=gpu_fraction,
                    ttl=ttl,
                )
            )

    checks: tuple[Callable[[], str | None], ...] = (
        lambda: check_headroom(str(settings.data_dir)),
        lambda: check_host_ollama_collision(),
        lambda: check_stale_containers(
            # compose_env precedence (.env over shell), matching what Compose
            # itself actually runs with -- not settings.get, where shell wins.
            str(settings.root),
            settings.compose_env.get("COMPOSE_PROJECT_NAME") or "serveshed",
        ),
        lambda: check_default_model_acceptance(settings),
    )
    warnings: list[str] = [found for found in (check() for check in checks) if found]
    from serveshed.backup import inspect_nas

    if not inspect_nas(settings).marker_present:
        warnings.append("NAS marker missing -- backups will refuse to run")
    warnings.append(ADR_0018_WARNING)

    gateway = Service("Bifrost", settings.bifrost_port, GATEWAY_NOTE)
    surfaces = [
        Service("Open WebUI", settings.openwebui_port, "chat + history"),
        Service("Phoenix", settings.phoenix_port, "traces · content logging ON"),
    ]
    gateway_key = settings.get("BIFROST_VK_HERMES", "")
    gateway_aliases = (
        probe_gateway(gateway_key, f"{settings.bifrost_base_url}/v1/models")
        if gateway_key
        else None
    )

    return Rig(
        profile=target,
        runtime=runtime,
        models=models,
        gateway=gateway,
        surfaces=surfaces,
        gateway_key_present=bool(gateway_key),
        gateway_aliases=gateway_aliases,
        warnings=warnings,
    )


# ── render ─────────────────────────────────────────────────────────────
def rule(w: int, left: str = "", right: str = "") -> str:
    if not left:
        return c(" " + "─" * (w - 2), CHROME)
    fill = max(w - plain_len(left) - plain_len(right) - 6, 1)
    return c(" ─ ", CHROME) + left + " " + c("─" * fill, CHROME) + (f" {right} " if right else " ")


def render(rig: Rig) -> str:
    w = min(shutil.get_terminal_size((84, 24)).columns, 100)
    gpu = rig.gpu or read_gpu()
    states = [svc.listening() for svc in (rig.gateway, *rig.surfaces)]

    left = c("serve", BOLD, LAMP) + c("shed", BOLD, INK) + c(f"   {rig.profile}", CHROME)
    right = c(f"{sum(states)}/{len(states)} up", CHROME)
    out: list[str] = ["", rule(w, left, right), ""]

    # The card. One GPU, one runtime, by construction.
    holder = (
        f"{rig.runtime} holds the card" if rig.runtime else "core only — card left to the desktop"
    )
    if gpu:
        out.append(f"   {c('CARD  ', BOLD, CHROME)}{c(gpu['name'], INK)}   {c(holder, CHROME)}")
        detail = f"{gpu['used_gib']:.1f} / {gpu['total_gib']:.1f} GiB"
        if gpu["temp_c"] is not None:
            detail += f"   {gpu['temp_c']:.0f}°C"
        if gpu["watts"] is not None and gpu["cap_w"]:
            detail += f"   {gpu['watts']:.0f}/{gpu['cap_w']:.0f} W"
        out.append(f"         {vram_bar(gpu['used_gib'], gpu['total_gib'])}  {c(detail, CHROME)}")
    else:
        out.append(f"   {c('CARD  ', BOLD, CHROME)}{c('nvidia-smi unavailable', DEAD)}")
    out.append("")

    # Every alias, sorted by how close it is to answering a request.
    order = {"resident": 0, "spilling": 1, "cached": 2, "registered": 3}
    ranked = sorted(rig.models, key=lambda m: (order.get(m.residency, 9), m.alias))
    span = max((len(m.alias) for m in ranked), default=0) + 2
    for i, model in enumerate(ranked):
        tag = c("MODELS", BOLD, CHROME) if i == 0 else "      "
        tone = {"default": LIVE, "experimental": WARM}.get(model.standing, CHROME)
        out.append(
            f"   {tag} {model.mark}  {c(model.alias.ljust(span), INK)}"
            f"{c(model.standing.ljust(14), tone)}{model.detail}"
        )
    if any(
        m.standing == "experimental" and m.residency in ("resident", "spilling") for m in ranked
    ):
        out.append(
            f"          {c('experimental alias loaded — never a judge or eval grader', WARM)}"
        )
    out.append("")

    # Bifrost stands alone: it is the door. Everything else is a window.
    up = states[0]
    if rig.gateway_aliases is not None:
        served = c(f"{rig.gateway_aliases} aliases resolve", CHROME)
    elif up and rig.gateway_key_present:
        served = c("key rejected or providers unresolved", DEAD)
    elif up:
        served = c("no BIFROST_VK_HERMES in .env — auth probe skipped", WARM)
    else:
        served = c(rig.gateway.note, CHROME)
    out.append(
        f"   {c('DOOR  ', BOLD, CHROME)}{c('●', LIVE) if up else c('○', CHROME)}  "
        f"{c('Bifrost'.ljust(11), INK)}{c(link(rig.gateway.url), LAMP if up else CHROME)}   {served}"
    )
    for i, (svc, alive) in enumerate(zip(rig.surfaces, states[1:], strict=True)):
        out.append(
            f"   {c('ALSO  ', BOLD, CHROME) if i == 0 else '      '}"
            f"{c('●', LIVE) if alive else c('○', CHROME)}  {c(svc.name.ljust(11), INK)}"
            f"{c(link(svc.url), LAMP if alive else CHROME)}   {c(svc.note, CHROME)}"
        )

    # Silence means healthy. Only degraded conditions get to speak here.
    if rig.warnings:
        out.append("")
        for warning in rig.warnings:
            out.append(f"   {c('⚠', WARM)}  {c(warning, WARM)}")

    out += [
        "",
        f"   {c('egress blocked on backend — no cloud route exists to take', CHROME)}",
        f"   {c('gpu-off hands the card back when you are done', CHROME)}",
        rule(w),
    ]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    print(render(Rig()))
