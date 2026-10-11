"""Export end to end, without a trace backend container.

Runs the real CLI, which starts the real MCP server as a subprocess (simulated telemetry), with
tracing on, and captures what both processes actually send over OTLP/HTTP at a small collector
listening on an ephemeral localhost port. What this proves that the in-memory tests cannot:
spans really leave each process, the MCP server subprocess is told to export (and where), and the
trace context handed to it over the environment ties its spans to the CLI's investigation.
"""

from __future__ import annotations

import http.server
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)

from opspilot_mcp.backends.simulated import FaultSpec, SimulationSpec


@dataclass(frozen=True)
class Exported:
    service: str
    name: str
    trace_id: str
    span_id: str
    parent_id: str  # empty for a root span


class Collector:
    """Accepts OTLP/HTTP trace exports (protobuf) and keeps the spans it was sent."""

    def __init__(self) -> None:
        self._spans: list[Exported] = []
        self._lock = threading.Lock()
        collector = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if self.path == "/v1/traces":
                    collector._record(ExportTraceServiceRequest.FromString(body))
                payload = ExportTraceServiceResponse().SerializeToString()
                self.send_response(200)
                self.send_header("Content-Type", "application/x-protobuf")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args: object) -> None:
                pass

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.endpoint = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def _record(self, request: ExportTraceServiceRequest) -> None:
        with self._lock:
            for resource_spans in request.resource_spans:
                service = next(
                    (
                        attribute.value.string_value
                        for attribute in resource_spans.resource.attributes
                        if attribute.key == "service.name"
                    ),
                    "",
                )
                for scope_spans in resource_spans.scope_spans:
                    for span in scope_spans.spans:
                        self._spans.append(
                            Exported(
                                service,
                                span.name,
                                span.trace_id.hex(),
                                span.span_id.hex(),
                                span.parent_span_id.hex(),
                            )
                        )

    def spans(self) -> list[Exported]:
        with self._lock:
            return list(self._spans)

    def wait_for(self, done: Callable[[list[Exported]], bool], timeout: float = 20.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if done(self.spans()):
                return
            time.sleep(0.1)

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def collector() -> Iterator[Collector]:
    server = Collector()
    yield server
    server.close()


def investigate(tmp_path: Path, collector: Collector, *, tracing: bool) -> None:
    """One investigation of a bad orders deploy by the playbook, approved by the CLI policy."""
    simulation = tmp_path / "simulation.json"
    simulation.write_text(
        SimulationSpec(fault=FaultSpec(type="bad_config_deploy", target="orders")).model_dump_json()
    )
    env = {**os.environ, "OTEL_EXPORTER_OTLP_ENDPOINT": collector.endpoint}
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env.pop("OPSPILOT_TRACING_ENABLED", None)
    if tracing:
        env["OPSPILOT_TRACING_ENABLED"] = "true"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "opspilot_agent.cli",
            "investigate",
            "Checkout error rate above SLO",
            "--backend",
            "simulated",
            "--simulation",
            str(simulation),
            "--model",
            "fake:playbook",
            "--approve",
            "yes",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]


def test_the_cli_and_the_mcp_server_export_one_connected_trace(tmp_path, collector):
    investigate(tmp_path, collector, tracing=True)

    def exported_everything(spans: list[Exported]) -> bool:
        server_tools = {s.name for s in spans if s.service == "opspilot-mcp"}
        return "mcp.tool/rollback_deploy" in server_tools and any(
            s.name == "investigation" for s in spans
        )

    collector.wait_for(exported_everything)
    spans = collector.spans()

    assert {s.service for s in spans} == {"opspilot-agent-cli", "opspilot-mcp"}
    assert len({s.trace_id for s in spans}) == 1, "the two processes must share one trace"

    by_id = {s.span_id: s for s in spans}
    assert [s.name for s in spans if not s.parent_id] == ["investigation"]
    for span in spans:
        node = span
        while node.parent_id:
            node = by_id[node.parent_id]  # a KeyError means a span whose parent never arrived
        assert node.name == "investigation", f"{span.name} is not under the investigation"

    agent = {s.name for s in spans if s.service == "opspilot-agent-cli"}
    assert {
        "graph.investigate",
        "llm.chat",
        "graph.tools",
        "graph.approval_gate",
        "approval_wait",
        "graph.execute_action",
    } <= agent

    # Each tool call is seen from both sides: the agent's call and the server handling it.
    for tool in ("get_service_health", "get_recent_deploys", "rollback_deploy"):
        sides = {s.service for s in spans if s.name == f"mcp.tool/{tool}"}
        assert sides == {"opspilot-agent-cli", "opspilot-mcp"}, tool
    # The server's spans hang directly off the investigation that started it.
    root = next(s for s in spans if s.name == "investigation")
    server_spans = [s for s in spans if s.service == "opspilot-mcp"]
    assert server_spans
    assert all(s.parent_id == root.span_id for s in server_spans)


def test_nothing_is_exported_unless_tracing_is_enabled(tmp_path, collector):
    # The endpoint is set and reachable, yet with the flag off no process connects to it: this
    # is what lets tests and CI run without any trace backend.
    investigate(tmp_path, collector, tracing=False)
    time.sleep(1.0)  # longer than any batch delay that could still be pending
    assert collector.spans() == []
