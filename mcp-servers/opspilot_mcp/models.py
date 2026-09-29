"""Data shapes shared by the telemetry backends and the MCP tools."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

HealthStatus = Literal["healthy", "unhealthy", "unreachable"]
LogLevel = Literal["DEBUG", "INFO", "WARN", "ERROR"]
LEVEL_ORDER: dict[str, int] = {"TRACE": 0, "DEBUG": 1, "INFO": 2, "WARN": 3, "ERROR": 4, "FATAL": 5}


class HealthReport(BaseModel):
    service: str
    status: HealthStatus
    http_status: int | None = None
    latency_ms: float | None = None
    version: str | None = None
    failing_components: list[str] = Field(default_factory=list)
    detail: str | None = None
    depends_on: list[str] = Field(default_factory=list)


class Series(BaseModel):
    """One time series as returned by a backend: optional labels plus (time, value) points."""

    labels: dict[str, str] = Field(default_factory=dict)
    points: list[tuple[datetime, float | None]]


class LogEntry(BaseModel):
    timestamp: datetime
    service: str
    level: str
    message: str
    logger: str | None = None
    trace_id: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    stack_trace: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)


class DeployEvent(BaseModel):
    id: str
    service: str
    kind: Literal["deploy", "rollback"]
    version: str
    previous_version: str | None = None
    deployed_at: datetime
    author: str
    change_summary: str
    config_diff: dict[str, dict[str, Any]] = Field(default_factory=dict)


class BackendError(Exception):
    """A backend could not answer. The message is shown to the model, so keep it actionable."""
