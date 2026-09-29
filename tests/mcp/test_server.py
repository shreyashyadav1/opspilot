"""The MCP tool surface, exercised through a real client session (in memory)."""

import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from opspilot_mcp.server import WRITE_TOOLS, build_server


@pytest.fixture
def server(simulate):
    return build_server(simulate("bad_config_deploy", "orders"))


async def call(server, name: str, args: dict) -> tuple[bool, dict | str]:
    # One session per call keeps each anyio task group inside a single test task; the
    # backend (and its state) is shared through the server object.
    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool(name, args)
    text = result.content[0].text
    return result.isError, text if result.isError else json.loads(text)


async def test_tools_are_annotated_read_only_or_destructive(server):
    async with create_connected_server_and_client_session(server) as session:
        tools = {t.name: t for t in (await session.list_tools()).tools}
    assert set(tools) == {
        "get_service_health",
        "query_metric",
        "search_logs",
        "get_recent_deploys",
        "rollback_deploy",
    }
    for name, tool in tools.items():
        assert tool.annotations.readOnlyHint is (name not in WRITE_TOOLS)
        assert tool.annotations.destructiveHint is (name in WRITE_TOOLS)


async def test_health_of_all_services(server):
    error, payload = await call(server, "get_service_health", {})
    assert not error
    assert [s["service"] for s in payload["services"]] == ["storefront", "orders", "payments"]


async def test_metric_and_log_results_are_compact_json(server):
    error, metric = await call(
        server, "query_metric", {"service": "orders", "metric": "error_rate"}
    )
    assert not error
    assert metric["series"][0]["trend"] == "rising"
    error, logs = await call(server, "search_logs", {"service": "orders", "level": "ERROR"})
    assert not error
    assert len(json.dumps(logs)) < 6000


@pytest.mark.parametrize(
    ("name", "args", "fragment"),
    [
        ("query_metric", {"service": "orders", "metric": "cpu"}, "Input should be"),
        ("query_metric", {"service": "payments", "metric": "db_pool_active"}, "only available"),
        ("search_logs", {"service": "billing"}, "Input should be"),
        ("search_logs", {"service": "orders", "since_minutes": 600}, "less than or equal"),
        ("rollback_deploy", {"service": "orders", "reason": "x"}, "at least 10"),
    ],
)
async def test_invalid_arguments_return_recoverable_errors(server, name, args, fragment):
    error, message = await call(server, name, args)
    assert error
    assert fragment in message


async def test_rollback_records_event(server):
    error, payload = await call(
        server, "rollback_deploy", {"service": "orders", "reason": "payments-v2 does not resolve"}
    )
    assert not error
    assert payload["event"]["kind"] == "rollback"
    _, deploys = await call(
        server, "get_recent_deploys", {"service": "orders", "since_minutes": 30}
    )
    assert [d["kind"] for d in deploys["deploys"]] == ["rollback", "deploy"]
