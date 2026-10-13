from decimal import Decimal

from app.amounts import parse_amount


def test_parse_amount():
    assert parse_amount("12.50") == Decimal("12.50")
