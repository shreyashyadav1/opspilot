from langchain_core.tools import StructuredTool

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
