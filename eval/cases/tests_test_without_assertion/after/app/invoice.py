"""Invoices."""

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class Invoice:
    lines: list[tuple[str, Decimal, int]] = field(default_factory=list)
    tax_rate: Decimal = Decimal("0.20")

    def total(self) -> Decimal:
        net = sum((price * qty for _, price, qty in self.lines), Decimal("0"))
        return (net * (1 + self.tax_rate)).quantize(Decimal("0.01"))
