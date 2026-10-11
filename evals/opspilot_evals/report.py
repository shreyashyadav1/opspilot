"""Write benchmark results as JSON (everything) and Markdown (the summary table)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def _num(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _cost(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.4f}"


def render_markdown(run: dict[str, Any]) -> str:
    meta, summary = run["run"], run["summary"]
    lines = [
        f"# OpsPilot benchmark: {meta['model']} on {meta['environment']}",
        "",
        f"- Run: `{meta['run_id']}`, commit `{meta['commit']}`, {meta['started_at']}",
        f"- Scenarios: {summary['scenarios']} (repeats per scenario: {meta['repeats']}), "
        f"errors: {summary['errors']}, approval policy: {meta['approval']}",
    ]
    if meta["environment"] == "simulated":
        lines.append(
            "- Simulated environment: these numbers check the harness and the baseline, "
            "they are not benchmark results."
        )
    if meta["model"].startswith("fake:"):
        lines.append(
            "- fake models make no model calls: tokens and cost below are genuinely zero, "
            "not an unmeasured gap."
        )
    lines += [
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Root-cause accuracy (service and category) | {_pct(summary['root_cause_accuracy'])} |",
        f"| Service accuracy | {_pct(summary['service_accuracy'])} |",
        f"| Category accuracy | {_pct(summary['category_accuracy'])} |",
        f"| Action accuracy | {_pct(summary['action_accuracy'])} |",
        f"| Tool-call precision | {_pct(summary['tool_call_precision'])} |",
        f"| Evidence recall | {_pct(summary['evidence_recall'])} |",
        f"| Mean steps (model turns) | {_num(summary['mean_steps'])} |",
        f"| Mean tool calls | {_num(summary['mean_tool_calls'])} |",
        f"| Time to diagnosis, mean / median / max (s) | "
        f"{_num(summary['mean_time_to_diagnosis_s'], 2)} / "
        f"{_num(summary['median_time_to_diagnosis_s'], 2)} / "
        f"{_num(summary['max_time_to_diagnosis_s'], 2)} |",
        f"| Mean tokens per incident (in / out) | {_num(summary['mean_input_tokens'], 0)} / "
        f"{_num(summary['mean_output_tokens'], 0)} |",
        f"| Mean cost per incident | {_cost(summary['mean_cost_usd'])} |",
        f"| Unapproved writes / policy violations | {summary['unapproved_writes']} / "
        f"{summary['policy_violations']} |",
        f"| Rollbacks executed / remediation verified | {summary['actions_executed']} / "
        f"{summary['remediations_verified']} |",
        "",
        "| Scenario | Expected | Diagnosed | Root cause | Action | Tool precision | Steps | "
        "Time (s) | Tokens | Cost |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in run["results"]:
        score, diagnosis = item["score"], item["investigation"].get("diagnosis") or {}
        diagnosed = (
            f"{diagnosis['root_cause_service']} / {diagnosis['category']}"
            if diagnosis
            else f"error: {item['error']}"
            if item.get("error")
            else "no diagnosis"
        )
        lines.append(
            f"| {item['scenario']} | {item['expected']} | {diagnosed} | "
            f"{'yes' if score['root_cause_correct'] else 'no'} | "
            f"{'yes' if score['action_correct'] else 'no'} | "
            f"{_pct(score['tool_call_precision'])} | {score['steps']} | "
            f"{_num(score['time_to_diagnosis_s'], 2)} | "
            f"{score['input_tokens'] + score['output_tokens']} | {_cost(score['cost_usd'])} |"
        )
    return "\n".join(lines) + "\n"


def write_report(run: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out_dir / "results.json", out_dir / "summary.md"
    json_path.write_text(json.dumps(run, indent=2, default=str) + "\n")
    md_path.write_text(render_markdown(run))
    return json_path, md_path
