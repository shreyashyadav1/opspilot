"""Command line entry point.

opspilot investigate "Checkout error rate above SLO" --service storefront
opspilot investigate "..." --model fake:playbook --approve no
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

from opspilot_agent.graph import AgentConfig
from opspilot_agent.llm import DEFAULT_MODEL, ModelSpecError, build_model
from opspilot_agent.mcp_client import mcp_toolset, stdio_connection
from opspilot_agent.prompts import alert_message
from opspilot_agent.runner import (
    ApprovalHandler,
    InvestigationResult,
    approve_all,
    reject_all,
    run_investigation,
)
from opspilot_agent.schemas import ApprovalDecision

console = Console(stderr=True)


def _print_event(node: str, values: dict[str, Any]) -> None:
    if node == "tools":
        for record in values.get("tool_calls", []):
            args = ", ".join(f"{k}={v!r}" for k, v in record["args"].items())
            status = "[green]ok[/]" if record["ok"] else f"[red]{record.get('error')}[/]"
            console.print(f"  [dim]turn {record['turn']}[/] {record['tool']}({args}) {status}")
    elif node == "validate" and not values.get("diagnosis"):
        console.print("  [yellow]diagnosis rejected by schema validation; retrying[/]")


async def ask_operator(request: dict[str, Any]) -> ApprovalDecision:
    action = request["action"]
    console.print(
        Panel(
            f"[bold]{request['tool']}[/] on [bold]{action['target_service']}[/]\n"
            f"{action['rationale']}\n\nconfidence {request['confidence']:.2f}",
            title="Approval required",
            border_style="yellow",
        )
    )
    approved = await asyncio.to_thread(Confirm.ask, "Execute this action?", default=False)
    return ApprovalDecision(approved=approved, reviewer="cli")


def _render(result: InvestigationResult) -> None:
    diagnosis = result.diagnosis
    if diagnosis is None:
        console.print(Panel("No valid diagnosis was produced.", border_style="red"))
        return
    evidence = "\n".join(f"- [{e.source}] {e.service}: {e.detail}" for e in diagnosis.evidence)
    action = diagnosis.proposed_action
    console.print(
        Panel(
            f"[bold]{diagnosis.root_cause_service}[/] / [bold]{diagnosis.category.value}[/] "
            f"(confidence {diagnosis.confidence:.2f})\n\n{diagnosis.summary}\n\n{evidence}\n\n"
            f"Proposed: [bold]{action.type.value}[/] on {action.target_service}: "
            f"{action.rationale}",
            title="Diagnosis",
            border_style="green",
        )
    )
    console.print(
        f"outcome={result.outcome} turns={result.turns} tool_calls={len(result.tool_calls)} "
        f"tokens={result.input_tokens}+{result.output_tokens} "
        f"time_to_diagnosis={result.time_to_diagnosis_s}s"
    )


async def _investigate(args: argparse.Namespace) -> int:
    try:
        model = build_model(args.model)
    except ModelSpecError as exc:
        console.print(f"[red]{exc}[/]")
        return 2
    handlers: dict[str, ApprovalHandler] = {
        "ask": ask_operator,
        "yes": approve_all,
        "no": reject_all,
    }
    alert = alert_message(args.alert, args.service, args.details or args.alert)
    connection = stdio_connection(args.backend, args.simulation)
    async with mcp_toolset(connection) as tools:
        console.print(f"Investigating with {args.model or DEFAULT_MODEL} ({args.backend} backend)")
        result = await run_investigation(
            alert,
            model,
            tools,
            handlers[args.approve],
            config=AgentConfig(max_turns=args.max_turns),
            on_event=_print_event,
        )
    _render(result)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
    return 0 if result.diagnosis else 1


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="opspilot", description="AI on-call investigator")
    sub = parser.add_subparsers(dest="command", required=True)
    inv = sub.add_parser("investigate", help="investigate an alert")
    inv.add_argument("alert", help="alert title, e.g. 'Checkout error rate above SLO'")
    inv.add_argument("--service", default="storefront", help="service the alert fired on")
    inv.add_argument("--details", help="alert details (defaults to the title)")
    inv.add_argument("--model", default=None, help=f"provider:model (default {DEFAULT_MODEL})")
    inv.add_argument("--backend", choices=["live", "simulated"], default="live")
    inv.add_argument("--simulation", type=Path, help="SimulationSpec JSON for --backend simulated")
    inv.add_argument("--approve", choices=["ask", "yes", "no"], default="ask")
    inv.add_argument("--max-turns", type=int, default=12)
    inv.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = parser.parse_args(argv)
    sys.exit(asyncio.run(_investigate(args)))


if __name__ == "__main__":
    main()
