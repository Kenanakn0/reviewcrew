from app.rate_limit import RateLimiter


def test_blocks_after_limit():
    limiter = RateLimiter(limit=2, window_seconds=60)
    assert limiter.allow("a")
    assert limiter.allow("a")
    assert not limiter.allow("a")


def test_keys_are_independent():
    limiter = RateLimiter(limit=1, window_seconds=60)
    assert limiter.allow("a")
    assert limiter.allow("b")
