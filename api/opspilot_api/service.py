"""Investigations as background tasks over the LangGraph agent, with a durable approval gate.

Lifecycle: queued -> running -> (awaiting_approval -> executing) -> a terminal status.

- A run opens its own MCP tool-server session, streams the graph and records a trace event per
  node update. When the graph pauses at the approval gate, the session is closed; the paused
  run lives on in the checkpoint, so it survives an API restart.
- Approving resumes the checkpoint with a fresh tool session, so the write tool can run.
- Rejecting resumes it on a graph that has no tools at all: whatever the graph did next, there
  is nothing it could execute.
- On startup, unfinished records are reconciled with their checkpoints. Runs that were cut off
  are marked failed instead of being retried; nothing is executed twice.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable, Coroutine
from contextlib import AbstractAsyncContextManager
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command

from opspilot_agent.graph import AgentConfig, build_graph
from opspilot_agent.llm import ModelSpecError, build_model
from opspilot_agent.llm.fake import ScriptedChatModel
from opspilot_agent.mcp_client import ToolSet, mcp_toolset, stdio_connection
from opspilot_agent.prompts import alert_message
from opspilot_agent.schemas import ApprovalDecision
from opspilot_api.errors import ApiError
from opspilot_api.schemas import (
    OUTCOME_STATUS,
    Alert,
    Approval,
    CreateInvestigation,
    Decision,
    InvestigationDetail,
    InvestigationRecord,
)
from opspilot_api.settings import ApiSettings
from opspilot_api.store import InvestigationStore, utcnow
from opspilot_api.trace import events_from_update

log = logging.getLogger(__name__)

ModelFactory = Callable[[str], BaseChatModel]
ToolsetFactory = Callable[[], AbstractAsyncContextManager[ToolSet]]
RECURSION_LIMIT = 80


def inert_model() -> BaseChatModel:
    """Stands in for the model when a graph resumes at the approval gate. No node after the
    gate calls the model, and a decision must not depend on an API key."""
    return ScriptedChatModel(responses=[])


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:500]


class InvestigationService:
    def __init__(
        self,
        store: InvestigationStore,
        checkpointer: BaseCheckpointSaver,
        settings: ApiSettings,
        *,
        model_factory: ModelFactory | None = None,
        toolset_factory: ToolsetFactory | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self._checkpointer = checkpointer
        self._model_factory = model_factory or build_model
        self._toolset_factory = toolset_factory or self._mcp_toolset
        self._config = AgentConfig(max_turns=settings.max_turns)
        # Same graph structure without a model or tools: reads checkpoints, applies rejections.
        self._toolless = build_graph(
            inert_model(), [], {}, config=self._config, checkpointer=checkpointer
        )
        self._slots = asyncio.Semaphore(settings.max_concurrent)
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._tasks: set[asyncio.Task[None]] = set()
        self._changed = asyncio.Condition()
        self._versions: defaultdict[str, int] = defaultdict(int)

    def _mcp_toolset(self) -> AbstractAsyncContextManager[ToolSet]:
        return mcp_toolset(stdio_connection(self.settings.backend, self.settings.simulation))

    def _graph(self, model: BaseChatModel, tools: ToolSet) -> Any:
        return build_graph(
            model, tools.read, tools.write, config=self._config, checkpointer=self._checkpointer
        )

    @staticmethod
    def _thread(investigation_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": investigation_id}, "recursion_limit": RECURSION_LIMIT}

    # -- queries ---------------------------------------------------------------------------

    async def get(self, investigation_id: str) -> InvestigationRecord:
        record = await self.store.get(investigation_id)
        if record is None:
            raise ApiError(404, f"unknown investigation {investigation_id!r}")
        return record

    async def detail(self, investigation_id: str) -> InvestigationDetail:
        record = await self.get(investigation_id)
        return InvestigationDetail.build(record, await self.store.events(investigation_id))

    def version(self, investigation_id: str) -> int:
        return self._versions[investigation_id]

    async def wait_for_change(self, investigation_id: str, seen: int) -> None:
        async with self._changed:
            await self._changed.wait_for(lambda: self._versions[investigation_id] > seen)

    # -- commands --------------------------------------------------------------------------

    async def create(self, request: CreateInvestigation) -> InvestigationRecord:
        spec = request.model or self.settings.model
        if spec not in self.settings.models:
            raise ApiError(422, f"model must be one of: {', '.join(self.settings.models)}")
        try:
            model = self._model_factory(spec)
        except ModelSpecError as exc:
            raise ApiError(422, str(exc)) from exc
        alert = Alert(
            title=request.alert,
            service=request.service,
            details=request.details,
            firing_minutes=request.firing_minutes,
        )
        record = await self.store.create(alert, spec)
        await self._event(record.id, "alert", alert.model_dump())
        log.info("Queued %s with %s", record.id, spec)
        self._spawn(self._investigate(record.id, model), name=f"investigate-{record.id}")
        return record

    async def decide(self, investigation_id: str, decision: Decision) -> InvestigationRecord:
        async with self._locks[investigation_id]:
            record = await self.get(investigation_id)
            if record.status != "awaiting_approval":
                raise ApiError(
                    409, f"{investigation_id} is not waiting for a decision ({record.status})"
                )
            snapshot = await self._toolless.aget_state(self._thread(investigation_id))
            if not snapshot.interrupts:
                raise ApiError(409, f"{investigation_id} has no pending approval request")

            approved = decision.decision == "approve"
            record.approval = Approval(
                approved=approved,
                reviewer=decision.reviewer,
                comment=decision.comment,
                decided_at=utcnow(),
            )
            if approved:
                record.status = "executing"
            await self._save(record)
            await self._event(
                investigation_id,
                "decision",
                {
                    "decision": decision.decision,
                    "reviewer": decision.reviewer,
                    "comment": decision.comment,
                },
            )
            log.info("%s %sd by %s", investigation_id, decision.decision, decision.reviewer)
            resume = Command(
                resume=ApprovalDecision(
                    approved=approved, reviewer=decision.reviewer, comment=decision.comment
                ).model_dump()
            )
            if approved:
                self._spawn(
                    self._execute(investigation_id, resume), name=f"execute-{investigation_id}"
                )
            else:
                await self._reject(investigation_id, resume)
        return await self.get(investigation_id)

    # -- lifecycle -------------------------------------------------------------------------

    async def recover(self) -> None:
        """Reconcile unfinished records with their checkpoints after a restart."""
        for record in await self.store.unfinished():
            if record.status == "executing":
                cause = (
                    "The API restarted while the approved action was being applied. Check the "
                    "deploy history before acting again."
                )
            else:
                cause = "The API restarted before this investigation finished."
            await self._settle(record.id, cause, restarted=True)

    async def close(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # -- internals -------------------------------------------------------------------------

    def _spawn(self, coro: Coroutine[Any, Any, None], name: str) -> None:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _investigate(self, investigation_id: str, model: BaseChatModel) -> None:
        async with self._slots:
            record = await self.get(investigation_id)
            record.status, record.started_at = "running", utcnow()
            await self._save(record)
            alert = record.alert
            text = alert_message(
                alert.title, alert.service, alert.details, started_minutes_ago=alert.firing_minutes
            )
            error = None
            try:
                async with self._toolset_factory() as tools:
                    await self._stream(
                        investigation_id,
                        self._graph(model, tools),
                        {"messages": [HumanMessage(text)]},
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # the run fails, the API keeps serving
                log.exception("Investigation %s failed", investigation_id)
                error = _error_text(exc)
            await self._settle(investigation_id, error)

    async def _execute(self, investigation_id: str, resume: Command) -> None:
        error = None
        try:
            async with self._toolset_factory() as tools:
                await self._stream(investigation_id, self._graph(inert_model(), tools), resume)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Approved action of %s failed", investigation_id)
            error = _error_text(exc)
        await self._settle(investigation_id, error)

    async def _reject(self, investigation_id: str, resume: Command) -> None:
        error = None
        try:
            await self._stream(investigation_id, self._toolless, resume)
        except Exception as exc:
            log.exception("Rejecting %s failed", investigation_id)
            error = _error_text(exc)
        await self._settle(investigation_id, error)

    async def _stream(self, investigation_id: str, graph: Any, payload: Any) -> None:
        async for update in graph.astream(
            payload, self._thread(investigation_id), stream_mode="updates"
        ):
            for node, values in update.items():
                if node != "__interrupt__":
                    await self._apply(investigation_id, node, values or {})

    async def _apply(self, investigation_id: str, node: str, values: dict[str, Any]) -> None:
        record = await self.get(investigation_id)
        if node == "investigate":
            usage = (values.get("usage") or [{}])[-1]
            record.usage.turns = values.get("turns", record.usage.turns)
            record.usage.model_calls += 1
            record.usage.input_tokens += int(usage.get("input_tokens", 0))
            record.usage.output_tokens += int(usage.get("output_tokens", 0))
        elif node == "tools":
            record.usage.tool_calls += len(values.get("tool_calls", []))
        elif node == "validate" and values.get("diagnosis"):
            record.diagnosis, record.diagnosed_at = values["diagnosis"], utcnow()
        elif node == "execute_action":
            record.action_result = values.get("action_result")
        for kind, data in events_from_update(node, values):
            await self.store.add_event(investigation_id, kind, data)
        await self._save(record)

    async def _settle(
        self, investigation_id: str, error: str | None, *, restarted: bool = False
    ) -> None:
        """Derive the record's status from the checkpoint once the graph has stopped."""
        snapshot = await self._toolless.aget_state(self._thread(investigation_id))
        record = await self.get(investigation_id)
        if snapshot.interrupts:
            request = snapshot.interrupts[0].value
            if record.approval is not None:
                # The decision never reached the graph, so nothing ran. Ask again.
                record.approval = None
                cause = "the API restarted" if restarted else error
                await self._event(
                    investigation_id,
                    "error",
                    {
                        "message": f"The decision was not applied ({cause}), so nothing was "
                        "executed. Decide again."
                    },
                )
            if record.approval_request != request:
                record.approval_request = request
                await self._event(investigation_id, "approval_requested", request)
            record.status = "awaiting_approval"
        elif not snapshot.next and (outcome := snapshot.values.get("outcome")):
            record.status = OUTCOME_STATUS.get(outcome, "failed")
            record.outcome = outcome
            record.action_result = snapshot.values.get("action_result") or record.action_result
            record.finished_at = utcnow()
            await self._event(investigation_id, "finished", {"outcome": outcome})
        else:
            record.status = "failed"
            record.error = error or "The investigation stopped before it finished."
            record.finished_at = utcnow()
            await self._event(investigation_id, "error", {"message": record.error})
        await self._save(record)
        log.info("%s is %s%s", investigation_id, record.status, " (recovered)" if restarted else "")

    async def _save(self, record: InvestigationRecord) -> None:
        await self.store.save(record)
        await self._notify(record.id)

    async def _event(self, investigation_id: str, kind: str, data: dict[str, Any]) -> None:
        await self.store.add_event(investigation_id, kind, data)
        await self._notify(investigation_id)

    async def _notify(self, investigation_id: str) -> None:
        async with self._changed:
            self._versions[investigation_id] += 1
            self._changed.notify_all()
