from datetime import UTC, datetime, timedelta

import pytest

from opspilot_mcp.logsearch import message_shape, parse_line, search_logs
from opspilot_mcp.metrics import METRICS, summarize_metric, summarize_series
from opspilot_mcp.models import Series

T0 = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)

PYTHON_LINE = (
    '{"timestamp":"2026-09-24T02:08:57.554Z","level":"ERROR","service":"storefront",'
    '"logger":"upstream.orders","message":"Call to orders returned HTTP 500: POST /orders",'
    '"version":"2.14.0","trace_id":"c0a72fd57b4f14ee1c5aab7e353a78c8","upstream":"orders"}'
)
SPRING_LINE = (
    '{"@timestamp":"2026-09-24T02:08:57.54925397Z","@version":"1","message":"Unhandled '
    'exception while handling POST /orders","logger_name":"http.server","level":"ERROR",'
    '"level_value":40000,"traceId":"c0a72fd57b4f14ee1c5aab7e353a78c8","error_type":'
    '"NullPointerException","stack_trace":"java.lang.NullPointerException: boom\\n\\tat a.B.c'
    '(B.java:1)\\n\\tat a.B.d(B.java:2)\\n\\tat a.B.e(B.java:3)\\n\\tat a.B.f(B.java:4)"}'
)


def series(values: list[float | None]) -> Series:
    return Series(points=[(T0 + timedelta(seconds=15 * i), v) for i, v in enumerate(values)])


def test_summary_reports_rising_error_rate_against_baseline():
    summary = summarize_series(series([0.0] * 30 + [0.4] * 10), "ratio")
    assert summary["baseline"] == 0.0
    assert summary["latest"] == 0.4
    assert summary["trend"] == "rising"
    assert len(summary["points"]) <= 11
    assert summary["points"][-1] == ["12:09:45", 0.4]


def test_summary_treats_nan_as_missing_and_flags_no_recent_data():
    summary = summarize_series(series([10.0] * 5 + [float("nan")] * 5), "ms")
    assert summary["latest"] is None
    assert (summary["last_value"], summary["last_seen"]) == (10.0, "12:01:00")
    empty = summarize_metric("payments", "error_rate", 15, [series([None, None])])
    assert empty["series"][0]["trend"] == "no recent data"
    assert "No recent data" in empty["note"]


def test_small_absolute_changes_are_flat():
    assert summarize_series(series([20.0] * 20 + [23.0] * 5), "ms")["trend"] == "flat"


@pytest.mark.parametrize("metric", sorted(METRICS))
def test_every_metric_query_targets_the_service_job(metric):
    query = METRICS[metric].query("orders")
    assert 'job="orders"' in query
    assert "$job" not in query


def test_parses_both_log_formats_into_one_shape():
    python, spring = parse_line(PYTHON_LINE, "storefront"), parse_line(SPRING_LINE, "orders")
    assert python is not None
    assert spring is not None
    assert (python.level, python.logger, python.trace_id) == (
        "ERROR",
        "upstream.orders",
        "c0a72fd57b4f14ee1c5aab7e353a78c8",
    )
    assert spring.logger == "http.server"
    assert spring.trace_id == python.trace_id
    assert spring.error_type == "NullPointerException"
    assert spring.timestamp.microsecond == 549253
    assert parse_line("Picked up JAVA_TOOL_OPTIONS", "orders") is None


def test_search_filters_groups_and_truncates():
    entries = [parse_line(SPRING_LINE, "orders")] * 3 + [parse_line(PYTHON_LINE, "orders")]
    info = parse_line(PYTHON_LINE.replace('"ERROR"', '"INFO"'), "orders")
    result = search_logs([*entries, info], level="WARN", limit=2)
    assert result["total_matched"] == 4
    assert result["by_level"] == {"ERROR": 4}
    assert result["top_messages"][0]["count"] == 3
    assert len(result["recent"]) == 2
    java = next(r for r in result["recent"] if "stack" in r)
    assert java["stack"].count("\n") == 3


def test_search_by_query_and_trace_id():
    entries = [parse_line(SPRING_LINE, "orders"), parse_line(PYTHON_LINE, "orders")]
    assert search_logs(entries, query="nullpointer")["total_matched"] == 1
    assert search_logs(entries, trace_id="c0a72fd57b4f14ee1c5aab7e353a78c8")["total_matched"] == 2
    assert search_logs(entries, trace_id="0" * 32)["total_matched"] == 0


def test_message_shape_ignores_numbers_and_ids():
    assert message_shape("POST /orders/1042 503 1508ms") == message_shape("POST /orders/7 503 12ms")
