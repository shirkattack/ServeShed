# Hermes Agent adapter

Hermes Agent should use Bifrost's OpenAI-compatible endpoint and the dedicated Hermes virtual key. Direct Ollama access is diagnostic-only because it bypasses gateway governance and OpenTelemetry traces.

Conceptual values:

```text
base URL: http://127.0.0.1:8080/v1
API key: value of BIFROST_VK_HERMES in .env
model: ollama/local/qwen-fast
```

Verify the installed Hermes Agent release and its exact environment/config names before creating runtime state. Never commit Hermes secrets, history, tool credentials, or messaging bridge configuration.
