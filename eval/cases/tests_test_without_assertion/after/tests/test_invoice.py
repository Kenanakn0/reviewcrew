from decimal import Decimal

from app.invoice import Invoice


def test_invoice_total():
    invoice = Invoice(lines=[("pen", Decimal("2.50"), 4)])
    invoice.total()
