"""Demo fault injection through the control plane's chaos API.

This is the benchmark harness's side of the system, exposed so a dashboard can stage an
incident. It is never part of the agent's tool surface: the MCP server is not configured with
the chaos endpoints, and `OPSPILOT_CHAOS_URL` is not passed to it.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from opspilot_api.errors import ApiError
from opspilot_mcp.catalog import ServiceName


class FaultInjection(BaseModel):
    """What the dashboard may ask for. The control plane validates the rest (targets, params)."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(pattern=r"^[a-z_]{3,40}$")
    target: ServiceName
    params: dict[str, float | int] = Field(default_factory=dict)


class ChaosClient:
    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=15.0, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def catalog(self) -> Any:
        return await self._request("GET", "/chaos/catalog")

    async def faults(self) -> Any:
        return await self._request("GET", "/chaos/faults")

    async def inject(self, body: dict[str, Any]) -> Any:
        return await self._request("POST", "/chaos/faults", body)

    async def clear(self, fault_id: str) -> Any:
        return await self._request("DELETE", f"/chaos/faults/{fault_id}")

    async def reset(self) -> Any:
        return await self._request("POST", "/chaos/reset")

    async def _request(self, method: str, path: str, body: Any = None) -> Any:
        try:
            response = await self._client.request(method, path, json=body)
        except httpx.HTTPError as exc:
            raise ApiError(
                502, f"control plane unreachable at {self.base_url} ({type(exc).__name__})"
            ) from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            status = response.status_code if response.status_code < 500 else 502
            raise ApiError(status, f"control plane: {str(detail)[:300]}")
        return response.json()
