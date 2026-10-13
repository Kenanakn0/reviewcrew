"""Shipping costs."""

from decimal import Decimal

RATES = {"standard": Decimal("4.90"), "express": Decimal("9.90")}


def shipping_cost(method: str, items: int) -> Decimal:
    rate = RATES[method]
    if items > 5:
        rate = rate + Decimal("2.00")
    return rate
