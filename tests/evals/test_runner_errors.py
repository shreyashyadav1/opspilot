"""Scenario failures are recorded by cause, and failures before the first step are re-run once."""

from pathlib import Path
from typing import Any

from pydantic import PrivateAttr

from opspilot_agent.graph import AgentConfig
from opspilot_agent.llm.fake import PlaybookChatModel
from opspilot_agent.runner import approve_all
from opspilot_evals.environments import SimulatedEnvironment
from opspilot_evals.report import render_markdown
from opspilot_evals.runner import describe_error, run_benchmark, run_scenario
from opspilot_evals.scenario import load_scenarios
from opspilot_evals.scoring import Pricing

SCENARIOS = Path(__file__).resolve().parents[2] / "evals" / "scenarios"
SCENARIO_ID = "orders-bad-config-deploy"


class RateLimited(Exception):
    pass


class FlakyPlaybook(PlaybookChatModel):
    """The playbook model, except the model calls numbered in `fail_calls` raise a rate limit."""

    fail_calls: frozenset[int] = frozenset()
    _calls: int = PrivateAttr(default=0)

    def _generate(self, messages: list[Any], *args: Any, **kwargs: Any) -> Any:
        self._calls += 1
        if self._calls in self.fail_calls:
            raise RateLimited("429 rate_limit_exceeded")
        return super()._generate(messages, *args, **kwargs)


async def run_one(tmp_path: Path, model: PlaybookChatModel, **kwargs: Any) -> dict[str, Any]:
    (scenario,) = load_scenarios(SCENARIOS, [SCENARIO_ID])
    return await run_scenario(
        scenario,
        SimulatedEnvironment(tmp_path),
        model,
        approve_all,
        Pricing(input=0.0, output=0.0),
        AgentConfig(),
        retry_delay_s=0,
        **kwargs,
    )


def test_describe_error_names_the_wrapped_causes():
    group = ExceptionGroup(
        "unhandled errors in a TaskGroup",
        [RateLimited("429"), ExceptionGroup("inner", [TimeoutError("read timed out")])],
    )
    assert describe_error(group) == "RateLimited: 429; TimeoutError: read timed out"
    assert describe_error(ValueError("bad")) == "ValueError: bad"
    assert len(describe_error(ValueError("x" * 1000))) == 500


async def test_failure_before_the_first_step_is_retried_and_recorded(tmp_path):
    item = await run_one(tmp_path, FlakyPlaybook(fail_calls=frozenset({1})))
    assert item["error"] is None
    assert item["attempts"] == 2
    assert len(item["retried_errors"]) == 1
    assert "RateLimited: 429 rate_limit_exceeded" in item["retried_errors"][0]
    assert "TaskGroup" not in item["retried_errors"][0]
    assert item["score"]["root_cause_correct"] is True


async def test_persistent_failure_reports_the_cause_after_the_retries(tmp_path):
    item = await run_one(tmp_path, FlakyPlaybook(fail_calls=frozenset({1, 2, 3})))
    assert item["attempts"] == 2
    assert "RateLimited: 429 rate_limit_exceeded" in item["error"]
    assert "TaskGroup" not in item["error"]
    assert item["investigation"] == {}


async def test_retries_can_be_turned_off(tmp_path):
    item = await run_one(tmp_path, FlakyPlaybook(fail_calls=frozenset({1})), start_retries=0)
    assert item["attempts"] == 1
    assert item["retried_errors"] == []
    assert "RateLimited" in item["error"]


async def test_failure_after_the_agent_started_is_not_retried(tmp_path):
    # The first turn already ran tool calls, so a second attempt would not start from scratch.
    item = await run_one(tmp_path, FlakyPlaybook(fail_calls=frozenset({2})))
    assert item["attempts"] == 1
    assert item["retried_errors"] == []
    assert "RateLimited" in item["error"]


async def test_benchmark_summary_and_report_count_retried_scenarios(tmp_path):
    run = await run_benchmark(
        load_scenarios(SCENARIOS, [SCENARIO_ID]),
        SimulatedEnvironment(tmp_path),
        FlakyPlaybook(fail_calls=frozenset({1})),
        "fake:playbook",
        approve_all,
        "approve",
        Pricing(input=0.0, output=0.0),
        retry_delay_s=0,
    )
    assert run["summary"]["errors"] == 0
    assert run["summary"]["retried"] == 1
    assert run["run"]["start_retries"] == 1
    assert "Re-run after failing before the first step: 1" in render_markdown(run)
