"""Fixed-window rate limiting."""

import time


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = window_seconds
        self.counts: dict[str, tuple[int, float]] = {}

    def allow(self, key: str) -> bool:
        count, started = self.counts.get(key, (0, time.monotonic()))
        if time.monotonic() - started >= self.window:
            count, started = 0, time.monotonic()
        if count >= self.limit:
            return False
        self.counts[key] = (count + 1, started)
        return True
