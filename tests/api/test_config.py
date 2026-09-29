"""What the API reports about its configuration, and how it picks the default model."""

from dataclasses import replace

from opspilot_api.app import create_app
from opspilot_api.settings import BASELINE_MODEL, default_model
from tests.api.support import FakeTools, build_app, serve


async def test_config_labels_the_playbook_as_a_baseline(settings):
    async with serve(build_app(settings, FakeTools(), "escalate")) as client:
        config = (await client.get("/config")).json()
    assert config["model"] == {
        "spec": "fake:playbook",
        "kind": "baseline",
        "label": "Rule-based playbook",
        "description": "A fixed triage runbook with simple rules over the tool results. "
        "A deterministic baseline, not an LLM.",
    }
    assert [m["spec"] for m in config["models"]] == ["fake:playbook"]
    assert config["services"] == ["storefront", "orders", "payments"]


async def test_a_model_without_its_key_is_reported_not_run(settings, monkeypatch):
    monkeypatch.setattr("opspilot_agent.llm.factory.load_dotenv", lambda: None)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    settings = replace(settings, model="groq:llama-3.3-70b-versatile")
    async with serve(create_app(settings, toolset_factory=FakeTools().session)) as client:
        config = (await client.get("/config")).json()
        assert config["model"]["kind"] == "llm"
        assert "GROQ_API_KEY is not set" in config["model_error"]
        assert [m["spec"] for m in config["models"]] == [
            "groq:llama-3.3-70b-versatile",
            BASELINE_MODEL,
        ]
        refused = await client.post("/investigations", json={"alert": "Checkout errors"})
        assert refused.status_code == 422
        baseline = await client.post(
            "/investigations", json={"alert": "Checkout errors", "model": BASELINE_MODEL}
        )
        assert baseline.status_code == 201


def test_default_model_prefers_explicit_config_then_a_groq_key(monkeypatch):
    monkeypatch.delenv("OPSPILOT_MODEL", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert default_model() == "fake:playbook"
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    assert default_model() == "groq:llama-3.3-70b-versatile"
    monkeypatch.setenv("OPSPILOT_MODEL", "openai:gpt-4o-mini")
    assert default_model() == "openai:gpt-4o-mini"
