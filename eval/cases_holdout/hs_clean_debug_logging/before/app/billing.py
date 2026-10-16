"""Billing."""

from decimal import Decimal


def invoice_total(lines: list[tuple[Decimal, int]]) -> Decimal:
    return sum((price * quantity for price, quantity in lines), Decimal("0"))
