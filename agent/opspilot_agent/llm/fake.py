"""Deterministic chat models that implement the LangChain interface without an API.

- `ScriptedChatModel` replays a fixed list of responses. Tests use it to drive every branch of
  the graph.
- `PlaybookChatModel` follows a fixed triage runbook and applies simple rules to the tool
  results. It needs no key, is fully reproducible, and serves as the non-LLM baseline in the
  benchmark. Its logic is deliberately simple: health and deploys, then error rate and p95
  latency everywhere, then logs of the most downstream abnormal service.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import PrivateAttr

from opspilot_agent.prompts import SUBMIT_TOOL

DOWNSTREAM_FIRST = ("payments", "orders", "storefront")


def _estimate_tokens(value: Any) -> int:
    """Stable token estimate for fakes (about four characters per token)."""
    return max(1, len(json.dumps(value, default=str)) // 4)


def _with_usage(message: AIMessage, messages: Sequence[BaseMessage]) -> AIMessage:
    if message.usage_metadata:
        return message
    prompt = [m.content for m in messages]
    input_tokens = _estimate_tokens(prompt)
    output_tokens = _estimate_tokens([message.content, message.tool_calls])
    return message.model_copy(
        update={
            "usage_metadata": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            }
        }
    )


class _FakeBase(BaseChatModel):
    def bind_tools(self, tools: Sequence[Any], *, tool_choice: Any = None, **kwargs: Any) -> Any:
        formatted = [convert_to_openai_tool(tool) for tool in tools]
        return self.bind(tools=formatted, tool_choice=tool_choice, **kwargs)


class ScriptedChatModel(_FakeBase):
    """Replays `responses` in order and records what it was called with."""

    responses: list[AIMessage]
    _index: int = PrivateAttr(default=0)
    _calls: list[dict[str, Any]] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self._calls

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        tools = [t["function"]["name"] for t in kwargs.get("tools") or []]
        self._calls.append(
            {"messages": list(messages), "tools": tools, "tool_choice": kwargs.get("tool_choice")}
        )
        if self._index >= len(self.responses):
            raise IndexError("ScriptedChatModel ran out of responses")
        message = self.responses[self._index]
        self._index += 1
        return ChatResult(generations=[ChatGeneration(message=_with_usage(message, messages))])


def _observations(messages: Sequence[BaseMessage]) -> list[tuple[str, dict[str, Any], Any]]:
    """(tool name, args, parsed JSON payload or None) for every answered tool call."""
    requested: dict[str, tuple[str, dict[str, Any]]] = {}
    observed = []
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                requested[call["id"]] = (call["name"], call["args"])
        elif isinstance(message, ToolMessage) and message.tool_call_id in requested:
            name, args = requested[message.tool_call_id]
            payload = None
            if message.status != "error" and isinstance(message.content, str):
                try:
                    payload = json.loads(message.content)
                except json.JSONDecodeError:
                    payload = None
            observed.append((name, args, payload))
    return observed


class _Findings:
    """What the playbook has learned so far, indexed for its rules."""

    def __init__(self, observations: list[tuple[str, dict[str, Any], Any]]) -> None:
        self.health: dict[str, dict[str, Any]] = {}
        self.metrics: dict[tuple[str, str], dict[str, Any]] = {}
        self.logs: dict[str, dict[str, Any]] = {}
        self.deploys: list[dict[str, Any]] = []
        for name, args, payload in observations:
            if payload is None:
                continue
            if name == "get_service_health":
                self.health.update({s["service"]: s for s in payload["services"]})
            elif name == "query_metric" and payload.get("series"):
                self.metrics[(args["service"], args["metric"])] = payload["series"][0]
            elif name == "search_logs":
                self.logs[args["service"]] = payload
            elif name == "get_recent_deploys":
                self.deploys = payload["deploys"]

    def metric(self, service: str, metric: str) -> dict[str, Any]:
        return self.metrics.get((service, metric), {})

    def errors_up(self, service: str) -> bool:
        m = self.metric(service, "error_rate")
        latest, baseline = m.get("latest"), m.get("baseline") or 0.0
        return latest is not None and latest > max(0.05, 3 * baseline)

    def slower(self, service: str) -> bool:
        m = self.metric(service, "latency_p95")
        latest, baseline = m.get("latest"), m.get("baseline")
        return latest is not None and bool(baseline) and latest > max(2 * baseline, baseline + 200)

    def unhealthy(self, service: str) -> bool:
        return self.health.get(service, {}).get("status", "healthy") != "healthy"

    def abnormal(self, service: str) -> bool:
        return self.unhealthy(service) or self.errors_up(service) or self.slower(service)

    def suspect(self) -> str:
        return next((s for s in DOWNSTREAM_FIRST if self.abnormal(s)), "storefront")

    def log_text(self, service: str) -> str:
        logs = self.logs.get(service, {})
        messages = [m["example"] for m in logs.get("top_messages", [])]
        messages += [r["message"] for r in logs.get("recent", [])]
        return " ".join(messages)

    def config_deploys(self, service: str) -> list[dict[str, Any]]:
        return [
            d
            for d in self.deploys
            if d["service"] == service and d["kind"] == "deploy" and d.get("config_diff")
        ]


def _metric_evidence(findings: _Findings, service: str) -> list[dict[str, Any]]:
    evidence = []
    for metric, unit in (("error_rate", ""), ("latency_p95", " ms")):
        m = findings.metric(service, metric)
        if m.get("latest") is not None:
            evidence.append(
                {
                    "source": "metrics",
                    "service": service,
                    "detail": f"{metric} {m['latest']}{unit} vs baseline {m['baseline']}{unit} "
                    f"({m['trend']})",
                }
            )
    return evidence


def playbook_diagnosis(findings: _Findings) -> dict[str, Any]:
    suspect = findings.suspect()
    health = findings.health.get(suspect, {})
    text = findings.log_text(suspect).lower()
    pending = (
        findings.metric("orders", "db_pool_pending").get("latest") if suspect == "orders" else 0
    )
    deploys = findings.config_deploys(suspect)
    down = health.get("detail") == "service_unavailable" or health.get("status") == "unreachable"

    if "connection is not available" in text or (pending or 0) > 0:
        category, action = "resource_exhaustion", "restart_service"
    elif down:
        category, action = "dependency_outage", "escalate"
    elif deploys:
        category, action = "bad_deploy", "rollback_deploy"
    elif findings.errors_up(suspect):
        category, action = "error_rate", "escalate"
    elif findings.slower(suspect):
        category, action = "latency", "escalate"
    else:
        category, action = "error_rate", "escalate"

    evidence: list[dict[str, Any]] = []
    if findings.unhealthy(suspect):
        evidence.append(
            {
                "source": "health",
                "service": suspect,
                "detail": f"{health.get('status')} (HTTP {health.get('http_status')}): "
                f"{health.get('detail') or 'no detail'}"[:400],
            }
        )
    evidence += _metric_evidence(findings, suspect)
    top = findings.logs.get(suspect, {}).get("top_messages", [])
    if top:
        evidence.append(
            {
                "source": "logs",
                "service": suspect,
                "detail": f"{top[0]['count']}x {top[0]['level']}: {top[0]['example']}"[:400],
            }
        )
    if category == "bad_deploy":
        deploy = deploys[0]
        evidence.append(
            {
                "source": "deploys",
                "service": suspect,
                "detail": f"{deploy['version']} deployed at {deploy['deployed_at']}: "
                f"{json.dumps(deploy['config_diff'])}"[:400],
            }
        )
    if not evidence:
        evidence.append(
            {"source": "health", "service": suspect, "detail": "no clear anomaly found"}
        )

    confident = findings.abnormal(suspect)
    return {
        "root_cause_service": suspect,
        "category": category,
        "summary": f"{suspect} is the most downstream service behaving abnormally; "
        f"signals point to {category.replace('_', ' ')}.",
        "evidence": evidence[:8],
        "confidence": 0.8 if confident else 0.3,
        "proposed_action": {
            "type": action,
            "target_service": suspect,
            "rationale": f"Runbook action for {category.replace('_', ' ')} in {suspect}.",
        },
    }


class PlaybookChatModel(_FakeBase):
    """A fixed four-turn triage runbook driven by tool results."""

    model_name: str = "playbook"

    @property
    def _llm_type(self) -> str:
        return "playbook"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        turn = sum(isinstance(m, AIMessage) for m in messages)
        findings = _Findings(_observations(messages))
        if turn == 0:
            calls = [
                ("get_service_health", {}),
                ("get_recent_deploys", {"since_minutes": 60}),
            ]
        elif turn == 1:
            calls = [
                ("query_metric", {"service": s, "metric": m})
                for s in DOWNSTREAM_FIRST
                for m in ("error_rate", "latency_p95")
            ]
        elif turn == 2:
            suspect = findings.suspect()
            calls = [("search_logs", {"service": suspect, "level": "WARN"})]
            if suspect == "orders":
                calls.append(("query_metric", {"service": "orders", "metric": "db_pool_pending"}))
        else:
            calls = [(SUBMIT_TOOL, playbook_diagnosis(findings))]
        message = AIMessage(
            content="",
            tool_calls=[
                {"name": name, "args": args, "id": f"call_{turn}_{i}", "type": "tool_call"}
                for i, (name, args) in enumerate(calls)
            ],
        )
        return ChatResult(generations=[ChatGeneration(message=_with_usage(message, messages))])
