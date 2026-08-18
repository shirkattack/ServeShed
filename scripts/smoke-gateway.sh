#!/bin/sh
set -eu

BASE_URL=${BIFROST_BASE_URL:-http://127.0.0.1:8080}
API_KEY=${BIFROST_API_KEY:-${BIFROST_VK_EVAL:-}}
MODEL=${BIFROST_MODEL:-ollama/local/qwen-fast}

if ! command -v curl >/dev/null 2>&1; then
  printf '%s\n' 'curl is required.' >&2
  exit 2
fi
if [ -z "$API_KEY" ]; then
  printf '%s\n' 'Export BIFROST_API_KEY or BIFROST_VK_EVAL; secrets are never read by sourcing .env.' >&2
  exit 2
fi

curl --fail --silent --show-error "$BASE_URL/health" >/dev/null
printf '%s\n' 'Bifrost health endpoint is reachable.'

payload=$(cat <<JSON
{"model":"$MODEL","messages":[{"role":"user","content":"Reply with exactly SERVESHED_OK"}],"temperature":0,"max_tokens":16,"stream":false}
JSON
)

curl --fail --silent --show-error \
  -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' \
  -H 'x-bf-eh-agent-id: shell-smoke' \
  -H 'x-bf-eh-workload: smoke' \
  --data "$payload" \
  "$BASE_URL/v1/chat/completions"
printf '\n'
