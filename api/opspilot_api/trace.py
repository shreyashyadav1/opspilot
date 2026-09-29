"""Turn graph updates into trace events, with a one-line summary of every tool result.

The summaries are for people skimming a timeline; the parsed tool output is kept next to them
(bounded in size) so the evidence behind each line is one click away.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from opspilot_agent.graph import tool_output_text
from opspilot_agent.prompts import SUBMIT_TOOL

MAX_OUTPUT_CHARS = 6000
MAX_TEXT_CHARS = 2000


def parse_output(text: str) -> Any:
    """Tool output as JSON when it parses, otherwise as (bounded) text."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text[:MAX_OUTPUT_CHARS]


def _num(value: Any, unit: str | None) -> str:
    if value is None:
        return "no data"
    if unit == "ratio":
        return f"{value * 100:.1f}%"
    suffix = {"ms": " ms", "req/s": " req/s"}.get(unit or "", "")
    return f"{value:g}{suffix}"


def _health(payload: dict[str, Any]) -> str:
    services = payload.get("services") or []
    if not services:
        return "No services reported."
    bad = [s for s in services if s.get("status") != "healthy"]
    if not bad:
        return f"All {len(services)} checked services healthy."
    parts = []
    for s in bad:
        detail = f" (HTTP {s['http_status']})" if s.get("http_status") else ""
        parts.append(f"{s.get('service')} {s.get('status')}{detail}")
    healthy = len(services) - len(bad)
    return "; ".join(parts) + (f"; {healthy} healthy." if healthy else ".")


def _metric(payload: dict[str, Any]) -> str:
    series = payload.get("series") or []
    unit = payload.get("unit")
    if not series or all(s.get("latest") is None for s in series):
        return payload.get("note") or "No recent data."
    s = series[0]
    labels = s.get("labels") or {}
    scope = f" ({', '.join(f'{k}={v}' for k, v in labels.items())})" if labels else ""
    more = f" (+{len(series) - 1} more series)" if len(series) > 1 else ""
    head = f"{payload.get('service')} {payload.get('metric')}{scope}: {_num(s.get('latest'), unit)}"
    if s.get("baseline") is None:
        return f"{head}, no baseline in the window yet{more}."
    return f"{head} vs baseline {_num(s.get('baseline'), unit)}, {s.get('trend')}{more}."


def _logs(payload: dict[str, Any]) -> str:
    total = payload.get("total_matched", 0)
    if not total:
        return "No matching log records."
    levels = ", ".join(
        f"{level} {count}" for level, count in (payload.get("by_level") or {}).items()
    )
    top = (payload.get("top_messages") or [{}])[0]
    example = str(top.get("example", ""))[:140]
    first = f" Most frequent: {top.get('count')}x {example}" if example else ""
    return f"{total} matching records ({levels}).{first}"


def _deploys(payload: dict[str, Any]) -> str:
    events = payload.get("deploys") or []
    if not events:
        return f"No deploys in the last {payload.get('since_minutes')} minutes."
    latest = events[0]
    changed = ", ".join(latest.get("config_diff") or {}) or "no config change"
    count = f"{len(events)} event{'' if len(events) == 1 else 's'}"
    return (
        f"{count}. Latest: {latest.get('service')} {latest.get('kind')} "
        f"{latest.get('version')} by {latest.get('author')} ({changed})."
    )


def _rollback(payload: dict[str, Any]) -> str:
    event = payload.get("event") or {}
    return (
        f"{event.get('service')} rolled back from {event.get('previous_version')} "
        f"to {event.get('version')}."
    )


_SUMMARIZERS = {
    "get_service_health": _health,
    "query_metric": _metric,
    "search_logs": _logs,
    "get_recent_deploys": _deploys,
    "rollback_deploy": _rollback,
}


def summarize(tool: str | None, output: Any, ok: bool) -> str:
    if not ok:
        text = output if isinstance(output, str) else json.dumps(output, default=str)
        return f"Failed: {text[:200]}"
    summarizer = _SUMMARIZERS.get(tool or "")
    if summarizer is not None and isinstance(output, dict):
        try:
            return summarizer(output)
        except (KeyError, TypeError, ValueError, AttributeError):
            pass
    text = output if isinstance(output, str) else json.dumps(output, default=str)
    return text[:200]


def _text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return " ".join(
        block.get("text", "") if isinstance(block, dict) else str(block) for block in content
    )


def events_from_update(node: str, values: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """(kind, data) trace events for one node update of the investigation graph."""
    values = values or {}
    if node == "investigate":
        message = values["messages"][-1]
        usage = (values.get("usage") or [{}])[-1]
        requested = [c["name"] for c in getattr(message, "tool_calls", None) or []]
        text = _text(message).strip()[:MAX_TEXT_CHARS] if isinstance(message, AIMessage) else ""
        return [
            (
                "model_turn",
                {"turn": values.get("turns"), "text": text, "requested": requested, **usage},
            )
        ]
    if node == "tools":
        by_id = {
            m.tool_call_id: m for m in values.get("messages", []) if isinstance(m, ToolMessage)
        }
        events = []
        for record in values.get("tool_calls", []):
            message = by_id.get(record.get("call_id"))
            output = parse_output(tool_output_text(message)) if message else None
            events.append(
                (
                    "tool_call",
                    {
                        **record,
                        "summary": summarize(record["tool"], output, bool(record.get("ok"))),
                        "output": output,
                    },
                )
            )
        return events
    if node == "nudge":
        return [("nudge", {"message": "The model replied without tools; asked it to continue."})]
    if node == "validate":
        if values.get("diagnosis"):
            return [("diagnosis", {"diagnosis": values["diagnosis"]})]
        feedback = next(
            (
                _text(m)
                for m in values.get("messages", [])
                if isinstance(m, ToolMessage) and m.name == SUBMIT_TOOL
            ),
            "",
        )
        return [("diagnosis_invalid", {"feedback": feedback[:MAX_TEXT_CHARS]})]
    if node == "execute_action":
        result = values.get("action_result") or {}
        ok = bool(result.get("ok"))
        summary = summarize(result.get("tool"), result.get("output"), ok)
        return [("action", {**result, "summary": summary})]
    # approval_gate is recorded when the decision is made; terminal nodes when the run settles.
    return []
