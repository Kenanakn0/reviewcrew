"""Order reports."""

from app.models import Order


def paid_order_summaries() -> list[dict]:
    orders = Order.objects.filter(status="paid")
    return [
        {"id": o.id, "customer": o.customer.name, "items": o.items.count()}
        for o in orders
    ]
