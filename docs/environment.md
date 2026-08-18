# Environment inventory

This is a worksheet, deliberately left blank in the public repository: the completed inventory describes a specific private machine (hostnames, serial-adjacent details, mount paths) and is kept out of Git by design. The values below are filled in locally on the target Ubuntu Desktop before host changes and never committed. The host verification narrative lives in `docs/verification-report.md`.

## Required observations

| Item | Value |
|---|---|
| Ubuntu version | pending |
| Kernel | pending |
| CPU | pending |
| RAM | pending |
| Swap | pending |
| Local NVMe capacity/free | pending |
| NVIDIA driver | pending |
| CUDA reported by driver | pending |
| RTX 5070 Ti VRAM | expected 16 GB; verify |
| Docker Engine | pending |
| Docker Compose | pending |
| NVIDIA Container Toolkit | pending |
| Tailscale | pending |
| Display connected to | pending |
| Synology protocol/address | not connected |

Generate the first read-only report with:

```bash
uv run serveshed doctor --json > environment-doctor.json
```

Do not commit the report until it has been reviewed for hostnames, usernames, mount paths, and other private information.
