"""The agent API's traces: one per investigation, across the approval pause, a resume and a restart.

Spans are captured with an in-memory exporter handed to create_app(); the MCP tool server is the
in-process FakeTools, so these tests cover what the API itself creates and persists. The
cross-process half (the MCP server subprocess joining the same trace) is covered by
tests/observability/test_export.py.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tests.api.support import TERMINAL, FakeTools, build_app, serve, wait_for

ALERT = {"alert": "Checkout error rate above SLO", "target": "storefront", "firing_minutes": 4}


def _provider() -> tuple[TracerProvider, InMemorySpanExporter]:
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


def _named(spans: tuple[ReadableSpan, ...], name: str) -> ReadableSpan:
    [span] = [s for s in spans if s.name == name]
    return span


def _at(unix_ns: int) -> datetime:
    return datetime.fromtimestamp(unix_ns / 1e9, UTC)


def _assert_one_connected_trace(spans: tuple[ReadableSpan, ...], trace_id: str) -> None:
    assert {f"{s.context.trace_id:032x}" for s in spans} == {trace_id}
    by_id = {s.context.span_id: s for s in spans}
    for span in spans:
        node = span
        while node.parent is not None:
            node = by_id[node.parent.span_id]  # a KeyError means an orphaned span
        assert node.name == "investigation", f"{span.name} is not under the investigation"


async def decide(client, investigation_id: str, body: dict) -> None:
    response = await client.post(f"/investigations/{investigation_id}/decision", json=body)
    assert response.status_code == 200, response.text


async def test_an_approved_investigation_is_one_trace_across_the_pause(settings, tools):
    provider, exporter = _provider()
    async with serve(build_app(settings, tools, "rollback_deploy", tracer_provider=provider)) as c:
        created = await c.post("/investigations", json=ALERT)
        investigation_id = created.json()["id"]
        paused = await wait_for(c, investigation_id, {"awaiting_approval"} | TERMINAL)
        assert paused["status"] == "awaiting_approval"
        await asyncio.sleep(0.05)  # so the approval wait has a measurable length
        await decide(c, investigation_id, {"decision": "approve", "reviewer": "alice"})
        done = await wait_for(c, investigation_id, TERMINAL)
    assert done["status"] == "executed"

    spans = exporter.get_finished_spans()
    _assert_one_connected_trace(spans, done["trace_id"])

    root = _named(spans, "investigation")
    resume = _named(spans, "investigation.resume")
    wait = _named(spans, "approval_wait")
    assert resume.parent.span_id == root.context.span_id
    assert wait.parent.span_id == root.context.span_id
    names = [s.name for s in spans]
    assert "llm.chat" in names
    assert "mcp.tool/get_service_health" in names
    assert "mcp.tool/rollback_deploy" in names

    # The wait is built from the persisted timestamps: it starts when the approval was
    # requested and ends at the decision, not whenever the resume happened to run.
    events = {event["kind"]: event for event in done["trace"]}
    requested_at = datetime.fromisoformat(events["approval_requested"]["at"])
    decided_at = datetime.fromisoformat(done["approval"]["decided_at"])
    assert abs((_at(wait.start_time) - requested_at).total_seconds()) < 1.0
    assert abs((_at(wait.end_time) - decided_at).total_seconds()) < 0.001
    assert wait.end_time - wait.start_time >= 40_000_000  # slept for 50 ms
    assert wait.attributes["opspilot.approval.reviewer"] == "alice"
    assert wait.attributes["opspilot.approval.approved"] is True


async def test_a_rejection_is_traced_into_the_same_trace(settings, tools):
    provider, exporter = _provider()
    async with serve(build_app(settings, tools, "rollback_deploy", tracer_provider=provider)) as c:
        investigation_id = (await c.post("/investigations", json=ALERT)).json()["id"]
        await wait_for(c, investigation_id, {"awaiting_approval"})
        await decide(c, investigation_id, {"decision": "reject", "reviewer": "bob"})
        done = await wait_for(c, investigation_id, TERMINAL)
    assert done["status"] == "rejected"

    spans = exporter.get_finished_spans()
    _assert_one_connected_trace(spans, done["trace_id"])
    names = [s.name for s in spans]
    assert "graph.rejected" in names
    assert "mcp.tool/rollback_deploy" not in names
    assert _named(spans, "approval_wait").attributes["opspilot.approval.approved"] is False


async def test_a_decision_after_a_restart_joins_the_original_trace(settings, tools):
    before, before_spans = _provider()
    async with serve(build_app(settings, tools, "rollback_deploy", tracer_provider=before)) as c:
        investigation_id = (await c.post("/investigations", json=ALERT)).json()["id"]
        paused = await wait_for(c, investigation_id, {"awaiting_approval"})
    trace_id = paused["trace_id"]
    assert {f"{s.context.trace_id:032x}" for s in before_spans.get_finished_spans()} == {trace_id}

    # A new process: new tracer provider, new service object, only the SQLite files in common.
    after, after_spans = _provider()
    restarted = build_app(settings, FakeTools(), "rollback_deploy", tracer_provider=after)
    async with serve(restarted) as c:
        assert (await c.get(f"/investigations/{investigation_id}")).json()["trace_id"] == trace_id
        await decide(c, investigation_id, {"decision": "approve"})
        done = await wait_for(c, investigation_id, TERMINAL)
    assert done["status"] == "executed"

    resumed = after_spans.get_finished_spans()
    assert {f"{s.context.trace_id:032x}" for s in resumed} == {trace_id}
    names = [s.name for s in resumed]
    assert "approval_wait" in names
    assert "investigation.resume" in names
    assert "mcp.tool/rollback_deploy" in names
    # The original root span belongs to the first process; the resumed spans point back at it.
    root = _named(before_spans.get_finished_spans(), "investigation")
    assert _named(resumed, "investigation.resume").parent.span_id == root.context.span_id
