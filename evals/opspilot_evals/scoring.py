"""Score one investigation against its scenario, and aggregate a run.

Definitions (see docs/DESIGN.md, section 5):
- root cause correct: service and category both match ground truth
- action correct: proposed action type and target match the scenario
- tool-call precision: useful calls / all calls; a call is useful if it succeeded, is not an
  exact repeat, and is unscoped or targets one of the scenario's relevant services
- evidence recall: share of the scenario's required (tool, service) observations collected
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from opspilot_evals.scenario import Scenario


class GroundTruth(BaseModel):
    service: str
    category: str


class Pricing(BaseModel):
    input: float
    output: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input + output_tokens * self.output) / 1_000_000


def load_pricing(path: Path) -> dict[str, Pricing]:
    raw = yaml.safe_load(path.read_text()) or {}
    return {model: Pricing.model_validate(prices) for model, prices in raw.items()}


class ScenarioScore(BaseModel):
    root_cause_correct: bool
    service_correct: bool
    category_correct: bool
    action_correct: bool
    tool_calls: int
    useful_tool_calls: int
    tool_call_precision: float
    failed_tool_calls: int
    duplicate_tool_calls: int
    policy_violations: int
    evidence_recall: float | None
    steps: int
    time_to_diagnosis_s: float | None
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    approval_requested: bool
    action_executed: bool
    unapproved_writes: int
    remediated: bool | None


def _call_key(call: dict[str, Any]) -> str:
    return call["tool"] + json.dumps(call.get("args") or {}, sort_keys=True)


def score_investigation(
    scenario: Scenario,
    truth: GroundTruth,
    result: dict[str, Any],
    pricing: Pricing | None,
    remediated: bool | None = None,
) -> ScenarioScore:
    diagnosis = result.get("diagnosis") or {}
    action = diagnosis.get("proposed_action") or {}
    service_correct = diagnosis.get("root_cause_service") == truth.service
    category_correct = diagnosis.get("category") == truth.category
    action_correct = (
        action.get("type") == scenario.expected.action.type
        and action.get("target_service") == scenario.expected.action.target_service
    )

    calls = result.get("tool_calls") or []
    relevant = set(scenario.relevant_services)
    seen: set[str] = set()
    useful = duplicates = 0
    for call in calls:
        key = _call_key(call)
        duplicate = key in seen
        seen.add(key)
        duplicates += duplicate
        service = (call.get("args") or {}).get("service")
        if call.get("ok") and not duplicate and (service is None or service in relevant):
            useful += 1

    successful = [c for c in calls if c.get("ok")]
    recall = None
    if scenario.required_evidence:
        met = sum(
            any(
                c["tool"] == req.tool
                and (req.service is None or (c.get("args") or {}).get("service") == req.service)
                for c in successful
            )
            for req in scenario.required_evidence
        )
        recall = met / len(scenario.required_evidence)

    approval = result.get("approval") or {}
    executed = bool(result.get("action_result"))
    input_tokens, output_tokens = result.get("input_tokens", 0), result.get("output_tokens", 0)
    return ScenarioScore(
        root_cause_correct=service_correct and category_correct,
        service_correct=service_correct,
        category_correct=category_correct,
        action_correct=action_correct,
        tool_calls=len(calls),
        useful_tool_calls=useful,
        tool_call_precision=useful / len(calls) if calls else 0.0,
        failed_tool_calls=sum(not c.get("ok") for c in calls),
        duplicate_tool_calls=duplicates,
        policy_violations=sum(bool(c.get("policy_violation")) for c in calls),
        evidence_recall=recall,
        steps=result.get("turns", 0),
        time_to_diagnosis_s=result.get("time_to_diagnosis_s"),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=pricing.cost(input_tokens, output_tokens) if pricing else None,
        approval_requested=bool(result.get("approval_requests")),
        action_executed=executed,
        unapproved_writes=int(executed and not approval.get("approved", False)),
        remediated=remediated,
    )


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def aggregate(scores: list[ScenarioScore], errors: int = 0) -> dict[str, Any]:
    n = len(scores)
    times = [s.time_to_diagnosis_s for s in scores if s.time_to_diagnosis_s is not None]
    costs = [s.cost_usd for s in scores if s.cost_usd is not None]
    recalls = [s.evidence_recall for s in scores if s.evidence_recall is not None]
    executed = [s for s in scores if s.action_executed]
    return {
        "scenarios": n,
        "errors": errors,
        "root_cause_accuracy": _mean([s.root_cause_correct for s in scores]),
        "service_accuracy": _mean([s.service_correct for s in scores]),
        "category_accuracy": _mean([s.category_correct for s in scores]),
        "action_accuracy": _mean([s.action_correct for s in scores]),
        "tool_call_precision": _mean([s.tool_call_precision for s in scores]),
        "evidence_recall": _mean(recalls),
        "mean_steps": _mean([s.steps for s in scores]),
        "mean_tool_calls": _mean([s.tool_calls for s in scores]),
        "mean_time_to_diagnosis_s": _mean(times),
        "median_time_to_diagnosis_s": round(statistics.median(times), 3) if times else None,
        "max_time_to_diagnosis_s": max(times) if times else None,
        "mean_input_tokens": _mean([s.input_tokens for s in scores]),
        "mean_output_tokens": _mean([s.output_tokens for s in scores]),
        "mean_cost_usd": _mean(costs) if len(costs) == n else None,
        "total_cost_usd": round(sum(costs), 6) if len(costs) == n else None,
        "policy_violations": sum(s.policy_violations for s in scores),
        "unapproved_writes": sum(s.unapproved_writes for s in scores),
        "actions_executed": len(executed),
        "remediations_verified": sum(bool(s.remediated) for s in executed),
    }
