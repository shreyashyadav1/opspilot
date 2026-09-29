"""Run scenarios through an environment and score every investigation."""

from __future__ import annotations

import logging
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel

from opspilot_agent.graph import AgentConfig
from opspilot_agent.mcp_client import mcp_toolset
from opspilot_agent.prompts import alert_message
from opspilot_agent.runner import ApprovalHandler, run_investigation
from opspilot_evals.environments import Environment
from opspilot_evals.scenario import Scenario
from opspilot_evals.scoring import Pricing, ScenarioScore, aggregate, score_investigation

log = logging.getLogger(__name__)


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


async def run_scenario(
    scenario: Scenario,
    environment: Environment,
    model: BaseChatModel,
    approval: ApprovalHandler,
    pricing: Pricing | None,
    config: AgentConfig,
) -> dict[str, Any]:
    prepared = await environment.prepare(scenario)
    alert = alert_message(
        scenario.alert.title,
        scenario.alert.service,
        scenario.alert.details,
        started_minutes_ago=prepared.started_minutes_ago,
    )
    error = None
    investigation: dict[str, Any] = {}
    try:
        async with mcp_toolset(prepared.connection) as tools:
            result = await run_investigation(alert, model, tools, approval, config=config)
        investigation = result.to_dict()
    except Exception as exc:  # one failing scenario must not abort the whole run
        log.exception("scenario %s failed", scenario.id)
        error = f"{type(exc).__name__}: {exc}"[:500]
    remediated = await environment.remediated(scenario, prepared, investigation)
    await environment.cleanup()
    score = score_investigation(scenario, prepared.ground_truth, investigation, pricing, remediated)
    return {
        "scenario": scenario.id,
        "expected": f"{scenario.expected.root_cause_service} / {scenario.expected.category}",
        "ground_truth": prepared.ground_truth.model_dump(),
        "error": error,
        "score": score.model_dump(),
        "investigation": investigation,
    }


async def run_benchmark(
    scenarios: list[Scenario],
    environment: Environment,
    model: BaseChatModel,
    model_spec: str,
    approval: ApprovalHandler,
    approval_name: str,
    pricing: Pricing | None,
    repeats: int = 1,
    config: AgentConfig | None = None,
) -> dict[str, Any]:
    config = config or AgentConfig()
    started = datetime.now(UTC)
    results = []
    for scenario in scenarios:
        for repeat in range(repeats):
            log.info("Running %s (%d/%d)", scenario.id, repeat + 1, repeats)
            item = await run_scenario(scenario, environment, model, approval, pricing, config)
            item["repeat"] = repeat
            results.append(item)
    scores = [ScenarioScore.model_validate(r["score"]) for r in results]
    return {
        "run": {
            "run_id": f"{started:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}",
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "environment": environment.name,
            "model": model_spec,
            "approval": approval_name,
            "repeats": repeats,
            "max_turns": config.max_turns,
            "commit": git_commit(),
        },
        "summary": aggregate(scores, errors=sum(r["error"] is not None for r in results)),
        "results": results,
    }


def default_out_dir(root: Path, run: dict[str, Any]) -> Path:
    model = run["run"]["model"].replace(":", "-").replace("/", "-")
    return root / f"{run['run']['run_id']}-{run['run']['environment']}-{model}"
