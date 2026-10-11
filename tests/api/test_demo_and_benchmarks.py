"""Demo fault injection (proxied to the chaos API) and benchmark results."""

import json
from dataclasses import replace

import httpx
import pytest

from tests.api.support import FakeTools, build_app, serve

CATALOG = {
    "fault_types": [
        {
            "type": "latency_spike",
            "category": "latency",
            "description": "Adds a delay to the target's business requests.",
            "targets": ["orders", "payments", "storefront"],
            "params": {"delay_ms": {"type": "integer", "minimum": 50, "maximum": 10000}},
        }
    ]
}


class FakeControlPlane:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, object]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body))
        match request.method, request.url.path:
            case "GET", "/chaos/catalog":
                return httpx.Response(200, json=CATALOG)
            case "GET", "/chaos/faults":
                return httpx.Response(200, json={"faults": []})
            case "POST", "/chaos/faults" if body["target"] == "storefront":
                return httpx.Response(
                    409, json={"detail": "storefront already has an active fault"}
                )
            case "POST", "/chaos/faults":
                return httpx.Response(201, json={"id": "flt-0001", **body, "active": True})
            case "DELETE", "/chaos/faults/flt-0001":
                return httpx.Response(200, json={"id": "flt-0001", "active": False})
            case "POST", "/chaos/reset":
                return httpx.Response(200, json={"status": "reset", "resolved_faults": 1})
        return httpx.Response(404, json={"detail": "not found"})


@pytest.fixture
def plane() -> FakeControlPlane:
    return FakeControlPlane()


async def test_demo_endpoints_are_disabled_without_a_chaos_url(settings):
    async with serve(build_app(settings, FakeTools(), "escalate")) as client:
        assert (await client.get("/config")).json()["demo_enabled"] is False
        response = await client.get("/demo/catalog")
    assert response.status_code == 404
    assert "OPSPILOT_CHAOS_URL" in response.json()["detail"]


async def test_demo_endpoints_proxy_the_chaos_api(settings, plane):
    settings = replace(settings, chaos_url="http://control-plane:8080")
    app = build_app(settings, FakeTools(), "escalate", chaos_transport=httpx.MockTransport(plane))
    async with serve(app) as client:
        assert (await client.get("/config")).json()["demo_enabled"] is True
        assert (await client.get("/demo/catalog")).json() == CATALOG
        assert (await client.get("/demo/faults")).json() == {"faults": []}

        injected = await client.post(
            "/demo/faults",
            json={"type": "latency_spike", "target": "payments", "params": {"delay_ms": 900}},
        )
        assert injected.status_code == 201
        assert injected.json()["id"] == "flt-0001"

        conflict = await client.post(
            "/demo/faults", json={"type": "error_spike", "target": "storefront"}
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == "control plane: storefront already has an active fault"

        invalid = await client.post("/demo/faults", json={"type": "latency_spike", "target": "db"})
        assert invalid.status_code == 422

        assert (await client.delete("/demo/faults/flt-0001")).json()["active"] is False
        assert (await client.post("/demo/reset")).json()["resolved_faults"] == 1
    assert (
        "POST",
        "/chaos/faults",
        {"type": "latency_spike", "target": "payments", "params": {"delay_ms": 900}},
    ) in plane.requests


async def test_unreachable_control_plane_is_a_bad_gateway(settings):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    settings = replace(settings, chaos_url="http://control-plane:8080")
    app = build_app(settings, FakeTools(), "escalate", chaos_transport=httpx.MockTransport(refuse))
    async with serve(app) as client:
        response = await client.get("/demo/faults")
    assert response.status_code == 502
    assert "control plane unreachable" in response.json()["detail"]


def write_run(root, name: str, environment: str, model: str, started_at: str) -> None:
    run = {
        "run": {
            "run_id": name[:23],
            "started_at": started_at,
            "finished_at": started_at,
            "environment": environment,
            "model": model,
            "approval": "approve",
            "repeats": 1,
            "max_turns": 12,
            "commit": "abc1234",
        },
        "summary": {"scenarios": 1, "root_cause_accuracy": 1.0, "unapproved_writes": 0},
        "results": [
            {
                "scenario": "payments-outage",
                "expected": "payments / dependency_outage",
                "score": {"root_cause_correct": True, "action_correct": True},
                "investigation": {"diagnosis": None, "tool_calls": []},
            }
        ],
    }
    (root / name).mkdir(parents=True)
    (root / name / "results.json").write_text(json.dumps(run))


async def test_benchmarks_list_only_runs_that_exist(settings):
    async with serve(build_app(settings, FakeTools(), "escalate")) as client:
        assert (await client.get("/benchmarks")).json() == {"runs": []}

        results = settings.results_dir
        write_run(
            results, "run-a-simulated-fake-playbook", "simulated", "fake:playbook", "2026-09-01"
        )
        write_run(results, "run-b-live-groq", "live", "groq:openai/gpt-oss-120b", "2026-09-02")
        (results / "broken").mkdir()
        (results / "broken" / "results.json").write_text("{not json")
        (results / "notes.txt").write_text("not a run")

        runs = (await client.get("/benchmarks")).json()["runs"]
        assert [r["id"] for r in runs] == ["run-b-live-groq", "run-a-simulated-fake-playbook"]
        live, simulated = runs
        assert live["model"]["kind"] == "llm"
        assert live["reportable"] is True
        assert simulated["model"]["kind"] == "baseline"
        assert simulated["model"]["label"] == "Rule-based playbook"
        assert "not an LLM" in simulated["model"]["description"]
        assert simulated["reportable"] is False
        assert "not benchmark results" in simulated["environment_note"]

        detail = (await client.get("/benchmarks/run-a-simulated-fake-playbook")).json()
        assert detail["results"][0]["scenario"] == "payments-outage"
        assert (await client.get("/benchmarks/broken")).status_code == 404
        assert (await client.get("/benchmarks/missing")).status_code == 404
        assert (await client.get("/benchmarks/..%2F..%2Fetc")).status_code == 404
