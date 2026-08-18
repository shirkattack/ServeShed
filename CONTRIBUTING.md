# Contributing

Read `README.md` and the ADRs before changing architecture. Use `uv` for all
project-owned Python work and preserve the zero-dependency bootstrap unless an
approved change regenerates `uv.lock`.

Before a change is accepted:

```bash
scripts/check.sh
```

Host-dependent work must also run `uv run serveshed config validate --docker` on
the Ubuntu machine. Never commit `.env`, model weights, host inventory containing
private data, raw sensitive traces, or generated eval runs.
