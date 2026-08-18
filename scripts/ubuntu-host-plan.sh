#!/bin/sh
set -eu

cat <<'PLAN'
Ubuntu host preparation plan (not executed):

1. Record the host first:
   uv run serveshed doctor --json > environment-doctor.json

2. Install and verify native Docker Engine from Docker's current Ubuntu instructions.
   Do not install Docker Desktop for this project.

3. Install a supported NVIDIA driver and NVIDIA Container Toolkit from NVIDIA's
   current instructions, then verify a disposable CUDA container can run nvidia-smi.

4. Run:
   scripts/verify-images.sh
   uv run serveshed init
   uv run serveshed config validate --docker
   uv run serveshed up core

5. Validate persistence, Bifrost authentication, and Phoenix traces before any
   model download or Tailscale exposure.

6. Review `uv run serveshed model show local/qwen-fast`, free disk, RAM, and
   desktop GPU headroom before approving the first Qwen pull. Evaluate
   `local/qwen-quality` only after the daily profile is measured.

This script deliberately prints a plan and performs no package, driver, Docker,
Tailscale, firewall, model, or mount changes.
PLAN
