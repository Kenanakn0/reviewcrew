"""Pricing."""

from decimal import Decimal


def subtotal(prices: list[Decimal]) -> Decimal:
    return sum(prices, Decimal("0"))
