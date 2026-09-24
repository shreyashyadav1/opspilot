"""Payments: authorizes and captures charges for orders."""

from __future__ import annotations

import asyncio
import os
import random
import uuid
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel, Field

from opsdemo.common.runtime import ServiceRuntime
from opsdemo.common.service import create_service_app

DEFAULT_CONFIG: dict[str, Any] = {
    "rounding_mode": "HALF_EVEN",
    "settlement_currency": "USD",
}

ROUNDING_MODES = {"HALF_EVEN": ROUND_HALF_EVEN, "HALF_UP": ROUND_HALF_UP}
FX_RATES = {"USD": Decimal("1.0"), "EUR": Decimal("1.08"), "GBP": Decimal("1.27")}


class ConfigurationError(RuntimeError):
    pass


class ChargeRequest(BaseModel):
    order_id: int = Field(ge=1)
    amount_cents: int = Field(gt=0)
    currency: str = Field("USD", pattern="^[A-Z]{3}$")


runtime = ServiceRuntime("payments", os.getenv("SERVICE_VERSION", "3.2.0"), DEFAULT_CONFIG)
app = create_service_app(runtime, title="payments")


def settlement_amount(amount_cents: int, currency: str, *, stale_rates: bool = False) -> Decimal:
    rounding = ROUNDING_MODES.get(runtime.config["rounding_mode"])
    if rounding is None:
        raise ConfigurationError(
            f"unsupported rounding_mode {runtime.config['rounding_mode']!r}; "
            f"expected one of {', '.join(ROUNDING_MODES)}"
        )
    # The error_spike failure mode sets stale_rates on a share of requests: the rate cache
    # returns None and the arithmetic fails with a genuine TypeError, like a real regression.
    rate = None if stale_rates else FX_RATES.get(currency)
    return (Decimal(amount_cents) * rate).quantize(Decimal("1"), rounding=rounding)


@app.post("/charges", status_code=201)
async def create_charge(request: ChargeRequest) -> dict[str, Any]:
    # Card network round trip.
    await asyncio.sleep(random.uniform(0.004, 0.018))
    amount = settlement_amount(
        request.amount_cents, request.currency, stale_rates=runtime.should_fail()
    )
    charge_id = f"ch_{uuid.uuid4().hex[:16]}"
    return {
        "charge_id": charge_id,
        "order_id": request.order_id,
        "status": "captured",
        "amount_cents": int(amount),
        "currency": runtime.config["settlement_currency"],
    }
