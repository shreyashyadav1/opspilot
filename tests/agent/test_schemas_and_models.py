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
        build_model("groq:llama-3.3-70b-versatile")


def test_groq_model_is_openai_compatible(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    model = build_model("groq:llama-3.3-70b-versatile")
    assert model.model_name == "llama-3.3-70b-versatile"
    assert "groq.com" in str(model.openai_api_base)
    assert "test-key" not in repr(model)


@pytest.mark.parametrize("spec", ["llama", "fake:gpt", "acme:model"])
def test_bad_model_specs(spec):
    with pytest.raises(ModelSpecError):
        build_model(spec)
