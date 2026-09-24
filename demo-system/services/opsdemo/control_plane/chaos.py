"""Fault injection with ground-truth records, orchestrated through the services' admin API."""

from __future__ import annotations

import itertools
import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, computed_field

from opsdemo.control_plane.deploys import (
    BAD_CONFIG_CHANGES,
    BASELINES,
    DeployEvent,
    DeployRegistry,
    DeployRequest,
    RollbackRequest,
)

log = logging.getLogger("control_plane.chaos")


class FaultType(StrEnum):
    LATENCY_SPIKE = "latency_spike"
    ERROR_SPIKE = "error_spike"
    DB_POOL_EXHAUSTION = "db_pool_exhaustion"
    BAD_CONFIG_DEPLOY = "bad_config_deploy"
    DEPENDENCY_OUTAGE = "dependency_outage"


# Ground-truth category recorded for each fault type. These are the labels the agent's
# diagnosis is scored against.
CATEGORY: dict[FaultType, str] = {
    FaultType.LATENCY_SPIKE: "latency",
    FaultType.ERROR_SPIKE: "error_rate",
    FaultType.DB_POOL_EXHAUSTION: "resource_exhaustion",
    FaultType.BAD_CONFIG_DEPLOY: "bad_deploy",
    FaultType.DEPENDENCY_OUTAGE: "dependency_outage",
}

_ALL = frozenset(BASELINES)
ALLOWED_TARGETS: dict[FaultType, frozenset[str]] = {
    FaultType.LATENCY_SPIKE: _ALL,
    FaultType.ERROR_SPIKE: _ALL,
    FaultType.DB_POOL_EXHAUSTION: frozenset({"orders"}),
    FaultType.BAD_CONFIG_DEPLOY: _ALL,
    FaultType.DEPENDENCY_OUTAGE: frozenset({"orders", "payments"}),
}


class LatencyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delay_ms: int = Field(1200, ge=50, le=10_000)
    jitter_ms: int = Field(150, ge=0, le=5_000)


class ErrorParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error_rate: float = Field(0.4, gt=0.0, le=1.0)


class NoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


PARAMS: dict[FaultType, type[BaseModel]] = {
    FaultType.LATENCY_SPIKE: LatencyParams,
    FaultType.ERROR_SPIKE: ErrorParams,
    FaultType.DB_POOL_EXHAUSTION: NoParams,
    FaultType.BAD_CONFIG_DEPLOY: NoParams,
    FaultType.DEPENDENCY_OUTAGE: NoParams,
}


def failure_fields(fault_type: FaultType, params: BaseModel) -> dict[str, Any]:
    """Admin-API failure-mode fields that implement a fault (not used for bad deploys)."""
    match fault_type:
        case FaultType.LATENCY_SPIKE:
            assert isinstance(params, LatencyParams)
            return {"latency_ms": params.delay_ms, "latency_jitter_ms": params.jitter_ms}
        case FaultType.ERROR_SPIKE:
            assert isinstance(params, ErrorParams)
            return {"error_rate": params.error_rate}
        case FaultType.DB_POOL_EXHAUSTION:
            return {"pool_exhaustion": True}
        case FaultType.DEPENDENCY_OUTAGE:
            return {"outage": True}
    raise ValueError(f"{fault_type} is not implemented through failure modes")


class FaultRequest(BaseModel):
    type: FaultType
    target: str
    params: dict[str, Any] = Field(default_factory=dict)


class GroundTruth(BaseModel):
    service: str
    category: str


class FaultRecord(BaseModel):
    id: str
    type: FaultType
    target: str
    params: dict[str, Any]
    ground_truth: GroundTruth
    injected_at: datetime
    deploy_id: str | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def active(self) -> bool:
        return self.resolved_at is None


class ChaosError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class ServiceAdmin:
    """Client for the internal admin API that every demo service exposes."""

    def __init__(self, urls: dict[str, str], client: httpx.AsyncClient) -> None:
        self.urls = urls
        self._client = client

    async def put_failures(self, service: str, modes: dict[str, Any]) -> None:
        await self._call("PUT", service, "/admin/failures", modes)

    async def clear_failures(self, service: str) -> None:
        await self._call("DELETE", service, "/admin/failures")

    async def put_config(self, service: str, version: str, values: dict[str, Any]) -> None:
        await self._call("PUT", service, "/admin/config", {"version": version, "values": values})

    async def _call(self, method: str, service: str, path: str, body: Any = None) -> None:
        url = self.urls[service] + path
        try:
            response = await self._client.request(method, url, json=body, timeout=5.0)
        except httpx.HTTPError as exc:
            raise ChaosError(502, f"{service} admin API unreachable: {exc!r}") from exc
        if response.status_code >= 400:
            raise ChaosError(502, f"{service} rejected {method} {path}: {response.text[:300]}")


class ControlPlane:
    def __init__(self, admin: ServiceAdmin, registry: DeployRegistry) -> None:
        self.admin = admin
        self.registry = registry
        self.faults: list[FaultRecord] = []
        self._modes: dict[str, dict[str, Any]] = {s: {} for s in BASELINES}
        self._ids = itertools.count(1)
        self.registry.reset()

    # -- deploys ---------------------------------------------------------------------------

    async def deploy(self, request: DeployRequest) -> DeployEvent:
        if request.service not in BASELINES:
            raise ChaosError(404, f"unknown service {request.service!r}")
        event = self.registry.record_deploy(request)
        try:
            await self.admin.put_config(event.service, event.version, event.config)
        except ChaosError:
            self.registry.discard(event.id)
            raise
        log.info("Deployed %s %s", event.service, event.version, extra={"deploy_id": event.id})
        return event

    async def rollback(self, service: str, request: RollbackRequest) -> DeployEvent:
        if service not in BASELINES:
            raise ChaosError(404, f"unknown service {service!r}")
        try:
            event, rolled_back = self.registry.record_rollback(service, request)
        except LookupError as exc:
            raise ChaosError(409, str(exc)) from exc
        try:
            await self.admin.put_config(service, event.version, event.config)
        except ChaosError:
            self.registry.discard(event.id)
            raise
        for fault in self.faults:
            if fault.active and fault.deploy_id == rolled_back.id:
                self._resolve(fault, "rollback")
        log.info("Rolled back %s to %s", service, event.version, extra={"deploy_id": event.id})
        return event

    # -- faults ----------------------------------------------------------------------------

    async def inject(self, request: FaultRequest) -> FaultRecord:
        if request.target not in ALLOWED_TARGETS[request.type]:
            allowed = ", ".join(sorted(ALLOWED_TARGETS[request.type]))
            raise ChaosError(422, f"{request.type} supports targets: {allowed}")
        try:
            params = PARAMS[request.type].model_validate(request.params)
        except ValueError as exc:
            raise ChaosError(422, f"invalid params: {exc}") from exc
        if any(f.active and f.target == request.target for f in self.faults):
            raise ChaosError(409, f"{request.target} already has an active fault")

        deploy_id = None
        if request.type is FaultType.BAD_CONFIG_DEPLOY:
            change = BAD_CONFIG_CHANGES[request.target]
            event = await self.deploy(
                DeployRequest(
                    service=request.target,
                    change_summary=change.summary,
                    author=change.author,
                    config=change.values,
                )
            )
            deploy_id = event.id
        else:
            modes = {**self._modes[request.target], **failure_fields(request.type, params)}
            await self.admin.put_failures(request.target, modes)
            self._modes[request.target] = modes

        record = FaultRecord(
            id=f"flt-{next(self._ids):04d}",
            type=request.type,
            target=request.target,
            params=params.model_dump(),
            ground_truth=GroundTruth(service=request.target, category=CATEGORY[request.type]),
            injected_at=datetime.now(UTC),
            deploy_id=deploy_id,
        )
        self.faults.append(record)
        log.info("Injected %s into %s", record.type, record.target, extra={"fault_id": record.id})
        return record

    async def clear(self, fault_id: str) -> FaultRecord:
        record = next((f for f in self.faults if f.id == fault_id), None)
        if record is None:
            raise ChaosError(404, f"unknown fault {fault_id!r}")
        if not record.active:
            return record
        if record.type is FaultType.BAD_CONFIG_DEPLOY:
            await self.rollback(record.target, RollbackRequest(reason="fault cleared"))
            self._resolve(record, "cleared")
            return record
        fields = failure_fields(record.type, PARAMS[record.type].model_validate(record.params))
        modes = {k: v for k, v in self._modes[record.target].items() if k not in fields}
        await self.admin.put_failures(record.target, modes)
        self._modes[record.target] = modes
        self._resolve(record, "cleared")
        return record

    async def reset(self) -> int:
        """Clear every failure mode, restore baseline versions and config, reseed history."""
        for service, baseline in BASELINES.items():
            await self.admin.clear_failures(service)
            await self.admin.put_config(service, baseline.version, baseline.config)
        self._modes = {s: {} for s in BASELINES}
        self.registry.reset()
        active = [f for f in self.faults if f.active]
        for fault in active:
            self._resolve(fault, "reset")
        log.info("Reset demo system", extra={"resolved_faults": len(active)})
        return len(active)

    @staticmethod
    def _resolve(fault: FaultRecord, by: str) -> None:
        fault.resolved_at = datetime.now(UTC)
        fault.resolved_by = by
