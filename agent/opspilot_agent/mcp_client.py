"""Connect to the OpsPilot MCP server and split its tools into read and write sets."""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import StdioConnection
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp.client.stdio import get_default_environment

from opspilot_observability.tracing import subprocess_env

SERVER_NAME = "opspilot"
# Only settings the tool server needs. Model API keys never reach it.
_PASSTHROUGH_PREFIXES = (
    "OPSPILOT_PROMETHEUS",
    "OPSPILOT_CONTROL_PLANE",
    "OPSPILOT_SERVICE",
    "OPSPILOT_CONTAINER",
    "OPSPILOT_DOCKER",
    "OPSPILOT_LOG_BACKEND",
    "OPSPILOT_LOKI",
    "DOCKER_",
)
# The tool server exports its own spans, so it needs to know whether tracing is on and where to
# send them. Exact names, not an OTEL_ prefix: OTEL_EXPORTER_OTLP_HEADERS can carry a backend
# credential, which belongs with the agent like a model key does.
_PASSTHROUGH_NAMES = frozenset({"OPSPILOT_TRACING_ENABLED", "OTEL_EXPORTER_OTLP_ENDPOINT"})


def stdio_connection(backend: str = "live", simulation: Path | None = None) -> StdioConnection:
    args = ["-m", "opspilot_mcp", "--backend", backend]
    if simulation is not None:
        args += ["--simulation", str(simulation)]
    env = get_default_environment()
    env.update(
        {
            k: v
            for k, v in os.environ.items()
            if k.startswith(_PASSTHROUGH_PREFIXES) or k in _PASSTHROUGH_NAMES
        }
    )
    # Carries the current span's trace context to the server subprocess, if there is one (empty
    # when tracing is disabled or this is called outside an investigation's span), so its own
    # tool-call spans land in the same trace as the investigation that spawned it.
    env.update(subprocess_env())
    return {"transport": "stdio", "command": sys.executable, "args": args, "env": env}


@dataclass
class ToolSet:
    read: list[BaseTool] = field(default_factory=list)
    write: dict[str, BaseTool] = field(default_factory=dict)

    @classmethod
    def from_tools(cls, tools: list[BaseTool]) -> ToolSet:
        """Tools count as read-only only if the server says so; anything else needs approval."""
        toolset = cls()
        for tool in tools:
            if (tool.metadata or {}).get("readOnlyHint") is True:
                toolset.read.append(tool)
            else:
                toolset.write[tool.name] = tool
        return toolset


@asynccontextmanager
async def mcp_toolset(connection: StdioConnection) -> AsyncIterator[ToolSet]:
    """One persistent MCP session for a whole investigation."""
    client = MultiServerMCPClient({SERVER_NAME: connection})
    async with client.session(SERVER_NAME) as session:
        yield ToolSet.from_tools(await load_mcp_tools(session, server_name=SERVER_NAME))
