"""Against the running docker compose stack (`make up`). Skipped when it is not running."""

import httpx
import pytest

from opspilot_evals.environments import LiveEnvironment
from opspilot_mcp.backends.live import LiveBackend
from opspilot_mcp.catalog import SERVICES
from opspilot_mcp.logsearch import search_logs
from opspilot_mcp.metrics import summarize_metric

CONTROL_PLANE = "http://localhost:8190"


def _stack_running() -> bool:
    try:
        return httpx.get(f"{CONTROL_PLANE}/health", timeout=1.0).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _stack_running(), reason="demo stack is not running (make up)"),
]


@pytest.fixture
async def backend():
    backend = LiveBackend()
    yield backend
    await backend.aclose()


async def test_all_services_report_health(backend):
    reports = [await backend.health(service) for service in SERVICES]
    assert {r.service for r in reports} == set(SERVICES)
    assert all(r.version for r in reports if r.status == "healthy")


async def test_prometheus_has_request_metrics(backend):
    series = await backend.metric_series("storefront", "request_rate", 5)
    summary = summarize_metric("storefront", "request_rate", 5, series)
    assert summary["series"][0]["latest"] is not None


async def test_logs_are_read_from_containers(backend):
    entries = await backend.log_entries("orders", 5)
    assert search_logs(entries)["total_matched"] > 0


async def test_fault_injection_records_ground_truth():
    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(f"{CONTROL_PLANE}/chaos/reset")
        response = await client.post(
            f"{CONTROL_PLANE}/chaos/faults",
            json={"type": "error_spike", "target": "payments", "params": {"error_rate": 0.5}},
        )
        assert response.status_code == 201
        assert response.json()["ground_truth"] == {"service": "payments", "category": "error_rate"}
        await client.post(f"{CONTROL_PLANE}/chaos/reset")
    environment = LiveEnvironment()
    await environment.wait_until_healthy()
    await environment.aclose()
