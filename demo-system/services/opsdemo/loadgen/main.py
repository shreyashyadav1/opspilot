"""Steady synthetic traffic against the storefront so metrics always have data.

Mix: 55% checkout (storefront -> orders -> postgres + payments), 30% product listing
(storefront only), 15% order lookup (storefront -> orders -> postgres).
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from collections import Counter, deque

import httpx

from opsdemo.common.logs import configure_logging
from opsdemo.storefront.catalog import CATALOG

log = logging.getLogger("loadgen")

TARGET_URL = os.getenv("TARGET_URL", "http://storefront:8080").rstrip("/")
RPS = float(os.getenv("RPS", "4"))
MAX_IN_FLIGHT = int(os.getenv("MAX_IN_FLIGHT", "32"))
REPORT_EVERY_S = 30.0


class LoadGenerator:
    def __init__(self, client: httpx.AsyncClient, rng: random.Random | None = None) -> None:
        self.client = client
        self.rng = rng or random.Random()
        self.order_ids: deque[int] = deque(maxlen=100)
        self.stats: Counter[str] = Counter()

    async def one_request(self) -> None:
        roll = self.rng.random()
        try:
            if roll < 0.55:
                await self._checkout()
            elif roll < 0.85 or not self.order_ids:
                await self._record("products", await self.client.get(f"{TARGET_URL}/products"))
            else:
                order_id = self.rng.choice(self.order_ids)
                await self._record(
                    "lookup", await self.client.get(f"{TARGET_URL}/orders/{order_id}")
                )
        except httpx.HTTPError as exc:
            self.stats[f"transport_error:{type(exc).__name__}"] += 1

    async def _checkout(self) -> None:
        skus = self.rng.sample(sorted(CATALOG), k=self.rng.randint(1, 3))
        body = {
            "customer_id": f"cust-{self.rng.randint(1, 500):04d}",
            "items": [{"sku": sku, "quantity": self.rng.randint(1, 3)} for sku in skus],
        }
        response = await self.client.post(f"{TARGET_URL}/checkout", json=body)
        await self._record("checkout", response)
        if response.status_code == 201:
            self.order_ids.append(response.json()["order_id"])

    async def _record(self, kind: str, response: httpx.Response) -> None:
        self.stats[f"{kind}:{response.status_code}"] += 1


async def run() -> None:
    configure_logging("loadgen")
    semaphore = asyncio.Semaphore(MAX_IN_FLIGHT)
    async with httpx.AsyncClient(timeout=10.0) as client:
        generator = LoadGenerator(client)
        loop = asyncio.get_running_loop()
        next_report = loop.time() + REPORT_EVERY_S
        tasks: set[asyncio.Task[None]] = set()

        async def guarded() -> None:
            async with semaphore:
                await generator.one_request()

        log.info("Sending traffic to %s at %.1f rps", TARGET_URL, RPS)
        while True:
            if not semaphore.locked():
                task = asyncio.create_task(guarded())
                tasks.add(task)
                task.add_done_callback(tasks.discard)
            else:
                generator.stats["skipped:max_in_flight"] += 1
            if loop.time() >= next_report:
                log.info("Traffic summary", extra={"counts": dict(generator.stats)})
                generator.stats.clear()
                next_report = loop.time() + REPORT_EVERY_S
            await asyncio.sleep(generator.rng.expovariate(RPS))


if __name__ == "__main__":
    asyncio.run(run())
