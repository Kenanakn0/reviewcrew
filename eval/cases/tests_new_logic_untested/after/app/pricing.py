"""Pricing."""

from datetime import date
from decimal import Decimal

CODES = {
    "WELCOME10": {"percent": Decimal("10"), "min_total": Decimal("0"), "expires": date(2030, 1, 1)},
    "BIG50": {"percent": Decimal("50"), "min_total": Decimal("200"), "expires": date(2027, 6, 30)},
}


def subtotal(prices: list[Decimal]) -> Decimal:
    return sum(prices, Decimal("0"))


def apply_discount(total: Decimal, code: str | None, today: date) -> Decimal:
    if not code:
        return total
    rule = CODES.get(code.upper())
    if rule is None or today > rule["expires"]:
        raise ValueError("invalid or expired code")
    if total < rule["min_total"]:
        return total
    discounted = total * (Decimal("100") - rule["percent"]) / Decimal("100")
    return discounted.quantize(Decimal("0.01"))
