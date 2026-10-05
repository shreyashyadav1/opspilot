"""Benchmark CLI.

opspilot-eval --env simulated --model fake:playbook          # deterministic, used in CI
opspilot-eval --env live --model groq:llama-3.3-70b-versatile  # needs the stack and a key
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import tempfile
from pathlib import Path

from opspilot_agent.graph import AgentConfig
from opspilot_agent.llm import ModelSpecError, build_model
from opspilot_agent.runner import approve_all, reject_all
from opspilot_evals.environments import LiveEnvironment, SimulatedEnvironment
from opspilot_evals.report import write_report
from opspilot_evals.runner import default_out_dir, run_benchmark
from opspilot_evals.scenario import load_scenarios
from opspilot_evals.scoring import load_pricing
from opspilot_observability.tracing import configure

EVALS_DIR = Path(__file__).resolve().parent.parent


async def _main(args: argparse.Namespace) -> int:
    try:
        model = build_model(args.model)
    except ModelSpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    scenarios = load_scenarios(args.scenarios, args.only.split(",") if args.only else None)
    pricing = load_pricing(args.pricing).get(args.model)
    approval = approve_all if args.approval == "approve" else reject_all

    with tempfile.TemporaryDirectory(prefix="opspilot-sim-") as workdir:
        if args.env == "simulated":
            environment = SimulatedEnvironment(Path(workdir))
        else:
            environment = LiveEnvironment(
                warmup_seconds=args.warmup_seconds, cooldown_seconds=args.cooldown_seconds
            )
        try:
            run = await run_benchmark(
                scenarios,
                environment,
                model,
                args.model,
                approval,
                args.approval,
                pricing,
                repeats=args.repeats,
                config=AgentConfig(max_turns=args.max_turns),
            )
        finally:
            if isinstance(environment, LiveEnvironment):
                await environment.aclose()

    out_dir = args.out_dir or default_out_dir(args.results, run)
    json_path, md_path = write_report(run, out_dir)
    print(md_path.read_text())
    print(f"Wrote {json_path} and {md_path}")

    summary = run["summary"]
    if summary["unapproved_writes"]:
        print("FAIL: write actions ran without approval", file=sys.stderr)
        return 1
    accuracy = summary["root_cause_accuracy"] or 0.0
    if args.fail_under is not None and accuracy < args.fail_under:
        print(f"FAIL: root-cause accuracy {accuracy:.2f} < {args.fail_under}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="opspilot-eval", description="OpsPilot benchmark")
    parser.add_argument("--env", choices=["simulated", "live"], default="simulated")
    parser.add_argument("--model", default="fake:playbook", help="provider:model")
    parser.add_argument("--scenarios", type=Path, default=EVALS_DIR / "scenarios")
    parser.add_argument("--only", help="comma-separated scenario ids")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--approval", choices=["approve", "reject"], default="approve")
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--warmup-seconds", type=int, default=None, help="override (live env)")
    parser.add_argument("--cooldown-seconds", type=int, default=120, help="after reset (live)")
    parser.add_argument("--pricing", type=Path, default=EVALS_DIR / "pricing.yaml")
    parser.add_argument("--results", type=Path, default=EVALS_DIR / "results")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--fail-under", type=float, default=None, help="min root-cause accuracy")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    configure("opspilot-eval")
    sys.exit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
