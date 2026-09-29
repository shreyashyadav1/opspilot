"""The investigation graph.

    investigate -> tools -> investigate ... -> validate -> [approval_gate -> execute_action]

Only read-only MCP tools and the local `submit_diagnosis` schema are bound to the model. Write
tools are never offered to it: the only path to a state-changing call runs through
`approval_gate`, which pauses the graph with `interrupt()` until a human answers.
"""

from __future__ import annotations

import asyncio
import json
import operator
import time
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt
from pydantic import ValidationError

from opspilot_agent.prompts import SUBMIT_TOOL, nudge, system_prompt
from opspilot_agent.schemas import ApprovalDecision, Diagnosis


@dataclass(frozen=True)
class AgentConfig:
    max_turns: int = 12
    max_nudges: int = 2
    max_validation_retries: int = 2
    max_tool_output_chars: int = 6000


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    turns: int
    nudges: int
    validation_errors: int
    diagnosis: dict[str, Any] | None
    approval: dict[str, Any] | None
    action_result: dict[str, Any] | None
    outcome: str
    tool_calls: Annotated[list[dict[str, Any]], operator.add]
    usage: Annotated[list[dict[str, int]], operator.add]


def submit_tool_schema() -> dict[str, Any]:
    schema = convert_to_openai_tool(Diagnosis)
    schema["function"]["name"] = SUBMIT_TOOL
    schema["function"]["description"] = (
        "Submit the final root-cause diagnosis. Call exactly once, after investigating."
    )
    return schema


def tool_output_text(message: ToolMessage | Any) -> str:
    """Flatten MCP content blocks into plain text."""
    content = message.content if isinstance(message, ToolMessage) else message
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block["text"])
        elif isinstance(block, str):
            parts.append(block)
    return "\n".join(parts)


def _usage(message: AIMessage) -> dict[str, int]:
    usage = message.usage_metadata or {}
    return {
        "input_tokens": int(usage.get("input_tokens", 0)),
        "output_tokens": int(usage.get("output_tokens", 0)),
    }


def _validation_feedback(exc: ValidationError) -> str:
    problems = "; ".join(
        f"{'.'.join(str(p) for p in err['loc']) or 'input'}: {err['msg']}"
        for err in exc.errors()[:6]
    )
    return f"Invalid diagnosis ({problems}). Fix these fields and call {SUBMIT_TOOL} again."


def build_graph(
    model: BaseChatModel,
    read_tools: list[BaseTool],
    write_tools: dict[str, BaseTool],
    *,
    config: AgentConfig | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> Any:
    config = config or AgentConfig()
    tools_by_name = {tool.name: tool for tool in read_tools}
    offered = [*read_tools, submit_tool_schema()]
    model_with_tools = model.bind_tools(offered)
    model_forced = model.bind_tools(offered, tool_choice=SUBMIT_TOOL)
    system = SystemMessage(system_prompt(config.max_turns))

    async def investigate(state: AgentState) -> dict[str, Any]:
        turns = state.get("turns", 0) + 1
        runnable = model_forced if turns >= config.max_turns else model_with_tools
        response = await runnable.ainvoke([system, *state["messages"]])
        return {"messages": [response], "turns": turns, "usage": [_usage(response)]}

    def after_investigate(state: AgentState) -> str:
        last = state["messages"][-1]
        calls = getattr(last, "tool_calls", None) or []
        if any(call["name"] == SUBMIT_TOOL for call in calls):
            return "validate"
        if calls:
            return "tools"
        if state.get("nudges", 0) < config.max_nudges and state["turns"] < config.max_turns:
            return "nudge"
        return "give_up"

    def nudge_node(state: AgentState) -> dict[str, Any]:
        return {"messages": [HumanMessage(nudge())], "nudges": state.get("nudges", 0) + 1}

    async def run_tool(call: dict[str, Any], turn: int) -> tuple[ToolMessage, dict[str, Any]]:
        name, args = call["name"], call.get("args") or {}
        record: dict[str, Any] = {"turn": turn, "tool": name, "args": args}
        started = time.perf_counter()
        if name in write_tools:
            text = (
                f"{name} changes production state and needs human approval. Propose it as "
                f"proposed_action in {SUBMIT_TOOL} instead."
            )
            record.update(ok=False, error="write_tool_refused", policy_violation=True)
            message = ToolMessage(text, tool_call_id=call["id"], name=name, status="error")
        elif name not in tools_by_name:
            text = f"Unknown tool {name!r}. Available: {', '.join(sorted(tools_by_name))}."
            record.update(ok=False, error="unknown_tool")
            message = ToolMessage(text, tool_call_id=call["id"], name=name, status="error")
        else:
            try:
                result = await tools_by_name[name].ainvoke({**call, "type": "tool_call"})
                text = tool_output_text(result)
                ok = getattr(result, "status", "success") != "error"
            except Exception as exc:  # transport failures must not kill the investigation
                text, ok = f"Tool {name} failed: {type(exc).__name__}: {exc}", False
            if len(text) > config.max_tool_output_chars:
                text = text[: config.max_tool_output_chars] + " ... [truncated]"
            record.update(ok=ok, error=None if ok else text[:300])
            message = ToolMessage(
                text, tool_call_id=call["id"], name=name, status="success" if ok else "error"
            )
        record["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return message, record

    async def tools_node(state: AgentState) -> dict[str, Any]:
        last = state["messages"][-1]
        results = await asyncio.gather(
            *(run_tool(call, state["turns"]) for call in last.tool_calls)  # type: ignore[union-attr]
        )
        return {
            "messages": [message for message, _ in results],
            "tool_calls": [record for _, record in results],
        }

    def validate(state: AgentState) -> dict[str, Any]:
        last = state["messages"][-1]
        calls = last.tool_calls  # type: ignore[union-attr]
        submit = next(call for call in calls if call["name"] == SUBMIT_TOOL)
        # Every tool call needs an answer before the next model turn.
        others = [
            ToolMessage(
                f"Not executed: {SUBMIT_TOOL} ends the investigation.",
                tool_call_id=call["id"],
                name=call["name"],
                status="error",
            )
            for call in calls
            if call["id"] != submit["id"]
        ]
        try:
            diagnosis = Diagnosis.model_validate(submit.get("args") or {})
        except ValidationError as exc:
            reply = ToolMessage(
                _validation_feedback(exc),
                tool_call_id=submit["id"],
                name=SUBMIT_TOOL,
                status="error",
            )
            return {
                "messages": [reply, *others],
                "validation_errors": state.get("validation_errors", 0) + 1,
            }
        reply = ToolMessage("Diagnosis recorded.", tool_call_id=submit["id"], name=SUBMIT_TOOL)
        return {
            "messages": [reply, *others],
            "diagnosis": diagnosis.model_dump(mode="json"),
        }

    def after_validate(state: AgentState) -> str:
        diagnosis = state.get("diagnosis")
        if diagnosis is None:
            retries_left = state.get("validation_errors", 0) <= config.max_validation_retries
            return (
                "investigate" if retries_left and state["turns"] < config.max_turns else "give_up"
            )
        tool = Diagnosis.model_validate(diagnosis).executable_tool
        return "approval_gate" if tool and tool in write_tools else "advisory"

    def advisory(state: AgentState) -> dict[str, Any]:
        return {"outcome": "advisory"}

    def give_up(state: AgentState) -> dict[str, Any]:
        return {"outcome": "no_diagnosis"}

    def approval_gate(state: AgentState) -> dict[str, Any]:
        diagnosis = Diagnosis.model_validate(state["diagnosis"])
        request = {
            "type": "approval_request",
            "tool": diagnosis.executable_tool,
            "action": diagnosis.proposed_action.model_dump(mode="json"),
            "root_cause_service": diagnosis.root_cause_service,
            "category": diagnosis.category.value,
            "confidence": diagnosis.confidence,
            "summary": diagnosis.summary,
            "evidence": [e.model_dump(mode="json") for e in diagnosis.evidence],
        }
        decision = interrupt(request, response_schema=ApprovalDecision)
        return {"approval": ApprovalDecision.model_validate(decision).model_dump()}

    def after_approval(state: AgentState) -> str:
        return "execute_action" if (state.get("approval") or {}).get("approved") else "rejected"

    def rejected(state: AgentState) -> dict[str, Any]:
        return {"outcome": "rejected"}

    async def execute_action(state: AgentState) -> dict[str, Any]:
        diagnosis = Diagnosis.model_validate(state["diagnosis"])
        tool_name = diagnosis.executable_tool
        assert tool_name is not None
        action = diagnosis.proposed_action
        args = {"service": action.target_service, "reason": action.rationale[:300]}
        call = {"name": tool_name, "args": args, "id": "approved-action", "type": "tool_call"}
        try:
            message = await write_tools[tool_name].ainvoke(call)
            output = tool_output_text(message)
            ok = getattr(message, "status", "success") != "error"
            try:
                payload: Any = json.loads(output)
            except json.JSONDecodeError:
                payload = output
        except Exception as exc:
            ok, payload = False, f"{type(exc).__name__}: {exc}"
        result = {"tool": tool_name, "args": args, "ok": ok, "output": payload}
        return {"action_result": result, "outcome": "executed" if ok else "failed"}

    graph = StateGraph(AgentState)
    graph.add_node("investigate", investigate)
    graph.add_node("tools", tools_node)
    graph.add_node("nudge", nudge_node)
    graph.add_node("validate", validate)
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("execute_action", execute_action)
    graph.add_node("advisory", advisory)
    graph.add_node("rejected", rejected)
    graph.add_node("give_up", give_up)

    graph.add_edge(START, "investigate")
    graph.add_conditional_edges(
        "investigate", after_investigate, ["validate", "tools", "nudge", "give_up"]
    )
    graph.add_edge("tools", "investigate")
    graph.add_edge("nudge", "investigate")
    graph.add_conditional_edges(
        "validate", after_validate, ["investigate", "approval_gate", "advisory", "give_up"]
    )
    graph.add_conditional_edges("approval_gate", after_approval, ["execute_action", "rejected"])
    for terminal in ("execute_action", "advisory", "rejected", "give_up"):
        graph.add_edge(terminal, END)
    return graph.compile(checkpointer=checkpointer)
