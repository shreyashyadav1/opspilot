"""Static product catalog served by the storefront."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    price_cents: int


CATALOG: dict[str, Product] = {
    p.sku: p
    for p in (
        Product("SKU-1001", "Trail running shoes", 12999),
        Product("SKU-1002", "Merino base layer", 7450),
        Product("SKU-1003", "Insulated water bottle", 2899),
        Product("SKU-1004", "Headlamp 400 lm", 3999),
        Product("SKU-1005", "Packable rain shell", 15900),
        Product("SKU-1006", "Wool hiking socks (3 pack)", 2450),
    )
}
