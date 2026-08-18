# Python dependency phases

The first committed `uv.lock` contains only the local package. A tiny in-repository PEP 517 backend keeps the bootstrap independent of package indexes. This is intentional: the scaffold can be built and tested without a package index, while the infrastructure integrations remain pinned containers and configuration files.

After the Ubuntu host has network access and component compatibility has been reviewed, add groups with `uv add`, regenerate the lock, and run the full test suite.

Proposed groups:

```bash
uv add --group app openai httpx pydantic-settings typer rich
uv add --group tracing arize-phoenix-client arize-phoenix-otel opentelemetry-sdk
uv add --group dev pytest ruff mypy
```

Inspect AI and lm-evaluation-harness are deliberately absent from this list: per ADR 0017 they live in separate repos and connect to Bifrost as ordinary virtual-key callers, so their dependency trees never enter this repo's lockfile.

Versions must be selected from current upstream compatibility information at implementation time. Do not copy this list into `pyproject.toml` without generating and reviewing `uv.lock`.
