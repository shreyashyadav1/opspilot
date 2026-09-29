"""Run one investigation end to end, answering approval requests through a callback."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from opspilot_agent.graph import AgentConfig, build_graph
from opspilot_agent.mcp_client import ToolSet
from opspilot_agent.schemas import ApprovalDecision, Diagnosis

ApprovalHandler = Callable[[dict[str, Any]], Awaitable[ApprovalDecision]]
EventHandler = Callable[[str, dict[str, Any]], None]


async def approve_all(request: dict[str, Any]) -> ApprovalDecision:
    return ApprovalDecision(approved=True, reviewer="policy:approve-all")


async def reject_all(request: dict[str, Any]) -> ApprovalDecision:
    return ApprovalDecision(approved=False, reviewer="policy:reject-all")


@dataclass
class InvestigationResult:
    diagnosis: Diagnosis | None
    outcome: str
    turns: int
    tool_calls: list[dict[str, Any]]
    input_tokens: int
    output_tokens: int
    model_calls: int
    time_to_diagnosis_s: float | None
    total_time_s: float
    approval_requests: list[dict[str, Any]] = field(default_factory=list)
    approval: ApprovalDecision | None = None
    action_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnosis": self.diagnosis.model_dump(mode="json") if self.diagnosis else None,
            "outcome": self.outcome,
            "turns": self.turns,
            "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "model_calls": self.model_calls,
            "time_to_diagnosis_s": self.time_to_diagnosis_s,
            "total_time_s": self.total_time_s,
            "approval_requests": self.approval_requests,
            "approval": self.approval.model_dump() if self.approval else None,
            "action_result": self.action_result,
        }


async def run_investigation(
    alert: str,
    model: BaseChatModel,
    tools: ToolSet,
    approval_handler: ApprovalHandler,
    *,
    config: AgentConfig | None = None,
    on_event: EventHandler | None = None,
) -> InvestigationResult:
    graph = build_graph(model, tools.read, tools.write, config=config, checkpointer=InMemorySaver())
    thread: dict[str, Any] = {
        "configurable": {"thread_id": uuid.uuid4().hex},
        "recursion_limit": 80,
    }
    started = time.perf_counter()
    diagnosed_after: float | None = None
    requests: list[dict[str, Any]] = []
    approval: ApprovalDecision | None = None

    payload: Any = {"messages": [HumanMessage(alert)]}
    while True:
        async for update in graph.astream(payload, thread, stream_mode="updates"):
            for node, values in update.items():
                if node == "__interrupt__":
                    continue
                if node == "validate" and (values or {}).get("diagnosis"):
                    diagnosed_after = time.perf_counter() - started
                if on_event is not None:
                    on_event(node, values or {})
        snapshot = await graph.aget_state(thread)
        if not snapshot.interrupts:
            break
        request = snapshot.interrupts[0].value
        requests.append(request)
        if on_event is not None:
            on_event("approval_request", request)
        approval = await approval_handler(request)
        payload = Command(resume=approval.model_dump())

    state = snapshot.values
    usage = state.get("usage", [])
    return InvestigationResult(
        diagnosis=Diagnosis.model_validate(state["diagnosis"]) if state.get("diagnosis") else None,
        outcome=state.get("outcome", "no_diagnosis"),
        turns=state.get("turns", 0),
        tool_calls=state.get("tool_calls", []),
        input_tokens=sum(u["input_tokens"] for u in usage),
        output_tokens=sum(u["output_tokens"] for u in usage),
        model_calls=len(usage),
        time_to_diagnosis_s=round(diagnosed_after, 3) if diagnosed_after is not None else None,
        total_time_s=round(time.perf_counter() - started, 3),
        approval_requests=requests,
        approval=approval,
        action_result=state.get("action_result"),
    )
