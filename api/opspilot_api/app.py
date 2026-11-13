"""FastAPI application: investigations, approval decisions, live traces, demo faults, benchmarks.

POST /investigations                 start an investigation in the background
GET  /investigations                 newest first
GET  /investigations/{id}            status, trace, diagnosis, proposed action, approval
GET  /investigations/{id}/events     the same record as Server-Sent Events, on every change
POST /investigations/{id}/decision   approve or reject the proposed action
GET  /config                         model, available models, backend, demo availability
GET  /me                             who the API key belongs to and its role
GET  /demo/catalog, /demo/faults     the control plane's fault catalog and injected faults
POST /demo/faults, /demo/reset       inject a fault, reset the demo system
GET  /benchmarks, /benchmarks/{run}  benchmark runs found in the results directory

With OPSPILOT_API_KEYS set, every route but /health needs a key: reads need the viewer role,
starting investigations and demo faults need operator, and decisions need approver.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from opentelemetry.sdk.trace import TracerProvider

from opspilot_agent.llm import ModelSpecError, build_model
from opspilot_api.auth import Authenticator, Principal, Role
from opspilot_api.benchmarks import BenchmarkRun, BenchmarkRunDetail, list_runs, load_run
from opspilot_api.demo import ChaosClient, FaultInjection
from opspilot_api.errors import ApiError
from opspilot_api.modelinfo import describe_model
from opspilot_api.schemas import (
    TERMINAL,
    CreateInvestigation,
    Decision,
    InvestigationDetail,
    InvestigationSummary,
    Me,
    ServiceConfig,
)
from opspilot_api.service import InvestigationService, ModelFactory, ToolsetFactory
from opspilot_api.settings import ApiSettings
from opspilot_api.store import InvestigationStore
from opspilot_mcp.catalog import SERVICES
from opspilot_observability.tracing import configure

log = logging.getLogger(__name__)


def _service(request: Request) -> InvestigationService:
    return request.app.state.service


def _chaos(request: Request) -> ChaosClient:
    client: ChaosClient | None = request.app.state.chaos
    if client is None:
        raise ApiError(404, "Demo fault injection is disabled. Set OPSPILOT_CHAOS_URL.")
    return client


def _role(role: Role):
    def check(request: Request, authorization: Annotated[str | None, Header()] = None) -> Principal:
        authenticator: Authenticator = request.app.state.authenticator
        return authenticator.require(authorization, role)

    return check


Service = Annotated[InvestigationService, Depends(_service)]
Chaos = Annotated[ChaosClient, Depends(_chaos)]
Viewer = Annotated[Principal, Depends(_role("viewer"))]
Operator = Annotated[Principal, Depends(_role("operator"))]
Approver = Annotated[Principal, Depends(_role("approver"))]


async def _existing(investigation_id: str, svc: Service) -> str:
    await svc.get(investigation_id)
    return investigation_id


def _model_error(build: ModelFactory, spec: str) -> str | None:
    """Why the configured model cannot be used (for example a missing key), if it cannot."""
    try:
        build(spec)
    except ModelSpecError as exc:
        return str(exc)
    return None


def create_app(
    settings: ApiSettings | None = None,
    *,
    model_factory: ModelFactory | None = None,
    toolset_factory: ToolsetFactory | None = None,
    chaos_transport: httpx.AsyncBaseTransport | None = None,
    tracer_provider: TracerProvider | None = None,
) -> FastAPI:
    settings = settings or ApiSettings.from_env()
    build = model_factory or build_model
    tracer_provider = tracer_provider or configure("opspilot-agent-api")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store = await InvestigationStore.open(settings.records_db)
        chaos = ChaosClient(settings.chaos_url, chaos_transport) if settings.chaos_url else None
        try:
            async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoints_db)) as saver:
                service = InvestigationService(
                    store,
                    saver,
                    settings,
                    model_factory=build,
                    toolset_factory=toolset_factory,
                    tracer_provider=tracer_provider,
                )
                await service.recover()
                app.state.service, app.state.chaos = service, chaos
                app.state.model_error = _model_error(build, settings.model)
                log.info(
                    "Agent API ready: model %s, %s backend, demo faults %s",
                    settings.model,
                    settings.backend,
                    "enabled" if chaos else "disabled",
                )
                try:
                    yield
                finally:
                    await service.close()
        finally:
            if chaos is not None:
                await chaos.aclose()
            await store.close()

    app = FastAPI(
        title="OpsPilot agent API",
        version="0.1.0",
        description="Run incident investigations and decide on the actions they propose.",
        lifespan=lifespan,
    )

    # Set here rather than in the lifespan so a bad key list fails before anything starts.
    app.state.authenticator = Authenticator(settings.api_keys, settings.anonymous_role)

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/config")
    async def config(request: Request, _: Viewer) -> ServiceConfig:
        return ServiceConfig(
            backend=settings.backend,
            model=describe_model(settings.model),
            models=[describe_model(spec) for spec in settings.models],
            model_error=request.app.state.model_error,
            demo_enabled=request.app.state.chaos is not None,
            services=list(SERVICES),
            auth_required=request.app.state.authenticator.enabled,
        )

    @app.get("/me")
    async def me(request: Request, principal: Viewer) -> Me:
        return Me(
            name=principal.name,
            role=principal.role,
            authenticated=principal.authenticated,
            keys_enabled=request.app.state.authenticator.enabled,
        )

    # -- investigations --------------------------------------------------------------------

    @app.get("/investigations")
    async def list_investigations(
        svc: Service, _: Viewer, limit: Annotated[int, Query(ge=1, le=200)] = 50
    ) -> dict[str, list[InvestigationSummary]]:
        records = await svc.store.list(limit)
        return {"investigations": [InvestigationSummary.of(r) for r in records]}

    @app.post("/investigations", status_code=201)
    async def create_investigation(
        body: CreateInvestigation, svc: Service, _: Operator
    ) -> InvestigationDetail:
        record = await svc.create(body)
        return await svc.detail(record.id)

    @app.get("/investigations/{investigation_id}")
    async def get_investigation(
        investigation_id: str, svc: Service, _: Viewer
    ) -> InvestigationDetail:
        return await svc.detail(investigation_id)

    @app.get("/investigations/{investigation_id}/events", response_class=EventSourceResponse)
    async def investigation_events(
        _: Viewer, investigation_id: Annotated[str, Depends(_existing)], svc: Service
    ) -> AsyncIterator[ServerSentEvent]:
        """A `snapshot` event with the full record on connect and after every change, then
        `end` once the investigation reaches a terminal status."""
        while True:
            seen = svc.version(investigation_id)
            detail = await svc.detail(investigation_id)
            yield ServerSentEvent(event="snapshot", data=detail, id=str(seen))
            if detail.status in TERMINAL:
                yield ServerSentEvent(event="end", data={"status": detail.status})
                return
            await svc.wait_for_change(investigation_id, seen)

    @app.post("/investigations/{investigation_id}/decision")
    async def decide(
        investigation_id: str, body: Decision, svc: Service, principal: Approver
    ) -> InvestigationDetail:
        """Approve or reject the proposed action. Approving runs it in the background (status
        `executing`); rejecting ends the investigation without executing anything. With API
        keys on, the reviewer is the key's name."""
        await svc.decide(investigation_id, body, principal)
        return await svc.detail(investigation_id)

    # -- demo fault injection (the harness side; never offered to the agent) ------------------

    @app.get("/demo/catalog")
    async def demo_catalog(_: Viewer, client: Chaos) -> Any:
        return await client.catalog()

    @app.get("/demo/faults")
    async def demo_faults(_: Viewer, client: Chaos) -> Any:
        return await client.faults()

    @app.post("/demo/faults", status_code=201)
    async def demo_inject(_: Operator, body: FaultInjection, client: Chaos) -> Any:
        return await client.inject(body.model_dump())

    @app.delete("/demo/faults/{fault_id}")
    async def demo_clear(_: Operator, fault_id: str, client: Chaos) -> Any:
        return await client.clear(fault_id)

    @app.post("/demo/reset")
    async def demo_reset(_: Operator, client: Chaos) -> Any:
        return await client.reset()

    # -- benchmark results -----------------------------------------------------------------

    @app.get("/benchmarks")
    async def benchmarks(_: Viewer) -> dict[str, list[BenchmarkRun]]:
        return {"runs": list_runs(settings.results_dir)}

    @app.get("/benchmarks/{run_id}")
    async def benchmark(run_id: str, _: Viewer) -> BenchmarkRunDetail:
        run = load_run(settings.results_dir, run_id)
        if run is None:
            raise ApiError(404, f"no benchmark run {run_id!r} in the results directory")
        return run

    return app
