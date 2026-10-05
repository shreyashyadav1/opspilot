"""OpenTelemetry wiring shared by the agent, the agent API and the MCP server.

One trace per investigation: the process that starts an investigation opens an "investigation"
span before it spawns the MCP tool server, graph nodes and model/tool calls create spans
underneath it, and the MCP server (a separate process, started over stdio) is handed the trace
context through an environment variable so its own tool-call spans and outbound HTTP calls to
the demo services land in the same trace.

Exporting is opt-in (`OPSPILOT_TRACING_ENABLED`), so importing this module and calling
`configure()` is always safe without a trace backend running: with tracing disabled, spans are
still created (so trace ids are available for correlation) but no span processor is attached, so
nothing is ever sent anywhere and no network backend is required. This mirrors the convention the
demo services already use for their own OTLP export (see
`demo-system/services/opsdemo/common/service.py`).
"""

from __future__ import annotations

import os

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

TRACING_ENABLED_ENV = "OPSPILOT_TRACING_ENABLED"
OTLP_ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"
DEFAULT_OTLP_ENDPOINT = "http://localhost:4318"

# Carries the investigation's trace context to the MCP server subprocess (stdio transport has no
# headers to piggyback on, so an environment variable does the job instead).
TRACE_PARENT_ENV = "OPSPILOT_TRACE_PARENT"

_configured = False


def tracing_enabled() -> bool:
    return os.getenv(TRACING_ENABLED_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def otlp_endpoint() -> str:
    return (os.getenv(OTLP_ENDPOINT_ENV) or DEFAULT_OTLP_ENDPOINT).rstrip("/")


def configure(service_name: str, service_version: str = "0.1.0") -> TracerProvider:
    """Build this process's TracerProvider and install it as the global one.

    Safe to call more than once per process (later calls build and return a provider but do not
    replace the global one): call it once at the top of every entry point (the CLI, the agent
    API, the benchmark CLI, the MCP server). Tests do not call this at all; they build their own
    provider with an in-memory exporter and pass it directly to the code under test.
    """
    global _configured
    resource = Resource.create({"service.name": service_name, "service.version": service_version})
    provider = TracerProvider(resource=resource)
    if tracing_enabled():
        exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint()}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
    if not _configured:
        trace.set_tracer_provider(provider)
        _configured = True
    return provider


def get_tracer(name: str = "opspilot") -> trace.Tracer:
    """A tracer from the global provider (a harmless no-op tracer if `configure` was never
    called, which is exactly what unconfigured tests get)."""
    return trace.get_tracer(name)


def traceparent_of(context: otel_context.Context | None = None) -> str | None:
    """The W3C `traceparent` value for the current (or given) context, if a span is active."""
    carrier: dict[str, str] = {}
    inject(carrier, context=context)
    return carrier.get("traceparent")


def context_from_traceparent(traceparent: str | None) -> otel_context.Context:
    """A Context whose current span is the remote span described by `traceparent`.

    Spans started with this context as their parent are linked to the right trace even when the
    original span (and often the original process) is long gone, which is what lets the
    "approval_wait" span and a resumed investigation's spans land in the same trace as the run
    that was paused, possibly across an API restart.
    """
    if not traceparent:
        return otel_context.Context()
    return extract({"traceparent": traceparent})


def subprocess_env(context: otel_context.Context | None = None) -> dict[str, str]:
    """Environment variables that carry the current trace context to a child process.

    Empty when there is no active span (tracing disabled, or called outside one), so merging
    this into a subprocess's environment is always safe.
    """
    value = traceparent_of(context)
    return {TRACE_PARENT_ENV: value} if value else {}


def context_from_environ() -> otel_context.Context:
    """The parent context carried into this process by `subprocess_env`, if any."""
    return context_from_traceparent(os.environ.get(TRACE_PARENT_ENV))
