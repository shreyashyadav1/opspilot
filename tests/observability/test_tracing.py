"""opspilot_observability.tracing: env parsing and W3C trace-context propagation."""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from opspilot_observability.tracing import (
    TRACE_PARENT_ENV,
    context_from_environ,
    context_from_traceparent,
    otlp_endpoint,
    subprocess_env,
    traceparent_of,
    tracing_enabled,
)


@pytest.fixture
def tracer():
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(InMemorySpanExporter()))
    return provider.get_tracer("test")


def test_tracing_enabled_reads_truthy_strings(monkeypatch):
    monkeypatch.delenv("OPSPILOT_TRACING_ENABLED", raising=False)
    assert tracing_enabled() is False
    for value in ("1", "true", "True", "yes", "on"):
        monkeypatch.setenv("OPSPILOT_TRACING_ENABLED", value)
        assert tracing_enabled() is True
    monkeypatch.setenv("OPSPILOT_TRACING_ENABLED", "false")
    assert tracing_enabled() is False


def test_otlp_endpoint_defaults_and_strips_trailing_slash(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert otlp_endpoint() == "http://localhost:4318"
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4318/")
    assert otlp_endpoint() == "http://jaeger:4318"


def test_traceparent_of_is_none_without_an_active_span():
    assert traceparent_of() is None


def test_traceparent_of_matches_the_current_span(tracer):
    with tracer.start_as_current_span("root") as span:
        value = traceparent_of()
        ctx = span.get_span_context()
    assert value is not None
    parts = value.split("-")
    assert len(parts) == 4
    assert parts[1] == format(ctx.trace_id, "032x")
    assert parts[2] == format(ctx.span_id, "016x")


def test_context_from_traceparent_round_trips_the_trace_id(tracer):
    with tracer.start_as_current_span("root") as span:
        value = traceparent_of()
        trace_id = span.get_span_context().trace_id

    parent_context = context_from_traceparent(value)
    with tracer.start_as_current_span("child", context=parent_context) as child:
        assert child.get_span_context().trace_id == trace_id


def test_context_from_traceparent_is_empty_for_none_or_blank():
    assert context_from_traceparent(None) == context_from_traceparent("")
    assert context_from_traceparent(None) == {}


def test_subprocess_env_is_empty_without_an_active_span():
    assert subprocess_env() == {}


def test_subprocess_env_carries_the_current_span(tracer):
    with tracer.start_as_current_span("root"):
        env = subprocess_env()
    assert TRACE_PARENT_ENV in env
    assert env[TRACE_PARENT_ENV].count("-") == 3


def test_context_from_environ_reads_the_env_var(monkeypatch, tracer):
    with tracer.start_as_current_span("root") as span:
        value = traceparent_of()
        trace_id = span.get_span_context().trace_id
    monkeypatch.setenv(TRACE_PARENT_ENV, value)

    with tracer.start_as_current_span("child", context=context_from_environ()) as child:
        assert child.get_span_context().trace_id == trace_id


def test_context_from_environ_is_empty_without_the_env_var(monkeypatch):
    monkeypatch.delenv(TRACE_PARENT_ENV, raising=False)
    assert context_from_environ() == {}
