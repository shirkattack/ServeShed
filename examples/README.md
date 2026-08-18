# Python examples

Both examples use the dependency-free project client, route through Bifrost, and
identify callers with separate virtual keys. They do not connect directly to
Ollama or vLLM.

```bash
uv run python examples/simple_client.py "Reply with exactly hello"
uv run python examples/multi_agent_pipeline.py "Design a local document ingestion test"
```

The multi-agent example is deliberately sequential because one RTX 5070 Ti
normally serves one loaded model. Separate agents are identities, prompts, tools,
and trace metadata; they are not separate copies of the model.
