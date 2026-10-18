"""Investigations through the API: background runs, traces, the approval gate, restarts."""

import asyncio
from dataclasses import replace
from datetime import datetime

from opspilot_agent.llm import ModelSpecError
from opspilot_agent.llm.fake import ScriptedChatModel
from opspilot_api.app import create_app
from tests.api.support import (
    TERMINAL,
    BlockingTools,
    FakeTools,
    build_app,
    script,
    serve,
    wait_for,
)

ALERT = {"alert": "Checkout error rate above SLO", "target": "storefront", "firing_minutes": 4}


async def start(client, body=None) -> str:
    response = await client.post("/investigations", json=body or ALERT)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_investigation_runs_in_the_background_and_records_a_trace(settings, tools):
    async with serve(build_app(settings, tools, "escalate")) as client:
        created = await client.post("/investigations", json=ALERT)
        assert created.status_code == 201
        body = created.json()
        assert body["status"] in {"queued", "running", "advisory"}
        assert body["alert"] == {
            "title": "Checkout error rate above SLO",
            "service": "storefront",
            "details": None,
            "firing_minutes": 4,
        }

        done = await wait_for(client, body["id"], TERMINAL)
        assert done["status"] == "advisory"
        assert (done["root_cause_service"], done["category"]) == ("orders", "error_rate")
        assert done["proposed_action"] == {
            "type": "escalate",
            "target_service": "orders",
            "executable": False,
        }
        assert done["approval_state"] == "not_required"
        assert done["usage"]["turns"] == 2
        assert done["usage"]["tool_calls"] == 1
        assert done["time_to_diagnosis_s"] is not None

        kinds = [event["kind"] for event in done["trace"]]
        assert kinds == ["alert", "model_turn", "tool_call", "model_turn", "diagnosis", "finished"]
        turn = done["trace"][1]["data"]
        assert turn["requested"] == ["get_service_health"]
        assert turn["text"] == "Checking service health first."
        call = done["trace"][2]["data"]
        assert call["tool"] == "get_service_health"
        assert call["args"] == {}
        assert call["ok"] is True
        assert call["summary"] == "orders unhealthy (HTTP 503); 1 healthy."
        assert call["output"]["services"][1]["service"] == "orders"
        datetime.fromisoformat(call["started_at"])
        assert call["latency_ms"] >= 0
        timestamps = [datetime.fromisoformat(e["at"]) for e in done["trace"]]
        assert timestamps == sorted(timestamps)

        listed = (await client.get("/investigations")).json()["investigations"]
        assert [(i["id"], i["status"]) for i in listed] == [(body["id"], "advisory")]
    assert tools.rollbacks == []


async def test_approved_rollback_is_executed_exactly_once(settings, tools):
    async with serve(build_app(settings, tools, "rollback_deploy")) as client:
        investigation_id = await start(client)
        paused = await wait_for(client, investigation_id, {"awaiting_approval"} | TERMINAL)
        assert paused["status"] == "awaiting_approval"
        assert paused["approval_state"] == "pending"
        assert paused["proposed_action"]["executable"] is True
        assert paused["approval_request"]["tool"] == "rollback_deploy"
        assert paused["approval_request"]["action"]["target_service"] == "orders"
        assert paused["trace"][-1]["kind"] == "approval_requested"
        assert tools.rollbacks == []

        decided = await client.post(
            f"/investigations/{investigation_id}/decision",
            json={"decision": "approve", "reviewer": "alice", "comment": "matches the deploy"},
        )
        assert decided.status_code == 200
        assert decided.json()["status"] in {"executing", "executed"}

        done = await wait_for(client, investigation_id, TERMINAL)
        assert done["status"] == "executed"
        assert done["approval"]["approved"] is True
        assert done["approval"]["reviewer"] == "alice"
        assert done["approval_state"] == "approved"
        assert done["action_result"]["ok"] is True
        assert done["action_result"]["args"]["service"] == "orders"
        action = next(e for e in done["trace"] if e["kind"] == "action")
        assert action["data"]["summary"] == "orders rolled back from 1.8.4 to 1.8.3."
        decision = next(e for e in done["trace"] if e["kind"] == "decision")
        assert decision["data"] == {
            "decision": "approve",
            "reviewer": "alice",
            "comment": "matches the deploy",
        }

        again = await client.post(
            f"/investigations/{investigation_id}/decision", json={"decision": "approve"}
        )
        assert again.status_code == 409
    assert tools.rollbacks == [
        {"service": "orders", "reason": "Revert the deploy that introduced the failures."}
    ]


async def test_rejected_action_never_executes(settings, tools):
    async with serve(build_app(settings, tools, "rollback_deploy")) as client:
        investigation_id = await start(client)
        await wait_for(client, investigation_id, {"awaiting_approval"})
        sessions = tools.sessions

        rejected = await client.post(
            f"/investigations/{investigation_id}/decision",
            json={"decision": "reject", "reviewer": "bob", "comment": "deploy looks unrelated"},
        )
        assert rejected.status_code == 200
        body = rejected.json()
        assert body["status"] == "rejected"
        assert body["approval_state"] == "rejected"
        assert body["action_result"] is None
        assert "action" not in [e["kind"] for e in body["trace"]]

        # The rejection was applied without opening a tool-server session at all.
        assert tools.sessions == sessions
        late = await client.post(
            f"/investigations/{investigation_id}/decision", json={"decision": "approve"}
        )
        assert late.status_code == 409
        await asyncio.sleep(0.1)
        assert (await client.get(f"/investigations/{investigation_id}")).json()[
            "status"
        ] == "rejected"
    assert tools.rollbacks == []


async def test_concurrent_decisions_have_exactly_one_winner(settings, tools):
    async with serve(build_app(settings, tools, "rollback_deploy")) as client:
        investigation_id = await start(client)
        await wait_for(client, investigation_id, {"awaiting_approval"})
        url = f"/investigations/{investigation_id}/decision"
        responses = await asyncio.gather(
            client.post(url, json={"decision": "reject"}),
            client.post(url, json={"decision": "approve"}),
        )
        assert sorted(r.status_code for r in responses) == [200, 409]
        done = await wait_for(client, investigation_id, TERMINAL)
    winner = next(r for r in responses if r.status_code == 200).json()["approval"]
    assert done["status"] == ("executed" if winner["approved"] else "rejected")
    assert len(tools.rollbacks) == (1 if winner["approved"] else 0)


async def test_decisions_are_validated(settings, tools):
    async with serve(build_app(settings, tools, "escalate")) as client:
        missing = await client.post(
            "/investigations/inv-9999/decision", json={"decision": "reject"}
        )
        assert missing.status_code == 404

        investigation_id = await start(client)
        url = f"/investigations/{investigation_id}/decision"
        for body in ({"decision": "yes"}, {"approved": True}, {}):
            assert (await client.post(url, json=body)).status_code == 422
        await wait_for(client, investigation_id, TERMINAL)
        advisory = await client.post(url, json={"decision": "approve"})
        assert advisory.status_code == 409
        assert "not waiting for a decision" in advisory.json()["detail"]
    assert tools.rollbacks == []


async def test_pending_approval_survives_a_restart(settings, tools):
    async with serve(build_app(settings, tools, "rollback_deploy")) as client:
        investigation_id = await start(client)
        paused = await wait_for(client, investigation_id, {"awaiting_approval"})

    after_restart = FakeTools()
    async with serve(build_app(settings, after_restart, "rollback_deploy")) as client:
        restored = (await client.get(f"/investigations/{investigation_id}")).json()
        assert restored["status"] == "awaiting_approval"
        assert restored["approval_request"] == paused["approval_request"]
        assert restored["trace"] == paused["trace"]

        decided = await client.post(
            f"/investigations/{investigation_id}/decision", json={"decision": "approve"}
        )
        assert decided.status_code == 200
        done = await wait_for(client, investigation_id, TERMINAL)
        assert done["status"] == "executed"
    assert tools.rollbacks == []
    assert len(after_restart.rollbacks) == 1


async def test_rejection_after_a_restart_does_not_execute(settings, tools):
    async with serve(build_app(settings, tools, "rollback_deploy")) as client:
        investigation_id = await start(client)
        await wait_for(client, investigation_id, {"awaiting_approval"})

    after_restart = FakeTools()
    async with serve(build_app(settings, after_restart, "rollback_deploy")) as client:
        rejected = await client.post(
            f"/investigations/{investigation_id}/decision", json={"decision": "reject"}
        )
        assert rejected.json()["status"] == "rejected"
    assert after_restart.sessions == 0
    assert tools.rollbacks == after_restart.rollbacks == []


class BlockingModel(ScriptedChatModel):
    """Never answers, so the run is still in flight when the API shuts down."""

    async def _agenerate(self, *args, **kwargs):
        await asyncio.Event().wait()


async def test_run_cut_off_by_a_restart_is_marked_failed_when_resuming_is_off(settings, tools):
    settings = replace(settings, max_resumes=0)
    app = create_app(
        settings,
        model_factory=lambda spec: BlockingModel(responses=[]),
        toolset_factory=tools.session,
    )
    async with serve(app) as client:
        investigation_id = await start(client)
        await wait_for(client, investigation_id, {"running"})

    async with serve(build_app(settings, FakeTools(), "escalate")) as client:
        body = (await client.get(f"/investigations/{investigation_id}")).json()
    assert body["status"] == "failed"
    assert body["error"] == "The API restarted before this investigation finished."
    assert body["trace"][-1]["kind"] == "error"


async def wait_for_event(client, investigation_id, kind):
    """Poll until the investigation's trace has an event of `kind` (at most 5 seconds)."""
    async with asyncio.timeout(5):
        while True:
            body = (await client.get(f"/investigations/{investigation_id}")).json()
            if any(event["kind"] == kind for event in body["trace"]):
                return
            await asyncio.sleep(0.02)


def blocking_app(settings, tools):
    return create_app(
        settings,
        model_factory=lambda spec: BlockingModel(responses=[]),
        toolset_factory=tools.session,
    )


async def test_run_cut_off_in_its_first_step_starts_again_after_a_restart(settings, tools):
    async with serve(blocking_app(settings, tools)) as client:
        investigation_id = await start(client)
        await wait_for(client, investigation_id, {"running"})

    after_restart = FakeTools()
    async with serve(build_app(settings, after_restart, "escalate")) as client:
        body = await wait_for(client, investigation_id, TERMINAL)
    assert body["status"] == "advisory"
    assert body["error"] is None
    kinds = [event["kind"] for event in body["trace"]]
    assert kinds == [
        "alert",
        "note",
        "model_turn",
        "tool_call",
        "model_turn",
        "diagnosis",
        "finished",
    ]
    assert "Started again from the alert" in body["trace"][1]["data"]["message"]
    assert after_restart.calls == [("get_service_health", {"service": None})]


async def test_resume_repeats_only_the_interrupted_step(settings):
    first = create_app(
        settings,
        model_factory=lambda spec: ScriptedChatModel(responses=script("escalate")),
        toolset_factory=BlockingTools().session,
    )
    async with serve(first) as client:
        investigation_id = await start(client)
        await wait_for(client, investigation_id, {"running"})
        await wait_for_event(client, investigation_id, "model_turn")

    # After the restart the model only has the second answer: the first turn is not redone.
    after_restart = FakeTools()
    second = create_app(
        settings,
        model_factory=lambda spec: ScriptedChatModel(responses=script("escalate")[1:]),
        toolset_factory=after_restart.session,
    )
    async with serve(second) as client:
        body = await wait_for(client, investigation_id, TERMINAL)
    assert body["status"] == "advisory"
    assert body["usage"]["turns"] == 2
    assert [e["kind"] for e in body["trace"]].count("model_turn") == 2
    notes = [e["data"]["message"] for e in body["trace"] if e["kind"] == "note"]
    assert notes == ["The API restarted mid-run. Resumed from the last completed step."]
    assert after_restart.calls == [("get_service_health", {"service": None})]


async def test_a_run_is_resumed_at_most_max_resumes_times(settings, tools):
    async with serve(blocking_app(settings, tools)) as client:
        investigation_id = await start(client)
        await wait_for(client, investigation_id, {"running"})
    async with serve(blocking_app(settings, tools)) as client:
        await wait_for(client, investigation_id, {"running"})

    async with serve(build_app(settings, FakeTools(), "escalate")) as client:
        body = (await client.get(f"/investigations/{investigation_id}")).json()
    assert body["status"] == "failed"
    assert "already resumed 1 time(s)" in body["error"]


async def test_queued_run_is_started_after_a_restart(settings, tools):
    settings = replace(settings, max_concurrent=1)
    async with serve(blocking_app(settings, tools)) as client:
        running = await start(client)
        queued = await start(client)
        await wait_for(client, running, {"running"})
        assert (await client.get(f"/investigations/{queued}")).json()["status"] == "queued"

    async with serve(build_app(settings, FakeTools(), "escalate")) as client:
        first = await wait_for(client, running, TERMINAL)
        second = await wait_for(client, queued, TERMINAL)
    assert first["status"] == second["status"] == "advisory"
    assert "Started it now" in second["trace"][1]["data"]["message"]


async def test_run_whose_model_is_gone_after_a_restart_fails_with_the_reason(settings, tools):
    async with serve(blocking_app(settings, tools)) as client:
        investigation_id = await start(client)
        await wait_for(client, investigation_id, {"running"})

    def no_model(spec):
        raise ModelSpecError("GROQ_API_KEY is not set")

    app = create_app(settings, model_factory=no_model, toolset_factory=FakeTools().session)
    async with serve(app) as client:
        body = (await client.get(f"/investigations/{investigation_id}")).json()
    assert body["status"] == "failed"
    assert body["error"].endswith("It could not be resumed: GROQ_API_KEY is not set")


async def test_approved_action_cut_off_by_a_restart_is_not_retried(settings):
    class StuckRollback(FakeTools):
        def _toolset(self):
            toolset = super()._toolset()

            async def stuck(**kwargs):
                self.calls.append(("rollback_deploy", kwargs))
                self.entered.set()
                await asyncio.Event().wait()

            toolset.write["rollback_deploy"].coroutine = stuck
            return toolset

    stuck = StuckRollback()
    stuck.entered = asyncio.Event()
    async with serve(build_app(settings, stuck, "rollback_deploy")) as client:
        investigation_id = await start(client)
        await wait_for(client, investigation_id, {"awaiting_approval"})
        await client.post(
            f"/investigations/{investigation_id}/decision", json={"decision": "approve"}
        )
        await asyncio.wait_for(stuck.entered.wait(), 5)

    after_restart = FakeTools()
    async with serve(build_app(settings, after_restart, "rollback_deploy")) as client:
        body = (await client.get(f"/investigations/{investigation_id}")).json()
    assert body["status"] == "failed"
    assert "Check the deploy history" in body["error"]
    assert after_restart.sessions == 0


async def test_failed_tool_session_keeps_the_approval_request_open(settings, tools):
    class BrokenOnApproval(FakeTools):
        def session(self):
            if self.sessions >= 1:
                raise ConnectionError("tool server did not start")
            return super().session()

    broken = BrokenOnApproval()
    async with serve(build_app(settings, broken, "rollback_deploy")) as client:
        investigation_id = await start(client)
        await wait_for(client, investigation_id, {"awaiting_approval"})
        await client.post(
            f"/investigations/{investigation_id}/decision", json={"decision": "approve"}
        )
        await asyncio.sleep(0.2)
        body = await wait_for(client, investigation_id, {"awaiting_approval"} | TERMINAL)
    assert body["status"] == "awaiting_approval"
    assert body["approval"] is None
    assert "nothing was executed" in body["trace"][-1]["data"]["message"]
    assert broken.rollbacks == []


async def test_models_are_limited_to_the_configured_ones(settings, tools):
    async with serve(build_app(settings, tools, "escalate")) as client:
        response = await client.post(
            "/investigations", json={**ALERT, "model": "openai:gpt-4o-mini"}
        )
        assert response.status_code == 422
        assert "fake:playbook" in response.json()["detail"]
        invalid = await client.post("/investigations", json={"alert": "x"})
        assert invalid.status_code == 422


async def test_sse_streams_snapshots_until_the_investigation_ends(settings, tools):
    async with serve(build_app(settings, tools, "rollback_deploy")) as client:
        investigation_id = await start(client)
        await wait_for(client, investigation_id, {"awaiting_approval"})

        async def approve_soon():
            await asyncio.sleep(0.2)
            await client.post(
                f"/investigations/{investigation_id}/decision", json={"decision": "approve"}
            )

        stream, _ = await asyncio.gather(
            client.get(f"/investigations/{investigation_id}/events"), approve_soon()
        )
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        events = [block for block in stream.text.split("\n\n") if block.startswith("event:")]
        names = [block.splitlines()[0].removeprefix("event: ") for block in events]
        assert names[0] == "snapshot"
        assert names[-1] == "end"
        assert '"status":"awaiting_approval"' in events[0]
        assert '"status":"executed"' in events[-2]

        missing = await client.get("/investigations/inv-9999/events")
        assert missing.status_code == 404


async def test_concurrent_investigations_are_all_recorded(settings, tools):
    async with serve(build_app(settings, tools, "escalate")) as client:
        ids = [await start(client) for _ in range(6)]
        done = await asyncio.gather(*(wait_for(client, i, TERMINAL) for i in ids))
        listed = (await client.get("/investigations")).json()["investigations"]
    assert {d["status"] for d in done} == {"advisory"}
    assert [i["id"] for i in listed] == list(reversed(ids))
    assert all(len(d["trace"]) == 6 for d in done)
