from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from serveshed import __version__
from serveshed.settings import Settings


@dataclass(frozen=True, slots=True)
class ServiceProbe:
    service: str
    endpoint: str
    ok: bool
    status: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def probe_http(service: str, endpoint: str, *, timeout: float = 1.5) -> ServiceProbe:
    request = Request(endpoint, headers={"User-Agent": f"serveshed-health/{__version__}"})
    try:
        with urlopen(request, timeout=timeout) as response:
            code = int(response.status)
            return ServiceProbe(service, endpoint, 200 <= code < 500, str(code), "reachable")
    except HTTPError as exc:
        return ServiceProbe(service, endpoint, False, str(exc.code), exc.reason or "HTTP error")
    except (OSError, URLError) as exc:
        return ServiceProbe(service, endpoint, False, "unreachable", str(exc))


def collect_service_health(settings: Settings) -> tuple[ServiceProbe, ...]:
    return (
        probe_http("bifrost", f"http://127.0.0.1:{settings.bifrost_port}/health"),
        probe_http("phoenix", f"http://127.0.0.1:{settings.phoenix_port}/"),
    )
