"""Mutable runtime state of a service: version, config and injected failure modes.

The control plane changes this state through the internal admin API. Deploys update the version
and config; the chaos API sets failure modes. Admin traffic is excluded from logs and metrics,
so an investigator only sees the effects, never the injection itself.
"""

from __future__ import annotations

import random
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field


class FailureModes(BaseModel):
    """Failure modes a service can be put into. Everything off by default."""

    model_config = ConfigDict(extra="forbid")

    latency_ms: int = Field(0, ge=0, le=30_000, description="Delay added to business requests")
    latency_jitter_ms: int = Field(0, ge=0, le=10_000)
    error_rate: float = Field(0.0, ge=0.0, le=1.0, description="Share of requests hitting a bug")
    outage: bool = Field(False, description="Stop serving everything except the admin API")


class ConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str | None = None
    values: dict[str, Any] = Field(default_factory=dict)


def _matches_type(value: Any, expected: type) -> bool:
    # bool is a subclass of int; keep the two apart so "true" never becomes a timeout.
    if expected is bool or isinstance(value, bool):
        return expected is bool and isinstance(value, bool)
    if expected is float:
        return isinstance(value, int | float)
    return isinstance(value, expected)


class ServiceRuntime:
    def __init__(
        self,
        name: str,
        version: str,
        default_config: dict[str, Any],
        rng: random.Random | None = None,
    ) -> None:
        self.name = name
        self.version = version
        self._defaults = dict(default_config)
        self.config: dict[str, Any] = dict(default_config)
        self.failures = FailureModes()
        self._rng = rng or random.Random()

    def should_fail(self) -> bool:
        """Roll the dice for the configured error rate."""
        rate = self.failures.error_rate
        return rate > 0 and self._rng.random() < rate

    def added_latency_s(self) -> float:
        base = self.failures.latency_ms
        if base == 0:
            return 0.0
        jitter = self.failures.latency_jitter_ms
        return max(0.0, base + self._rng.uniform(-jitter, jitter)) / 1000

    def apply_config(self, update: ConfigUpdate) -> None:
        unknown = sorted(set(update.values) - set(self._defaults))
        if unknown:
            raise ValueError(f"unknown config keys: {', '.join(unknown)}")
        for key, value in update.values.items():
            expected = type(self._defaults[key])
            if not _matches_type(value, expected):
                raise ValueError(f"{key} must be of type {expected.__name__}")
        self.config.update(update.values)
        if update.version:
            self.version = update.version

    def admin_router(self) -> APIRouter:
        router = APIRouter(prefix="/admin", include_in_schema=False)

        @router.get("/failures")
        def get_failures() -> FailureModes:
            return self.failures

        @router.put("/failures")
        def set_failures(modes: FailureModes) -> FailureModes:
            self.failures = modes
            return self.failures

        @router.delete("/failures")
        def clear_failures() -> FailureModes:
            self.failures = FailureModes()
            return self.failures

        @router.get("/config")
        def get_config() -> dict[str, Any]:
            return {"version": self.version, "values": self.config}

        @router.put("/config")
        def put_config(update: ConfigUpdate) -> dict[str, Any]:
            try:
                self.apply_config(update)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            return {"version": self.version, "values": self.config}

        return router
