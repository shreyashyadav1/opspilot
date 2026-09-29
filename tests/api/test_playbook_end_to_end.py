"""The default setup end to end: fake:playbook, the real MCP server (simulated telemetry)."""

from dataclasses import replace

from opspilot_api.app import create_app
from opspilot_mcp.backends.simulated import FaultSpec, SimulationSpec
from tests.api.support import TERMINAL, serve, wait_for


async def test_playbook_diagnoses_a_bad_deploy_and_rolls_it_back(settings, tmp_path):
    spec = tmp_path / "simulation.json"
    spec.write_text(
        SimulationSpec(fault=FaultSpec(type="bad_config_deploy", target="orders")).model_dump_json()
    )
    app = create_app(replace(settings, backend="simulated", simulation=spec))
    async with serve(app) as client:
        config = (await client.get("/config")).json()
        assert config["model"]["kind"] == "baseline"
        assert config["model_error"] is None

        created = await client.post(
            "/investigations",
            json={"alert": "Checkout error rate above SLO", "service": "storefront"},
        )
        investigation_id = created.json()["id"]
        paused = await wait_for(client, investigation_id, {"awaiting_approval"} | TERMINAL)
        assert paused["status"] == "awaiting_approval", paused.get("error")
        assert paused["model"]["spec"] == "fake:playbook"
        assert (paused["root_cause_service"], paused["category"]) == ("orders", "bad_deploy")
        assert paused["proposed_action"]["type"] == "rollback_deploy"

        calls = [e["data"] for e in paused["trace"] if e["kind"] == "tool_call"]
        assert [c["tool"] for c in calls[:2]] == ["get_service_health", "get_recent_deploys"]
        assert all(c["ok"] and c["summary"] for c in calls)
        deploys = next(c for c in calls if c["tool"] == "get_recent_deploys")
        assert "payments.base-url" in deploys["summary"]

        await client.post(
            f"/investigations/{investigation_id}/decision", json={"decision": "approve"}
        )
        done = await wait_for(client, investigation_id, TERMINAL)
    assert done["status"] == "executed", done.get("error")
    assert done["action_result"]["output"]["status"] == "rolled_back"
