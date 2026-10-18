"""Request and response models of the agent API, and the stored investigation record."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from opspilot_agent.schemas import EXECUTABLE_ACTIONS
from opspilot_api.modelinfo import ModelInfo, describe_model
from opspilot_mcp.catalog import ServiceName

Status = Literal[
    "queued",
    "running",
    "awaiting_approval",
    "executing",
    "executed",
    "action_failed",
    "rejected",
    "advisory",
    "no_diagnosis",
    "failed",
]
TERMINAL: frozenset[str] = frozenset(
    {"executed", "action_failed", "rejected", "advisory", "no_diagnosis", "failed"}
)
UNFINISHED: frozenset[str] = frozenset({"queued", "running", "awaiting_approval", "executing"})

# Graph outcome -> investigation status.
OUTCOME_STATUS: dict[str, Status] = {
    "executed": "executed",
    "failed": "action_failed",
    "rejected": "rejected",
    "advisory": "advisory",
    "no_diagnosis": "no_diagnosis",
}

EventKind = Literal[
    "alert",
    "model_turn",
    "tool_call",
    "nudge",
    "diagnosis",
    "diagnosis_invalid",
    "approval_requested",
    "decision",
    "action",
    "finished",
    "note",
    "error",
]


class CreateInvestigation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alert: str = Field(min_length=3, max_length=200, description="Alert title as it fired.")
    service: ServiceName | None = Field(
        None,
        validation_alias=AliasChoices("service", "target"),
        description="Service the alert fired on, if known.",
    )
    details: str | None = Field(None, max_length=1000)
    firing_minutes: int | None = Field(None, ge=1, le=240, description="How long it has fired.")
    model: str | None = Field(None, description="One of the models listed by GET /config.")


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    reviewer: str = Field("operator", min_length=1, max_length=64)
    comment: str | None = Field(None, max_length=500)


class Alert(BaseModel):
    title: str
    service: str | None = None
    details: str | None = None
    firing_minutes: int | None = None


class Usage(BaseModel):
    turns: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    # None when the model in use has no entry in the price table (see ApiSettings.pricing_file);
    # a baseline model such as fake:playbook has an entry priced at zero, so its cost is 0.0, not
    # None, which is what tells the dashboard it is a real "no cost" rather than an unknown one.
    cost_usd: float | None = None


class Approval(BaseModel):
    approved: bool
    reviewer: str
    comment: str | None = None
    decided_at: datetime


class TraceEvent(BaseModel):
    seq: int
    at: datetime
    kind: EventKind
    data: dict[str, Any]


class InvestigationRecord(BaseModel):
    """What the API stores per investigation. The LangGraph checkpoint (same thread id) holds
    the graph's execution state; this record is the read model and the audit trail."""

    id: str
    status: Status
    alert: Alert
    model: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    diagnosis: dict[str, Any] | None = None
    diagnosed_at: datetime | None = None
    approval_request: dict[str, Any] | None = None
    approval_requested_at: datetime | None = None
    approval: Approval | None = None
    action_result: dict[str, Any] | None = None
    outcome: str | None = None
    usage: Usage = Field(default_factory=Usage)
    error: str | None = None
    # The investigation's root span, as a W3C traceparent string: lets a decision made minutes
    # or an API restart later still record its "approval_wait" span in the same trace.
    trace_parent: str | None = None
    # How many times a run cut off by an API restart was picked up again (see
    # InvestigationService.recover). Bounded by ApiSettings.max_resumes.
    resumes: int = 0


ApprovalState = Literal["not_required", "pending", "approved", "rejected"]


class ProposedActionBrief(BaseModel):
    type: str
    target_service: str
    executable: bool


class InvestigationSummary(BaseModel):
    id: str
    status: Status
    alert: Alert
    model: ModelInfo
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    root_cause_service: str | None
    category: str | None
    confidence: float | None
    proposed_action: ProposedActionBrief | None
    approval_state: ApprovalState | None

    @classmethod
    def of(cls, record: InvestigationRecord) -> InvestigationSummary:
        return cls(**_summary_fields(record))


def trace_id_of(trace_parent: str | None) -> str | None:
    """The hex trace id inside a W3C traceparent string ("00-<trace_id>-<span_id>-<flags>")."""
    if not trace_parent:
        return None
    parts = trace_parent.split("-")
    return parts[1] if len(parts) == 4 else None


class InvestigationDetail(InvestigationSummary):
    started_at: datetime | None
    diagnosis: dict[str, Any] | None
    approval_request: dict[str, Any] | None
    approval: Approval | None
    action_result: dict[str, Any] | None
    usage: Usage
    time_to_diagnosis_s: float | None
    error: str | None
    trace: list[TraceEvent]
    trace_id: str | None = None

    @classmethod
    def build(cls, record: InvestigationRecord, trace: list[TraceEvent]) -> InvestigationDetail:
        time_to_diagnosis = None
        if record.diagnosed_at and record.started_at:
            time_to_diagnosis = round((record.diagnosed_at - record.started_at).total_seconds(), 3)
        return cls(
            **_summary_fields(record),
            started_at=record.started_at,
            diagnosis=record.diagnosis,
            approval_request=record.approval_request,
            approval=record.approval,
            action_result=record.action_result,
            usage=record.usage,
            time_to_diagnosis_s=time_to_diagnosis,
            error=record.error,
            trace=trace,
            trace_id=trace_id_of(record.trace_parent),
        )


def approval_state(record: InvestigationRecord) -> ApprovalState | None:
    if record.approval is not None:
        return "approved" if record.approval.approved else "rejected"
    if record.approval_request is not None:
        return "pending"
    if record.diagnosis is not None and record.status in TERMINAL:
        return "not_required"
    return None


def _summary_fields(record: InvestigationRecord) -> dict[str, Any]:
    diagnosis = record.diagnosis or {}
    action = diagnosis.get("proposed_action")
    return {
        "id": record.id,
        "status": record.status,
        "alert": record.alert,
        "model": describe_model(record.model),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "finished_at": record.finished_at,
        "root_cause_service": diagnosis.get("root_cause_service"),
        "category": diagnosis.get("category"),
        "confidence": diagnosis.get("confidence"),
        "proposed_action": ProposedActionBrief(
            type=action["type"],
            target_service=action["target_service"],
            executable=action["type"] in EXECUTABLE_ACTIONS,
        )
        if action
        else None,
        "approval_state": approval_state(record),
    }


class ServiceConfig(BaseModel):
    backend: str
    model: ModelInfo
    models: list[ModelInfo]
    model_error: str | None
    demo_enabled: bool
    services: list[str]
