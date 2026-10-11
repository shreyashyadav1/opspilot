"""Control plane API.

`/deploys` is the deploy registry: the history a CD system would show, plus rollbacks. It is
part of what an investigator (and the OpsPilot MCP server) may read.

`/chaos` is the benchmark harness's side: fault injection and ground truth. The MCP server is
never configured with it.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from opsdemo.common.logs import configure_logging
from opsdemo.common.service import build_tracer_provider, instrumented_client
from opsdemo.control_plane.chaos import (
    ChaosError,
    ControlPlane,
    FaultRecord,
    FaultRequest,
    FaultTypeInfo,
    ServiceAdmin,
    fault_catalog,
)
from opsdemo.control_plane.deploys import (
    BASELINES,
    DeployEvent,
    DeployRegistry,
    DeployRequest,
    RollbackRequest,
)

log = logging.getLogger("control_plane")


def service_urls_from_env() -> dict[str, str]:
    raw = os.getenv(
        "CP_SERVICE_URLS",
        "storefront=http://storefront:8080,orders=http://orders:8080,payments=http://payments:8080",
    )
    urls = dict(item.split("=", 1) for item in raw.split(",") if item)
    missing = set(BASELINES) - set(urls)
    if missing:
        raise RuntimeError(f"CP_SERVICE_URLS is missing: {', '.join(sorted(missing))}")
    return {name: url.rstrip("/") for name, url in urls.items()}


async def _reset_when_ready(plane: ControlPlane, attempts: int = 45, delay_s: float = 2.0) -> None:
    """Push baseline state once every service is up, so a fresh stack starts consistent."""
    for attempt in range(1, attempts + 1):
        try:
            await plane.reset()
            log.info("Baseline applied to all services", extra={"attempt": attempt})
            return
        except ChaosError as exc:
            log.info("Waiting for services before applying baseline: %s", exc.detail)
            await asyncio.sleep(delay_s)
    log.error("Services did not become ready; baseline not applied")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Instrumented so a rollback (and any other deploy-registry call) that arrives with a
    # traceparent header - from the MCP server, on behalf of an investigation - continues that
    # trace into the target service's admin API.
    client = instrumented_client(tracer_provider)
    app.state.plane = ControlPlane(ServiceAdmin(service_urls_from_env(), client), DeployRegistry())
    task = None
    if os.getenv("CP_RESET_ON_STARTUP", "true").lower() == "true":
        task = asyncio.create_task(_reset_when_ready(app.state.plane))
    yield
    if task is not None:
        task.cancel()
    await client.aclose()


configure_logging("control-plane")
tracer_provider = build_tracer_provider("control-plane")
app = FastAPI(title="OpsPilot demo control plane", lifespan=lifespan)
# /chaos/* (fault injection, benchmark-only) is excluded so fault injection itself leaves no
# trace, matching how it is already kept out of logs and metrics.
FastAPIInstrumentor.instrument_app(
    app, tracer_provider=tracer_provider, excluded_urls="health,chaos"
)


@app.exception_handler(ChaosError)
async def chaos_error_handler(_: Request, exc: ChaosError) -> JSONResponse:
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


def _plane(request: Request) -> ControlPlane:
    return request.app.state.plane


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "control-plane"}


# -- deploy registry ----------------------------------------------------------------------


@app.get("/deploys")
def list_deploys(
    request: Request,
    service: str | None = None,
    since_minutes: int = Query(24 * 60, ge=1, le=14 * 24 * 60),
) -> dict[str, list[DeployEvent]]:
    since = datetime.now(UTC) - timedelta(minutes=since_minutes)
    return {"deploys": _plane(request).registry.list(service=service, since=since)}


@app.post("/deploys", status_code=201)
async def create_deploy(request: Request, body: DeployRequest) -> DeployEvent:
    return await _plane(request).deploy(body)


@app.post("/deploys/{service}/rollback", status_code=201)
async def rollback(request: Request, service: str, body: RollbackRequest) -> DeployEvent:
    return await _plane(request).rollback(service, body)


# -- chaos (benchmark harness only) --------------------------------------------------------


@app.get("/chaos/catalog")
def catalog() -> dict[str, list[FaultTypeInfo]]:
    """Fault types with their ground-truth category, allowed targets and parameter bounds."""
    return {"fault_types": fault_catalog()}


@app.get("/chaos/faults")
def list_faults(request: Request, active_only: bool = False) -> dict[str, list[FaultRecord]]:
    faults = _plane(request).faults
    return {"faults": [f for f in faults if f.active] if active_only else faults}


@app.post("/chaos/faults", status_code=201)
async def inject_fault(request: Request, body: FaultRequest) -> FaultRecord:
    return await _plane(request).inject(body)


@app.delete("/chaos/faults/{fault_id}")
async def clear_fault(request: Request, fault_id: str) -> FaultRecord:
    return await _plane(request).clear(fault_id)


@app.post("/chaos/reset")
async def reset(request: Request) -> dict[str, Any]:
    resolved = await _plane(request).reset()
    return {"status": "reset", "resolved_faults": resolved}
