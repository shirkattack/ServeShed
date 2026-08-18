#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUTPUT=${1:-"$ROOT/../serveshed.zip"}
case "$OUTPUT" in
  /*) ;;
  *) OUTPUT="$(pwd)/$OUTPUT" ;;
esac

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT HUP INT TERM
mkdir -p "$STAGE/serveshed" "$(dirname -- "$OUTPUT")"

# Copy the source tree while excluding generated state, secrets, caches, and built distributions.
tar -C "$ROOT" -cf - \
  --exclude='./.git' \
  --exclude='./.venv' \
  --exclude='./.env' \
  --exclude='./.env.phoenix' \
  --exclude='./.env.bak-*' \
  --exclude='./__pycache__' \
  --exclude='*/__pycache__' \
  --exclude='*.pyc' \
  --exclude='./.pytest_cache' \
  --exclude='./.mypy_cache' \
  --exclude='./.ruff_cache' \
  --exclude='./eval-runs' \
  --exclude='./dist' \
  . | tar -C "$STAGE/serveshed" -xf -

rm -f "$OUTPUT"
case "$OUTPUT" in
  *.zip)
    (cd "$STAGE" && zip -qr "$OUTPUT" serveshed)
    ;;
  *.tar.gz|*.tgz)
    tar -C "$STAGE" -czf "$OUTPUT" serveshed
    ;;
  *)
    printf '%s\n' "Unsupported archive extension: $OUTPUT" >&2
    exit 2
    ;;
esac

printf '%s\n' "$OUTPUT"
