from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from opsdemo.control_plane.chaos import ALLOWED_TARGETS, CATEGORY, FaultType
from opspilot_evals.scenario import FAULT_CATEGORY, Scenario, load_scenarios

SCENARIOS = Path(__file__).resolve().parents[2] / "evals" / "scenarios"
READ_TOOLS = {"get_service_health", "query_metric", "search_logs", "get_recent_deploys"}


@pytest.fixture(scope="module")
def scenarios() -> list[Scenario]:
    return load_scenarios(SCENARIOS)


def test_at_least_eight_unique_scenarios_covering_every_fault_type(scenarios):
    assert len(scenarios) >= 8
    assert len({s.id for s in scenarios}) == len(scenarios)
    assert {s.fault.type for s in scenarios} == set(FAULT_CATEGORY)


def test_ground_truth_categories_match_the_control_plane():
    assert {t.value: c for t, c in CATEGORY.items()} == {
        k: v.value for k, v in FAULT_CATEGORY.items()
    }


def test_every_fault_is_injectable_by_the_control_plane(scenarios):
    for scenario in scenarios:
        assert scenario.fault.target in ALLOWED_TARGETS[FaultType(scenario.fault.type)]


def test_required_evidence_uses_real_tools(scenarios):
    for scenario in scenarios:
        assert {req.tool for req in scenario.required_evidence} <= READ_TOOLS


def test_inconsistent_expectations_are_rejected():
    raw = yaml.safe_load((SCENARIOS / "01-payments-latency-spike.yaml").read_text())
    raw["expected"]["category"] = "bad_deploy"
    with pytest.raises(ValidationError, match="scored as"):
        Scenario.model_validate(raw)


def test_filtering_by_id(scenarios):
    assert [s.id for s in load_scenarios(SCENARIOS, ["payments-outage"])] == ["payments-outage"]
    with pytest.raises(ValueError, match="unknown scenario"):
        load_scenarios(SCENARIOS, ["nope"])
