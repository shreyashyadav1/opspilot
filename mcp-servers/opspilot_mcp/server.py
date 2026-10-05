"""The OpsPilot observability MCP server.

Four read-only investigation tools and one write tool. Read tools are annotated
`readOnlyHint=True`; `rollback_deploy` is annotated `destructiveHint=True`, and the agent only
calls it after a human approves. Every argument is validated against an enum or a bounded range
before a backend is called, and results are compact JSON summaries.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from opentelemetry import trace
from pydantic import Field

from opspilot_mcp.backends.base import TelemetryBackend
from opspilot_mcp.catalog import SERVICES, ServiceName
from opspilot_mcp.logsearch import search_logs as run_log_search
from opspilot_mcp.metrics import METRICS, MetricName, summarize_metric
from opspilot_mcp.models import BackendError, LogLevel
from opspilot_observability.tracing import context_from_environ

READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
DESTRUCTIVE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False
)
WRITE_TOOLS = frozenset({"rollback_deploy"})

INSTRUCTIONS = (
    "Observability tools for the OpsPilot demo system (storefront -> orders -> postgres, "
    "payments). Start broad (health, recent deploys), then narrow down with metrics and logs. "
    "rollback_deploy changes production state and must only be called after human approval."
)


def _result(payload: dict[str, Any]) -> CallToolResult:
    """Compact JSON for the model plus the same payload as structured content."""
    text = json.dumps(payload, separators=(",", ":"), default=str)
    trace.get_current_span().set_attribute("opspilot.tool.result_size", len(text))
    return CallToolResult(content=[TextContent(type="text", text=text)], structuredContent=payload)


def build_server(
    backend: TelemetryBackend,
    name: str = "opspilot-observability",
    tracer_provider: trace.TracerProvider | None = None,
) -> FastMCP:
    mcp = FastMCP(name, instructions=INSTRUCTIONS, log_level="WARNING")
    tracer = (tracer_provider or trace.get_tracer_provider()).get_tracer("opspilot.mcp")
    # Set once at process startup: one MCP server subprocess serves one investigation, so every
    # tool call it handles is a child of that investigation's trace.
    investigation_context = context_from_environ()

    def tool_span(tool: str, **attributes: Any) -> Any:
        return tracer.start_as_current_span(
            f"mcp.tool/{tool}",
            context=investigation_context,
            attributes={"opspilot.tool.name": tool, **attributes},
        )

    @mcp.tool(annotations=READ_ONLY)
    async def get_service_health(service: ServiceName | None = None) -> CallToolResult:
        """Health check results: status (healthy, unhealthy, unreachable), HTTP status,
        latency, running version, failing components and declared dependencies.

        Omit `service` to check every service at once.
        """
        args = json.dumps({"service": service})
        with tool_span("get_service_health", **{"opspilot.tool.args": args}):
            targets = [service] if service else list(SERVICES)
            reports = [await backend.health(s) for s in targets]
            return _result({"services": [r.model_dump(exclude_none=True) for r in reports]})

    @mcp.tool(annotations=READ_ONLY)
    async def query_metric(
        service: ServiceName,
        metric: MetricName,
        window_minutes: Annotated[int, Field(ge=5, le=60)] = 15,
    ) -> CallToolResult:
        """Summarize one metric for a service over the last `window_minutes`.

        Metrics: request_rate (req/s), error_rate (share of 5xx, 0-1), latency_p50/p95/p99
        (ms), upstream_error_rate and upstream_latency_p95 (outbound calls, per dependency),
        db_pool_active and db_pool_pending (orders only), up (1 if Prometheus can scrape it).
        Returns latest, baseline (median of the first half of the window), min, max, trend
        and a few points.
        """
        args = {"service": service, "metric": metric, "window_minutes": window_minutes}
        with tool_span("query_metric", **{"opspilot.tool.args": json.dumps(args)}):
            definition = METRICS[metric]
            if definition.only_for and service not in definition.only_for:
                raise ToolError(f"{metric} is only available for: {', '.join(definition.only_for)}")
            try:
                series = await backend.metric_series(service, metric, window_minutes)
            except BackendError as exc:
                raise ToolError(str(exc)) from exc
            return _result(summarize_metric(service, metric, window_minutes, series))

    @mcp.tool(annotations=READ_ONLY)
    async def search_logs(
        service: ServiceName,
        query: Annotated[str | None, Field(max_length=200)] = None,
        level: LogLevel | None = None,
        since_minutes: Annotated[int, Field(ge=1, le=60)] = 15,
        trace_id: Annotated[str | None, Field(pattern="^[0-9a-f]{32}$")] = None,
        limit: Annotated[int, Field(ge=1, le=25)] = 8,
    ) -> CallToolResult:
        """Search a service's structured logs.

        `query` is a case-insensitive substring matched against message, error type and stack
        trace. `level` is a minimum level (WARN includes ERROR). `trace_id` follows one request
        across services. Returns counts by level, the most frequent message shapes (errors
        first) and the most recent matching records.
        """
        args = {"service": service, "query": query, "level": level, "since_minutes": since_minutes}
        with tool_span("search_logs", **{"opspilot.tool.args": json.dumps(args)}):
            try:
                entries = await backend.log_entries(service, since_minutes)
            except BackendError as exc:
                raise ToolError(str(exc)) from exc
            result = run_log_search(
                entries, query=query, level=level, trace_id=trace_id, limit=limit
            )
            return _result({"service": service, "since_minutes": since_minutes, **result})

    @mcp.tool(annotations=READ_ONLY)
    async def get_recent_deploys(
        service: ServiceName | None = None,
        since_minutes: Annotated[int, Field(ge=5, le=7 * 24 * 60)] = 180,
    ) -> CallToolResult:
        """Deploys and rollbacks, newest first, with version, author, change summary and
        config diff. Omit `service` to see every service."""
        args = {"service": service, "since_minutes": since_minutes}
        with tool_span("get_recent_deploys", **{"opspilot.tool.args": json.dumps(args)}):
            try:
                events = await backend.deploys(service, since_minutes)
            except BackendError as exc:
                raise ToolError(str(exc)) from exc
            events = sorted(events, key=lambda e: e.deployed_at, reverse=True)
            return _result(
                {
                    "since_minutes": since_minutes,
                    "deploys": [e.model_dump(mode="json", exclude_none=True) for e in events],
                }
            )

    @mcp.tool(annotations=DESTRUCTIVE)
    async def rollback_deploy(
        service: ServiceName,
        reason: Annotated[str, Field(min_length=10, max_length=300)],
    ) -> CallToolResult:
        """Roll the service back to the version before its current one. Changes production
        state: call only after a human has approved the action."""
        args = {"service": service, "reason": reason}
        with tool_span("rollback_deploy", **{"opspilot.tool.args": json.dumps(args)}):
            try:
                event = await backend.rollback(service, reason)
            except BackendError as exc:
                raise ToolError(str(exc)) from exc
            return _result({"status": "rolled_back", "event": event.model_dump(mode="json")})

    return mcp
