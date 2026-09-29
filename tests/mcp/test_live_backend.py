"""LiveBackend against stubbed HTTP endpoints and a stub docker CLI (no stack needed)."""

import json
import stat

import httpx
import pytest

from opspilot_mcp.backends.live import LiveBackend, LiveSettings
from opspilot_mcp.models import BackendError

SPRING_DOWN = {
    "status": "DOWN",
    "components": {
        "db": {"status": "DOWN", "details": {"error": "CannotGetJdbcConnectionException"}},
        "service": {"status": "UP", "details": {"version": "1.8.3"}},
    },
}


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/actuator/health":
        return httpx.Response(503, json=SPRING_DOWN)
    if path == "/health":
        return httpx.Response(200, json={"status": "ok", "version": "3.2.0"})
    if path == "/api/v1/query_range":
        assert 'job="payments"' in request.url.params["query"]
        start, step = int(request.url.params["start"]), int(request.url.params["step"])
        values = [[start, "0.5"], [start + step, "NaN"]]
        result = [{"metric": {"job": "payments", "client_name": "x"}, "values": values}]
        return httpx.Response(200, json={"status": "success", "data": {"result": result}})
    if path == "/deploys":
        return httpx.Response(200, json={"deploys": []})
    if path == "/deploys/orders/rollback":
        return httpx.Response(409, json={"detail": "orders has no earlier version to roll back to"})
    return httpx.Response(404)


@pytest.fixture
def backend(tmp_path):
    fake_docker = tmp_path / "docker"
    lines = [
        json.dumps({"timestamp": "2026-09-28T12:00:00.000Z", "level": "ERROR", "message": "boom"}),
        "not json",
    ]
    fake_docker.write_text("#!/bin/sh\n" + "".join(f"echo '{line}'\n" for line in lines))
    fake_docker.chmod(fake_docker.stat().st_mode | stat.S_IEXEC)
    settings = LiveSettings(docker_bin=str(fake_docker))
    return LiveBackend(settings, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_spring_health_reports_failing_components(backend):
    report = await backend.health("orders")
    assert report.status == "unhealthy"
    assert report.failing_components == ["db"]
    assert report.version == "1.8.3"
    assert (await backend.health("payments")).status == "healthy"


async def test_unreachable_service():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    backend = LiveBackend(client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)))
    assert (await backend.health("storefront")).status == "unreachable"


async def test_prometheus_range_query_parsing(backend):
    [series] = await backend.metric_series("payments", "upstream_error_rate", 15)
    assert series.labels == {"client_name": "x"}
    assert series.points[0][1] == 0.5
    # Steps Prometheus did not return are kept as gaps so staleness is visible.
    assert len(series.points) == 31
    assert series.points[-1][1] is None


async def test_logs_come_from_the_container_runtime(backend):
    [entry] = await backend.log_entries("orders", 15)
    assert (entry.service, entry.level, entry.message) == ("orders", "ERROR", "boom")


async def test_rollback_rejection_is_reported(backend):
    with pytest.raises(BackendError, match="no earlier version"):
        await backend.rollback("orders", "testing rejection path")
