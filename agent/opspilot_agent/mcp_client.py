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

SERVER_NAME = "opspilot"
# Only settings the tool server needs. Model API keys never reach it.
_PASSTHROUGH_PREFIXES = (
    "OPSPILOT_PROMETHEUS",
    "OPSPILOT_CONTROL_PLANE",
    "OPSPILOT_SERVICE",
    "OPSPILOT_CONTAINER",
    "OPSPILOT_DOCKER",
    "DOCKER_",
)


def stdio_connection(backend: str = "live", simulation: Path | None = None) -> StdioConnection:
    args = ["-m", "opspilot_mcp", "--backend", backend]
    if simulation is not None:
        args += ["--simulation", str(simulation)]
    env = get_default_environment()
    env.update({k: v for k, v in os.environ.items() if k.startswith(_PASSTHROUGH_PREFIXES)})
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
