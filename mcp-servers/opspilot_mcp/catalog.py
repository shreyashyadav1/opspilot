"""Service catalog: what exists, who owns it and what it depends on.

This is the static knowledge an on-call engineer has about the system (the equivalent of a
Backstage catalog entry), and it is included in health reports so the agent can reason about
the dependency graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

ServiceName = Literal["storefront", "orders", "payments"]
SERVICES: tuple[str, ...] = get_args(ServiceName)


@dataclass(frozen=True)
class ServiceInfo:
    name: str
    description: str
    owner: str
    depends_on: tuple[str, ...]
    health_path: str


CATALOG: dict[str, ServiceInfo] = {
    "storefront": ServiceInfo(
        name="storefront",
        description="Public checkout API (FastAPI). Calls orders for checkout and order lookups.",
        owner="team-web",
        depends_on=("orders",),
        health_path="/health",
    ),
    "orders": ServiceInfo(
        name="orders",
        description="Order management (Spring Boot). Stores orders in Postgres, charges payments.",
        owner="team-commerce",
        depends_on=("postgres", "payments"),
        health_path="/actuator/health",
    ),
    "payments": ServiceInfo(
        name="payments",
        description="Card charges (FastAPI). No downstream dependencies in this system.",
        owner="team-payments",
        depends_on=(),
        health_path="/health",
    ),
}


def dependency_summary() -> str:
    """One line per service, used in the agent's system prompt."""
    lines = []
    for info in CATALOG.values():
        deps = ", ".join(info.depends_on) or "none"
        lines.append(f"- {info.name} (owner {info.owner}): {info.description} Depends on: {deps}.")
    return "\n".join(lines)
