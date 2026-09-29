"""The agent's structured output and the approval contract."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ServiceName = Literal["storefront", "orders", "payments", "postgres"]


class FaultCategory(StrEnum):
    LATENCY = "latency"
    ERROR_RATE = "error_rate"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    BAD_DEPLOY = "bad_deploy"
    DEPENDENCY_OUTAGE = "dependency_outage"


class ActionType(StrEnum):
    ROLLBACK_DEPLOY = "rollback_deploy"
    RESTART_SERVICE = "restart_service"
    ESCALATE = "escalate"
    NONE = "none"


# Proposed actions the agent can carry out itself (after approval), mapped to the MCP write
# tool that performs them. Everything else is a recommendation for the operator.
EXECUTABLE_ACTIONS: dict[ActionType, str] = {ActionType.ROLLBACK_DEPLOY: "rollback_deploy"}


def _decode_json_string(value: Any) -> Any:
    """Some models send nested objects as JSON strings; accept that, validate the rest."""
    if isinstance(value, str) and value.strip().startswith(("{", "[")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["logs", "metrics", "deploys", "health"] = Field(
        description="Which tool family the observation came from."
    )
    service: ServiceName = Field(description="Service the observation is about.")
    detail: str = Field(
        min_length=5,
        max_length=400,
        description="The concrete observation, with numbers or quoted log text.",
    )


class ProposedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ActionType = Field(description="rollback_deploy, restart_service, escalate or none.")
    target_service: ServiceName = Field(description="Service the action applies to.")
    rationale: str = Field(min_length=10, max_length=400, description="Why this action helps.")


class Diagnosis(BaseModel):
    """Root-cause diagnosis of the incident. Submit exactly once, after investigating."""

    model_config = ConfigDict(extra="forbid")

    root_cause_service: ServiceName = Field(
        description="The service where the fault originates, not where symptoms show up."
    )
    category: FaultCategory = Field(description="The kind of fault.")
    summary: str = Field(min_length=10, max_length=600, description="Two or three sentences.")
    evidence: list[Evidence] = Field(min_length=1, max_length=8)
    confidence: float = Field(ge=0.0, le=1.0, description="0 to 1.")
    proposed_action: ProposedAction

    @field_validator("evidence", "proposed_action", mode="before")
    @classmethod
    def _accept_json_strings(cls, value: Any) -> Any:
        return _decode_json_string(value)

    @property
    def executable_tool(self) -> str | None:
        return EXECUTABLE_ACTIONS.get(self.proposed_action.type)


class ApprovalDecision(BaseModel):
    """What a human (or an eval policy) answers to an approval request."""

    approved: bool
    reviewer: str = "operator"
    comment: str | None = None
