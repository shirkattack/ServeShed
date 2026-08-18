#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE=${1:-"$ROOT/.env.example"}

if ! command -v docker >/dev/null 2>&1; then
  printf '%s\n' 'Docker is not installed; image manifests were not checked.' >&2
  exit 2
fi

status=0
while IFS='=' read -r key image; do
  case "$key" in
    *_IMAGE)
      if [ -z "$image" ]; then
        continue
      fi
      printf 'checking %-18s %s\n' "$key" "$image"
      if ! docker manifest inspect "$image" >/dev/null 2>&1; then
        printf 'FAILED: %s\n' "$image" >&2
        status=1
      fi
      ;;
  esac
done < "$ENV_FILE"

if [ "$status" -ne 0 ]; then
  printf '%s\n' 'One or more image tags could not be resolved.' >&2
  exit "$status"
fi
printf '%s\n' 'All declared image tags resolved. Record immutable digests before deployment acceptance.'
