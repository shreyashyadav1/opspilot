"""Inbound telemetry middleware and an instrumented client for outbound calls."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from opsdemo.common.metrics import (
    HTTP_CLIENT_REQUESTS,
    HTTP_SERVER_REQUESTS,
    IO_ERROR_STATUS,
    outcome_for,
)
from opsdemo.common.runtime import ServiceRuntime

access_log = logging.getLogger("http.access")
error_log = logging.getLogger("http.server")

# Never logged or measured: this is how the control plane talks to the service.
ADMIN_PREFIX = "/admin"
# Measured by Prometheus itself and by probes; kept out of access logs and request metrics.
QUIET_PATHS = frozenset({"/health", "/metrics"})


async def _send_json(send: Send, status: int, body: dict[str, Any]) -> None:
    payload = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})


class TelemetryMiddleware:
    """Access logs, request metrics, unhandled-error logging and service-level failure modes."""

    def __init__(self, app: ASGIApp, runtime: ServiceRuntime) -> None:
        self.app = app
        self.runtime = runtime

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope["path"]
        if path.startswith(ADMIN_PREFIX):
            await self.app(scope, receive, send)
            return
        if self.runtime.failures.outage:
            # An unavailable instance emits nothing: no logs, no metrics, failed scrapes.
            await _send_json(send, 503, {"error": "service_unavailable"})
            return
        if path in QUIET_PATHS:
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        delay = self.runtime.added_latency_s()
        if delay:
            # Counted in the request duration: to callers and metrics this is the service
            # being slow.
            await asyncio.sleep(delay)

        response_started = False
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started, status
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
            await send(message)

        method: str = scope["method"]
        try:
            self.runtime.remember_request(path)
            await self.app(scope, receive, send_wrapper)
        except Exception:
            status = 500
            error_log.exception(
                "Unhandled exception while handling %s %s",
                method,
                path,
                extra={"http_method": method, "http_path": path},
            )
            if not response_started:
                await _send_json(send, 500, {"error": "internal_error"})
        finally:
            elapsed = time.perf_counter() - started
            route = scope.get("route")
            uri = getattr(route, "path", None) or "UNKNOWN"
            HTTP_SERVER_REQUESTS.labels(method, uri, str(status), outcome_for(status)).observe(
                elapsed
            )
            access_log.log(
                logging.WARNING if status >= 500 else logging.INFO,
                "%s %s %d %.0fms",
                method,
                path,
                status,
                elapsed * 1000,
                extra={
                    "http_method": method,
                    "http_route": uri,
                    "http_status": status,
                    "duration_ms": round(elapsed * 1000, 1),
                },
            )


class UpstreamError(Exception):
    """An outbound call failed. `kind` is one of: timeout, unreachable, bad_status."""

    def __init__(self, upstream: str, kind: str, status_code: int | None = None) -> None:
        super().__init__(f"{upstream}: {kind}" + (f" ({status_code})" if status_code else ""))
        self.upstream = upstream
        self.kind = kind
        self.status_code = status_code

    @property
    def http_status(self) -> int:
        return 504 if self.kind == "timeout" else 502

    def to_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {"error": f"upstream_{self.kind}", "upstream": self.upstream}
        if self.status_code:
            body["upstream_status"] = self.status_code
        return body


class UpstreamClient:
    """Outbound HTTP client that records metrics and logs failures and slow calls."""

    def __init__(
        self,
        name: str,
        client: httpx.AsyncClient,
        base_url: Callable[[], str],
        timeout_ms: Callable[[], int],
        slow_call_ms: int = 1000,
    ) -> None:
        self.name = name
        self._client = client
        self._base_url = base_url
        self._timeout_ms = timeout_ms
        self._slow_call_ms = slow_call_ms
        self._log = logging.getLogger(f"upstream.{name}")

    async def request(
        self, method: str, uri_template: str, path: str, json_body: Any = None
    ) -> httpx.Response:
        timeout_ms = self._timeout_ms()
        url = self._base_url().rstrip("/") + path
        fields = {"upstream": self.name, "http_method": method, "http_route": uri_template}
        started = time.perf_counter()
        try:
            response = await self._client.request(
                method, url, json=json_body, timeout=timeout_ms / 1000
            )
        except httpx.TimeoutException as exc:
            self._record(method, uri_template, IO_ERROR_STATUS, "UNKNOWN", started)
            self._log.error(
                "Call to %s timed out after %d ms: %s %s",
                self.name,
                timeout_ms,
                method,
                uri_template,
                extra={**fields, "timeout_ms": timeout_ms, "error_type": type(exc).__name__},
            )
            raise UpstreamError(self.name, "timeout") from exc
        except httpx.TransportError as exc:
            self._record(method, uri_template, IO_ERROR_STATUS, "UNKNOWN", started)
            self._log.error(
                "Call to %s failed: %s: %s",
                self.name,
                type(exc).__name__,
                exc or "connection error",
                extra={**fields, "error_type": type(exc).__name__},
            )
            raise UpstreamError(self.name, "unreachable") from exc

        elapsed_ms = self._record(
            method,
            uri_template,
            str(response.status_code),
            outcome_for(response.status_code),
            started,
        )
        if elapsed_ms > self._slow_call_ms:
            self._log.warning(
                "Slow call to %s: %s %s took %.0f ms",
                self.name,
                method,
                uri_template,
                elapsed_ms,
                extra={**fields, "duration_ms": round(elapsed_ms, 1)},
            )
        if response.status_code >= 500:
            self._log.error(
                "Call to %s returned HTTP %d: %s %s",
                self.name,
                response.status_code,
                method,
                uri_template,
                extra={
                    **fields,
                    "http_status": response.status_code,
                    "response_body": response.text[:200],
                },
            )
            raise UpstreamError(self.name, "bad_status", response.status_code)
        return response

    def _record(self, method: str, uri: str, status: str, outcome: str, started: float) -> float:
        elapsed = time.perf_counter() - started
        HTTP_CLIENT_REQUESTS.labels(self.name, method, uri, status, outcome).observe(elapsed)
        return elapsed * 1000
