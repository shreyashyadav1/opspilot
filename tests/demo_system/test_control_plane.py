"""Deploy registry and chaos API of the demo control plane."""

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from opsdemo.control_plane.chaos import ChaosError, ControlPlane, FaultRequest, FaultType
from opsdemo.control_plane.deploys import (
    BASELINES,
    DeployRegistry,
    DeployRequest,
    RollbackRequest,
)


class FakeAdmin:
    """Records admin API calls instead of making them."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.fail_for: set[str] = set()

    async def put_failures(self, service: str, modes: dict[str, Any]) -> None:
        self._record("put_failures", service, modes)

    async def clear_failures(self, service: str) -> None:
        self._record("clear_failures", service, None)

    async def put_config(self, service: str, version: str, values: dict[str, Any]) -> None:
        self._record("put_config", service, {"version": version, **values})

    def _record(self, op: str, service: str, payload: Any) -> None:
        if service in self.fail_for:
            raise ChaosError(502, f"{service} admin API unreachable")
        self.calls.append((op, service, payload))


@pytest.fixture
def admin() -> FakeAdmin:
    return FakeAdmin()


@pytest.fixture
def plane(admin: FakeAdmin) -> ControlPlane:
    return ControlPlane(admin, DeployRegistry())  # type: ignore[arg-type]


def test_seeded_history_ends_at_baseline_versions():
    registry = DeployRegistry()
    registry.reset(now=datetime(2026, 1, 1, tzinfo=UTC))
    for service, baseline in BASELINES.items():
        assert registry.current(service).version == baseline.version
    events = registry.list()
    assert [e.deployed_at for e in events] == sorted((e.deployed_at for e in events), reverse=True)


def test_deploy_records_version_bump_and_config_diff():
    registry = DeployRegistry()
    registry.reset()
    event = registry.record_deploy(
        DeployRequest(
            service="orders",
            change_summary="new endpoint",
            config={"payments.base-url": "http://payments-v2:8080"},
        )
    )
    assert (event.version, event.previous_version) == ("1.8.4", "1.8.3")
    assert event.config_diff == {
        "payments.base-url": {"from": "http://payments:8080", "to": "http://payments-v2:8080"}
    }


def test_consecutive_rollbacks_walk_back_through_history():
    registry = DeployRegistry()
    registry.reset()
    registry.record_deploy(
        DeployRequest(service="payments", change_summary="bad", config={"rounding_mode": "BANKERS"})
    )
    first, rolled_back = registry.record_rollback("payments", RollbackRequest(reason="errors"))
    assert (first.version, rolled_back.version) == ("3.2.0", "3.2.1")
    assert first.config["rounding_mode"] == "HALF_EVEN"
    second, _ = registry.record_rollback("payments", RollbackRequest(reason="still bad"))
    assert second.version == "3.1.5"


def test_next_deploy_after_rollback_gets_a_fresh_version():
    registry = DeployRegistry()
    registry.reset()
    registry.record_deploy(DeployRequest(service="storefront", change_summary="first"))
    registry.record_rollback("storefront", RollbackRequest(reason="revert"))
    event = registry.record_deploy(DeployRequest(service="storefront", change_summary="retry"))
    assert event.version == "2.14.2"


async def test_inject_records_ground_truth_and_applies_failure_modes(plane, admin):
    record = await plane.inject(
        FaultRequest(type=FaultType.LATENCY_SPIKE, target="payments", params={"delay_ms": 900})
    )
    assert record.ground_truth.model_dump() == {"service": "payments", "category": "latency"}
    assert record.active
    assert admin.calls[-1] == (
        "put_failures",
        "payments",
        {"latency_ms": 900, "latency_jitter_ms": 150},
    )


@pytest.mark.parametrize(
    ("fault_type", "target"),
    [(FaultType.DB_POOL_EXHAUSTION, "payments"), (FaultType.DEPENDENCY_OUTAGE, "storefront")],
)
async def test_inject_rejects_unsupported_targets(plane, fault_type, target):
    with pytest.raises(ChaosError) as excinfo:
        await plane.inject(FaultRequest(type=fault_type, target=target))
    assert excinfo.value.status_code == 422


async def test_inject_rejects_invalid_params_and_second_fault_on_same_target(plane):
    with pytest.raises(ChaosError):
        await plane.inject(
            FaultRequest(type=FaultType.ERROR_SPIKE, target="orders", params={"error_rate": 3})
        )
    await plane.inject(FaultRequest(type=FaultType.ERROR_SPIKE, target="orders"))
    with pytest.raises(ChaosError) as excinfo:
        await plane.inject(FaultRequest(type=FaultType.LATENCY_SPIKE, target="orders"))
    assert excinfo.value.status_code == 409


async def test_rollback_resolves_bad_config_deploy(plane, admin):
    record = await plane.inject(FaultRequest(type=FaultType.BAD_CONFIG_DEPLOY, target="orders"))
    assert admin.calls[-1][2]["payments.base-url"] == "http://payments-v2:8080"
    assert record.ground_truth.category == "bad_deploy"

    await plane.rollback("orders", RollbackRequest(reason="payments unreachable"))
    assert admin.calls[-1] == (
        "put_config",
        "orders",
        {
            "version": "1.8.3",
            "payments.base-url": "http://payments:8080",
            "payments.timeout-ms": 2000,
        },
    )
    assert not record.active
    assert record.resolved_by == "rollback"


async def test_rollback_of_unrelated_service_leaves_fault_active(plane):
    record = await plane.inject(FaultRequest(type=FaultType.BAD_CONFIG_DEPLOY, target="payments"))
    await plane.deploy(DeployRequest(service="storefront", change_summary="copy change"))
    await plane.rollback("storefront", RollbackRequest(reason="wrong guess"))
    assert record.active


async def test_failed_config_push_is_not_recorded_as_deploy(plane, admin):
    admin.fail_for.add("orders")
    before = len(plane.registry.list(service="orders"))
    with pytest.raises(ChaosError):
        await plane.deploy(DeployRequest(service="orders", change_summary="will fail"))
    assert len(plane.registry.list(service="orders")) == before


async def test_reset_clears_everything(plane, admin):
    record = await plane.inject(FaultRequest(type=FaultType.DEPENDENCY_OUTAGE, target="payments"))
    resolved = await plane.reset()
    assert resolved == 1
    assert record.resolved_by == "reset"
    assert ("clear_failures", "payments", None) in admin.calls


def test_api_hides_config_snapshots_and_validates_requests(monkeypatch, admin):
    monkeypatch.setenv("CP_RESET_ON_STARTUP", "false")
    from opsdemo.control_plane.app import app

    with TestClient(app) as client:
        app.state.plane = ControlPlane(admin, DeployRegistry())  # type: ignore[arg-type]
        deploys = client.get("/deploys", params={"service": "orders"}).json()["deploys"]
        assert deploys
        assert all("config" not in event for event in deploys)

        response = client.post(
            "/chaos/faults", json={"type": "db_pool_exhaustion", "target": "payments"}
        )
        assert response.status_code == 422

        created = client.post(
            "/chaos/faults",
            json={"type": "error_spike", "target": "orders", "params": {"error_rate": 0.5}},
        )
        assert created.status_code == 201
        assert created.json()["ground_truth"] == {"service": "orders", "category": "error_rate"}
        active = client.get("/chaos/faults", params={"active_only": True}).json()["faults"]
        assert [f["id"] for f in active] == [created.json()["id"]]


def test_catalog_lists_every_fault_type_with_targets_and_param_bounds(monkeypatch):
    monkeypatch.setenv("CP_RESET_ON_STARTUP", "false")
    from opsdemo.control_plane.app import app

    with TestClient(app) as client:
        response = client.get("/chaos/catalog")
    assert response.status_code == 200
    catalog = {entry["type"]: entry for entry in response.json()["fault_types"]}
    assert set(catalog) == {t.value for t in FaultType}
    assert catalog["db_pool_exhaustion"]["targets"] == ["orders"]
    assert catalog["dependency_outage"]["targets"] == ["orders", "payments"]
    assert catalog["memory_leak"]["targets"] == ["payments", "storefront"]
    assert catalog["memory_leak"]["category"] == "resource_exhaustion"
    assert catalog["bad_config_deploy"]["category"] == "bad_deploy"
    assert catalog["bad_config_deploy"]["params"] == {}
    delay = catalog["latency_spike"]["params"]["delay_ms"]
    assert (delay["minimum"], delay["maximum"], delay["default"]) == (50, 10_000, 1200)
    assert all(entry["description"].endswith(".") for entry in catalog.values())


async def test_memory_leak_sets_and_clears_its_failure_fields(plane, admin):
    record = await plane.inject(
        FaultRequest(type=FaultType.MEMORY_LEAK, target="storefront", params={"limit_mb": 48})
    )
    assert record.ground_truth.category == "resource_exhaustion"
    assert admin.calls[-1] == (
        "put_failures",
        "storefront",
        {"memory_leak_kb_per_request": 256, "memory_leak_limit_mb": 48},
    )
    await plane.clear(record.id)
    assert admin.calls[-1] == ("put_failures", "storefront", {})


@pytest.mark.parametrize(
    ("target", "params"),
    [("orders", {}), ("payments", {"kb_per_request": 64}), ("payments", {"limit_mb": 160})],
)
async def test_memory_leak_rejects_jvm_targets_and_unsafe_params(plane, target, params):
    with pytest.raises(ChaosError) as error:
        await plane.inject(FaultRequest(type=FaultType.MEMORY_LEAK, target=target, params=params))
    assert error.value.status_code == 422
