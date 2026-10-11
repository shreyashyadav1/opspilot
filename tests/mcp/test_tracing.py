"""Spans each MCP tool call creates, captured with an in-memory exporter."""

from __future__ import annotations

from mcp.shared.memory import create_connected_server_and_client_session
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from opspilot_mcp.server import build_server
from opspilot_observability.tracing import traceparent_of


def _provider() -> tuple[TracerProvider, InMemorySpanExporter]:
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


async def test_tool_call_span_carries_name_args_and_result_size(simulate):
    provider, exporter = _provider()
    server = build_server(simulate("bad_config_deploy", "orders"), tracer_provider=provider)

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool("get_service_health", {"service": "orders"})

    assert not result.isError
    [span] = [s for s in exporter.get_finished_spans() if s.name == "mcp.tool/get_service_health"]
    assert span.attributes["opspilot.tool.name"] == "get_service_health"
    assert "orders" in span.attributes["opspilot.tool.args"]
    result_size = span.attributes["opspilot.tool.result_size"]
    assert result_size > 0
    assert result_size == len(result.content[0].text)


async def test_failed_tool_call_is_still_traced(simulate):
    # Schema-invalid arguments (an unknown enum value, say) never reach the handler, so there is
    # nothing to trace; a ToolError the handler itself raises (an unsupported service/metric
    # combination) does reach it, after the span has already started.
    provider, exporter = _provider()
    server = build_server(simulate("bad_config_deploy", "orders"), tracer_provider=provider)

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool(
            "query_metric", {"service": "payments", "metric": "db_pool_active"}
        )

    assert result.isError
    [span] = [s for s in exporter.get_finished_spans() if s.name == "mcp.tool/query_metric"]
    assert span.status.status_code.name == "ERROR"


async def test_tool_calls_are_children_of_the_investigation_that_started_the_server(
    simulate, monkeypatch
):
    # build_server() reads OPSPILOT_TRACE_PARENT once, the same way the real subprocess does
    # (see opspilot_mcp.__main__ and opspilot_agent.mcp_client.stdio_connection).
    root_provider = TracerProvider()
    with root_provider.get_tracer("test").start_as_current_span("investigation") as root:
        trace_id = root.get_span_context().trace_id
        monkeypatch.setenv("OPSPILOT_TRACE_PARENT", traceparent_of())

    provider, exporter = _provider()
    server = build_server(simulate("bad_config_deploy", "orders"), tracer_provider=provider)

    async with create_connected_server_and_client_session(server) as session:
        await session.call_tool("get_service_health", {})
        await session.call_tool("get_recent_deploys", {})

    spans = exporter.get_finished_spans()
    assert len(spans) == 2
    assert all(span.parent is not None and span.parent.trace_id == trace_id for span in spans)
