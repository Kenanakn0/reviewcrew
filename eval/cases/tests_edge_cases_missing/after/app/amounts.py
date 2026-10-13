"""Parsing of user-entered money amounts."""

from decimal import Decimal, InvalidOperation


def parse_amount(text: str) -> Decimal:
    cleaned = text.strip().replace(",", "").removeprefix("$")
    if not cleaned:
        raise ValueError("empty amount")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {text!r}") from exc
    if value < 0:
        raise ValueError("amount must not be negative")
    return value.quantize(Decimal("0.01"))
