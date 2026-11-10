"""Behaviour of the FastAPI demo services: telemetry, failure modes and upstream handling."""

import json
import logging
import traceback

import httpx
import pytest
from fastapi.testclient import TestClient

from opsdemo.common.http import UpstreamClient
from opsdemo.common.logs import JsonFormatter
from opsdemo.common.runtime import FailureModes
from opsdemo.payments import app as payments_module
from opsdemo.storefront import app as storefront_module


@pytest.fixture
def payments():
    payments_module.runtime.set_failures(FailureModes())
    payments_module.runtime.config = dict(payments_module.DEFAULT_CONFIG)
    with TestClient(payments_module.app) as client:
        yield client
    payments_module.runtime.set_failures(FailureModes())


def orders_stub(handler):
    """Point the storefront's orders client at an in-memory transport."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return UpstreamClient(
        "orders",
        client,
        base_url=lambda: "http://orders.test",
        timeout_ms=lambda: storefront_module.runtime.config["orders_timeout_ms"],
    )


@pytest.fixture
def storefront():
    storefront_module.runtime.set_failures(FailureModes())
    storefront_module.runtime.config = dict(storefront_module.DEFAULT_CONFIG)
    with TestClient(storefront_module.app) as client:
        yield client
    storefront_module.runtime.set_failures(FailureModes())


CHECKOUT = {"customer_id": "cust-0001", "items": [{"sku": "SKU-1001", "quantity": 2}]}


def json_records(caplog, logger_prefix: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name.startswith(logger_prefix)]


def metric_lines(client: TestClient, name: str) -> list[str]:
    return [line for line in client.get("/metrics").text.splitlines() if line.startswith(name)]


def test_charge_succeeds(payments):
    response = payments.post("/charges", json={"order_id": 7, "amount_cents": 1999})
    assert response.status_code == 201
    assert response.json()["status"] == "captured"


def test_error_spike_raises_genuine_type_error(payments, caplog):
    payments_module.runtime.failures = FailureModes(error_rate=1.0)
    with caplog.at_level(logging.ERROR):
        response = payments.post("/charges", json={"order_id": 7, "amount_cents": 1999})
    assert response.status_code == 500
    [record] = json_records(caplog, "http.server")
    assert record.exc_info[0] is TypeError
    assert "settlement_amount" in "".join(traceback.format_exception(*record.exc_info))


def test_bad_rounding_config_fails_every_charge(payments):
    payments.put("/admin/config", json={"values": {"rounding_mode": "BANKERS"}})
    response = payments.post("/charges", json={"order_id": 7, "amount_cents": 1999})
    assert response.status_code == 500


def test_outage_blocks_everything_except_admin(payments):
    payments.put("/admin/failures", json={"outage": True})
    assert payments.get("/health").status_code == 503
    assert payments.get("/metrics").status_code == 503
    assert payments.post("/charges", json={"order_id": 1, "amount_cents": 5}).status_code == 503
    assert payments.get("/admin/failures").json()["outage"] is True
    payments.delete("/admin/failures")
    assert payments.get("/health").json()["status"] == "ok"


def test_memory_leak_fails_requests_once_its_budget_is_used(payments, caplog):
    # 4 MB per charge against an 8 MB budget: two charges succeed, the third cannot allocate.
    payments.put(
        "/admin/failures",
        json={"memory_leak_kb_per_request": 4096, "memory_leak_limit_mb": 8},
    )
    charge = {"order_id": 7, "amount_cents": 1999}
    with caplog.at_level(logging.ERROR):
        codes = [payments.post("/charges", json=charge).status_code for _ in range(3)]
    assert codes == [201, 201, 500]
    assert payments_module.runtime.memo.size_bytes == 8 * 1024 * 1024
    [record] = json_records(caplog, "http.server")
    assert record.exc_info[0] is MemoryError
    # Probes keep passing: the service looks up while every business request fails.
    assert payments.get("/health").json()["status"] == "ok"

    payments.delete("/admin/failures")
    assert payments_module.runtime.memo.size_bytes == 0
    assert payments.post("/charges", json=charge).status_code == 201


def test_simulated_memory_error_trace_matches_the_live_one(payments, caplog):
    from opspilot_mcp.backends.simulated import _PY_MEMORYERROR

    payments.put(
        "/admin/failures",
        json={"memory_leak_kb_per_request": 4096, "memory_leak_limit_mb": 8},
    )
    with caplog.at_level(logging.ERROR):
        for _ in range(3):
            payments.post("/charges", json={"order_id": 7, "amount_cents": 1999})
    [record] = json_records(caplog, "http.server")
    frames = [
        (f.filename.split("/opsdemo/")[-1], f.lineno, f.name)
        for f in traceback.extract_tb(record.exc_info[2])
    ]
    simulated = [
        (line.split('"')[1].split("/opsdemo/")[-1], int(line.split("line ")[1].split(",")[0]),
         line.rsplit(" in ", 1)[1])
        for line in _PY_MEMORYERROR.splitlines()
        if line.lstrip().startswith("File ")
    ]  # fmt: skip
    assert frames[-len(simulated) :] == simulated


def test_admin_and_probe_traffic_is_not_measured(payments):
    payments.get("/admin/config")
    payments.get("/health")
    assert not [
        line
        for line in metric_lines(payments, "http_server_requests_seconds_count")
        if "/admin" in line or "/health" in line
    ]


def test_access_log_carries_route_status_and_trace(payments, caplog):
    with caplog.at_level(logging.INFO):
        payments.post("/charges", json={"order_id": 7, "amount_cents": 1999})
    [record] = json_records(caplog, "http.access")
    assert record.http_route == "/charges"
    assert record.http_status == 201
    formatted = json.loads(JsonFormatter("payments").format(record))
    assert formatted["service"] == "payments"
    assert len(formatted["trace_id"]) == 32


def test_checkout_places_order(storefront):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["items"][0]["unit_price_cents"] == 12999
        return httpx.Response(201, json={"id": 42, "status": "PAID", "total_cents": 25998})

    storefront_module.app.state.orders = orders_stub(handler)
    response = storefront.post("/checkout", json=CHECKOUT)
    assert response.status_code == 201
    assert response.json() == {"order_id": 42, "status": "PAID", "total_cents": 25998}


def test_orders_server_error_maps_to_bad_gateway(storefront, caplog):
    storefront_module.app.state.orders = orders_stub(lambda r: httpx.Response(503, json={}))
    with caplog.at_level(logging.ERROR):
        response = storefront.post("/checkout", json=CHECKOUT)
    assert response.status_code == 502
    assert response.json()["upstream_status"] == 503
    assert "returned HTTP 503" in json_records(caplog, "upstream.orders")[0].getMessage()


def test_orders_timeout_maps_to_gateway_timeout(storefront, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    storefront_module.app.state.orders = orders_stub(handler)
    with caplog.at_level(logging.ERROR):
        response = storefront.post("/checkout", json=CHECKOUT)
    assert response.status_code == 504
    message = json_records(caplog, "upstream.orders")[0].getMessage()
    assert message == "Call to orders timed out after 2000 ms: POST /orders"


def test_error_spike_is_a_key_error_in_pricing(storefront, caplog):
    storefront_module.app.state.orders = orders_stub(
        lambda r: httpx.Response(201, json={"id": 1, "status": "PAID", "total_cents": 1})
    )
    storefront_module.runtime.failures = FailureModes(error_rate=1.0)
    with caplog.at_level(logging.ERROR):
        response = storefront.post("/checkout", json=CHECKOUT)
    assert response.status_code == 500
    [record] = json_records(caplog, "http.server")
    assert record.exc_info[0] is KeyError
