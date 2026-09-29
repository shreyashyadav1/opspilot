"""Graph behaviour with a scripted model: investigation, validation, approval gate, budgets."""

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool

from opspilot_agent.graph import AgentConfig
from opspilot_agent.llm.fake import ScriptedChatModel
from opspilot_agent.mcp_client import ToolSet
from opspilot_agent.prompts import SUBMIT_TOOL
from opspilot_agent.runner import approve_all, reject_all, run_investigation

ALERT = "ALERT: checkout errors\nService: storefront"


def diagnosis(action: str = "escalate", **overrides: Any) -> dict[str, Any]:
    body = {
        "root_cause_service": "orders",
        "category": "bad_deploy" if action == "rollback_deploy" else "error_rate",
        "summary": "orders started failing after the latest change.",
        "evidence": [{"source": "logs", "service": "orders", "detail": "NullPointerException x40"}],
        "confidence": 0.8,
        "proposed_action": {
            "type": action,
            "target_service": "orders",
            "rationale": "Revert the change that introduced the failures.",
        },
    }
    body.update(overrides)
    return body


def call(name: str, args: dict[str, Any], call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def submit(body: dict[str, Any], call_id: str = "submit-1") -> AIMessage:
    return call(SUBMIT_TOOL, body, call_id)


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def toolset(self) -> ToolSet:
        async def health(service: str | None = None) -> str:
            self.calls.append(("get_service_health", {"service": service}))
            return json.dumps({"services": [{"service": "orders", "status": "healthy"}]})

        async def rollback(service: str, reason: str) -> str:
            self.calls.append(("rollback_deploy", {"service": service, "reason": reason}))
            return json.dumps({"status": "rolled_back", "event": {"service": service}})

        read = StructuredTool.from_function(
            coroutine=health,
            name="get_service_health",
            description="health",
            metadata={"readOnlyHint": True},
        )
        write = StructuredTool.from_function(
            coroutine=rollback,
            name="rollback_deploy",
            description="rollback",
            metadata={"readOnlyHint": False, "destructiveHint": True},
        )
        return ToolSet.from_tools([read, write])


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


async def run(model, recorder, handler=approve_all, **config):
    return await run_investigation(
        ALERT, model, recorder.toolset(), handler, config=AgentConfig(**config)
    )


async def test_advisory_diagnosis_ends_without_approval(recorder):
    model = ScriptedChatModel(
        responses=[call("get_service_health", {}, "c1"), submit(diagnosis("escalate"))]
    )
    result = await run(model, recorder)
    assert result.outcome == "advisory"
    assert result.diagnosis.root_cause_service == "orders"
    assert result.approval_requests == []
    assert [c[0] for c in recorder.calls] == ["get_service_health"]
    assert result.turns == 2
    assert result.model_calls == 2
    assert result.input_tokens > 0
    assert result.tool_calls[0]["ok"] is True
    assert result.time_to_diagnosis_s is not None


async def test_write_tools_are_never_offered_to_the_model(recorder):
    model = ScriptedChatModel(responses=[submit(diagnosis())])
    await run(model, recorder)
    assert model.calls[0]["tools"] == ["get_service_health", SUBMIT_TOOL]


async def test_approved_rollback_is_executed_once(recorder):
    model = ScriptedChatModel(responses=[submit(diagnosis("rollback_deploy"))])
    result = await run(model, recorder, approve_all)
    assert result.outcome == "executed"
    [request] = result.approval_requests
    assert request["tool"] == "rollback_deploy"
    assert request["action"]["target_service"] == "orders"
    assert recorder.calls == [
        (
            "rollback_deploy",
            {"service": "orders", "reason": "Revert the change that introduced the failures."},
        )
    ]
    assert result.action_result["ok"] is True


async def test_rejected_rollback_is_not_executed(recorder):
    model = ScriptedChatModel(responses=[submit(diagnosis("rollback_deploy"))])
    result = await run(model, recorder, reject_all)
    assert result.outcome == "rejected"
    assert result.approval.approved is False
    assert recorder.calls == []
    assert result.action_result is None


async def test_direct_write_tool_call_is_refused(recorder):
    model = ScriptedChatModel(
        responses=[
            call("rollback_deploy", {"service": "orders", "reason": "just do it now"}, "c1"),
            submit(diagnosis("escalate")),
        ]
    )
    result = await run(model, recorder)
    assert recorder.calls == []
    [record] = result.tool_calls
    assert record["policy_violation"] is True
    refusal = next(m for m in model.calls[1]["messages"] if isinstance(m, ToolMessage))
    assert "needs human approval" in refusal.content


async def test_invalid_diagnosis_gets_feedback_and_a_retry(recorder):
    model = ScriptedChatModel(
        responses=[
            submit(diagnosis(category="network", confidence=3), "bad"),
            submit(diagnosis(), "good"),
        ]
    )
    result = await run(model, recorder)
    assert result.diagnosis is not None
    feedback = next(m for m in model.calls[1]["messages"] if isinstance(m, ToolMessage))
    assert feedback.status == "error"
    assert "category" in feedback.content
    assert "confidence" in feedback.content


async def test_last_turn_forces_submit_diagnosis(recorder):
    model = ScriptedChatModel(responses=[call("get_service_health", {}, "c1"), submit(diagnosis())])
    await run(model, recorder, max_turns=2)
    assert model.calls[0]["tool_choice"] is None
    assert model.calls[1]["tool_choice"] == SUBMIT_TOOL


async def test_text_reply_is_nudged_back_to_tools(recorder):
    model = ScriptedChatModel(
        responses=[AIMessage(content="I think it is orders."), submit(diagnosis())]
    )
    result = await run(model, recorder)
    assert result.diagnosis is not None
    assert isinstance(model.calls[1]["messages"][-1], HumanMessage)


async def test_gives_up_when_the_model_never_submits(recorder):
    model = ScriptedChatModel(responses=[AIMessage(content="thinking")] * 3)
    result = await run(model, recorder, max_nudges=2)
    assert result.outcome == "no_diagnosis"
    assert result.diagnosis is None
    assert result.time_to_diagnosis_s is None


async def test_unknown_tools_are_reported_to_the_model(recorder):
    model = ScriptedChatModel(responses=[call("restart_everything", {}, "c1"), submit(diagnosis())])
    result = await run(model, recorder)
    assert result.tool_calls[0]["error"] == "unknown_tool"


async def test_tool_call_records_carry_call_id_and_start_time(recorder):
    model = ScriptedChatModel(responses=[call("get_service_health", {}, "c1"), submit(diagnosis())])
    result = await run(model, recorder)
    [record] = result.tool_calls
    assert record["call_id"] == "c1"
    started = datetime.fromisoformat(record["started_at"])
    assert started.tzinfo is not None
    assert abs((datetime.now(UTC) - started).total_seconds()) < 60
