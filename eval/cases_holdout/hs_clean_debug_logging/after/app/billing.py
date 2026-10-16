"""Billing."""

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


def invoice_total(lines: list[tuple[Decimal, int]]) -> Decimal:
    total = sum((price * quantity for price, quantity in lines), Decimal("0"))
    logger.debug("invoice total computed for %d lines", len(lines))
    return total
