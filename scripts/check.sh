#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

UV=${UV:-uv}
PYTHON=${PYTHON:-3.12}

"$UV" lock --check --offline --python "$PYTHON"
"$UV" sync --locked --offline --python "$PYTHON"
"$UV" run --python "$PYTHON" python -m compileall -q src tests examples evals/inspect
"$UV" run --python "$PYTHON" python -m unittest discover -s tests -v
"$UV" run --python "$PYTHON" serveshed config validate
"$UV" run --python "$PYTHON" serveshed eval smoke --dry-run
"$UV" run --python "$PYTHON" serveshed eval qwen --dry-run
"$UV" run --python "$PYTHON" serveshed model recommend --vram-gib 16 --workload agents --json >/dev/null
"$UV" run --python "$PYTHON" serveshed benchmark plan interactive --repetitions 2 --warmup 1 --json >/dev/null
"$UV" run --python "$PYTHON" serveshed benchmark plan throughput --repetitions 1 --warmup 0 --json >/dev/null
"$UV" run --python "$PYTHON" serveshed runs list --json >/dev/null
"$UV" run --python "$PYTHON" python scripts/generate-model-matrix.py --check
"$UV" run --python "$PYTHON" python scripts/generate-manifest.py --check

if [ "${1:-}" = "--full" ]; then
  "$UV" tool run --from ruff==0.16.3 ruff check .
  "$UV" tool run --from ruff==0.16.3 ruff format --check .
  "$UV" tool run --from mypy==2.3.0 mypy src/serveshed
fi
