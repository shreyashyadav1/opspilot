"""The interface every telemetry backend implements."""

from __future__ import annotations

from typing import Protocol

from opspilot_mcp.models import DeployEvent, HealthReport, LogEntry, Series


class TelemetryBackend(Protocol):
    async def health(self, service: str) -> HealthReport: ...

    async def metric_series(self, service: str, metric: str, window_minutes: int) -> list[Series]:
        """Series for a named metric (see opspilot_mcp.metrics.METRICS) over the window."""
        ...

    async def log_entries(self, service: str, since_minutes: int) -> list[LogEntry]: ...

    async def deploys(self, service: str | None, since_minutes: int) -> list[DeployEvent]:
        """Deploy and rollback events, any order."""
        ...

    async def rollback(self, service: str, reason: str) -> DeployEvent: ...

    async def aclose(self) -> None: ...
