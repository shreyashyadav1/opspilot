"""The simulated backend must reproduce each fault's signature, deterministically."""

import pytest
from pydantic import ValidationError

from opspilot_mcp.backends.simulated import Distractor, SimulatedBackend
from opspilot_mcp.logsearch import search_logs
from opspilot_mcp.metrics import summarize_metric


async def latest(backend: SimulatedBackend, service: str, metric: str) -> float | None:
    series = await backend.metric_series(service, metric, 15)
    return summarize_metric(service, metric, 15, series)["series"][0]["latest"]


async def error_messages(backend: SimulatedBackend, service: str) -> str:
    result = search_logs(await backend.log_entries(service, 15), level="ERROR")
    return " | ".join(m["example"] for m in result["top_messages"])


async def test_healthy_system_has_no_errors_or_recent_deploys(simulate):
    backend = simulate()
    assert {(await backend.health(s)).status for s in ("storefront", "orders", "payments")} == {
        "healthy"
    }
    assert await error_messages(backend, "storefront") == ""
    assert await backend.deploys(None, 60) == []


async def test_payments_latency_spike_propagates_to_callers(simulate):
    backend = simulate("latency_spike", "payments")
    for service in ("payments", "orders", "storefront"):
        assert await latest(backend, service, "latency_p95") > 1000
    assert await latest(backend, "payments", "error_rate") < 0.05
    slow = search_logs(await backend.log_entries("orders", 15), query="slow call")
    assert slow["total_matched"] > 0


async def test_pool_exhaustion_signature(simulate):
    backend = simulate("db_pool_exhaustion", "orders")
    health = await backend.health("orders")
    assert health.status == "unhealthy"
    assert health.failing_components == ["db"]
    assert await latest(backend, "orders", "db_pool_active") == 5
    assert await latest(backend, "orders", "db_pool_pending") > 0
    assert "Connection is not available" in await error_messages(backend, "orders")


async def test_payments_outage_stops_its_telemetry(simulate):
    backend = simulate("dependency_outage", "payments")
    assert await latest(backend, "payments", "up") == 0
    series = await backend.metric_series("payments", "error_rate", 15)
    summary = summarize_metric("payments", "error_rate", 15, series)["series"][0]
    assert summary["latest"] is None
    assert summary["trend"] == "no recent data"
    assert summary["last_value"] == 0.0
    assert (await backend.health("payments")).http_status == 503
    recent = await backend.log_entries("payments", 2)
    assert recent == []
    assert "returned HTTP 503" in await error_messages(backend, "orders")


async def test_bad_orders_deploy_starves_payments_of_traffic(simulate):
    backend = simulate("bad_config_deploy", "orders")
    [deploy] = await backend.deploys("orders", 30)
    assert deploy.config_diff["payments.base-url"]["to"] == "http://payments-v2:8080"
    assert await latest(backend, "payments", "request_rate") < 0.1
    assert "UnknownHostException: payments-v2" in await error_messages(backend, "orders")


async def test_rollback_resolves_only_the_bad_deploy(simulate):
    backend = simulate("bad_config_deploy", "payments")
    await backend.rollback("storefront", "unrelated rollback")
    assert not backend.resolved
    event = await backend.rollback("payments", "rounding errors since 3.2.1")
    assert (event.version, event.previous_version) == ("3.2.0", "3.2.1")
    assert backend.resolved
    assert await latest(backend, "payments", "error_rate") < 0.05


async def test_distractor_deploy_is_benign(simulate):
    backend = simulate("error_spike", "orders", distractors=[Distractor(service="payments")])
    [deploy] = await backend.deploys(None, 30)
    assert deploy.service == "payments"
    assert deploy.config_diff == {}


async def test_config_distractor_shows_a_harmless_config_diff(simulate):
    backend = simulate(
        "dependency_outage",
        "payments",
        distractors=[Distractor(type="config_deploy", service="orders", minutes_ago=7)],
    )
    [deploy] = await backend.deploys(None, 30)
    assert (deploy.service, deploy.version, deploy.previous_version) == ("orders", "1.8.4", "1.8.3")
    assert deploy.config_diff == {"payments.timeout-ms": {"from": 2000, "to": 3000}}
    # Rolling the distractor back is allowed but leaves the fault in place.
    await backend.rollback("orders", "suspected timeout change")
    assert not backend.resolved
    assert (await backend.health("payments")).status == "unhealthy"


def test_config_distractor_needs_a_harmless_change_for_the_service():
    with pytest.raises(ValidationError, match="no harmless config change"):
        Distractor(type="config_deploy", service="payments")


async def test_rollback_after_an_earlier_deploy_of_the_same_service(simulate):
    backend = simulate(
        "bad_config_deploy",
        "payments",
        distractors=[Distractor(service="payments", minutes_ago=50)],
    )
    deploys = sorted(await backend.deploys("payments", 60), key=lambda d: d.deployed_at)
    assert [(d.version, bool(d.config_diff)) for d in deploys] == [
        ("3.2.1", False),
        ("3.2.2", True),
    ]
    event = await backend.rollback("payments", "rounding errors since 3.2.2")
    assert (event.version, event.previous_version) == ("3.2.1", "3.2.2")
    assert backend.resolved


@pytest.mark.parametrize(
    ("fault_type", "target"),
    [
        ("error_spike", "storefront"),
        ("bad_config_deploy", "storefront"),
        ("dependency_outage", "orders"),
        ("error_spike", "payments"),
    ],
)
async def test_output_is_deterministic(simulate, fault_type, target):
    first, second = simulate(fault_type, target), simulate(fault_type, target)
    assert await first.log_entries("storefront", 15) == await second.log_entries("storefront", 15)
    assert await first.metric_series("storefront", "error_rate", 15) == (
        await second.metric_series("storefront", "error_rate", 15)
    )
