"""End to end: scenarios -> MCP server subprocess (simulated) -> agent -> scorer -> reports."""

from pathlib import Path

from opspilot_agent.llm.fake import PlaybookChatModel
from opspilot_agent.runner import approve_all
from opspilot_evals.environments import SimulatedEnvironment
from opspilot_evals.report import write_report
from opspilot_evals.runner import run_benchmark
from opspilot_evals.scenario import load_scenarios
from opspilot_evals.scoring import Pricing

SCENARIOS = Path(__file__).resolve().parents[2] / "evals" / "scenarios"
IDS = ["orders-bad-config-deploy", "orders-error-spike-unrelated-deploy", "payments-outage"]


async def run_once(tmp_path: Path) -> dict:
    return await run_benchmark(
        load_scenarios(SCENARIOS, IDS),
        SimulatedEnvironment(tmp_path),
        PlaybookChatModel(),
        "fake:playbook",
        approve_all,
        "approve",
        Pricing(input=0.0, output=0.0),
    )


async def test_simulated_benchmark_end_to_end(tmp_path):
    run = await run_once(tmp_path / "a")
    summary = run["summary"]
    assert summary["scenarios"] == 3
    assert summary["errors"] == 0
    assert summary["unapproved_writes"] == 0
    assert summary["actions_executed"] == summary["remediations_verified"] == 1
    by_id = {r["scenario"]: r for r in run["results"]}
    rollback = by_id["orders-bad-config-deploy"]["investigation"]
    assert rollback["approval_requests"][0]["tool"] == "rollback_deploy"
    assert rollback["action_result"]["ok"] is True
    assert by_id["orders-error-spike-unrelated-deploy"]["investigation"]["action_result"] is None

    json_path, md_path = write_report(run, tmp_path / "report")
    assert json_path.exists()
    markdown = md_path.read_text()
    assert "not benchmark results" in markdown
    assert "| orders-bad-config-deploy |" in markdown


async def test_simulated_benchmark_is_deterministic(tmp_path):
    first, second = await run_once(tmp_path / "a"), await run_once(tmp_path / "b")
    strip = ("time_to_diagnosis_s",)
    scores = [
        [{k: v for k, v in r["score"].items() if k not in strip} for r in run["results"]]
        for run in (first, second)
    ]
    assert scores[0] == scores[1]
