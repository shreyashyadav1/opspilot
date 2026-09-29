"""FastAPI application: investigations, approval decisions and live traces.

POST /investigations                 start an investigation in the background
GET  /investigations                 newest first
GET  /investigations/{id}            status, trace, diagnosis, proposed action, approval
GET  /investigations/{id}/events     the same record as Server-Sent Events, on every change
POST /investigations/{id}/decision   approve or reject the proposed action
GET  /config                         model, available models, backend
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from opspilot_agent.llm import ModelSpecError, build_model
from opspilot_api.errors import ApiError
from opspilot_api.modelinfo import describe_model
from opspilot_api.schemas import (
    TERMINAL,
    CreateInvestigation,
    Decision,
    InvestigationDetail,
    InvestigationSummary,
    ServiceConfig,
)
from opspilot_api.service import InvestigationService, ModelFactory, ToolsetFactory
from opspilot_api.settings import ApiSettings
from opspilot_api.store import InvestigationStore
from opspilot_mcp.catalog import SERVICES

log = logging.getLogger(__name__)


def _service(request: Request) -> InvestigationService:
    return request.app.state.service


Service = Annotated[InvestigationService, Depends(_service)]


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
) -> FastAPI:
    settings = settings or ApiSettings.from_env()
    build = model_factory or build_model

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store = await InvestigationStore.open(settings.database)
        try:
            async with AsyncSqliteSaver.from_conn_string(str(settings.database)) as saver:
                service = InvestigationService(
                    store,
                    saver,
                    settings,
                    model_factory=build,
                    toolset_factory=toolset_factory,
                )
                await service.recover()
                app.state.service = service
                app.state.model_error = _model_error(build, settings.model)
                log.info("Agent API ready: model %s, %s backend", settings.model, settings.backend)
                try:
                    yield
                finally:
                    await service.close()
        finally:
            await store.close()

    app = FastAPI(
        title="OpsPilot agent API",
        version="0.1.0",
        description="Run incident investigations and decide on the actions they propose.",
        lifespan=lifespan,
    )

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/config")
    async def config(request: Request) -> ServiceConfig:
        return ServiceConfig(
            backend=settings.backend,
            model=describe_model(settings.model),
            models=[describe_model(spec) for spec in settings.models],
            model_error=request.app.state.model_error,
            services=list(SERVICES),
        )

    # -- investigations --------------------------------------------------------------------

    @app.get("/investigations")
    async def list_investigations(
        svc: Service, limit: Annotated[int, Query(ge=1, le=200)] = 50
    ) -> dict[str, list[InvestigationSummary]]:
        records = await svc.store.list(limit)
        return {"investigations": [InvestigationSummary.of(r) for r in records]}

    @app.post("/investigations", status_code=201)
    async def create_investigation(body: CreateInvestigation, svc: Service) -> InvestigationDetail:
        record = await svc.create(body)
        return await svc.detail(record.id)

    @app.get("/investigations/{investigation_id}")
    async def get_investigation(investigation_id: str, svc: Service) -> InvestigationDetail:
        return await svc.detail(investigation_id)

    @app.get("/investigations/{investigation_id}/events", response_class=EventSourceResponse)
    async def investigation_events(
        investigation_id: Annotated[str, Depends(_existing)], svc: Service
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
    async def decide(investigation_id: str, body: Decision, svc: Service) -> InvestigationDetail:
        """Approve or reject the proposed action. Approving runs it in the background (status
        `executing`); rejecting ends the investigation without executing anything."""
        await svc.decide(investigation_id, body)
        return await svc.detail(investigation_id)

    return app
