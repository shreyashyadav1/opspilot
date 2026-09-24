"""Deploy registry: the deploy history a CD system would show, plus rollbacks.

Deploys change a service's version and runtime config through its admin API. The registry
keeps a config snapshot per deploy so a rollback can restore the previous one exactly.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

DeployKind = Literal["deploy", "rollback"]


@dataclass(frozen=True)
class Baseline:
    version: str
    config: dict[str, Any]


# Must match each service's default config (and the orders application.yml).
BASELINES: dict[str, Baseline] = {
    "storefront": Baseline("2.14.0", {"orders_timeout_ms": 2000, "max_items_per_order": 20}),
    "orders": Baseline(
        "1.8.3", {"payments.base-url": "http://payments:8080", "payments.timeout-ms": 2000}
    ),
    "payments": Baseline("3.2.0", {"rounding_mode": "HALF_EVEN", "settlement_currency": "USD"}),
}

# (version, age, author, summary) leading up to each baseline version.
_HISTORY: dict[str, list[tuple[str, timedelta, str, str]]] = {
    "storefront": [
        ("2.13.2", timedelta(days=6, hours=3), "a.nguyen", "Add product recommendations carousel"),
        ("2.13.3", timedelta(days=3, hours=1), "a.nguyen", "Fix currency formatting on receipts"),
        ("2.14.0", timedelta(hours=26), "j.okafor", "Upgrade FastAPI and uvicorn"),
    ],
    "orders": [
        ("1.8.1", timedelta(days=5, hours=2), "m.garcia", "Add index on orders(customer_id)"),
        ("1.8.2", timedelta(days=2, hours=4), "m.garcia", "Retry payment calls on connect timeout"),
        ("1.8.3", timedelta(hours=9), "s.patel", "Lower Hikari max-lifetime to 10 minutes"),
    ],
    "payments": [
        ("3.1.4", timedelta(days=4, hours=6), "l.chen", "Add EUR and GBP settlement"),
        ("3.1.5", timedelta(hours=30), "l.chen", "Rotate acquirer API credentials"),
        ("3.2.0", timedelta(hours=7), "r.silva", "Move fraud scoring to async worker"),
    ],
}


@dataclass(frozen=True)
class ConfigChange:
    summary: str
    author: str
    values: dict[str, Any]


# The config change shipped by a bad_config_deploy fault. Each breaks the service in a way that
# only shows up under traffic, which is how bad config usually escapes review.
BAD_CONFIG_CHANGES: dict[str, ConfigChange] = {
    "storefront": ConfigChange(
        "Tighten upstream timeouts so checkout fails fast under load",
        "j.okafor",
        {"orders_timeout_ms": 20},
    ),
    "orders": ConfigChange(
        "Route payment calls through the new payments endpoint",
        "s.patel",
        {"payments.base-url": "http://payments-v2:8080"},
    ),
    "payments": ConfigChange(
        "Adopt banker's rounding for settlement amounts",
        "r.silva",
        {"rounding_mode": "BANKERS"},
    ),
}

# Harmless changes used as distractors: a deploy that happens to land near an incident.
BENIGN_CHANGES: dict[str, ConfigChange] = {
    "storefront": ConfigChange("Update copy on the order confirmation page", "a.nguyen", {}),
    "orders": ConfigChange("Add request id to structured log fields", "m.garcia", {}),
    "payments": ConfigChange("Upgrade HTTP client library to the latest patch", "l.chen", {}),
}


class DeployEvent(BaseModel):
    id: str
    service: str
    kind: DeployKind
    version: str
    previous_version: str | None
    deployed_at: datetime
    author: str
    change_summary: str
    config_diff: dict[str, dict[str, Any]] = Field(default_factory=dict)
    status: Literal["succeeded"] = "succeeded"
    # Full config after this deploy; used for rollbacks, not shown to readers of the history.
    config: dict[str, Any] = Field(default_factory=dict, exclude=True)


class DeployRequest(BaseModel):
    service: str
    change_summary: str = Field(min_length=3, max_length=200)
    author: str = Field("deploy-bot", min_length=1, max_length=64)
    config: dict[str, Any] = Field(default_factory=dict)
    version: str | None = None
    minutes_ago: float = Field(0, ge=0, le=24 * 60, description="Backdate the event (seeding)")


class RollbackRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    requested_by: str = Field("opspilot", min_length=1, max_length=64)


def bump_patch(version: str) -> str:
    major, minor, patch = version.split(".")
    return f"{major}.{minor}.{int(patch) + 1}"


def config_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        key: {"from": before.get(key), "to": value}
        for key, value in after.items()
        if before.get(key) != value
    }


class DeployRegistry:
    def __init__(self) -> None:
        self._events: list[DeployEvent] = []
        self._ids = itertools.count(1)

    def reset(self, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        self._events.clear()
        seeded = []
        for service, history in _HISTORY.items():
            previous = None
            for version, age, author, summary in history:
                seeded.append((now - age, service, version, previous, author, summary))
                previous = version
        for deployed_at, service, version, previous, author, summary in sorted(seeded):
            self._append(
                service=service,
                kind="deploy",
                version=version,
                previous_version=previous,
                deployed_at=deployed_at,
                author=author,
                change_summary=summary,
                diff={},
                config=dict(BASELINES[service].config),
            )

    def current(self, service: str) -> DeployEvent:
        for event in reversed(self._events):
            if event.service == service:
                return event
        raise KeyError(service)

    def record_deploy(self, request: DeployRequest, now: datetime | None = None) -> DeployEvent:
        now = now or datetime.now(UTC)
        current = self.current(request.service)
        new_config = {**current.config, **request.config}
        return self._append(
            service=request.service,
            kind="deploy",
            version=request.version or bump_patch(self._highest_version(request.service)),
            previous_version=current.version,
            deployed_at=now - timedelta(minutes=request.minutes_ago),
            author=request.author,
            change_summary=request.change_summary,
            diff=config_diff(current.config, new_config),
            config=new_config,
        )

    def record_rollback(
        self, service: str, request: RollbackRequest, now: datetime | None = None
    ) -> tuple[DeployEvent, DeployEvent]:
        """Roll back the running version to the one it replaced.

        Returns (rollback event, deploy event of the version that was rolled back).
        """
        running = self._deploy_of(service, self.current(service).version)
        target = self._deploy_of(service, running.previous_version if running else None)
        if running is None or target is None:
            raise LookupError(f"{service} has no earlier version to roll back to")
        current_config = self.current(service).config
        event = self._append(
            service=service,
            kind="rollback",
            version=target.version,
            previous_version=running.version,
            deployed_at=now or datetime.now(UTC),
            author=request.requested_by,
            change_summary=f"Rollback {running.version} -> {target.version}: {request.reason}",
            diff=config_diff(current_config, target.config),
            config=dict(target.config),
        )
        return event, running

    def list(self, service: str | None = None, since: datetime | None = None) -> list[DeployEvent]:
        events = [
            e
            for e in self._events
            if (service is None or e.service == service)
            and (since is None or e.deployed_at >= since)
        ]
        return sorted(events, key=lambda e: e.deployed_at, reverse=True)

    def discard(self, event_id: str) -> None:
        """Drop an event whose config push failed, so history reflects what actually ran."""
        self._events = [e for e in self._events if e.id != event_id]

    def _highest_version(self, service: str) -> str:
        versions = [e.version for e in self._events if e.service == service]
        return max(versions, key=lambda v: tuple(int(part) for part in v.split(".")))

    def _deploy_of(self, service: str, version: str | None) -> DeployEvent | None:
        """The (latest) deploy event that originally shipped `version`."""
        if version is None:
            return None
        for event in reversed(self._events):
            if event.service == service and event.version == version and event.kind == "deploy":
                return event
        return None

    def _append(
        self,
        *,
        service: str,
        kind: DeployKind,
        version: str,
        previous_version: str | None,
        deployed_at: datetime,
        author: str,
        change_summary: str,
        diff: dict[str, dict[str, Any]],
        config: dict[str, Any],
    ) -> DeployEvent:
        event = DeployEvent(
            id=f"dep-{next(self._ids):04d}",
            service=service,
            kind=kind,
            version=version,
            previous_version=previous_version,
            deployed_at=deployed_at,
            author=author,
            change_summary=change_summary,
            config_diff=diff,
            config=config,
        )
        self._events.append(event)
        return event
