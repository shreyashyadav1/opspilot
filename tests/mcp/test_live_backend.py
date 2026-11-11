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


def _loki_backend(handler, **overrides) -> LiveBackend:
    settings = LiveSettings(log_backend="loki", loki_url="http://loki.test:3100", **overrides)
    return LiveBackend(settings, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _line(ts: str, level: str, message: str) -> str:
    return json.dumps({"timestamp": ts, "level": level, "message": message})


async def test_logs_can_come_from_loki_without_the_docker_cli():
    seen: list[httpx.Request] = []

    def loki(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.path == "/loki/api/v1/query_range"
        streams = [
            {
                "stream": {"service": "payments", "stream": "stdout"},
                # Loki returns newest first for direction=backward.
                "values": [
                    ["1790000002000000000", _line("2026-09-28T12:00:02Z", "ERROR", "second")],
                    ["1790000001000000000", "not json"],
                ],
            },
            {
                "stream": {"service": "payments", "stream": "stderr"},
                "values": [["1790000000000000000", _line("2026-09-28T12:00:00Z", "WARN", "first")]],
            },
        ]
        data = {"resultType": "streams", "result": streams}
        return httpx.Response(200, json={"status": "success", "data": data})

    backend = _loki_backend(loki, loki_tenant="demo", docker_bin="/nonexistent/docker")
    entries = await backend.log_entries("payments", 15)

    assert [(e.level, e.message) for e in entries] == [("WARN", "first"), ("ERROR", "second")]
    assert all(e.service == "payments" for e in entries)
    [request] = seen
    params = request.url.params
    assert params["query"] == '{service="payments"}'
    assert params["direction"] == "backward"
    assert params["limit"] == "5000"
    window_ns = int(params["end"]) - int(params["start"])
    assert abs(window_ns - 15 * 60 * 10**9) < 10**9
    assert request.headers["X-Scope-OrgID"] == "demo"


async def test_loki_selector_uses_the_configured_label_and_no_tenant_header():
    def loki(request: httpx.Request) -> httpx.Response:
        assert request.url.params["query"] == '{app="orders"}'
        assert "X-Scope-OrgID" not in request.headers
        data = {"resultType": "streams", "result": []}
        return httpx.Response(200, json={"status": "success", "data": data})

    assert await _loki_backend(loki, loki_service_label="app").log_entries("orders", 5) == []


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(502, text="bad gateway"), "Loki returned 502"),
        (httpx.Response(200, text="<html>"), "JSONDecodeError"),
        (httpx.Response(200, json={"status": "error", "error": "parse error"}), "query failed"),
        (
            httpx.Response(
                200, json={"status": "success", "data": {"resultType": "matrix", "result": []}}
            ),
            "unexpected Loki result",
        ),
    ],
)
async def test_loki_failures_become_backend_errors(response, message):
    backend = _loki_backend(lambda request: response)
    with pytest.raises(BackendError, match=message):
        await backend.log_entries("storefront", 15)


async def test_loki_connection_failure_is_a_backend_error():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(BackendError, match="ConnectError"):
        await _loki_backend(refuse).log_entries("storefront", 15)


async def test_unknown_services_never_reach_a_log_backend():
    def loki(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    with pytest.raises(BackendError, match="unknown service"):
        await _loki_backend(loki).log_entries('x"} or {job=~".+', 15)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"log_backend": "files"}, "unknown log backend"),
        ({"loki_service_label": 'service"}'}, "invalid Loki label"),
        ({"loki_limit": 0}, "loki_limit"),
    ],
)
def test_invalid_log_settings_fail_at_startup(overrides, message):
    with pytest.raises(ValueError, match=message):
        LiveSettings(**overrides)


def test_log_backend_settings_from_env(monkeypatch):
    monkeypatch.setenv("OPSPILOT_LOG_BACKEND", "Loki")
    monkeypatch.setenv("OPSPILOT_LOKI_URL", "http://loki:3100/")
    monkeypatch.setenv("OPSPILOT_LOKI_SERVICE_LABEL", "app")
    monkeypatch.setenv("OPSPILOT_LOKI_LIMIT", "200")
    settings = LiveSettings.from_env()
    assert (settings.log_backend, settings.loki_url) == ("loki", "http://loki:3100")
    assert (settings.loki_service_label, settings.loki_limit, settings.loki_tenant) == (
        "app",
        200,
        None,
    )
    monkeypatch.delenv("OPSPILOT_LOG_BACKEND")
    assert LiveSettings.from_env().log_backend == "docker"
