"""One-line summaries of tool results, as shown in the investigation timeline."""

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from opspilot_api.trace import events_from_update, parse_output, summarize


@pytest.mark.parametrize(
    ("tool", "output", "expected"),
    [
        (
            "get_service_health",
            {"services": [{"service": s, "status": "healthy"} for s in ("storefront", "orders")]},
            "All 2 checked services healthy.",
        ),
        (
            "get_service_health",
            {
                "services": [
                    {"service": "payments", "status": "unreachable"},
                    {"service": "orders", "status": "unhealthy", "http_status": 503},
                    {"service": "storefront", "status": "healthy"},
                ]
            },
            "payments unreachable; orders unhealthy (HTTP 503); 1 healthy.",
        ),
        (
            "query_metric",
            {
                "service": "payments",
                "metric": "error_rate",
                "unit": "ratio",
                "series": [{"latest": 0.412, "baseline": 0.002, "trend": "rising"}],
            },
            "payments error_rate: 41.2% vs baseline 0.2%, rising.",
        ),
        (
            "query_metric",
            {
                "service": "orders",
                "metric": "latency_p95",
                "unit": "ms",
                "series": [
                    {
                        "labels": {"peer": "payments"},
                        "latest": 1310.5,
                        "baseline": 22.0,
                        "trend": "rising",
                    },
                    {"labels": {"peer": "postgres"}, "latest": 3.0, "baseline": 3.0},
                ],
            },
            "orders latency_p95 (peer=payments): 1310.5 ms vs baseline 22 ms, rising "
            "(+1 more series).",
        ),
        (
            "query_metric",
            {"metric": "up", "series": [], "note": "No recent data. The service may be down."},
            "No recent data. The service may be down.",
        ),
        (
            "query_metric",
            {
                "service": "orders",
                "metric": "error_rate",
                "unit": "ratio",
                "series": [{"latest": 0.806, "baseline": None, "trend": "new"}],
            },
            "orders error_rate: 80.6%, no baseline in the window yet.",
        ),
        (
            "search_logs",
            {
                "total_matched": 42,
                "by_level": {"ERROR": 40, "WARN": 2},
                "top_messages": [
                    {"level": "ERROR", "count": 40, "example": "Connection is not available"}
                ],
            },
            "42 matching records (ERROR 40, WARN 2). "
            "Most frequent: 40x Connection is not available",
        ),
        ("search_logs", {"total_matched": 0}, "No matching log records."),
        (
            "get_recent_deploys",
            {
                "since_minutes": 60,
                "deploys": [
                    {
                        "service": "orders",
                        "kind": "deploy",
                        "version": "1.8.4",
                        "author": "s.patel",
                        "config_diff": {"payments.base-url": {"from": "a", "to": "b"}},
                    }
                ],
            },
            "1 event. Latest: orders deploy 1.8.4 by s.patel (payments.base-url).",
        ),
        (
            "get_recent_deploys",
            {"since_minutes": 60, "deploys": []},
            "No deploys in the last 60 minutes.",
        ),
    ],
)
def test_summaries(tool, output, expected):
    assert summarize(tool, output, ok=True) == expected


def test_failed_and_unknown_results_fall_back_to_their_text():
    assert summarize("search_logs", "could not read logs for orders", ok=False) == (
        "Failed: could not read logs for orders"
    )
    assert summarize("mystery", {"a": 1}, ok=True) == '{"a": 1}'
    assert summarize("query_metric", {"series": "garbled"}, ok=True).startswith("{")
    assert parse_output("not json") == "not json"


def test_tool_results_are_joined_to_their_calls_by_id():
    update = {
        "messages": [
            ToolMessage('{"total_matched": 0}', tool_call_id="b", name="search_logs"),
            ToolMessage("boom", tool_call_id="a", name="get_service_health", status="error"),
        ],
        "tool_calls": [
            {"turn": 1, "tool": "get_service_health", "args": {}, "call_id": "a", "ok": False},
            {
                "turn": 1,
                "tool": "search_logs",
                "args": {"service": "orders"},
                "call_id": "b",
                "ok": True,
            },
        ],
    }
    first, second = events_from_update("tools", update)
    assert first == (
        "tool_call",
        {**update["tool_calls"][0], "summary": "Failed: boom", "output": "boom"},
    )
    assert second[1]["summary"] == "No matching log records."
    assert second[1]["output"] == {"total_matched": 0}


def test_model_turns_keep_the_reasoning_text_and_requested_tools():
    message = AIMessage(
        content="Payments looks slow; checking its logs.",
        tool_calls=[{"name": "search_logs", "args": {"service": "payments"}, "id": "c1"}],
    )
    [(kind, data)] = events_from_update(
        "investigate",
        {"messages": [message], "turns": 3, "usage": [{"input_tokens": 10, "output_tokens": 2}]},
    )
    assert kind == "model_turn"
    assert data == {
        "turn": 3,
        "text": "Payments looks slow; checking its logs.",
        "requested": ["search_logs"],
        "input_tokens": 10,
        "output_tokens": 2,
    }
