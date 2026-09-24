"""Prometheus metrics shared by the Python services.

Metric names, labels and histogram buckets deliberately match what Spring Boot's Micrometer
publishes for the orders service (`http_server_requests_seconds`, `http_client_requests_seconds`
with SLO buckets), so one PromQL catalog covers every service.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Histogram, generate_latest
from starlette.responses import Response

# Seconds. Kept in sync with management.metrics.distribution.slo in orders/application.yml.
LATENCY_BUCKETS = (
    0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.25, 0.4, 0.6, 0.8,
    1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 5.0, 10.0,
)  # fmt: skip

HTTP_SERVER_REQUESTS = Histogram(
    "http_server_requests_seconds",
    "Duration of inbound HTTP requests.",
    ["method", "uri", "status", "outcome"],
    buckets=LATENCY_BUCKETS,
)

HTTP_CLIENT_REQUESTS = Histogram(
    "http_client_requests_seconds",
    "Duration of outbound HTTP requests.",
    ["client_name", "method", "uri", "status", "outcome"],
    buckets=LATENCY_BUCKETS,
)

# Status label used when no HTTP response was received (timeout, connection refused), matching
# Micrometer's convention for client-side I/O failures.
IO_ERROR_STATUS = "CLIENT_ERROR"


def outcome_for(status: int | None) -> str:
    if status is None:
        return "UNKNOWN"
    if status < 200:
        return "INFORMATIONAL"
    if status < 300:
        return "SUCCESS"
    if status < 400:
        return "REDIRECTION"
    if status < 500:
        return "CLIENT_ERROR"
    return "SERVER_ERROR"


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
