"""Named metrics, their PromQL, and the compact summaries the model sees.

The model chooses a metric by name; the server owns the PromQL. Every service exposes the same
Micrometer-style metric names, so one template per metric covers them all.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Literal, get_args

from opspilot_mcp.models import Series

MetricName = Literal[
    "request_rate",
    "error_rate",
    "latency_p50",
    "latency_p95",
    "latency_p99",
    "upstream_error_rate",
    "upstream_latency_p95",
    "db_pool_active",
    "db_pool_pending",
    "memory_used_mb",
    "up",
]
METRIC_NAMES: tuple[str, ...] = get_args(MetricName)

_BUSINESS = 'uri!~"/actuator.*|/admin.*"'


@dataclass(frozen=True)
class MetricDefinition:
    unit: str
    description: str
    promql: str
    only_for: tuple[str, ...] | None = None

    def query(self, service: str) -> str:
        return self.promql.replace("$job", service)


def _quantile(q: float) -> str:
    return (
        f"histogram_quantile({q}, sum by (le) "
        f'(rate(http_server_requests_seconds_bucket{{job="$job",{_BUSINESS}}}[1m]))) * 1000'
    )


METRICS: dict[str, MetricDefinition] = {
    "request_rate": MetricDefinition(
        "req/s",
        "Business requests handled per second.",
        f'sum(rate(http_server_requests_seconds_count{{job="$job",{_BUSINESS}}}[1m]))',
    ),
    "error_rate": MetricDefinition(
        "ratio",
        "Share of business requests answered with a 5xx status (0-1).",
        # "or vector(0)": a service that has never returned a 5xx has no 5xx series at all.
        f'(sum(rate(http_server_requests_seconds_count{{job="$job",{_BUSINESS},status=~"5.."}}'
        f"[1m])) or vector(0)) / sum(rate(http_server_requests_seconds_count"
        f'{{job="$job",{_BUSINESS}}}[1m]))',
    ),
    "latency_p50": MetricDefinition("ms", "Median request latency.", _quantile(0.5)),
    "latency_p95": MetricDefinition("ms", "95th percentile request latency.", _quantile(0.95)),
    "latency_p99": MetricDefinition("ms", "99th percentile request latency.", _quantile(0.99)),
    "upstream_error_rate": MetricDefinition(
        "ratio",
        "Share of this service's outbound calls that failed (5xx or no response), per dependency.",
        '(sum by (client_name) (rate(http_client_requests_seconds_count{job="$job",'
        'outcome=~"SERVER_ERROR|UNKNOWN"}[1m])) or sum by (client_name) '
        '(rate(http_client_requests_seconds_count{job="$job"}[1m])) * 0) / sum by (client_name) '
        '(rate(http_client_requests_seconds_count{job="$job"}[1m]))',
    ),
    "upstream_latency_p95": MetricDefinition(
        "ms",
        "95th percentile latency of this service's outbound calls, per dependency.",
        "histogram_quantile(0.95, sum by (le, client_name) "
        '(rate(http_client_requests_seconds_bucket{job="$job"}[1m]))) * 1000',
    ),
    "db_pool_active": MetricDefinition(
        "connections",
        "Connections in use in the database pool (pool size 5).",
        'sum(hikaricp_connections_active{job="$job"})',
        only_for=("orders",),
    ),
    "db_pool_pending": MetricDefinition(
        "threads",
        "Threads waiting for a database connection.",
        'sum(hikaricp_connections_pending{job="$job"})',
        only_for=("orders",),
    ),
    "memory_used_mb": MetricDefinition(
        "MB",
        "Resident memory of the process (storefront, payments); JVM heap in use (orders).",
        # prometheus_client's process collector for the Python services, Micrometer's JVM
        # metrics for orders.
        '(max(process_resident_memory_bytes{job="$job"}) or '
        'sum(jvm_memory_used_bytes{job="$job",area="heap"})) / 1048576',
    ),
    "up": MetricDefinition(
        "bool",
        "1 if Prometheus could scrape the service, 0 if the scrape failed.",
        'up{job="$job"}',
    ),
}

MAX_POINTS = 10


def _clean(value: float | None) -> float | None:
    if value is None or math.isnan(value) or math.isinf(value):
        return None
    return value


def _round(value: float | None, unit: str) -> float | None:
    if value is None:
        return None
    return round(value, 3 if unit == "ratio" else 1)


def _trend(baseline: float | None, latest: float | None, unit: str) -> str:
    if latest is None:
        return "no recent data"
    if baseline is None:
        return "new"
    floor = {"ratio": 0.01, "ms": 5.0, "req/s": 0.2}.get(unit, 0.5)
    if abs(latest - baseline) < floor:
        return "flat"
    if baseline <= 0:
        return "rising"
    ratio = latest / baseline
    if ratio >= 1.5:
        return "rising"
    if ratio <= 0.67:
        return "falling"
    return "flat"


def summarize_series(series: Series, unit: str) -> dict[str, Any]:
    """Latest vs. baseline, extremes, trend and a few points.

    The baseline is the median of the first half of the window, which tolerates a short
    earlier spike. Points cover the whole window with gaps as None; a value only counts as
    "latest" if it is among the last three points, so a service that stopped reporting shows
    as missing data instead of its last healthy value.
    """
    values = [(ts, _clean(v)) for ts, v in series.points]
    present = [(ts, v) for ts, v in values if v is not None]
    first_half = [v for _, v in values[: max(1, len(values) // 2)] if v is not None]
    recent = [v for _, v in values[-3:] if v is not None]
    latest = recent[-1] if recent else None
    baseline = statistics.median(first_half) if first_half else None

    step = max(1, math.ceil(len(values) / MAX_POINTS))
    sampled = values[::step]
    if values and sampled[-1] is not values[-1]:
        sampled.append(values[-1])

    summary: dict[str, Any] = {
        "latest": _round(latest, unit),
        "baseline": _round(baseline, unit),
        "min": _round(min(v for _, v in present), unit) if present else None,
        "max": _round(max(v for _, v in present), unit) if present else None,
        "trend": _trend(baseline, latest, unit),
        "points": [[ts.strftime("%H:%M:%S"), _round(v, unit)] for ts, v in sampled],
    }
    if latest is None and present:
        summary["last_value"] = _round(present[-1][1], unit)
        summary["last_seen"] = present[-1][0].strftime("%H:%M:%S")
    if series.labels:
        summary = {"labels": series.labels, **summary}
    return summary


def summarize_metric(
    service: str, metric: str, window_minutes: int, series: list[Series]
) -> dict[str, Any]:
    definition = METRICS[metric]
    result: dict[str, Any] = {
        "service": service,
        "metric": metric,
        "unit": definition.unit,
        "window_minutes": window_minutes,
        "series": [summarize_series(s, definition.unit) for s in series],
    }
    if not series or all(s["latest"] is None for s in result["series"]):
        result["note"] = (
            "No recent data. The service may be down, not receiving traffic, "
            "or failing its metrics scrape (check the 'up' metric and health)."
        )
    return result
