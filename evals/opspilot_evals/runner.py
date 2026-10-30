"""Run scenarios through an environment and score every investigation."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from opentelemetry import trace

from opspilot_agent.graph import AgentConfig
from opspilot_agent.mcp_client import mcp_toolset
from opspilot_agent.prompts import alert_message
from opspilot_agent.runner import ApprovalHandler, run_investigation
from opspilot_evals.environments import Environment
from opspilot_evals.scenario import Scenario
from opspilot_evals.scoring import Pricing, ScenarioScore, aggregate, score_investigation
from opspilot_observability.tracing import subprocess_env

log = logging.getLogger(__name__)


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _leaf_exceptions(exc: BaseException) -> Iterator[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        for inner in exc.exceptions:
            yield from _leaf_exceptions(inner)
    else:
        yield exc


def describe_error(exc: BaseException) -> str:
    """Name the errors that actually failed, not the task group that wrapped them.

    The MCP stdio session runs inside an anyio task group, so a model error such as a rate limit
    surfaces as "ExceptionGroup: unhandled errors in a TaskGroup", which says nothing about the
    cause on its own.
    """
    return "; ".join(f"{type(e).__name__}: {e}" for e in _leaf_exceptions(exc))[:500]


async def run_scenario(
    scenario: Scenario,
    environment: Environment,
    model: BaseChatModel,
    approval: ApprovalHandler,
    pricing: Pricing | None,
    config: AgentConfig,
    *,
    start_retries: int = 1,
    retry_delay_s: float = 30.0,
) -> dict[str, Any]:
    prepared = await environment.prepare(scenario)
    alert = alert_message(
        scenario.alert.title,
        scenario.alert.service,
        scenario.alert.details,
        started_minutes_ago=prepared.started_minutes_ago,
    )
    error = None
    retried_errors: list[str] = []
    investigation: dict[str, Any] = {}
    tracer = trace.get_tracer("opspilot.eval")
    attempt = 0
    while True:
        attempt += 1
        # Set by the first graph step. Until then the agent has made no tool calls, so the
        # scenario's environment is untouched and the attempt can be repeated as if it never ran.
        started = False

        def mark_started(node: str, values: dict[str, Any]) -> None:
            nonlocal started
            started = True

        try:
            attributes = {"opspilot.scenario": scenario.id, "opspilot.attempt": attempt}
            with tracer.start_as_current_span("investigation", attributes=attributes):
                prepared.connection["env"].update(subprocess_env())
                async with mcp_toolset(prepared.connection) as tools:
                    result = await run_investigation(
                        alert, model, tools, approval, config=config, on_event=mark_started
                    )
            investigation = result.to_dict()
        except Exception as exc:  # one failing scenario must not abort the whole run
            log.exception("scenario %s failed (attempt %d)", scenario.id, attempt)
            error = describe_error(exc)
            if not started and len(retried_errors) < start_retries:
                # Failed before the first step: a tool server that didn't start or a model call
                # refused outright (rate limit, timeout). Recorded, then tried once more.
                retried_errors.append(error)
                error = None
                await asyncio.sleep(retry_delay_s)
                continue
        break
    remediated = await environment.remediated(scenario, prepared, investigation)
    await environment.cleanup()
    score = score_investigation(scenario, prepared.ground_truth, investigation, pricing, remediated)
    return {
        "scenario": scenario.id,
        "expected": f"{scenario.expected.root_cause_service} / {scenario.expected.category}",
        "ground_truth": prepared.ground_truth.model_dump(),
        "error": error,
        "attempts": attempt,
        "retried_errors": retried_errors,
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
    start_retries: int = 1,
    retry_delay_s: float = 30.0,
) -> dict[str, Any]:
    config = config or AgentConfig()
    started = datetime.now(UTC)
    results = []
    for scenario in scenarios:
        for repeat in range(repeats):
            log.info("Running %s (%d/%d)", scenario.id, repeat + 1, repeats)
            item = await run_scenario(
                scenario,
                environment,
                model,
                approval,
                pricing,
                config,
                start_retries=start_retries,
                retry_delay_s=retry_delay_s,
            )
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
            "start_retries": start_retries,
            "commit": git_commit(),
        },
        "summary": {
            **aggregate(scores, errors=sum(r["error"] is not None for r in results)),
            "retried": sum(r["attempts"] > 1 for r in results),
        },
        "results": results,
    }


def default_out_dir(root: Path, run: dict[str, Any]) -> Path:
    model = run["run"]["model"].replace(":", "-").replace("/", "-")
    return root / f"{run['run']['run_id']}-{run['run']['environment']}-{model}"
