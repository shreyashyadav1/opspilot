"""Spans the investigation graph creates, captured with an in-memory exporter.

Companion to test_graph.py, which covers graph behaviour; this file only asserts what gets
traced (node spans, the llm.chat span and its token usage, mcp.tool spans and their arguments
and result size, and the approval_wait span around the approval callback).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from opspilot_agent.llm.fake import ScriptedChatModel
from opspilot_agent.mcp_client import ToolSet
from opspilot_agent.prompts import SUBMIT_TOOL
from opspilot_agent.runner import approve_all, reject_all, run_investigation

ALERT = "ALERT: checkout errors\nService: storefront"


def diagnosis(action: str = "escalate") -> dict[str, Any]:
    return {
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


def call(name: str, args: dict[str, Any], call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def submit(body: dict[str, Any], call_id: str = "submit-1") -> AIMessage:
    return call(SUBMIT_TOOL, body, call_id)


def toolset() -> ToolSet:
    async def health(service: str | None = None) -> str:
        return json.dumps({"services": [{"service": "orders", "status": "healthy"}]})

    async def rollback(service: str, reason: str) -> str:
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
def traces():
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


async def test_advisory_run_traces_nodes_llm_and_tool_calls(traces):
    provider, exporter = traces
    model = ScriptedChatModel(
        responses=[call("get_service_health", {}, "c1"), submit(diagnosis("escalate"))]
    )
    result = await run_investigation(ALERT, model, toolset(), approve_all, tracer_provider=provider)
    assert result.outcome == "advisory"

    names = [span.name for span in exporter.get_finished_spans()]
    assert names.count("graph.investigate") == 2
    assert "graph.tools" in names
    assert "graph.validate" in names
    assert "graph.advisory" in names
    assert names.count("llm.chat") == 2
    assert "mcp.tool/get_service_health" in names
    # No approval was requested for an advisory outcome.
    assert "approval_wait" not in names


async def test_llm_span_carries_model_and_token_usage(traces):
    provider, exporter = traces
    model = ScriptedChatModel(responses=[submit(diagnosis("escalate"))])
    await run_investigation(ALERT, model, toolset(), approve_all, tracer_provider=provider)

    [llm_span] = [s for s in exporter.get_finished_spans() if s.name == "llm.chat"]
    assert llm_span.attributes["gen_ai.request.model"] == "scripted"
    assert llm_span.attributes["gen_ai.usage.input_tokens"] > 0
    assert llm_span.attributes["gen_ai.usage.output_tokens"] > 0


async def test_tool_call_span_carries_name_args_and_result_size(traces):
    provider, exporter = traces
    model = ScriptedChatModel(
        responses=[call("get_service_health", {"service": "orders"}, "c1"), submit(diagnosis())]
    )
    await run_investigation(ALERT, model, toolset(), approve_all, tracer_provider=provider)

    [tool_span] = [
        s for s in exporter.get_finished_spans() if s.name == "mcp.tool/get_service_health"
    ]
    assert tool_span.attributes["opspilot.tool.name"] == "get_service_health"
    assert "orders" in tool_span.attributes["opspilot.tool.args"]
    assert tool_span.attributes["opspilot.tool.ok"]
    assert tool_span.attributes["opspilot.tool.result_size"] > 0
    assert tool_span.attributes["opspilot.tool.latency_ms"] >= 0


async def test_approval_wait_span_brackets_the_approval_callback(traces):
    provider, exporter = traces
    model = ScriptedChatModel(responses=[submit(diagnosis("rollback_deploy"))])
    result = await run_investigation(ALERT, model, toolset(), approve_all, tracer_provider=provider)
    assert result.outcome == "executed"

    names = [span.name for span in exporter.get_finished_spans()]
    assert "approval_wait" in names
    assert "graph.approval_gate" in names
    assert "graph.execute_action" in names
    assert "mcp.tool/rollback_deploy" in names


async def test_rejected_rollback_still_traces_the_wait(traces):
    provider, exporter = traces
    model = ScriptedChatModel(responses=[submit(diagnosis("rollback_deploy"))])
    result = await run_investigation(ALERT, model, toolset(), reject_all, tracer_provider=provider)
    assert result.outcome == "rejected"

    names = [span.name for span in exporter.get_finished_spans()]
    assert "approval_wait" in names
    assert "graph.rejected" in names
    assert "mcp.tool/rollback_deploy" not in names
