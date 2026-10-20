import pytest
from pydantic import ValidationError

from opspilot_agent.llm import ModelSpecError, build_model
from opspilot_agent.llm.fake import PlaybookChatModel
from opspilot_agent.schemas import Diagnosis

VALID = {
    "root_cause_service": "payments",
    "category": "latency",
    "summary": "payments p95 latency rose from 22 ms to 1.3 s.",
    "evidence": [{"source": "metrics", "service": "payments", "detail": "p95 1310 ms vs 22 ms"}],
    "confidence": 0.7,
    "proposed_action": {
        "type": "escalate",
        "target_service": "payments",
        "rationale": "Page the payments on-call engineer.",
    },
}


def test_valid_diagnosis_has_no_executable_tool_for_escalation():
    assert Diagnosis.model_validate(VALID).executable_tool is None


def test_rollback_maps_to_the_mcp_write_tool():
    body = {**VALID, "proposed_action": {**VALID["proposed_action"], "type": "rollback_deploy"}}
    assert Diagnosis.model_validate(body).executable_tool == "rollback_deploy"


def test_nested_json_strings_are_accepted():
    import json

    body = {**VALID, "evidence": json.dumps(VALID["evidence"])}
    assert Diagnosis.model_validate(body).evidence[0].service == "payments"


@pytest.mark.parametrize(
    "change",
    [
        {"root_cause_service": "billing"},
        {"category": "network"},
        {"confidence": 1.5},
        {"evidence": []},
        {"unexpected": True},
    ],
)
def test_invalid_diagnoses_are_rejected(change):
    with pytest.raises(ValidationError):
        Diagnosis.model_validate({**VALID, **change})


def test_fake_model_needs_no_key():
    assert isinstance(build_model("fake:playbook"), PlaybookChatModel)


def test_missing_api_key_is_a_clear_error(monkeypatch):
    monkeypatch.setattr("opspilot_agent.llm.factory.load_dotenv", lambda: None)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(ModelSpecError, match="GROQ_API_KEY is not set"):
        build_model("groq:openai/gpt-oss-120b")


def test_groq_model_is_openai_compatible(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    model = build_model("groq:openai/gpt-oss-120b")
    assert model.model_name == "openai/gpt-oss-120b"
    assert "groq.com" in str(model.openai_api_base)
    assert "test-key" not in repr(model)


@pytest.mark.parametrize("spec", ["llama", "fake:gpt", "acme:model"])
def test_bad_model_specs(spec):
    with pytest.raises(ModelSpecError):
        build_model(spec)


def test_playbook_evidence_names_a_missing_baseline():
    from opspilot_agent.llm.fake import _Findings, _metric_evidence

    findings = _Findings([])
    findings.metrics[("orders", "error_rate")] = {"latest": 0.8, "baseline": None, "trend": "new"}
    [evidence] = _metric_evidence(findings, "orders")
    assert evidence["detail"] == "error_rate 0.8 with no baseline in the window yet (new)"


def test_switchyard_defaults_to_a_local_gateway(monkeypatch):
    monkeypatch.setattr("opspilot_agent.llm.factory.load_dotenv", lambda: None)
    monkeypatch.delenv("SWITCHYARD_URL", raising=False)
    monkeypatch.setenv("SWITCHYARD_API_KEY", "sy-test-not-real")
    model = build_model("switchyard:gpt-oss-120b")
    assert model.model_name == "gpt-oss-120b"
    assert str(model.openai_api_base) == "http://localhost:8080/v1"


def test_switchyard_url_and_missing_key(monkeypatch):
    monkeypatch.setattr("opspilot_agent.llm.factory.load_dotenv", lambda: None)
    monkeypatch.setenv("SWITCHYARD_URL", "http://gateway.test:9000/v1")
    monkeypatch.setenv("SWITCHYARD_API_KEY", "sy-test-not-real")
    assert str(build_model("switchyard:gpt-oss-120b").openai_api_base) == (
        "http://gateway.test:9000/v1"
    )
    monkeypatch.delenv("SWITCHYARD_API_KEY")
    with pytest.raises(ModelSpecError, match="SWITCHYARD_API_KEY is not set"):
        build_model("switchyard:gpt-oss-120b")


def test_custom_provider_needs_a_base_url(monkeypatch):
    monkeypatch.setattr("opspilot_agent.llm.factory.load_dotenv", lambda: None)
    monkeypatch.delenv("OPSPILOT_LLM_BASE_URL", raising=False)
    with pytest.raises(ModelSpecError, match="set OPSPILOT_LLM_BASE_URL"):
        build_model("custom:some-model")


def test_hosted_providers_get_no_trace_context(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    assert build_model("groq:openai/gpt-oss-120b").http_async_client is None


async def test_gateway_requests_carry_the_current_trace(monkeypatch):
    """A real request through the OpenAI client reaches the gateway with the caller's span as
    its `traceparent`, so the gateway's spans land in the investigation's trace."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from opentelemetry.sdk.trace import TracerProvider

    seen: list[str | None] = []

    class Gateway(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            seen.append(self.headers.get("traceparent"))
            body = json.dumps(
                {
                    "id": "chatcmpl-1",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "gpt-oss-120b",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr("opspilot_agent.llm.factory.load_dotenv", lambda: None)
        monkeypatch.setenv("SWITCHYARD_URL", f"http://127.0.0.1:{server.server_port}/v1")
        monkeypatch.setenv("SWITCHYARD_API_KEY", "sy-test-not-real")
        model = build_model("switchyard:gpt-oss-120b")
        tracer = TracerProvider().get_tracer("test")
        with tracer.start_as_current_span("llm.chat") as span:
            reply = await model.ainvoke("hi")
            trace_id = format(span.get_span_context().trace_id, "032x")
            span_id = format(span.get_span_context().span_id, "016x")
    finally:
        server.shutdown()
        server.server_close()

    assert reply.content == "ok"
    assert len(seen) == 1
    assert seen[0].startswith(f"00-{trace_id}-{span_id}-")
