from __future__ import annotations

from collections.abc import Mapping


def request_headers(
    metadata: Mapping[str, object] | None = None,
    *,
    session_id: str | None = None,
) -> dict[str, str]:
    """Translate run metadata into Bifrost extra-header attributes."""

    headers: dict[str, str] = {}
    for key, value in (metadata or {}).items():
        normalized = key.lower().replace("_", "-")
        if normalized in {"session-id", "x-bf-session-id"}:
            continue
        if normalized in {"agent", "agent-name"}:
            normalized = "agent-id"
        if not normalized.startswith("x-bf-eh-"):
            normalized = f"x-bf-eh-{normalized}"
        headers[normalized] = str(value)
    if session_id:
        headers["x-bf-session-id"] = session_id
    return headers
