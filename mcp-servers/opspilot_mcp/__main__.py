"""Run the OpsPilot observability MCP server.

opspilot-mcp                                    # live backend, stdio transport
opspilot-mcp --backend simulated --simulation spec.json
opspilot-mcp --transport streamable-http --port 8150
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from opspilot_mcp.backends.base import TelemetryBackend
from opspilot_mcp.server import build_server


def build_backend(kind: str, simulation: Path | None = None) -> TelemetryBackend:
    if kind == "simulated":
        from opspilot_mcp.backends.simulated import SimulatedBackend, SimulationSpec

        spec = (
            SimulationSpec.model_validate_json(simulation.read_text())
            if simulation
            else SimulationSpec()
        )
        return SimulatedBackend(spec)
    from opspilot_mcp.backends.live import LiveBackend

    return LiveBackend()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="opspilot-mcp", description=__doc__.splitlines()[0])
    parser.add_argument(
        "--backend",
        choices=["live", "simulated"],
        default=os.getenv("OPSPILOT_BACKEND", "live"),
    )
    parser.add_argument("--simulation", type=Path, help="SimulationSpec JSON (simulated backend)")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8150)
    args = parser.parse_args(argv)

    # stdout carries the MCP protocol on stdio; diagnostics go to stderr only.
    logging.basicConfig(level=logging.WARNING)
    server = build_server(build_backend(args.backend, args.simulation))
    if args.transport == "streamable-http":
        server.settings.host = args.host
        server.settings.port = args.port
        server.run("streamable-http")
    else:
        server.run("stdio")


if __name__ == "__main__":
    main()
