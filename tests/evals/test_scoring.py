from pathlib import Path

import pytest

from opspilot_evals.scenario import load_scenarios
from opspilot_evals.scoring import GroundTruth, Pricing, aggregate, score_investigation

SCENARIOS = Path(__file__).resolve().parents[2] / "evals" / "scenarios"


@pytest.fixture(scope="module")
def scenario():
    [scenario] = load_scenarios(SCENARIOS, ["orders-bad-config-deploy"])
    return scenario


TRUTH = GroundTruth(service="orders", category="bad_deploy")


def investigation(**overrides):
    base = {
        "diagnosis": {
            "root_cause_service": "orders",
            "category": "bad_deploy",
            "proposed_action": {"type": "rollback_deploy", "target_service": "orders"},
        },
        "tool_calls": [
            {"tool": "get_recent_deploys", "args": {}, "ok": True},
            {"tool": "search_logs", "args": {"service": "orders"}, "ok": True},
        ],
        "turns": 3,
        "input_tokens": 1_000_000,
        "output_tokens": 500_000,
        "time_to_diagnosis_s": 4.2,
        "approval_requests": [{"tool": "rollback_deploy"}],
        "approval": {"approved": True},
        "action_result": {"ok": True},
    }
    base.update(overrides)
    return base


def test_fully_correct_investigation(scenario):
    score = score_investigation(
        scenario, TRUTH, investigation(), Pricing(input=0.5, output=1.0), True
    )
    assert score.root_cause_correct
    assert score.action_correct
    assert score.tool_call_precision == 1.0
    assert score.evidence_recall == 1.0
    assert score.cost_usd == pytest.approx(1.0)
    assert score.unapproved_writes == 0
    assert score.remediated is True


def test_right_service_wrong_category_is_not_a_correct_root_cause(scenario):
    result = investigation(
        diagnosis={
            "root_cause_service": "orders",
            "category": "error_rate",
            "proposed_action": {"type": "escalate", "target_service": "orders"},
        }
    )
    score = score_investigation(scenario, TRUTH, result, None)
    assert score.service_correct
    assert not score.category_correct
    assert not score.root_cause_correct
    assert not score.action_correct
    assert score.cost_usd is None


def test_precision_penalizes_failures_repeats_and_irrelevant_services():
    [scenario] = load_scenarios(SCENARIOS, ["storefront-error-spike"])
    calls = [
        {"tool": "search_logs", "args": {"service": "storefront"}, "ok": True},
        {"tool": "search_logs", "args": {"service": "storefront"}, "ok": True},
        {"tool": "query_metric", "args": {"service": "payments"}, "ok": True},
        {"tool": "query_metric", "args": {"service": "storefront"}, "ok": False},
        {"tool": "get_service_health", "args": {}, "ok": True},
    ]
    truth = GroundTruth(service="storefront", category="error_rate")
    score = score_investigation(scenario, truth, investigation(tool_calls=calls), None)
    assert score.useful_tool_calls == 2
    assert score.tool_call_precision == pytest.approx(0.4)
    assert (score.duplicate_tool_calls, score.failed_tool_calls) == (1, 1)


def test_missing_evidence_lowers_recall(scenario):
    calls = [{"tool": "get_recent_deploys", "args": {}, "ok": True}]
    score = score_investigation(scenario, TRUTH, investigation(tool_calls=calls), None)
    assert score.evidence_recall == 0.5


def test_executed_action_without_approval_is_flagged(scenario):
    score = score_investigation(scenario, TRUTH, investigation(approval=None), None)
    assert score.unapproved_writes == 1


def test_failed_run_scores_as_wrong(scenario):
    score = score_investigation(scenario, TRUTH, {}, None)
    assert not score.root_cause_correct
    assert score.tool_call_precision == 0.0
    assert score.evidence_recall == 0.0


def test_aggregate(scenario):
    good = score_investigation(scenario, TRUTH, investigation(), Pricing(input=1, output=1), True)
    bad = score_investigation(scenario, TRUTH, {}, Pricing(input=1, output=1))
    summary = aggregate([good, bad], errors=1)
    assert summary["root_cause_accuracy"] == 0.5
    assert summary["errors"] == 1
    assert summary["actions_executed"] == 1
    assert summary["remediations_verified"] == 1
    assert summary["median_time_to_diagnosis_s"] == 4.2
