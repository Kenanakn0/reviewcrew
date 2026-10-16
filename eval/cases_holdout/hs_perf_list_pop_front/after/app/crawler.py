"""Breadth-first walk over the internal documentation site (tens of thousands of pages)."""

from collections.abc import Callable


def reachable_pages(
    start: str, links: Callable[[str], list[str]], limit: int = 50_000
) -> list[str]:
    seen = {start}
    order: list[str] = []
    queue = [start]
    while queue and len(order) < limit:
        page = queue.pop(0)
        order.append(page)
        for target in links(page):
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return order
