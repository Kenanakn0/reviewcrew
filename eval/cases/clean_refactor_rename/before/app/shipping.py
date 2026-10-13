"""Shipping costs."""

from decimal import Decimal

RATES = {"standard": Decimal("4.90"), "express": Decimal("9.90")}


def shipping_cost(method: str, items: int) -> Decimal:
    r = RATES[method]
    if items > 5:
        r = r + Decimal("2.00")
    return r
