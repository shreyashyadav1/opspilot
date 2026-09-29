"""Benchmark scenarios: one injected fault, the alert it triggers, and the expected diagnosis."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from opspilot_agent.schemas import ActionType, FaultCategory, ServiceName
from opspilot_mcp.backends.simulated import Distractor, FaultSpec

# Ground-truth category per fault type; must match the control plane's chaos API.
FAULT_CATEGORY: dict[str, FaultCategory] = {
    "latency_spike": FaultCategory.LATENCY,
    "error_spike": FaultCategory.ERROR_RATE,
    "db_pool_exhaustion": FaultCategory.RESOURCE_EXHAUSTION,
    "bad_config_deploy": FaultCategory.BAD_DEPLOY,
    "dependency_outage": FaultCategory.DEPENDENCY_OUTAGE,
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AlertSpec(_Strict):
    title: str
    service: ServiceName
    details: str


class ExpectedAction(_Strict):
    type: ActionType
    target_service: ServiceName


class Expected(_Strict):
    root_cause_service: ServiceName
    category: FaultCategory
    action: ExpectedAction


class EvidenceRequirement(_Strict):
    tool: str
    service: ServiceName | None = None


class Scenario(_Strict):
    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    title: str
    description: str
    alert: AlertSpec
    fault: FaultSpec
    distractors: list[Distractor] = Field(default_factory=list)
    expected: Expected
    relevant_services: list[ServiceName] = Field(min_length=1)
    required_evidence: list[EvidenceRequirement] = Field(default_factory=list)
    warmup_seconds: int = Field(60, ge=10, le=600)

    @model_validator(mode="after")
    def _expected_matches_fault(self) -> Scenario:
        if self.expected.root_cause_service != self.fault.target:
            raise ValueError("expected.root_cause_service must be the fault target")
        if self.expected.category != FAULT_CATEGORY[self.fault.type]:
            raise ValueError(f"{self.fault.type} is scored as {FAULT_CATEGORY[self.fault.type]}")
        if self.fault.target not in self.relevant_services:
            raise ValueError("relevant_services must include the fault target")
        return self


def load_scenarios(directory: Path, only: list[str] | None = None) -> list[Scenario]:
    scenarios = [
        Scenario.model_validate(yaml.safe_load(path.read_text()))
        for path in sorted(directory.glob("*.yaml"))
    ]
    if only:
        wanted = set(only)
        unknown = wanted - {s.id for s in scenarios}
        if unknown:
            raise ValueError(f"unknown scenario ids: {', '.join(sorted(unknown))}")
        scenarios = [s for s in scenarios if s.id in wanted]
    return scenarios
