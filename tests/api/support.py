"""Helpers for the agent API tests: scripted models, fake tools, an in-process server."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from opspilot_agent.llm.fake import ScriptedChatModel
from opspilot_agent.mcp_client import ToolSet
from opspilot_agent.prompts import SUBMIT_TOOL
from opspilot_api.app import create_app
from opspilot_api.settings import ApiSettings

TERMINAL = {"executed", "action_failed", "rejected", "advisory", "no_diagnosis", "failed"}


def diagnosis(action: str) -> dict[str, Any]:
    return {
        "root_cause_service": "orders",
        "category": "bad_deploy" if action == "rollback_deploy" else "error_rate",
        "summary": "orders started failing right after its latest deploy.",
        "evidence": [
            {"source": "deploys", "service": "orders", "detail": "1.8.4 changed payments.base-url"}
        ],
        "confidence": 0.8,
        "proposed_action": {
            "type": action,
            "target_service": "orders",
            "rationale": "Revert the deploy that introduced the failures.",
        },
    }


def script(action: str) -> list[AIMessage]:
    """Check health once, then submit a diagnosis proposing `action`."""
    return [
        AIMessage(
            content="Checking service health first.",
            tool_calls=[{"name": "get_service_health", "args": {}, "id": "call-1"}],
        ),
        AIMessage(
            content="",
            tool_calls=[{"name": SUBMIT_TOOL, "args": diagnosis(action), "id": "call-2"}],
        ),
    ]


def scripted(action: str) -> Callable[[str], ScriptedChatModel]:
    return lambda spec: ScriptedChatModel(responses=script(action))


class FakeTools:
    """In-process stand-in for the MCP tool server. Records sessions and calls."""

    def __init__(self) -> None:
        self.sessions = 0
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @property
    def rollbacks(self) -> list[dict[str, Any]]:
        return [args for name, args in self.calls if name == "rollback_deploy"]

    @asynccontextmanager
    async def session(self) -> AsyncIterator[ToolSet]:
        self.sessions += 1
        yield self._toolset()

    def _toolset(self) -> ToolSet:
        async def health(service: str | None = None) -> str:
            self.calls.append(("get_service_health", {"service": service}))
            return json.dumps(
                {
                    "services": [
                        {"service": "storefront", "status": "healthy", "http_status": 200},
                        {"service": "orders", "status": "unhealthy", "http_status": 503},
                    ]
                }
            )

        async def rollback(service: str, reason: str) -> str:
            self.calls.append(("rollback_deploy", {"service": service, "reason": reason}))
            event = {"service": service, "version": "1.8.3", "previous_version": "1.8.4"}
            return json.dumps({"status": "rolled_back", "event": event})

        read = StructuredTool.from_function(
            coroutine=health,
            name="get_service_health",
            description="Health of every service.",
            metadata={"readOnlyHint": True},
        )
        write = StructuredTool.from_function(
            coroutine=rollback,
            name="rollback_deploy",
            description="Roll back a deploy.",
            metadata={"readOnlyHint": False, "destructiveHint": True},
        )
        return ToolSet.from_tools([read, write])


class BlockingTools(FakeTools):
    """The first health check never returns, so the run is cut off inside the tools node."""

    def _toolset(self):
        toolset = super()._toolset()
        health = toolset.read[0]

        async def stuck(**kwargs):
            await asyncio.Event().wait()

        health.coroutine = stuck
        return toolset


@asynccontextmanager
async def serve(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Run the app's lifespan (startup recovery, shutdown) around an in-process client."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
            yield client


async def wait_for(
    client: httpx.AsyncClient, investigation_id: str, statuses: set[str]
) -> dict[str, Any]:
    """Poll until the investigation reaches one of `statuses` (at most 20 seconds)."""
    async with asyncio.timeout(20):
        while True:
            body = (await client.get(f"/investigations/{investigation_id}")).json()
            if body["status"] in statuses:
                return body
            await asyncio.sleep(0.02)


def build_app(settings: ApiSettings, tools: FakeTools, action: str, **kwargs: Any) -> FastAPI:
    return create_app(
        settings, model_factory=scripted(action), toolset_factory=tools.session, **kwargs
    )
