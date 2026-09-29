from datetime import UTC, datetime

import pytest

from opspilot_mcp.backends.simulated import FaultSpec, SimulatedBackend, SimulationSpec

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


@pytest.fixture
def simulate():
    def build(fault_type: str | None = None, target: str = "orders", **kwargs) -> SimulatedBackend:
        fault = FaultSpec(type=fault_type, target=target) if fault_type else None
        return SimulatedBackend(SimulationSpec(fault=fault, now=NOW, **kwargs))

    return build
