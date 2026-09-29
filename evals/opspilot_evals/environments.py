"""Where a scenario runs: the simulated backend (CI) or the live docker compose stack."""

from __future__ import annotations

import asyncio
import logging
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from opspilot_agent.mcp_client import stdio_connection
from opspilot_evals.scenario import FAULT_CATEGORY, Scenario
from opspilot_evals.scoring import GroundTruth
from opspilot_mcp.backends.live import LiveBackend
from opspilot_mcp.backends.simulated import SimulationSpec
from opspilot_mcp.catalog import SERVICES

log = logging.getLogger(__name__)

# Change summaries for distractor deploys (same text as the simulated backend).
BENIGN_CHANGES = {
    "storefront": ("Update copy on the order confirmation page", "a.nguyen"),
    "orders": ("Add request id to structured log fields", "m.garcia"),
    "payments": ("Upgrade HTTP client library to the latest patch", "l.chen"),
}


@dataclass
class Prepared:
    connection: Any
    ground_truth: GroundTruth
    fault_id: str | None = None


class Environment(Protocol):
    name: str

    async def prepare(self, scenario: Scenario) -> Prepared: ...

    async def remediated(self, scenario: Scenario, prepared: Prepared, result: dict) -> bool | None:
        """None when no action was executed."""
        ...

    async def cleanup(self) -> None: ...


class SimulatedEnvironment:
    """Deterministic: the MCP server generates the scenario's telemetry itself."""

    name = "simulated"

    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir
        workdir.mkdir(parents=True, exist_ok=True)

    async def prepare(self, scenario: Scenario) -> Prepared:
        spec = SimulationSpec(
            fault=scenario.fault,
            distractors=scenario.distractors,
            seed=zlib.crc32(scenario.id.encode()),
        )
        path = self.workdir / f"{scenario.id}.json"
        path.write_text(spec.model_dump_json(indent=2))
        truth = GroundTruth(
            service=scenario.fault.target, category=FAULT_CATEGORY[scenario.fault.type].value
        )
        return Prepared(connection=stdio_connection("simulated", path), ground_truth=truth)

    async def remediated(self, scenario: Scenario, prepared: Prepared, result: dict) -> bool | None:
        action = result.get("action_result")
        if not action:
            return None
        # Mirrors the simulated backend: only rolling back the bad deploy resolves a fault.
        return bool(
            action.get("ok")
            and scenario.fault.type == "bad_config_deploy"
            and action["args"]["service"] == scenario.fault.target
        )

    async def cleanup(self) -> None:
        return None


class LiveEnvironment:
    """The docker compose demo system. Faults go through the control plane's chaos API."""

    name = "live"

    def __init__(
        self,
        control_plane_url: str = "http://localhost:8190",
        warmup_seconds: int | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.url = control_plane_url.rstrip("/")
        self.warmup_seconds = warmup_seconds
        self.client = client or httpx.AsyncClient(timeout=15.0)
        self.backend = LiveBackend()

    async def _post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        response = await self.client.post(self.url + path, json=body)
        if response.status_code >= 400:
            raise RuntimeError(f"control plane {path} failed: {response.text[:300]}")
        return response.json()

    async def wait_until_healthy(self, timeout_s: float = 90.0) -> None:
        deadline = time.monotonic() + timeout_s
        while True:
            reports = [await self.backend.health(s) for s in SERVICES]
            if all(r.status == "healthy" for r in reports):
                return
            if time.monotonic() > deadline:
                raise RuntimeError(f"services not healthy: {[r.service for r in reports]}")
            await asyncio.sleep(2)

    async def prepare(self, scenario: Scenario) -> Prepared:
        await self._post("/chaos/reset")
        await self.wait_until_healthy()
        for distractor in scenario.distractors:
            summary, author = BENIGN_CHANGES[distractor.service]
            await self._post(
                "/deploys",
                {
                    "service": distractor.service,
                    "change_summary": summary,
                    "author": author,
                    "minutes_ago": distractor.minutes_ago,
                },
            )
        record = await self._post(
            "/chaos/faults",
            {
                "type": scenario.fault.type,
                "target": scenario.fault.target,
                "params": scenario.fault.params,
            },
        )
        truth = GroundTruth.model_validate(record["ground_truth"])
        warmup = self.warmup_seconds or scenario.warmup_seconds
        log.info("Injected %s into %s; waiting %ss", record["type"], record["target"], warmup)
        await asyncio.sleep(warmup)
        return Prepared(
            connection=stdio_connection("live"), ground_truth=truth, fault_id=record["id"]
        )

    async def remediated(self, scenario: Scenario, prepared: Prepared, result: dict) -> bool | None:
        if not result.get("action_result"):
            return None
        response = await self.client.get(self.url + "/chaos/faults")
        faults = {f["id"]: f for f in response.json()["faults"]}
        fault = faults.get(prepared.fault_id or "", {})
        return fault.get("resolved_by") == "rollback"

    async def cleanup(self) -> None:
        await self._post("/chaos/reset")

    async def aclose(self) -> None:
        await self.client.aclose()
        await self.backend.aclose()
