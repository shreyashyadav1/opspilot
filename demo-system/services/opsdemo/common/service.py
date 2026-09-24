"""Application factory shared by the Python services."""

from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
from fastapi import FastAPI
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from starlette.responses import Response

from opsdemo.common.http import TelemetryMiddleware
from opsdemo.common.logs import configure_logging
from opsdemo.common.metrics import metrics_response
from opsdemo.common.runtime import ServiceRuntime

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def build_tracer_provider(runtime: ServiceRuntime) -> TracerProvider:
    """Spans are always created so trace ids reach the logs; export is opt-in via OTLP env."""
    provider = TracerProvider(
        resource=Resource.create({"service.name": runtime.name, "service.version": runtime.version})
    )
    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    return provider


def instrumented_client(provider: TracerProvider, **kwargs: Any) -> httpx.AsyncClient:
    client = httpx.AsyncClient(**kwargs)
    HTTPXClientInstrumentor.instrument_client(client, tracer_provider=provider)
    return client


def create_service_app(
    runtime: ServiceRuntime, *, title: str, lifespan: Lifespan | None = None
) -> FastAPI:
    """Build a FastAPI app with health, metrics, admin API, telemetry and tracing.

    `lifespan` runs after `app.state.runtime` and `app.state.tracer_provider` are set.
    """
    configure_logging(runtime.name, version_getter=lambda: runtime.version)
    provider = build_tracer_provider(runtime)

    app = FastAPI(title=title, version=runtime.version, lifespan=lifespan)
    app.state.runtime = runtime
    app.state.tracer_provider = provider
    app.add_middleware(TelemetryMiddleware, runtime=runtime)
    app.include_router(runtime.admin_router())

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": runtime.name, "version": runtime.version}

    @app.get("/metrics", tags=["ops"], include_in_schema=False)
    def metrics() -> Response:
        return metrics_response()

    FastAPIInstrumentor.instrument_app(
        app, tracer_provider=provider, excluded_urls="health,metrics,admin"
    )
    return app
