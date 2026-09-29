"""Simulated backend: deterministic synthetic telemetry for one injected fault.

It mirrors the failure signatures of the live demo system (the same log messages, metric names
and shapes, health payloads and deploy history) so that the agent, the tools and the benchmark
harness can run without Docker. It exists for tests and CI; its numbers are never reported as
benchmark results.

Time does not advance: everything is generated relative to a fixed `now`, so repeated queries
return identical data.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from opspilot_mcp.catalog import CATALOG, SERVICES, ServiceName
from opspilot_mcp.models import BackendError, DeployEvent, HealthReport, LogEntry, Series

FaultType = Literal[
    "latency_spike", "error_spike", "db_pool_exhaustion", "bad_config_deploy", "dependency_outage"
]


class FaultSpec(BaseModel):
    type: FaultType
    target: ServiceName
    params: dict[str, Any] = Field(default_factory=dict)


class Distractor(BaseModel):
    type: Literal["benign_deploy"] = "benign_deploy"
    service: ServiceName
    minutes_ago: float = Field(5.0, ge=0, le=600)


class SimulationSpec(BaseModel):
    fault: FaultSpec | None = None
    distractors: list[Distractor] = Field(default_factory=list)
    onset_minutes_ago: float = Field(4.0, gt=0, le=50)
    seed: int = 7
    now: datetime | None = None


STEP = timedelta(seconds=15)
HISTORY = timedelta(minutes=60)
LOG_SAMPLING = 0.1  # share of requests materialized as access-log lines
UPSTREAM = {"storefront": "orders", "orders": "payments"}
BASE_RATE = {"storefront": 4.0, "orders": 2.8, "payments": 2.2}
BASE_LATENCY = {
    "storefront": (14.0, 48.0, 65.0),
    "orders": (16.0, 35.0, 50.0),
    "payments": (12.0, 22.0, 30.0),
}
BASE_ERROR = {"storefront": 0.002, "orders": 0.001, "payments": 0.0}
CHECKOUT_SHARE = 0.55  # of storefront traffic; goes storefront -> orders -> payments
ORDERS_SHARE = 0.70  # of storefront traffic that calls orders (checkout + lookups)
ORDERS_POST_SHARE = 2.2 / 2.8  # of orders traffic that calls payments

# (service, version, previous, age, author, summary), mirroring the control plane's seed.
_SEED_DEPLOYS = (
    (
        "storefront",
        "2.13.3",
        "2.13.2",
        timedelta(days=3, hours=1),
        "a.nguyen",
        "Fix currency formatting on receipts",
    ),
    (
        "orders",
        "1.8.2",
        "1.8.1",
        timedelta(days=2, hours=4),
        "m.garcia",
        "Retry payment calls on connect timeout",
    ),
    (
        "payments",
        "3.1.5",
        "3.1.4",
        timedelta(hours=30),
        "l.chen",
        "Rotate acquirer API credentials",
    ),
    (
        "storefront",
        "2.14.0",
        "2.13.3",
        timedelta(hours=26),
        "j.okafor",
        "Upgrade FastAPI and uvicorn",
    ),
    (
        "orders",
        "1.8.3",
        "1.8.2",
        timedelta(hours=9),
        "s.patel",
        "Lower Hikari max-lifetime to 10 minutes",
    ),
    (
        "payments",
        "3.2.0",
        "3.1.5",
        timedelta(hours=7),
        "r.silva",
        "Move fraud scoring to async worker",
    ),
)
_BAD_CONFIG = {
    "storefront": (
        "Tighten upstream timeouts so checkout fails fast under load",
        "j.okafor",
        {"orders_timeout_ms": {"from": 2000, "to": 20}},
    ),
    "orders": (
        "Route payment calls through the new payments endpoint",
        "s.patel",
        {"payments.base-url": {"from": "http://payments:8080", "to": "http://payments-v2:8080"}},
    ),
    "payments": (
        "Adopt banker's rounding for settlement amounts",
        "r.silva",
        {"rounding_mode": {"from": "HALF_EVEN", "to": "BANKERS"}},
    ),
}
_BENIGN = {
    "storefront": ("Update copy on the order confirmation page", "a.nguyen"),
    "orders": ("Add request id to structured log fields", "m.garcia"),
    "payments": ("Upgrade HTTP client library to the latest patch", "l.chen"),
}

_PY_KEYERROR = (
    "Traceback (most recent call last):\n"
    '  File "/app/opsdemo/storefront/app.py", line 73, in build_order_request\n'
    '  File "/app/opsdemo/storefront/app.py", line 82, in _promo_unit_price\n'
    "KeyError: 'promo_price_cents'"
)
_PY_TYPEERROR = (
    "Traceback (most recent call last):\n"
    '  File "/app/opsdemo/payments/app.py", line 57, in create_charge\n'
    '  File "/app/opsdemo/payments/app.py", line 50, in settlement_amount\n'
    "TypeError: unsupported operand type(s) for *: 'decimal.Decimal' and 'NoneType'"
)
_PY_CONFIGERROR = (
    "Traceback (most recent call last):\n"
    '  File "/app/opsdemo/payments/app.py", line 43, in settlement_amount\n'
    "opsdemo.payments.app.ConfigurationError: unsupported rounding_mode 'BANKERS'; "
    "expected one of HALF_EVEN, HALF_UP"
)
_JAVA_NPE = (
    'java.lang.NullPointerException: Cannot invoke "java.math.BigDecimal.negate()" because '
    '"discount" is null\n'
    "\tat dev.opspilot.orders.domain.OrderPricing.totalCents(OrderPricing.java:27)\n"
    "\tat dev.opspilot.orders.domain.OrderService.create(OrderService.java:25)\n"
    "\tat dev.opspilot.orders.api.OrderController.create(OrderController.java:27)"
)
_JAVA_LEAK = (
    "java.lang.Exception: Apparent connection leak detected\n"
    "\tat com.zaxxer.hikari.HikariDataSource.getConnection(HikariDataSource.java:127)\n"
    "\tat dev.opspilot.orders.export.OrderExportJob.readBatch(OrderExportJob.java:81)\n"
    "\tat dev.opspilot.orders.export.OrderExportJob.run(OrderExportJob.java:65)"
)


@dataclass
class ServiceState:
    up: bool
    rate: float
    error: float
    latency: tuple[float, float, float]
    upstream_error: float = 0.0
    upstream_p95: float = 0.0
    pool: tuple[float, float] | None = None

    def slower(self, delay_ms: float) -> None:
        self.latency = tuple(v + delay_ms for v in self.latency)  # type: ignore[assignment]


@dataclass
class _Line:
    service: str
    level: str
    logger: str
    message: str
    extra: dict[str, Any] = field(default_factory=dict)


class SimulatedBackend:
    def __init__(self, spec: SimulationSpec) -> None:
        self.spec = spec
        self.now = (spec.now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
        self.onset = self.now - timedelta(minutes=spec.onset_minutes_ago)
        self.fault = spec.fault
        self.resolved = False
        self._events: list[DeployEvent] = []
        self._bad_deploy_id: str | None = None
        self._seed_deploys()
        self._logs = self._generate_logs()

    async def aclose(self) -> None:
        return None

    # -- model -------------------------------------------------------------------------------

    def _fault_active(self, t: datetime) -> bool:
        return self.fault is not None and not self.resolved and t >= self.onset

    def _state(self, t: datetime) -> dict[str, ServiceState]:
        states = {
            s: ServiceState(
                up=True,
                rate=BASE_RATE[s],
                error=BASE_ERROR[s],
                latency=BASE_LATENCY[s],
                upstream_p95=BASE_LATENCY[UPSTREAM[s]][1] + 3 if s in UPSTREAM else 0.0,
                pool=(1.0, 0.0) if s == "orders" else None,
            )
            for s in SERVICES
        }
        if self._fault_active(t):
            assert self.fault is not None
            self._apply_fault(states, self.fault)
        return states

    @staticmethod
    def _apply_fault(states: dict[str, ServiceState], fault: FaultSpec) -> None:
        sf, orders, pay = states["storefront"], states["orders"], states["payments"]
        target = fault.target
        match fault.type:
            case "latency_spike":
                delay = float(fault.params.get("delay_ms", 1200))
                states[target].slower(delay)
                if target in ("orders", "payments"):
                    sf.slower(delay)
                    sf.upstream_p95 += delay
                if target == "payments":
                    orders.slower(delay)
                    orders.upstream_p95 += delay
            case "error_spike":
                rate = float(fault.params.get("error_rate", 0.4))
                if target == "payments":
                    pay.error = rate
                    orders.error, orders.upstream_error = rate * ORDERS_POST_SHARE, rate
                    sf.error, sf.upstream_error = rate * CHECKOUT_SHARE, rate * ORDERS_POST_SHARE
                elif target == "orders":
                    orders.error = rate * ORDERS_POST_SHARE
                    sf.error, sf.upstream_error = rate * CHECKOUT_SHARE, rate * ORDERS_POST_SHARE
                    pay.rate *= 1 - rate
                else:
                    sf.error = rate * CHECKOUT_SHARE
                    orders.rate = BASE_RATE["orders"] - BASE_RATE["payments"] * rate
                    pay.rate *= 1 - rate
            case "db_pool_exhaustion":
                orders.error, orders.latency, orders.pool = 0.97, (1510.0, 1560.0, 1600.0), (5, 4)
                sf.error, sf.latency = ORDERS_SHARE * 0.97, (1505.0, 1570.0, 1610.0)
                sf.upstream_error, sf.upstream_p95 = 0.97, 1560.0
                pay.rate = 0.05
            case "bad_config_deploy":
                if target == "storefront":
                    sf.error, sf.latency = 0.51, (18.0, 26.0, 40.0)
                    sf.upstream_error, sf.upstream_p95 = 0.73, 21.0
                else:
                    orders.error = ORDERS_POST_SHARE
                    orders.upstream_error, orders.upstream_p95 = 1.0, 6.0
                    sf.error, sf.upstream_error = CHECKOUT_SHARE, ORDERS_POST_SHARE
                    if target == "orders":
                        pay.rate = 0.0
                    else:
                        pay.error = 1.0
            case "dependency_outage":
                states[target].up = False
                if target == "payments":
                    orders.error = ORDERS_POST_SHARE
                    orders.upstream_error, orders.upstream_p95 = 1.0, 5.0
                    sf.error, sf.upstream_error = CHECKOUT_SHARE, ORDERS_POST_SHARE
                else:
                    sf.error, sf.upstream_error, sf.upstream_p95 = ORDERS_SHARE, 1.0, 5.0
                    pay.rate = 0.0

    # -- metrics -----------------------------------------------------------------------------

    def _noise(self, *key: object) -> float:
        return random.Random(":".join(map(str, (self.spec.seed, *key)))).uniform(0.94, 1.06)

    def _value(self, state: ServiceState, service: str, metric: str, i: int) -> float | None:
        if metric == "up":
            return 1.0 if state.up else 0.0
        if not state.up:
            return None
        noise = self._noise(service, metric, i)
        match metric:
            case "request_rate":
                return state.rate * noise
            case "error_rate":
                return min(1.0, state.error * noise) if state.rate > 0.01 else None
            case "latency_p50" | "latency_p95" | "latency_p99":
                index = {"latency_p50": 0, "latency_p95": 1, "latency_p99": 2}[metric]
                return state.latency[index] * noise
            case "upstream_error_rate":
                return min(1.0, state.upstream_error * noise)
            case "upstream_latency_p95":
                return state.upstream_p95 * noise
            case "db_pool_active":
                return state.pool[0] if state.pool else None
            case "db_pool_pending":
                return state.pool[1] if state.pool else None
        raise BackendError(f"unknown metric {metric}")

    async def metric_series(self, service: str, metric: str, window_minutes: int) -> list[Series]:
        start = self.now - timedelta(minutes=window_minutes)
        points: list[tuple[datetime, float | None]] = []
        t, i = start, 0
        while t <= self.now:
            points.append((t, self._value(self._state(t)[service], service, metric, i)))
            t, i = t + STEP, i + 1
        if metric.startswith("upstream_"):
            if service not in UPSTREAM:
                return []
            return [Series(labels={"client_name": UPSTREAM[service]}, points=points)]
        return [Series(points=points)]

    # -- health ------------------------------------------------------------------------------

    async def health(self, service: str) -> HealthReport:
        state = self._state(self.now)[service]
        depends_on = list(CATALOG[service].depends_on)
        version = self._current(service).version
        if not state.up:
            return HealthReport(
                service=service,
                status="unhealthy",
                http_status=503,
                latency_ms=2.1,
                detail="service_unavailable",
                depends_on=depends_on,
            )
        if service == "orders" and state.pool == (5, 4):
            return HealthReport(
                service=service,
                status="unhealthy",
                http_status=503,
                latency_ms=1503.2,
                version=version,
                failing_components=["db"],
                detail="db: org.springframework.jdbc.CannotGetJdbcConnectionException: "
                "Failed to obtain JDBC Connection",
                depends_on=depends_on,
            )
        return HealthReport(
            service=service,
            status="healthy",
            http_status=200,
            latency_ms=round(4.0 * self._noise("health", service), 1),
            version=version,
            depends_on=depends_on,
        )

    # -- deploys -----------------------------------------------------------------------------

    def _add_event(self, **kwargs: Any) -> DeployEvent:
        event = DeployEvent(id=f"dep-{len(self._events) + 1:04d}", **kwargs)
        self._events.append(event)
        return event

    def _current(self, service: str) -> DeployEvent:
        return [e for e in self._events if e.service == service][-1]

    def _seed_deploys(self) -> None:
        for service, version, previous, age, author, summary in _SEED_DEPLOYS:
            self._add_event(
                service=service,
                kind="deploy",
                version=version,
                previous_version=previous,
                deployed_at=self.now - age,
                author=author,
                change_summary=summary,
            )
        changes: list[tuple[datetime, str, bool]] = [
            (self.now - timedelta(minutes=d.minutes_ago), d.service, False)
            for d in self.spec.distractors
        ]
        if self.fault and self.fault.type == "bad_config_deploy":
            changes.append((self.onset, self.fault.target, True))
        for when, service, bad in sorted(changes):
            current = self._current(service).version
            major, minor, patch = current.split(".")
            summary, author, diff = _BAD_CONFIG[service] if bad else (*_BENIGN[service], {})
            event = self._add_event(
                service=service,
                kind="deploy",
                version=f"{major}.{minor}.{int(patch) + 1}",
                previous_version=current,
                deployed_at=when,
                author=author,
                change_summary=summary,
                config_diff=diff,
            )
            if bad:
                self._bad_deploy_id = event.id

    async def deploys(self, service: str | None, since_minutes: int) -> list[DeployEvent]:
        since = self.now - timedelta(minutes=since_minutes)
        return [
            e for e in self._events if (service in (None, e.service)) and e.deployed_at >= since
        ]

    async def rollback(self, service: str, reason: str) -> DeployEvent:
        current = self._current(service)
        running = next(
            e
            for e in reversed(self._events)
            if e.service == service and e.kind == "deploy" and e.version == current.version
        )
        if running.previous_version is None:
            raise BackendError(f"{service} has no earlier version to roll back to")
        diff = {k: {"from": v["to"], "to": v["from"]} for k, v in running.config_diff.items()}
        event = self._add_event(
            service=service,
            kind="rollback",
            version=running.previous_version,
            previous_version=running.version,
            deployed_at=self.now,
            author="opspilot",
            config_diff=diff,
            change_summary=f"Rollback {running.version} -> {running.previous_version}: {reason}",
        )
        if running.id == self._bad_deploy_id:
            self.resolved = True
        return event

    # -- logs --------------------------------------------------------------------------------

    async def log_entries(self, service: str, since_minutes: int) -> list[LogEntry]:
        since = self.now - timedelta(minutes=since_minutes)
        return [e for e in self._logs if e.service == service and e.timestamp >= since]

    def _generate_logs(self) -> list[LogEntry]:
        rng = random.Random(self.spec.seed)
        entries: list[LogEntry] = []

        def emit(t: datetime, line: _Line, trace_id: str | None) -> None:
            if t > self.now:
                return
            extra = dict(line.extra)
            entries.append(
                LogEntry(
                    timestamp=t,
                    service=line.service,
                    level=line.level,
                    message=line.message,
                    logger=line.logger,
                    trace_id=trace_id,
                    error_type=extra.pop("error_type", None),
                    error_message=extra.pop("error_message", None),
                    stack_trace=extra.pop("stack_trace", None),
                    fields=extra,
                )
            )

        t = self.now - HISTORY
        while t <= self.now:
            states = self._state(t)
            for service in SERVICES:
                state = states[service]
                if not state.up or state.rate <= 0.01:
                    continue
                ok_lines = round(state.rate * (1 - state.error) * 15 * LOG_SAMPLING)
                for _ in range(max(1, ok_lines)):
                    offset = timedelta(seconds=rng.uniform(0, 14.9))
                    line = self._access_line(service, state, rng)
                    emit(t + offset, line, rng.randbytes(16).hex())
            if self._fault_active(t):
                for _ in range(self._affected_requests(states)):
                    trace_id = rng.randbytes(16).hex()
                    offset = timedelta(seconds=rng.uniform(0, 14.9))
                    for line in self._failure_chain(rng):
                        emit(t + offset, line, trace_id)
                for line in self._periodic_lines(t):
                    emit(t, line, None)
            t += STEP
        return sorted(entries, key=lambda e: e.timestamp)

    def _affected_requests(self, states: dict[str, ServiceState]) -> int:
        """Sampled number of failing (or slow) requests per step while the fault is active."""
        assert self.fault is not None
        share = (
            CHECKOUT_SHARE
            if self.fault.type == "latency_spike"
            else max(s.error for s in states.values())
        )
        return max(1, round(BASE_RATE["storefront"] * share * 15 * LOG_SAMPLING))

    @staticmethod
    def _access_line(service: str, state: ServiceState, rng: random.Random) -> _Line:
        """A successful request; failures are logged by the fault's failure chain."""
        routes = {
            "storefront": [("POST", "/checkout"), ("GET", "/products"), ("GET", "/orders/1042")],
            "orders": [("POST", "/orders"), ("GET", "/orders/1042")],
            "payments": [("POST", "/charges")],
        }
        method, path = rng.choice(routes[service])
        status = 201 if method == "POST" else 200
        duration = state.latency[0] * rng.uniform(0.7, 1.4)
        return _Line(
            service,
            "INFO",
            "http.access",
            f"{method} {path} {status} {duration:.0f}ms",
            {"http_status": status, "duration_ms": round(duration, 1)},
        )

    def _periodic_lines(self, t: datetime) -> list[_Line]:
        assert self.fault is not None
        if self.fault.type != "db_pool_exhaustion":
            return []
        lines = [
            _Line(
                "orders",
                "WARN",
                "dev.opspilot.orders.export.OrderExportJob",
                "Order export batch failed: orders-db - Connection is not available, "
                "request timed out after 1501ms (total=5, active=5, idle=0, waiting=6)",
            )
        ]
        since_onset = t - self.onset
        if since_onset < STEP:
            lines.append(
                _Line(
                    "orders",
                    "INFO",
                    "dev.opspilot.orders.export.OrderExportJob",
                    "Order export started",
                )
            )
        elif since_onset < 2 * STEP:
            lines += [
                _Line(
                    "orders",
                    "WARN",
                    "com.zaxxer.hikari.pool.ProxyLeakTask",
                    f"Connection leak detection triggered for org.postgresql.jdbc.PgConnection@"
                    f"{0x591F6F83 + n:x} on thread order-export-worker, stack trace follows",
                    {"stack_trace": _JAVA_LEAK},
                )
                for n in range(5)
            ]
        return lines

    def _failure_chain(self, rng: random.Random) -> list[_Line]:
        """Log lines one failing (or, for latency, slow) request leaves across services."""
        assert self.fault is not None
        kind, target = self.fault.type, self.fault.target
        ms = rng.randint(3, 40)

        def storefront_gets(status: int) -> list[_Line]:
            return [
                _Line(
                    "storefront",
                    "ERROR",
                    "upstream.orders",
                    f"Call to orders returned HTTP {status}: POST /orders",
                ),
                _Line("storefront", "WARN", "http.access", f"POST /checkout 502 {ms + 20}ms"),
            ]

        def orders_payment_failed(detail: str, status: int | None) -> list[_Line]:
            upstream = (
                f"Call to payments returned HTTP {status}: POST /charges"
                if status
                else f"Call to payments failed: {detail}"
            )
            return [
                _Line("orders", "ERROR", "upstream.payments", upstream),
                _Line(
                    "orders",
                    "WARN",
                    "http.server",
                    "Order could not be completed: "
                    + (f"payments returned HTTP {status}" if status else "payments call failed"),
                ),
                _Line("orders", "WARN", "http.access", f"POST /orders 502 {ms}ms"),
                *storefront_gets(502),
            ]

        match kind, target:
            case "latency_spike", _:
                delay = int(self.fault.params.get("delay_ms", 1200)) + rng.randint(-150, 150)
                lines = []
                if target == "payments":
                    lines.append(
                        _Line(
                            "orders",
                            "WARN",
                            "upstream.payments",
                            f"Slow call to payments: POST /charges took {delay} ms",
                        )
                    )
                if target in ("orders", "payments"):
                    lines.append(
                        _Line(
                            "storefront",
                            "WARN",
                            "upstream.orders",
                            f"Slow call to orders: POST /orders took {delay + 18} ms",
                        )
                    )
                return lines
            case "error_spike", "payments":
                return [
                    _Line(
                        "payments",
                        "ERROR",
                        "http.server",
                        "Unhandled exception while handling POST /charges",
                        {
                            "error_type": "TypeError",
                            "stack_trace": _PY_TYPEERROR,
                            "error_message": "unsupported operand type(s) for *: "
                            "'decimal.Decimal' and 'NoneType'",
                        },
                    ),
                    _Line("payments", "WARN", "http.access", f"POST /charges 500 {ms}ms"),
                    *orders_payment_failed("", 500),
                ]
            case "error_spike", "orders":
                return [
                    _Line(
                        "orders",
                        "ERROR",
                        "http.server",
                        "Unhandled exception while handling POST /orders",
                        {"error_type": "NullPointerException", "stack_trace": _JAVA_NPE},
                    ),
                    _Line("orders", "WARN", "http.access", f"POST /orders 500 {ms}ms"),
                    *storefront_gets(500),
                ]
            case "error_spike", "storefront":
                return [
                    _Line(
                        "storefront",
                        "ERROR",
                        "http.server",
                        "Unhandled exception while handling POST /checkout",
                        {
                            "error_type": "KeyError",
                            "error_message": "'promo_price_cents'",
                            "stack_trace": _PY_KEYERROR,
                        },
                    ),
                    _Line("storefront", "WARN", "http.access", f"POST /checkout 500 {ms}ms"),
                ]
            case "db_pool_exhaustion", _:
                waited = rng.randint(1501, 1515)
                return [
                    _Line(
                        "orders",
                        "ERROR",
                        "http.server",
                        f"Database access failed on POST /orders: orders-db - Connection is not "
                        f"available, request timed out after {waited}ms (total=5, active=5, "
                        f"idle=0, waiting={rng.randint(2, 6)})",
                        {"error_type": "SQLTransientConnectionException"},
                    ),
                    _Line("orders", "WARN", "http.access", f"POST /orders 503 {waited + 4}ms"),
                    *storefront_gets(503),
                ]
            case "bad_config_deploy", "storefront":
                return [
                    _Line(
                        "storefront",
                        "ERROR",
                        "upstream.orders",
                        "Call to orders timed out after 20 ms: POST /orders",
                        {"error_type": "ReadTimeout", "timeout_ms": 20},
                    ),
                    _Line("storefront", "WARN", "http.access", "POST /checkout 504 22ms"),
                ]
            case "bad_config_deploy", "orders":
                return orders_payment_failed(
                    "UnknownHostException: payments-v2 (POST http://payments-v2:8080/charges)", None
                )
            case "bad_config_deploy", "payments":
                return [
                    _Line(
                        "payments",
                        "ERROR",
                        "http.server",
                        "Unhandled exception while handling POST /charges",
                        {
                            "error_type": "ConfigurationError",
                            "stack_trace": _PY_CONFIGERROR,
                            "error_message": "unsupported rounding_mode 'BANKERS'; expected one "
                            "of HALF_EVEN, HALF_UP",
                        },
                    ),
                    _Line("payments", "WARN", "http.access", f"POST /charges 500 {ms}ms"),
                    *orders_payment_failed("", 500),
                ]
            case "dependency_outage", "payments":
                return orders_payment_failed("", 503)
            case "dependency_outage", "orders":
                return storefront_gets(503)
        raise BackendError(f"unsupported fault {kind} on {target}")
