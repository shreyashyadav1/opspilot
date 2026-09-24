"""Storefront: product catalog and checkout, backed by the orders service."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from opsdemo.common.http import UpstreamClient, UpstreamError
from opsdemo.common.runtime import ServiceRuntime
from opsdemo.common.service import create_service_app, instrumented_client
from opsdemo.storefront.catalog import CATALOG

ORDERS_URL = os.getenv("ORDERS_URL", "http://orders:8080")

DEFAULT_CONFIG: dict[str, Any] = {
    "orders_timeout_ms": 2000,
    "max_items_per_order": 20,
}


class CartItem(BaseModel):
    sku: str
    quantity: int = Field(ge=1, le=10)


class CheckoutRequest(BaseModel):
    customer_id: str = Field(min_length=1, max_length=64)
    items: list[CartItem] = Field(min_length=1)


runtime = ServiceRuntime("storefront", os.getenv("SERVICE_VERSION", "2.14.0"), DEFAULT_CONFIG)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    client = instrumented_client(app.state.tracer_provider)
    app.state.orders = UpstreamClient(
        "orders",
        client,
        base_url=lambda: ORDERS_URL,
        timeout_ms=lambda: runtime.config["orders_timeout_ms"],
    )
    yield
    await client.aclose()


app = create_service_app(runtime, title="storefront", lifespan=lifespan)


def build_order_request(
    customer_id: str, items: list[CartItem], *, promo_pricing: bool = False
) -> dict[str, Any]:
    lines = []
    for item in items:
        product = CATALOG.get(item.sku)
        if product is None:
            raise HTTPException(status_code=422, detail=f"unknown sku {item.sku}")
        line: dict[str, Any] = {
            "sku": product.sku,
            "quantity": item.quantity,
            "unit_price_cents": product.price_cents,
        }
        if promo_pricing:
            line["unit_price_cents"] = _promo_unit_price(line)
        lines.append(line)
    return {"customer_id": customer_id, "currency": "USD", "items": lines}


def _promo_unit_price(line: dict[str, Any]) -> int:
    # The error_spike failure mode routes a share of checkouts through this path. It has a
    # latent bug (the promo price is never attached to the line), so the failure looks exactly
    # like a real regression: a KeyError with a genuine traceback.
    return line["promo_price_cents"]


def _upstream_failure(exc: UpstreamError) -> JSONResponse:
    return JSONResponse(exc.to_body(), status_code=exc.http_status)


@app.get("/products")
async def list_products() -> dict[str, list[dict[str, Any]]]:
    return {"products": [asdict(p) for p in CATALOG.values()]}


@app.post("/checkout", status_code=201, response_model=None)
async def checkout(request: CheckoutRequest) -> dict[str, Any] | JSONResponse:
    if len(request.items) > runtime.config["max_items_per_order"]:
        raise HTTPException(status_code=422, detail="too many items in one order")
    order_request = build_order_request(
        request.customer_id, request.items, promo_pricing=runtime.should_fail()
    )
    try:
        response = await app.state.orders.request(
            "POST", "/orders", "/orders", json_body=order_request
        )
    except UpstreamError as exc:
        return _upstream_failure(exc)
    if response.status_code >= 400:
        return JSONResponse(response.json(), status_code=response.status_code)
    order = response.json()
    return {"order_id": order["id"], "status": order["status"], "total_cents": order["total_cents"]}


@app.get("/orders/{order_id}", response_model=None)
async def get_order(order_id: int) -> dict[str, Any] | JSONResponse:
    try:
        response = await app.state.orders.request("GET", "/orders/{id}", f"/orders/{order_id}")
    except UpstreamError as exc:
        return _upstream_failure(exc)
    if response.status_code >= 400:
        return JSONResponse(response.json(), status_code=response.status_code)
    return response.json()
