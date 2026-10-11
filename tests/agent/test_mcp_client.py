from langchain_core.tools import StructuredTool
from opentelemetry.sdk.trace import TracerProvider

from opspilot_agent.mcp_client import ToolSet, stdio_connection


def _tool(name: str, metadata: dict | None) -> StructuredTool:
    return StructuredTool.from_function(
        func=lambda: "ok", name=name, description=name, metadata=metadata
    )


def test_model_api_keys_never_reach_the_tool_server(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "not-a-real-key")
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    monkeypatch.setenv("OPSPILOT_PROMETHEUS_URL", "http://prometheus.test:9090")
    connection = stdio_connection("simulated")
    assert "GROQ_API_KEY" not in connection["env"]
    assert "OPENAI_API_KEY" not in connection["env"]
    assert connection["env"]["OPSPILOT_PROMETHEUS_URL"] == "http://prometheus.test:9090"
    assert connection["args"][-2:] == ["--backend", "simulated"]


def test_tracing_settings_reach_the_tool_server_but_not_exporter_credentials(monkeypatch):
    monkeypatch.setenv("OPSPILOT_TRACING_ENABLED", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger.test:4318")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "authorization=Bearer not-a-real-token")
    env = stdio_connection("simulated")["env"]
    assert env["OPSPILOT_TRACING_ENABLED"] == "true"
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://jaeger.test:4318"
    assert "OTEL_EXPORTER_OTLP_HEADERS" not in env


def test_the_current_trace_context_reaches_the_tool_server():
    with TracerProvider().get_tracer("test").start_as_current_span("investigation") as span:
        env = stdio_connection("simulated")["env"]
    context = span.get_span_context()
    version, trace_id, span_id, flags = env["OPSPILOT_TRACE_PARENT"].split("-")
    assert (version, trace_id, span_id) == (
        "00",
        f"{context.trace_id:032x}",
        f"{context.span_id:016x}",
    )
    assert int(flags, 16) & 1, "the sampled flag must survive, or the server's spans are dropped"


def test_no_trace_context_is_passed_outside_an_investigation():
    assert "OPSPILOT_TRACE_PARENT" not in stdio_connection("simulated")["env"]


def test_only_explicitly_read_only_tools_are_read_tools():
    tools = ToolSet.from_tools(
        [
            _tool("get_service_health", {"readOnlyHint": True}),
            _tool("rollback_deploy", {"readOnlyHint": False, "destructiveHint": True}),
            _tool("mystery", None),
        ]
    )
    assert [t.name for t in tools.read] == ["get_service_health"]
    assert set(tools.write) == {"rollback_deploy", "mystery"}
