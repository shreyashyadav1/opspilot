"""Live backend: the docker compose demo system.

- metrics: Prometheus HTTP API (range queries)
- logs: container stdout via the Docker CLI (services log JSON lines to stdout only)
- health: each service's health endpoint
- deploys and rollbacks: the control plane's deploy API (never its chaos API)
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from opentelemetry import trace
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from opspilot_mcp.catalog import CATALOG
from opspilot_mcp.logsearch import parse_line
from opspilot_mcp.metrics import METRICS
from opspilot_mcp.models import BackendError, DeployEvent, HealthReport, LogEntry, Series


def _parse_urls(raw: str) -> dict[str, str]:
    return {k: v.rstrip("/") for k, v in (item.split("=", 1) for item in raw.split(",") if item)}


@dataclass(frozen=True)
class LiveSettings:
    prometheus_url: str = "http://localhost:9095"
    control_plane_url: str = "http://localhost:8190"
    service_urls: dict[str, str] = field(
        default_factory=lambda: {
            "storefront": "http://localhost:8101",
            "orders": "http://localhost:8102",
            "payments": "http://localhost:8103",
        }
    )
    container_prefix: str = "opspilot-"
    docker_bin: str = "docker"
    health_timeout_s: float = 3.0

    @classmethod
    def from_env(cls) -> LiveSettings:
        defaults = cls()
        urls = os.getenv("OPSPILOT_SERVICE_URLS")
        return cls(
            prometheus_url=os.getenv("OPSPILOT_PROMETHEUS_URL", defaults.prometheus_url),
            control_plane_url=os.getenv("OPSPILOT_CONTROL_PLANE_URL", defaults.control_plane_url),
            service_urls=_parse_urls(urls) if urls else defaults.service_urls,
            container_prefix=os.getenv("OPSPILOT_CONTAINER_PREFIX", defaults.container_prefix),
            docker_bin=os.getenv("OPSPILOT_DOCKER_BIN", defaults.docker_bin),
        )


def _health_details(service: str, body: Any) -> tuple[str | None, list[str], str | None]:
    """Extract (version, failing components, detail) from either health payload shape."""
    if not isinstance(body, dict):
        return None, [], None
    if "components" in body:  # Spring Boot actuator
        components: dict[str, Any] = body["components"]
        version = components.get("service", {}).get("details", {}).get("version")
        failing, details = [], []
        for name, component in components.items():
            if component.get("status") != "UP":
                failing.append(name)
                error = component.get("details", {}).get("error")
                details.append(f"{name}: {error}" if error else name)
        return version, failing, "; ".join(details) or None
    detail = body.get("error")
    return body.get("version"), [], detail


class LiveBackend:
    def __init__(
        self,
        settings: LiveSettings | None = None,
        client: httpx.AsyncClient | None = None,
        tracer_provider: trace.TracerProvider | None = None,
    ) -> None:
        self.settings = settings or LiveSettings.from_env()
        if client is not None:
            self._client = client
        else:
            self._client = httpx.AsyncClient(timeout=10.0)
            # So a rollback (and, on services that do not exclude it, a health check) continues
            # the investigation's trace into the demo system, instead of starting a new one.
            HTTPXClientInstrumentor.instrument_client(
                self._client, tracer_provider=tracer_provider or trace.get_tracer_provider()
            )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self, service: str) -> HealthReport:
        info = CATALOG[service]
        url = self.settings.service_urls[service] + info.health_path
        started = time.perf_counter()
        try:
            response = await self._client.get(url, timeout=self.settings.health_timeout_s)
        except httpx.TimeoutException:
            return HealthReport(
                service=service,
                status="unreachable",
                detail=f"health check timed out after {self.settings.health_timeout_s:.0f}s",
                depends_on=list(info.depends_on),
            )
        except httpx.TransportError as exc:
            return HealthReport(
                service=service,
                status="unreachable",
                detail=f"connection failed: {type(exc).__name__}",
                depends_on=list(info.depends_on),
            )
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        try:
            body = response.json()
        except ValueError:
            body = None
        version, failing, detail = _health_details(service, body)
        healthy = response.status_code == 200 and not failing
        return HealthReport(
            service=service,
            status="healthy" if healthy else "unhealthy",
            http_status=response.status_code,
            latency_ms=latency_ms,
            version=version,
            failing_components=failing,
            detail=None if healthy else detail,
            depends_on=list(info.depends_on),
        )

    async def metric_series(self, service: str, metric: str, window_minutes: int) -> list[Series]:
        end = datetime.now(UTC)
        start = end - timedelta(minutes=window_minutes)
        step = max(15, window_minutes * 60 // 30)
        params = {
            "query": METRICS[metric].query(service),
            "start": int(start.timestamp()),
            "end": int(end.timestamp()),
            "step": step,
        }
        try:
            response = await self._client.get(
                f"{self.settings.prometheus_url}/api/v1/query_range", params=params
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BackendError(f"Prometheus query failed: {type(exc).__name__}") from exc
        payload = response.json()
        if payload.get("status") != "success":
            raise BackendError(f"Prometheus returned an error: {payload.get('error')}")
        # Prometheus omits steps without data (for example while a scrape target is down).
        # Return the full grid with gaps as None so summaries can tell stale from current.
        grid = [int(start.timestamp()) + k * step for k in range(window_minutes * 60 // step + 1)]
        result = []
        for item in payload["data"]["result"]:
            values = {round(float(ts)): float(value) for ts, value in item["values"]}
            result.append(
                Series(
                    labels={
                        k: v for k, v in item["metric"].items() if k not in {"job", "instance"}
                    },
                    points=[(datetime.fromtimestamp(ts, UTC), values.get(ts)) for ts in grid],
                )
            )
        return result

    async def log_entries(self, service: str, since_minutes: int) -> list[LogEntry]:
        container = self.settings.container_prefix + service
        try:
            process = await asyncio.create_subprocess_exec(
                self.settings.docker_bin,
                "logs",
                "--since",
                f"{since_minutes * 60}s",
                container,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
        except (OSError, TimeoutError) as exc:
            raise BackendError(f"could not read logs for {service}: {type(exc).__name__}") from exc
        if process.returncode != 0:
            raise BackendError(f"could not read logs for {service}: container not found")
        lines = (stdout + b"\n" + stderr).decode("utf-8", errors="replace").splitlines()
        entries = [entry for line in lines if (entry := parse_line(line, service))]
        return sorted(entries, key=lambda e: e.timestamp)

    async def deploys(self, service: str | None, since_minutes: int) -> list[DeployEvent]:
        params: dict[str, Any] = {"since_minutes": since_minutes}
        if service:
            params["service"] = service
        try:
            response = await self._client.get(
                f"{self.settings.control_plane_url}/deploys", params=params
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BackendError(f"deploy history unavailable: {type(exc).__name__}") from exc
        return [DeployEvent.model_validate(item) for item in response.json()["deploys"]]

    async def rollback(self, service: str, reason: str) -> DeployEvent:
        try:
            response = await self._client.post(
                f"{self.settings.control_plane_url}/deploys/{service}/rollback",
                json={"reason": reason, "requested_by": "opspilot"},
            )
        except httpx.HTTPError as exc:
            raise BackendError(f"rollback request failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise BackendError(f"rollback rejected: {response.json().get('detail', response.text)}")
        return DeployEvent.model_validate(response.json())
