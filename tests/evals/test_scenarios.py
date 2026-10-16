from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from opsdemo.control_plane.chaos import ALLOWED_TARGETS, CATEGORY, FaultType
from opsdemo.control_plane.deploys import BASELINES, BENIGN_CHANGES, DeployRequest
from opspilot_evals.environments import distractor_deploy
from opspilot_evals.scenario import FAULT_CATEGORY, Scenario, load_scenarios
from opspilot_mcp.backends.simulated import HARMLESS_CONFIG_CHANGES, Distractor

SCENARIOS = Path(__file__).resolve().parents[2] / "evals" / "scenarios"
READ_TOOLS = {"get_service_health", "query_metric", "search_logs", "get_recent_deploys"}


@pytest.fixture(scope="module")
def scenarios() -> list[Scenario]:
    return load_scenarios(SCENARIOS)


def test_unique_scenarios_cover_every_injectable_fault(scenarios):
    assert len(scenarios) >= 25
    assert len({s.id for s in scenarios}) == len(scenarios)
    covered = {(s.fault.type, s.fault.target) for s in scenarios}
    injectable = {(t.value, target) for t, targets in ALLOWED_TARGETS.items() for target in targets}
    assert covered == injectable


def test_scenarios_include_both_kinds_of_distractor(scenarios):
    kinds = {d.type for s in scenarios for d in s.distractors}
    assert kinds == {"benign_deploy", "config_deploy"}
    # A distractor on the faulty service itself is the hardest case: it must not be the trigger.
    assert any(d.service == s.fault.target for s in scenarios for d in s.distractors)


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


def test_harmless_config_changes_start_from_the_live_baseline():
    for service, (_, _, values) in HARMLESS_CONFIG_CHANGES.items():
        for key, (old, _new) in values.items():
            assert BASELINES[service].config[key] == old, (service, key)


def test_live_distractor_deploys_match_the_simulation():
    config = distractor_deploy(Distractor(type="config_deploy", service="orders", minutes_ago=9))
    assert config["config"] == {"payments.timeout-ms": 3000}
    assert config["minutes_ago"] == 9
    benign = distractor_deploy(Distractor(service="payments"))
    assert benign["config"] == {}
    assert benign["change_summary"] == BENIGN_CHANGES["payments"].summary
    for request in (config, benign):
        DeployRequest.model_validate(request)
