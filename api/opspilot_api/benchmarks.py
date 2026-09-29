"""Read benchmark runs written by `opspilot-eval` (one directory per run with results.json).

Only runs that exist on disk are listed; nothing is computed or filled in here. Every run is
labelled with what it measures: runs in the simulated environment check the harness, and the
playbook model is a rule-based baseline, not an LLM.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from opspilot_api.modelinfo import ModelInfo, describe_model

log = logging.getLogger(__name__)
RUN_DIR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")

ENVIRONMENTS = {
    "simulated": (
        "Simulated telemetry. Checks the harness and the baseline; these numbers are not "
        "benchmark results."
    ),
    "live": "Live demo stack with real fault injection.",
}


class RunMeta(BaseModel):
    run_id: str
    started_at: str
    finished_at: str | None = None
    environment: str
    model: str
    approval: str
    repeats: int = 1
    max_turns: int | None = None
    commit: str | None = None


class RunFile(BaseModel):
    run: RunMeta
    summary: dict[str, Any]
    results: list[dict[str, Any]]


class BenchmarkRun(BaseModel):
    id: str
    run: RunMeta
    model: ModelInfo
    environment_note: str
    reportable: bool
    summary: dict[str, Any]


class BenchmarkRunDetail(BenchmarkRun):
    results: list[dict[str, Any]]


def _load(path: Path) -> RunFile | None:
    try:
        return RunFile.model_validate(json.loads(path.read_text()))
    except (OSError, ValueError, ValidationError) as exc:
        log.warning("Skipping unreadable benchmark results %s: %s", path, type(exc).__name__)
        return None


def _describe(run_dir: str, data: RunFile) -> dict[str, Any]:
    environment = data.run.environment
    return {
        "id": run_dir,
        "run": data.run,
        "model": describe_model(data.run.model),
        "environment_note": ENVIRONMENTS.get(environment, environment),
        # Only live runs with a real model measure the agent; see docs/DESIGN.md section 5.
        "reportable": environment == "live" and describe_model(data.run.model).kind == "llm",
        "summary": data.summary,
    }


def list_runs(results_dir: Path) -> list[BenchmarkRun]:
    if not results_dir.is_dir():
        return []
    runs = []
    for path in results_dir.glob("*/results.json"):
        data = _load(path)
        if data is not None:
            runs.append(BenchmarkRun(**_describe(path.parent.name, data)))
    return sorted(runs, key=lambda r: r.run.started_at, reverse=True)


def load_run(results_dir: Path, run_dir: str) -> BenchmarkRunDetail | None:
    if not RUN_DIR.match(run_dir):
        return None
    path = results_dir / run_dir / "results.json"
    if not path.is_file():
        return None
    data = _load(path)
    if data is None:
        return None
    return BenchmarkRunDetail(**_describe(run_dir, data), results=data.results)
