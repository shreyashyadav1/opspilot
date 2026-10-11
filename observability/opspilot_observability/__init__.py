"""Shared OpenTelemetry setup for the agent, the agent API and the MCP server.

Kept as its own package (rather than folded into `opspilot_agent`) because the MCP server does
not otherwise depend on the agent, and should not have to start doing so just to get tracing.
"""

from opspilot_observability.tracing import (
    DEFAULT_OTLP_ENDPOINT,
    configure,
    context_from_environ,
    context_from_traceparent,
    get_tracer,
    otlp_endpoint,
    subprocess_env,
    traceparent_of,
    tracing_enabled,
)

__all__ = [
    "DEFAULT_OTLP_ENDPOINT",
    "configure",
    "context_from_environ",
    "context_from_traceparent",
    "get_tracer",
    "otlp_endpoint",
    "subprocess_env",
    "traceparent_of",
    "tracing_enabled",
]
